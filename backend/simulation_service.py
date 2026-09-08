"""Read-only, in-memory batch scheduling simulation against live configuration."""

from __future__ import annotations

import statistics
import time as wall_time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from psycopg import Connection

from optimizer.siligent_optimizer import (
    Appointment,
    Doctor,
    EquipmentReservation,
    EquipmentUnit,
    Interval,
    ProcedurePhase,
    Provider,
    ReservedProcedureBlock,
    ResourceReservation,
    Room,
    SchedulingRequest,
    recommend_slots,
)

from .config import settings
from .scheduling import _availability_from_hours, _subtract, daterange, local_interval
from .simulation_import import serialize_preview_row


def _catalog(connection: Connection) -> tuple[dict[str, dict], dict[str, str], dict[str, int]]:
    procedures = connection.execute(
        """
        SELECT id, code, name, duration_minutes, preparation_minutes,
               cleanup_minutes, production_cents
          FROM procedures WHERE active ORDER BY code
        """
    ).fetchall()
    doctors = connection.execute(
        "SELECT id, staff_code FROM doctors WHERE active ORDER BY staff_code"
    ).fetchall()
    phase_totals = connection.execute(
        """
        SELECT procedure_id,
               sum(duration_minutes)::integer AS standard_minutes,
               sum(COALESCE(complex_duration_minutes, duration_minutes))::integer
                   AS complex_minutes
          FROM procedure_phase_templates
         WHERE active GROUP BY procedure_id
        """
    ).fetchall()
    totals: dict[str, int] = {}
    for row in phase_totals:
        totals[f"{row['procedure_id']}:standard"] = int(row["standard_minutes"])
        totals[f"{row['procedure_id']}:complex"] = int(row["complex_minutes"])
    return (
        {row["code"]: dict(row) for row in procedures},
        {row["staff_code"].upper(): str(row["id"]) for row in doctors},
        totals,
    )


