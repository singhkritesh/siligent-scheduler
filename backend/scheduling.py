from __future__ import annotations

import json
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


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def local_interval(day: date, start: time, end: time, timezone: ZoneInfo) -> Interval:
    return Interval(
        datetime.combine(day, start, tzinfo=timezone),
        datetime.combine(day, end, tzinfo=timezone),
    )


def _future_patient_windows(
    start_date: date,
    end_date: date,
    start_time: time,
    end_time: time,
    timezone: ZoneInfo,
    now_local: datetime,
) -> tuple[Interval, ...]:
    windows: list[Interval] = []
    for day in daterange(start_date, end_date):
        daily = local_interval(day, start_time, end_time, timezone)
        start = max(daily.start, now_local) if day == now_local.date() else daily.start
        if start < daily.end:
            windows.append(Interval(start, daily.end))
    return tuple(windows)


def _subtract(base: Interval, exclusions: list[Interval]) -> list[Interval]:
    pieces = [base]
    for exclusion in exclusions:
        next_pieces: list[Interval] = []
        for piece in pieces:
            if not piece.overlaps(exclusion):
                next_pieces.append(piece)
                continue
            if piece.start < exclusion.start:
                next_pieces.append(Interval(piece.start, min(piece.end, exclusion.start)))
            if exclusion.end < piece.end:
                next_pieces.append(Interval(max(piece.start, exclusion.end), piece.end))
        pieces = next_pieces
    return pieces


def _availability_from_hours(
    hours: list[dict],
    start_date: date,
    end_date: date,
    timezone: ZoneInfo,
    exclusions: list[Interval],
    shift_overrides: dict[date, dict] | None = None,
) -> tuple[Interval, ...]:
    windows: list[Interval] = []
    shift_overrides = shift_overrides or {}
    for day in daterange(start_date, end_date):
        override = shift_overrides.get(day)
        if override:
            if override["status"] == "off":
                continue
            windows.extend(
                _subtract(
                    local_interval(day, override["local_start"], override["local_end"], timezone),
                    exclusions,
                )
            )
            continue
        for schedule in hours:
            if (
                schedule["weekday"] == day.weekday()
                and schedule["effective_from"] <= day
                and (
                    schedule["effective_through"] is None
                    or schedule["effective_through"] >= day
                )
            ):
                windows.extend(
                    _subtract(
                        local_interval(day, schedule["local_start"], schedule["local_end"], timezone),
                        exclusions,
                    )
                )
    return tuple(sorted(windows))


def _limit_to_effective_dates(
    windows: tuple[Interval, ...],
    effective_from: date,
    effective_through: date | None,
) -> tuple[Interval, ...]:
    """Keep daily availability only while a dated authorization is active."""

    return tuple(
        interval for interval in windows
        if effective_from <= interval.start.date()
        and (effective_through is None or effective_through >= interval.start.date())
    )


def _shift_overrides(connection: Connection, provider_id: str, start: date, end: date) -> dict[date, dict]:
    rows = connection.execute(
        """
        SELECT shift_date, status, local_start, local_end
          FROM provider_shift_overrides
         WHERE provider_id = %s AND shift_date BETWEEN %s AND %s
        """,
        (provider_id, start, end),
    ).fetchall()
    return {row["shift_date"]: row for row in rows}


def _phase_payload(candidate) -> list[dict]:
    return [
        {
            "sequence": index,
            "code": phase.code,
            "name": phase.name,
            "role": phase.role,
            "provider_id": phase.provider_id,
            "provider_name": phase.provider_name,
            "starts_at": phase.interval.start.isoformat(),
            "ends_at": phase.interval.end.isoformat(),
        }
        for index, phase in enumerate(candidate.phases, 1)
    ]