def prepare_simulation(
    connection: Connection,
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    procedures, doctors_by_code, phase_totals = _catalog(connection)
    issues: list[str] = []
    prepared: list[dict[str, object]] = []
    duration_adjustments = 0
    production_adjustments = 0
    for row in rows:
        prefix = f"Row {row['row_number']}"
        procedure = procedures.get(str(row["procedure_code"]))
        if not procedure:
            issues.append(f"{prefix}: unknown or inactive procedure {row['procedure_code']}")
            continue
        preferred_code = str(row["preferred_doctor_code"])
        established_code = str(row["established_doctor_code"])
        if preferred_code and preferred_code not in doctors_by_code:
            issues.append(f"{prefix}: unknown or inactive preferred dentist {preferred_code}")
        if established_code and established_code not in doctors_by_code:
            issues.append(f"{prefix}: unknown or inactive established dentist {established_code}")
        configured_minutes = phase_totals.get(
            f"{procedure['id']}:{row['difficulty']}",
            int(procedure["duration_minutes"])
            + int(procedure["preparation_minutes"])
            + int(procedure["cleanup_minutes"]),
        )
        uploaded_minutes = row["scheduled_minutes"]
        if uploaded_minutes is not None and int(uploaded_minutes) != configured_minutes:
            duration_adjustments += 1
        uploaded_production = row["uploaded_production_cents"]
        if uploaded_production is not None and int(uploaded_production) != int(procedure["production_cents"]):
            production_adjustments += 1
        prepared.append(
            {
                **row,
                "procedure": procedure,
                "configured_minutes": configured_minutes,
                "preferred_doctor_id": doctors_by_code.get(preferred_code),
                "established_doctor_id": doctors_by_code.get(established_code),
            }
        )
    if issues:
        displayed = issues[:8]
        if len(issues) > len(displayed):
            displayed.append(f"{len(issues) - len(displayed)} more row error(s)")
        raise ValueError("; ".join(displayed))
    procedures_used = Counter(str(row["procedure_code"]) for row in prepared)
    priorities = Counter(str(row["priority"]) for row in prepared)
    summary = {
        "row_count": len(prepared),
        "date_from": min(row["availability_start_date"] for row in prepared).isoformat(),
        "date_to": max(row["availability_end_date"] for row in prepared).isoformat(),
        "procedure_counts": dict(sorted(procedures_used.items())),
        "priority_counts": dict(sorted(priorities.items())),
        "duration_policy_adjustments": duration_adjustments,
        "production_policy_adjustments": production_adjustments,
        "policy_note": "Configured procedure durations and production values replace uploaded estimates.",
    }
    return prepared, summary


def preview_simulation(connection: Connection, rows: list[dict[str, object]]) -> dict[str, object]:
    prepared, summary = prepare_simulation(connection, rows)
    return {
        "summary": summary,
        "preview_rows": [serialize_preview_row(row) for row in prepared[:12]],
        "preview_limit": 12,
        "calendar_effect": "No appointments are created, changed, cancelled, or moved.",
    }


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return dict(grouped)


def _load_context(connection: Connection, start: date, end: date) -> dict[str, object]:
    timezone = ZoneInfo(settings.practice_timezone)
    window_start = datetime.combine(start, time.min, tzinfo=timezone).astimezone(UTC)
    window_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
    closure_rows = connection.execute(
        """
        SELECT lower(closed_during) AS starts_at, upper(closed_during) AS ends_at
          FROM practice_closures
         WHERE closed_during && tstzrange(%s, %s, '[)')
        """,
        (window_start, window_end),
    ).fetchall()
    closures = [Interval(row["starts_at"], row["ends_at"]) for row in closure_rows]

    provider_rows = connection.execute(
        """
        SELECT p.id, p.display_name, p.role::text AS role, p.doctor_id,
               d.max_active_rooms
          FROM providers p LEFT JOIN doctors d ON d.id = p.doctor_id
         WHERE p.active AND (p.doctor_id IS NULL OR d.active)
         ORDER BY p.id
        """
    ).fetchall()
    provider_hours = _group(
        connection.execute(
            """
            SELECT provider_id, weekday, local_start, local_end, effective_from, effective_through
              FROM provider_working_hours
             WHERE effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
            """,
            (end, start),
        ).fetchall(),
        "provider_id",
    )
    provider_leave = _group(
        connection.execute(
            """
            SELECT provider_id, lower(unavailable_during) AS starts_at,
                   upper(unavailable_during) AS ends_at
              FROM provider_unavailability
             WHERE unavailable_during && tstzrange(%s, %s, '[)')
            """,
            (window_start, window_end),
        ).fetchall(),
        "provider_id",
    )
    shift_rows = _group(
        connection.execute(
            """
            SELECT provider_id, shift_date, status, local_start, local_end
              FROM provider_shift_overrides WHERE shift_date BETWEEN %s AND %s
            """,
            (start, end),
        ).fetchall(),
        "provider_id",
    )
    availability_by_provider: dict[str, tuple[Interval, ...]] = {}
    for provider in provider_rows:
        provider_id = str(provider["id"])
        exclusions = closures + [
            Interval(row["starts_at"], row["ends_at"])
            for row in provider_leave.get(provider_id, [])
        ]
        overrides = {row["shift_date"]: row for row in shift_rows.get(provider_id, [])}
        availability_by_provider[provider_id] = _availability_from_hours(
            provider_hours.get(provider_id, []), start, end, timezone, exclusions, overrides
        )
    support_providers = tuple(
        Provider(
            str(row["id"]),
            row["display_name"],
            row["role"],
            availability_by_provider[str(row["id"])],
        )
        for row in provider_rows
        if row["role"] in {"assistant", "hygienist"}
    )
    doctor_rows = [dict(row) for row in provider_rows if row["doctor_id"]]

    qualification_rows = connection.execute(
        """
        SELECT q.doctor_id, q.procedure_id, q.effective_from, q.effective_through
          FROM doctor_procedure_qualifications q
          JOIN doctors d ON d.id = q.doctor_id AND d.active
         WHERE q.effective_from <= %s
           AND (q.effective_through IS NULL OR q.effective_through >= %s)
        """,
        (end, start),
    ).fetchall()
    qualifications = _group(qualification_rows, "doctor_id")
    preference_rows = connection.execute(
        "SELECT provider_id, procedure_id, preference FROM provider_procedure_preferences"
    ).fetchall()
    preferences = {
        (str(row["provider_id"]), str(row["procedure_id"])): int(row["preference"])
        for row in preference_rows
    }
    target_rows = _group(
        connection.execute(
            """
            SELECT provider_id, weekday, target_cents, effective_from, effective_through
              FROM provider_daily_targets
             WHERE effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
             ORDER BY provider_id, weekday, effective_from DESC
            """,
            (end, start),
        ).fetchall(),
        "provider_id",
    )
    credited_rows = connection.execute(
        """
        SELECT c.provider_id, (a.starts_at AT TIME ZONE %s)::date AS service_date,
               COALESCE(sum(c.amount_cents), 0)::integer AS amount_cents
          FROM appointment_production_credits c
          JOIN appointments a ON a.id = c.appointment_id
         WHERE a.status IN ('confirmed', 'completed')
           AND a.starts_at < %s AND a.ends_at > %s
         GROUP BY c.provider_id, service_date
        """,
        (settings.practice_timezone, window_end, window_start),
    ).fetchall()
    credited_by_provider_day = {
        (str(row["provider_id"]), row["service_date"]): int(row["amount_cents"])
        for row in credited_rows
    }

    emergency_rules = connection.execute(
        """
        SELECT weekday, local_start, local_end, release_hours_before
          FROM emergency_capacity_rules WHERE active
        """
    ).fetchall()
    now_local = datetime.now(timezone)
    protected_intervals = tuple(
        interval
        for day in daterange(start, end)
        for rule in emergency_rules
        if rule["weekday"] == day.weekday()
        for interval in (local_interval(day, rule["local_start"], rule["local_end"], timezone),)
        if interval.start - now_local > timedelta(hours=rule["release_hours_before"])
    )

    room_rows = connection.execute("SELECT id, name FROM rooms WHERE active ORDER BY id").fetchall()
    room_hours = _group(
        connection.execute(
            """
            SELECT room_id, weekday, local_start, local_end, effective_from, effective_through
              FROM room_working_hours
             WHERE effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
            """,
            (end, start),
        ).fetchall(),
        "room_id",
    )
    room_eligibility = _group(
        connection.execute(
            """
            SELECT e.room_id, p.code AS procedure_code
              FROM procedure_room_eligibility e
              JOIN procedures p ON p.id = e.procedure_id AND p.active
            """
        ).fetchall(),
        "room_id",
    )
    rooms = tuple(
        Room(
            str(row["id"]),
            row["name"],
            frozenset(
                eligibility["procedure_code"]
                for eligibility in room_eligibility.get(str(row["id"]), [])
            ),
            _availability_from_hours(
                room_hours.get(str(row["id"]), []), start, end, timezone, closures
            ),
        )
        for row in room_rows
    )

    phase_rows = connection.execute(
        """
        SELECT procedure_id, sequence, code, name, required_role,
               duration_minutes, complex_duration_minutes
          FROM procedure_phase_templates WHERE active ORDER BY procedure_id, sequence
        """
    ).fetchall()
    phases_by_procedure = _group(phase_rows, "procedure_id")
    equipment_requirement_rows = connection.execute(
        """
        SELECT procedure_id, equipment_id, quantity
          FROM procedure_equipment_requirements ORDER BY procedure_id, equipment_id
        """
    ).fetchall()
    equipment_requirements = _group(equipment_requirement_rows, "procedure_id")
    production_share_rows = connection.execute(
        """
        SELECT procedure_id, role::text AS role, basis_points
          FROM procedure_role_production_share
         ORDER BY procedure_id, role
        """
    ).fetchall()
    production_shares = _group(production_share_rows, "procedure_id")
    equipment_rows = connection.execute(
        "SELECT id, name, quantity FROM equipment WHERE active ORDER BY id"
    ).fetchall()
    equipment_windows = tuple(
        piece
        for day in daterange(start, end)
        for piece in _subtract(
            Interval(
                datetime.combine(day, time.min, tzinfo=timezone),
                datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone),
            ),
            closures,
        )
    )
    equipment_units = tuple(
        EquipmentUnit(
            f"{row['id']}:{unit_number}",
            str(row["id"]),
            f"{row['name']} {unit_number}",
            unit_number,
            equipment_windows,
        )
        for row in equipment_rows
        for unit_number in range(1, int(row["quantity"]) + 1)
    )

    appointment_rows = connection.execute(
        """
        SELECT id, patient_id, doctor_id, room_id, starts_at, ends_at, status::text AS status
          FROM appointments
         WHERE status IN ('held', 'confirmed')
           AND starts_at < %s AND ends_at > %s
        """,
        (window_end, window_start),
    ).fetchall()
    appointments = tuple(
        Appointment(
            str(row["id"]),
            str(row["patient_id"]),
            str(row["doctor_id"]),
            str(row["room_id"]) if row["room_id"] else None,
            Interval(row["starts_at"], row["ends_at"]),
            locked=row["status"] == "confirmed",
        )
        for row in appointment_rows
    )
    reservation_rows = connection.execute(
        """
        SELECT ap.appointment_id, ap.provider_id, ap.starts_at, ap.ends_at
          FROM appointment_phases ap JOIN appointments a ON a.id = ap.appointment_id
         WHERE ap.active AND ap.provider_id IS NOT NULL
           AND a.status IN ('held', 'confirmed')
           AND ap.starts_at < %s AND ap.ends_at > %s
        """,
        (window_end, window_start),
    ).fetchall()
    reservations = tuple(
        ResourceReservation(
            str(row["appointment_id"]),
            str(row["provider_id"]),
            Interval(row["starts_at"], row["ends_at"]),
        )
        for row in reservation_rows
    )
    equipment_reservation_rows = connection.execute(
        """
        SELECT r.appointment_id, r.equipment_id, r.unit_number, r.starts_at, r.ends_at
          FROM appointment_equipment_reservations r
          JOIN appointments a ON a.id = r.appointment_id
         WHERE r.active AND a.status IN ('held', 'confirmed')
           AND r.starts_at < %s AND r.ends_at > %s
        """,
        (window_end, window_start),
    ).fetchall()
    equipment_reservations = tuple(
        EquipmentReservation(
            str(row["appointment_id"]),
            f"{row['equipment_id']}:{row['unit_number']}",
            Interval(row["starts_at"], row["ends_at"]),
        )
        for row in equipment_reservation_rows
    )
    block_rows = connection.execute(
        """
        SELECT b.id, b.doctor_id, p.code AS procedure_code,
               lower(b.reserved_during) AS starts_at,
               upper(b.reserved_during) AS ends_at,
               b.room_id, b.equipment_id, b.equipment_unit_number
          FROM reserved_procedure_blocks b
          JOIN procedures p ON p.id = b.procedure_id
         WHERE b.status = 'active'
           AND (b.release_at IS NULL OR b.release_at > transaction_timestamp())
           AND b.reserved_during && tstzrange(%s, %s, '[)')
        """,
        (window_start, window_end),
    ).fetchall()
    reserved_blocks = tuple(
        ReservedProcedureBlock(
            str(row["id"]),
            str(row["doctor_id"]),
            row["procedure_code"],
            Interval(row["starts_at"], row["ends_at"]),
            str(row["room_id"]) if row["room_id"] else None,
            f"{row['equipment_id']}:{row['equipment_unit_number']}"
            if row["equipment_id"]
            else None,
        )
        for row in block_rows
    )
    return {
        "timezone": timezone,
        "start": start,
        "end": end,
        "doctor_rows": doctor_rows,
        "qualifications": qualifications,
        "preferences": preferences,
        "targets": target_rows,
        "credited_by_provider_day": credited_by_provider_day,
        "availability_by_provider": availability_by_provider,
        "protected_intervals": protected_intervals,
        "providers": support_providers,
        "rooms": rooms,
        "phases_by_procedure": phases_by_procedure,
        "equipment_requirements": equipment_requirements,
        "production_shares": production_shares,
        "equipment_units": equipment_units,
        "appointments": appointments,
        "reservations": reservations,
        "equipment_reservations": equipment_reservations,
        "reserved_blocks": reserved_blocks,
    }


def _production_gap(
    provider_id: str,
    service_date: date,
    context: dict[str, object],
    hypothetical_credits: dict[tuple[str, date], int],
) -> int:
    target = next(
        (
            item
            for item in context["targets"].get(provider_id, [])
            if int(item["weekday"]) == service_date.weekday()
            and item["effective_from"] <= service_date
            and (item["effective_through"] is None or item["effective_through"] >= service_date)
        ),
        None,
    )
    target_cents = int(target["target_cents"]) if target else 0
    credited = int(context["credited_by_provider_day"].get((provider_id, service_date), 0))
    credited += int(hypothetical_credits.get((provider_id, service_date), 0))
    return max(target_cents - credited, 0)


def _request_inputs(
    row: dict[str, object],
    context: dict[str, object],
    hypothetical_credits: dict[tuple[str, date], int],
):
    procedure = row["procedure"]
    procedure_id = str(procedure["id"])
    procedure_code = str(procedure["code"])
    qualification_rows = context["qualifications"]
    doctors: list[Doctor] = []
    for provider in context["doctor_rows"]:
        doctor_id = str(provider["doctor_id"])
        eligible_periods = [
            item
            for item in qualification_rows.get(doctor_id, [])
            if str(item["procedure_id"]) == procedure_id
        ]
        if not eligible_periods:
            continue
        availability = tuple(
            window
            for window in context["availability_by_provider"][str(provider["id"])]
            if any(
                item["effective_from"] <= window.start.date()
                and (item["effective_through"] is None or item["effective_through"] >= window.start.date())
                for item in eligible_periods
            )
        )
        doctors.append(
            Doctor(
                doctor_id,
                provider["display_name"],
                frozenset({procedure_code}),
                availability,
                provider_id=str(provider["id"]),
                procedure_preference=context["preferences"].get(
                    (str(provider["id"]), procedure_id), 0
                ),
                production_gap_cents=_production_gap(
                    str(provider["id"]),
                    row["availability_start_date"],
                    context,
                    hypothetical_credits,
                ),
                protected_intervals=context["protected_intervals"],
                max_active_visits=int(provider["max_active_rooms"]),
            )
        )
    phase_rows = context["phases_by_procedure"].get(procedure_id, [])
    phases = tuple(
        ProcedurePhase(
            item["code"],
            item["name"],
            item["required_role"],
            timedelta(
                minutes=(
                    item["complex_duration_minutes"] or item["duration_minutes"]
                    if row["difficulty"] == "complex"
                    else item["duration_minutes"]
                )
            ),
        )
        for item in phase_rows
    )
    total_minutes = int(sum((phase.duration for phase in phases), timedelta()).total_seconds() // 60)
    if not total_minutes:
        total_minutes = int(row["configured_minutes"])
    request_received_at = row["request_received_at"].astimezone(context["timezone"])
    patient_windows = tuple(
        Interval(max(window.start, request_received_at), window.end)
        for day in daterange(row["availability_start_date"], row["availability_end_date"])
        for window in (
            local_interval(
                day,
                row["daily_start_time"],
                row["daily_end_time"],
                context["timezone"],
            ),
        )
        if window.end > request_received_at
    )
    request = SchedulingRequest(
        id=str(row["request_id"]),
        patient_id=f"simulation:{row['patient_ref']}",
        procedure_code=procedure_code,
        duration=timedelta(minutes=total_minutes),
        patient_availability=patient_windows,
        preferred_intervals=patient_windows,
        preferred_doctor_id=row["preferred_doctor_id"],
        established_doctor_id=row["established_doctor_id"],
        phases=phases,
        priority=str(row["priority"]),
        required_equipment=tuple(
            (str(item["equipment_id"]), int(item["quantity"]))
            for item in context["equipment_requirements"].get(procedure_id, [])
        ),
        allow_reserved_block_override=False,
    )
    return request, tuple(doctors)


def _validate_hypothetical_schedule(
    appointments: list[Appointment],
    provider_reservations: list[ResourceReservation],
    equipment_reservations: list[EquipmentReservation],
    originals: dict[str, Interval],
    hypothetical_ids: set[str],
) -> list[str]:
    failures: list[str] = []
    for appointment in appointments:
        if appointment.id in hypothetical_ids and not appointment.locked:
            failures.append(f"{appointment.id}: result is not locked")
        if appointment.id in originals and originals[appointment.id] != appointment.interval:
            failures.append(f"{appointment.id}: snapshot visit moved")
    for index, first in enumerate(appointments):
        for second in appointments[index + 1 :]:
            if not first.interval.overlaps(second.interval):
                continue
            if first.patient_id == second.patient_id:
                failures.append(f"{first.id}/{second.id}: patient overlap")
            if first.room_id and first.room_id == second.room_id:
                failures.append(f"{first.id}/{second.id}: room overlap")
    for index, first in enumerate(provider_reservations):
        for second in provider_reservations[index + 1 :]:
            if first.provider_id == second.provider_id and first.interval.overlaps(second.interval):
                failures.append(f"{first.appointment_id}/{second.appointment_id}: provider overlap")
    for index, first in enumerate(equipment_reservations):
        for second in equipment_reservations[index + 1 :]:
            if first.unit_id == second.unit_id and first.interval.overlaps(second.interval):
                failures.append(f"{first.appointment_id}/{second.appointment_id}: equipment overlap")
    return failures


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def run_simulation(
    connection: Connection,
    rows: list[dict[str, object]],
    *,
    actor_id: str,
) -> dict[str, object]:
    del actor_id  # The caller uses the actor only for the PHI-free audit event.
    started = wall_time.perf_counter()
    prepared, input_summary = prepare_simulation(connection, rows)
    context = _load_context(
        connection,
        min(row["availability_start_date"] for row in prepared),
        max(row["availability_end_date"] for row in prepared),
    )
    hypothetical_appointments: list[Appointment] = []
    provider_reservations: list[ResourceReservation] = []
    equipment_reservations: list[EquipmentReservation] = []
    hypothetical_credits: dict[tuple[str, date], int] = defaultdict(int)
    originals = {
        appointment.id: appointment.interval for appointment in context["appointments"]
    }
    hypothetical_ids: set[str] = set()
    results: list[dict[str, object]] = []
    availability_delays: list[float] = []
    booking_leads: list[float] = []
    by_procedure: Counter[str] = Counter()
    by_doctor: Counter[str] = Counter()
    scheduled_production = 0
    unscheduled_production = 0
    horizon_end = datetime.combine(
        context["end"] + timedelta(days=1), time.min, tzinfo=context["timezone"]
    )

    for row in prepared:
        procedure = row["procedure"]
        request, doctors = _request_inputs(row, context, hypothetical_credits)
        recommendation = recommend_slots(
            request,
            doctors,
            context["rooms"],
            context["appointments"] + tuple(hypothetical_appointments),
            horizon_end=horizon_end,
            grid_minutes=30,
            limit=5,
            providers=context["providers"],
            reservations=context["reservations"] + tuple(provider_reservations),
            equipment_units=context["equipment_units"],
            equipment_reservations=context["equipment_reservations"]
            + tuple(equipment_reservations),
            reserved_blocks=context["reserved_blocks"],
        )
        base = {
            "request_id": row["request_id"],
            "patient_ref": row["patient_ref"],
            "request_received_at": row["request_received_at"].isoformat(),
            "procedure_code": row["procedure_code"],
            "procedure_name": procedure["name"],
            "difficulty": row["difficulty"],
            "priority": row["priority"],
            "production_cents": int(procedure["production_cents"]),
        }
        if not recommendation.candidates:
            unscheduled_production += int(procedure["production_cents"])
            results.append(
                {
                    **base,
                    "result": "unscheduled",
                    "doctor_name": "",
                    "room_name": "",
                    "starts_at": "",
                    "ends_at": "",
                    "scheduled_minutes": 0,
                    "wait_days": None,
                    "booking_lead_days": None,
                    "availability_delay_days": None,
                    "locked": False,
                    "blocking_reason": "; ".join(recommendation.blocking_reasons),
                }
            )
            continue
        chosen = recommendation.candidates[0]
        appointment_id = f"simulation:{row['request_id']}"
        appointment = Appointment(
            appointment_id,
            f"simulation:{row['patient_ref']}",
            chosen.doctor_id,
            chosen.room_id,
            chosen.interval,
            locked=True,
        )
        hypothetical_appointments.append(appointment)
        originals[appointment_id] = chosen.interval
        hypothetical_ids.add(appointment_id)
        provider_reservations.extend(
            ResourceReservation(appointment_id, phase.provider_id, phase.interval)
            for phase in chosen.phases
            if phase.provider_id
        )
        equipment_reservations.extend(
            EquipmentReservation(appointment_id, unit_id, chosen.interval)
            for unit_id in chosen.equipment_unit_ids
        )
        phases_by_role: dict[str, str] = {}
        for phase in chosen.phases:
            if phase.provider_id and phase.role not in phases_by_role:
                phases_by_role[phase.role] = phase.provider_id
        for share in context["production_shares"].get(str(procedure["id"]), []):
            provider_id = phases_by_role.get(str(share["role"]))
            if provider_id:
                hypothetical_credits[(provider_id, chosen.interval.start.date())] += (
                    int(procedure["production_cents"]) * int(share["basis_points"]) // 10000
                )
        first_available = datetime.combine(
            row["availability_start_date"],
            row["daily_start_time"],
            tzinfo=context["timezone"],
        )
        availability_delay_days = max(
            0.0, (chosen.interval.start - first_available).total_seconds() / 86400
        )
        booking_lead_days = max(
            0.0,
            (
                chosen.interval.start.astimezone(UTC)
                - row["request_received_at"].astimezone(UTC)
            ).total_seconds()
            / 86400,
        )
        availability_delays.append(availability_delay_days)
        booking_leads.append(booking_lead_days)
        by_procedure[str(row["procedure_code"])] += 1
        by_doctor[chosen.doctor_name] += 1
        scheduled_production += int(procedure["production_cents"])
        results.append(
            {
                **base,
                "result": "scheduled",
                "doctor_name": chosen.doctor_name,
                "room_name": chosen.room_name,
                "starts_at": chosen.interval.start.isoformat(),
                "ends_at": chosen.interval.end.isoformat(),
                "scheduled_minutes": int(
                    (chosen.interval.end - chosen.interval.start).total_seconds() // 60
                ),
                "wait_days": round(availability_delay_days, 2),
                "booking_lead_days": round(booking_lead_days, 2),
                "availability_delay_days": round(availability_delay_days, 2),
                "locked": True,
                "blocking_reason": "",
            }
        )

    failures = _validate_hypothetical_schedule(
        list(context["appointments"]) + hypothetical_appointments,
        list(context["reservations"]) + provider_reservations,
        list(context["equipment_reservations"]) + equipment_reservations,
        originals,
        hypothetical_ids,
    )
    scheduled_count = len(hypothetical_appointments)
    report = {
        **input_summary,
        "scheduled": scheduled_count,
        "unscheduled": len(prepared) - scheduled_count,
        "schedule_rate_percent": round(100 * scheduled_count / len(prepared), 1),
        "confirmed_and_locked_in_simulation": scheduled_count,
        "locked_appointments_moved": 0,
        "mean_wait_days": (
            round(statistics.mean(availability_delays), 2) if availability_delays else 0
        ),
        "p95_wait_days": round(_percentile(availability_delays, 0.95), 2),
        "mean_availability_delay_days": (
            round(statistics.mean(availability_delays), 2) if availability_delays else 0
        ),
        "p95_availability_delay_days": round(
            _percentile(availability_delays, 0.95), 2
        ),
        "mean_booking_lead_days": (
            round(statistics.mean(booking_leads), 2) if booking_leads else 0
        ),
        "p95_booking_lead_days": round(_percentile(booking_leads, 0.95), 2),
        "scheduled_production_cents": scheduled_production,
        "unscheduled_production_cents": unscheduled_production,
        "scheduled_by_procedure": dict(sorted(by_procedure.items())),
        "scheduled_by_doctor": dict(sorted(by_doctor.items())),
        "invariant_failures": failures,
        "live_calendar_changed": False,
        "runtime_seconds": round(wall_time.perf_counter() - started, 3),
        "method": (
            "Deterministic incremental replay against one read-only calendar snapshot, "
            "including live and simulated production-target progress."
        ),
    }
    return {"report": report, "results": results}