def create_recommendations(
    connection: Connection,
    *,
    scheduling_request_id: str,
    patient_id: str,
    procedure: dict,
    start_date: date,
    end_date: date,
    start_time: time,
    end_time: time,
    preferred_doctor_id: str | None,
    actor_id: str,
    priority: str = "routine",
    difficulty: str = "standard",
    reschedules_appointment_id: str | None = None,
    allow_reserved_block_override: bool = False,
    required_doctor_id: str | None = None,
    required_room_id: str | None = None,
    required_starts_at: datetime | None = None,
) -> list[dict]:
    timezone = ZoneInfo(settings.practice_timezone)
    now_local = datetime.now(timezone)
    today = now_local.date()
    horizon_date = today + timedelta(days=settings.scheduling_horizon_days)
    effective_start = max(start_date, today)
    effective_end = min(end_date, horizon_date)
    if effective_end < effective_start:
        return []

    patient_windows = _future_patient_windows(
        effective_start,
        effective_end,
        start_time,
        end_time,
        timezone,
        now_local,
    )
    if not patient_windows:
        return []
    window_start = patient_windows[0].start.astimezone(UTC)
    window_end = patient_windows[-1].end.astimezone(UTC)

    closure_rows = connection.execute(
        """
        SELECT lower(closed_during) AS starts_at, upper(closed_during) AS ends_at
          FROM practice_closures
         WHERE closed_during && tstzrange(%s, %s, '[)')
        """,
        (window_start, window_end),
    ).fetchall()
    closures = [Interval(row["starts_at"], row["ends_at"]) for row in closure_rows]

    reserved_block_rows = connection.execute(
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
            id=str(row["id"]),
            doctor_id=str(row["doctor_id"]),
            procedure_code=row["procedure_code"],
            interval=Interval(row["starts_at"], row["ends_at"]),
            room_id=str(row["room_id"]) if row["room_id"] else None,
            equipment_unit_id=(
                f"{row['equipment_id']}:{row['equipment_unit_number']}"
                if row["equipment_id"] else None
            ),
        )
        for row in reserved_block_rows
    )

    phase_rows = connection.execute(
        """
        SELECT code, name, required_role,
               CASE WHEN %s = 'complex'
                    THEN COALESCE(complex_duration_minutes, duration_minutes)
                    ELSE duration_minutes END AS duration_minutes
          FROM procedure_phase_templates
         WHERE procedure_id = %s AND active
         ORDER BY sequence
        """,
        (difficulty, procedure["id"]),
    ).fetchall()
    phases = tuple(
        ProcedurePhase(
            row["code"], row["name"], row["required_role"],
            timedelta(minutes=row["duration_minutes"]),
        )
        for row in phase_rows
    )
    total_minutes = sum((row["duration_minutes"] for row in phase_rows), 0) or (
        procedure["preparation_minutes"]
        + procedure["duration_minutes"]
        + procedure["cleanup_minutes"]
    )

    doctor_rows = connection.execute(
        """
        SELECT d.id, d.display_name, d.staff_code, d.max_active_rooms, pv.id AS provider_id,
               COALESCE(pref.preference, 0) AS preference,
               q.effective_from AS qualification_from,
               q.effective_through AS qualification_through
          FROM doctors d
          JOIN providers pv ON pv.doctor_id = d.id AND pv.active
          JOIN doctor_procedure_qualifications q ON q.doctor_id = d.id
          LEFT JOIN provider_procedure_preferences pref
            ON pref.provider_id = pv.id AND pref.procedure_id = q.procedure_id
         WHERE q.procedure_id = %s
           AND d.active
           AND q.effective_from <= %s
           AND (q.effective_through IS NULL OR q.effective_through >= %s)
         ORDER BY d.display_name
        """,
        (procedure["id"], effective_end, effective_start),
    ).fetchall()
    if required_doctor_id:
        doctor_rows = [row for row in doctor_rows if str(row["id"]) == required_doctor_id]
    doctors: list[Doctor] = []
    for row in doctor_rows:
        hours = connection.execute(
            """
            SELECT weekday, local_start, local_end, effective_from, effective_through
              FROM provider_working_hours
             WHERE provider_id = %s
               AND effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
            """,
            (row["provider_id"], effective_end, effective_start),
        ).fetchall()
        leave_rows = connection.execute(
            """
            SELECT lower(unavailable_during) AS starts_at, upper(unavailable_during) AS ends_at
              FROM provider_unavailability
             WHERE provider_id = %s
               AND unavailable_during && tstzrange(%s, %s, '[)')
            """,
            (row["provider_id"], window_start, window_end),
        ).fetchall()
        exclusions = closures + [Interval(item["starts_at"], item["ends_at"]) for item in leave_rows]

        protected: list[Interval] = []
        if procedure["code"] != "emergency":
            rules = connection.execute(
                """
                SELECT weekday, local_start, local_end, release_hours_before
                  FROM emergency_capacity_rules WHERE active
                """
            ).fetchall()
            for day in daterange(effective_start, effective_end):
                for rule in rules:
                    if rule["weekday"] != day.weekday():
                        continue
                    interval = local_interval(day, rule["local_start"], rule["local_end"], timezone)
                    if interval.start - now_local > timedelta(hours=rule["release_hours_before"]):
                        protected.append(interval)

        target_row = connection.execute(
            """
            SELECT target_cents FROM provider_daily_targets
             WHERE provider_id = %s AND weekday = %s
               AND effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
             ORDER BY effective_from DESC LIMIT 1
            """,
            (row["provider_id"], effective_start.weekday(), effective_start, effective_start),
        ).fetchone()
        credited = connection.execute(
            """
            SELECT COALESCE(sum(c.amount_cents), 0) AS amount
              FROM appointment_production_credits c
              JOIN appointments a ON a.id = c.appointment_id
             WHERE c.provider_id = %s
               AND (a.starts_at AT TIME ZONE %s)::date = %s
               AND a.status IN ('confirmed', 'completed')
            """,
            (row["provider_id"], settings.practice_timezone, effective_start),
        ).fetchone()["amount"]
        target_gap = max((target_row["target_cents"] if target_row else 0) - credited, 0)
        availability = _availability_from_hours(
            hours, effective_start, effective_end, timezone, exclusions,
            _shift_overrides(connection, str(row["provider_id"]), effective_start, effective_end),
        )
        availability = _limit_to_effective_dates(
            availability,
            row["qualification_from"],
            row["qualification_through"],
        )
        doctors.append(
            Doctor(
                id=str(row["id"]),
                display_name=row["display_name"],
                qualified_procedure_codes=frozenset({procedure["code"]}),
                availability=availability,
                provider_id=str(row["provider_id"]),
                procedure_preference=row["preference"],
                production_gap_cents=target_gap,
                protected_intervals=tuple(protected),
                max_active_visits=row["max_active_rooms"],
            )
        )

    support_rows = connection.execute(
        """
        SELECT id, display_name, role::text AS role
          FROM providers WHERE active AND role IN ('assistant', 'hygienist')
         ORDER BY display_name
        """
    ).fetchall()
    providers: list[Provider] = []
    for row in support_rows:
        hours = connection.execute(
            """
            SELECT weekday, local_start, local_end, effective_from, effective_through
              FROM provider_working_hours
             WHERE provider_id = %s
               AND effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
            """,
            (row["id"], effective_end, effective_start),
        ).fetchall()
        leave_rows = connection.execute(
            """
            SELECT lower(unavailable_during) AS starts_at, upper(unavailable_during) AS ends_at
              FROM provider_unavailability
             WHERE provider_id = %s
               AND unavailable_during && tstzrange(%s, %s, '[)')
            """,
            (row["id"], window_start, window_end),
        ).fetchall()
        exclusions = closures + [Interval(item["starts_at"], item["ends_at"]) for item in leave_rows]
        providers.append(
            Provider(
                id=str(row["id"]),
                display_name=row["display_name"],
                role=row["role"],
                availability=_availability_from_hours(
                    hours, effective_start, effective_end, timezone, exclusions,
                    _shift_overrides(connection, str(row["id"]), effective_start, effective_end),
                ),
            )
        )

    room_rows = connection.execute(
        """
        SELECT r.id, r.name
          FROM rooms r
          JOIN procedure_room_eligibility e ON e.room_id = r.id
         WHERE e.procedure_id = %s AND r.active
         ORDER BY r.name
        """,
        (procedure["id"],),
    ).fetchall()
    if required_room_id:
        room_rows = [row for row in room_rows if str(row["id"]) == required_room_id]
    rooms: list[Room] = []
    for row in room_rows:
        hours = connection.execute(
            """
            SELECT weekday, local_start, local_end, effective_from, effective_through
              FROM room_working_hours
             WHERE room_id = %s
               AND effective_from <= %s
               AND (effective_through IS NULL OR effective_through >= %s)
            """,
            (row["id"], effective_end, effective_start),
        ).fetchall()
        rooms.append(
            Room(
                id=str(row["id"]),
                display_name=row["name"],
                supported_procedure_codes=frozenset({procedure["code"]}),
                availability=_availability_from_hours(hours, effective_start, effective_end, timezone, closures),
            )
        )

    appointment_rows = connection.execute(
        """
        SELECT id, patient_id, doctor_id, room_id, starts_at, ends_at, status::text AS status
          FROM appointments
         WHERE status IN ('held', 'confirmed')
           AND starts_at < %s AND ends_at > %s
           AND (%s::uuid IS NULL OR id <> %s::uuid)
        """,
        (window_end, window_start, reschedules_appointment_id, reschedules_appointment_id),
    ).fetchall()
    appointments = [
        Appointment(
            id=str(row["id"]), patient_id=str(row["patient_id"]),
            doctor_id=str(row["doctor_id"]),
            room_id=str(row["room_id"]) if row["room_id"] else None,
            interval=Interval(row["starts_at"], row["ends_at"]),
            active=True, locked=row["status"] == "confirmed",
        )
        for row in appointment_rows
    ]
    phase_reservation_rows = connection.execute(
        """
        SELECT ap.appointment_id, ap.provider_id, ap.starts_at, ap.ends_at
          FROM appointment_phases ap
          JOIN appointments a ON a.id = ap.appointment_id
         WHERE ap.active AND ap.provider_id IS NOT NULL
           AND ap.starts_at < %s AND ap.ends_at > %s
           AND (%s::uuid IS NULL OR ap.appointment_id <> %s::uuid)
           AND a.status IN ('held', 'confirmed')
        """,
        (window_end, window_start, reschedules_appointment_id, reschedules_appointment_id),
    ).fetchall()
    reservations = [
        ResourceReservation(
            appointment_id=str(row["appointment_id"]), provider_id=str(row["provider_id"]),
            interval=Interval(row["starts_at"], row["ends_at"]),
        )
        for row in phase_reservation_rows
    ]

    equipment_requirement_rows = connection.execute(
        """
        SELECT e.id, e.name, e.quantity AS available_quantity, r.quantity AS required_quantity
          FROM procedure_equipment_requirements r
          JOIN equipment e ON e.id = r.equipment_id AND e.active
         WHERE r.procedure_id = %s
         ORDER BY e.code
        """,
        (procedure["id"],),
    ).fetchall()
    equipment_units: list[EquipmentUnit] = []
    equipment_windows = tuple(
        piece
        for day in daterange(effective_start, effective_end)
        for piece in _subtract(local_interval(day, start_time, end_time, timezone), closures)
    )
    for equipment in equipment_requirement_rows:
        for unit_number in range(1, equipment["available_quantity"] + 1):
            equipment_units.append(
                EquipmentUnit(
                    id=f"{equipment['id']}:{unit_number}",
                    equipment_id=str(equipment["id"]),
                    display_name=equipment["name"],
                    unit_number=unit_number,
                    availability=equipment_windows,
                )
            )
    equipment_reservation_rows = connection.execute(
        """
        SELECT appointment_id, equipment_id, unit_number, starts_at, ends_at
          FROM appointment_equipment_reservations
         WHERE active AND starts_at < %s AND ends_at > %s
           AND (%s::uuid IS NULL OR appointment_id <> %s::uuid)
        """,
        (window_end, window_start, reschedules_appointment_id, reschedules_appointment_id),
    ).fetchall()
    equipment_reservations = [
        EquipmentReservation(
            appointment_id=str(row["appointment_id"]),
            unit_id=f"{row['equipment_id']}:{row['unit_number']}",
            interval=Interval(row["starts_at"], row["ends_at"]),
        )
        for row in equipment_reservation_rows
    ]

    request = SchedulingRequest(
        id=scheduling_request_id,
        patient_id=patient_id,
        procedure_code=procedure["code"],
        duration=timedelta(minutes=total_minutes),
        patient_availability=patient_windows,
        preferred_doctor_id=preferred_doctor_id,
        phases=phases,
        priority=priority,
        required_equipment=tuple(
            (str(row["id"]), row["required_quantity"])
            for row in equipment_requirement_rows
        ),
        allow_reserved_block_override=allow_reserved_block_override,
    )
    result = recommend_slots(
        request, doctors, rooms, appointments,
        horizon_end=datetime.combine(horizon_date + timedelta(days=1), time.min, tzinfo=timezone),
        grid_minutes=30,
        limit=5,
        providers=providers,
        reservations=reservations,
        equipment_units=equipment_units,
        equipment_reservations=equipment_reservations,
        reserved_blocks=reserved_blocks,
    )

    stored = []
    candidates = result.candidates
    if required_starts_at is not None:
        candidates = tuple(
            candidate for candidate in candidates
            if candidate.interval.start == required_starts_at
        )
    for candidate in candidates:
        phase_plan = _phase_payload(candidate)
        row = connection.execute(
            """
            INSERT INTO recommendation_snapshots (
                scheduling_request_id, reschedules_appointment_id, doctor_id,
                room_id, starts_at, ends_at, score, explanation, phase_plan,
                production_cents, equipment_plan, created_by, expires_at,
                reserved_block_conflicts, requires_reserved_block_override
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      transaction_timestamp() + interval '15 minutes', %s, %s)
            RETURNING id
            """,
            (
                scheduling_request_id, reschedules_appointment_id,
                candidate.doctor_id, candidate.room_id,
                candidate.interval.start, candidate.interval.end,
                candidate.score, json.dumps(candidate.explanation), json.dumps(phase_plan),
                procedure.get("production_cents", 0),
                json.dumps([
                    {"equipment_id": unit_id.rsplit(":", 1)[0],
                     "unit_number": int(unit_id.rsplit(":", 1)[1])}
                    for unit_id in candidate.equipment_unit_ids
                ]),
                actor_id,
                json.dumps(list(candidate.reserved_block_ids)),
                candidate.requires_reserved_block_override,
            ),
        ).fetchone()
        stored.append(
            {
                "id": str(row["id"]), "doctor_id": candidate.doctor_id,
                "doctor_name": candidate.doctor_name, "room_id": candidate.room_id,
                "room_name": candidate.room_name,
                "starts_at": candidate.interval.start.isoformat(),
                "ends_at": candidate.interval.end.isoformat(),
                "score": candidate.score, "explanation": list(candidate.explanation),
                "phases": phase_plan, "production_cents": procedure.get("production_cents", 0),
                "equipment": [
                    {"equipment_id": unit_id.rsplit(":", 1)[0],
                     "unit_number": int(unit_id.rsplit(":", 1)[1])}
                    for unit_id in candidate.equipment_unit_ids
                ],
                "reserved_block_ids": list(candidate.reserved_block_ids),
                "requires_reserved_block_override": candidate.requires_reserved_block_override,
            }
        )
    return stored
