#!/usr/bin/env python3
"""Replay synthetic CSV requests through the deterministic optimizer."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time as wall_time
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1]))

from siligent_optimizer import (  # noqa: E402
    Appointment,
    Doctor,
    EquipmentReservation,
    EquipmentUnit,
    Interval,
    ProcedurePhase,
    Provider,
    ResourceReservation,
    Room,
    SchedulingRequest,
    recommend_slots,
)


TIMEZONE = ZoneInfo("America/New_York")
DEFAULT_INPUT = Path("data/synthetic/synthetic_appointment_requests_100.csv")
DEFAULT_OUTPUT = Path("data/synthetic/synthetic_schedule_results_100.csv")
DEFAULT_REPORT = Path("data/synthetic/synthetic_simulation_report_100.json")

PROCEDURE_PHASES = {
    "exam": (("assistant", 10), ("doctor", 20), ("assistant", 10)),
    "cleaning": (("hygienist", 40), ("doctor", 10), ("hygienist", 10)),
    "filling": (("assistant", 10), ("doctor", 30), ("assistant", 30), ("room", 10)),
    "crown": (("assistant", 10), ("doctor", 60), ("assistant", 30), ("room", 15)),
    "crown-seat": (("assistant", 10), ("doctor", 20), ("assistant", 10)),
    "root-canal": (("assistant", 10), ("doctor", 90), ("assistant", 15)),
    "extraction": (("assistant", 15), ("doctor", 60), ("assistant", 15)),
    "implant": (("assistant", 10), ("doctor", 80), ("assistant", 20), ("room", 10)),
    "emergency": (("assistant", 10), ("doctor", 30), ("assistant", 20)),
}

PROCEDURE_EQUIPMENT = {
    "exam": ("xray", 1),
    "crown": ("scanner", 1),
    "root-canal": ("microscope", 1),
    "extraction": ("surgical-kit", 1),
    "implant": ("implant-kit", 1),
}

RESULT_FIELDS = (
    "request_id",
    "patient_ref",
    "procedure_code",
    "difficulty",
    "priority",
    "result",
    "doctor_id",
    "doctor_name",
    "room_id",
    "room_name",
    "starts_at",
    "ends_at",
    "wait_days",
    "expected_production_cents",
    "locked",
    "blocking_reason",
)


def work_windows(start: date, end: date) -> tuple[Interval, ...]:
    windows: list[Interval] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            windows.append(
                Interval(
                    datetime.combine(current, time(8), tzinfo=TIMEZONE),
                    datetime.combine(current, time(17), tzinfo=TIMEZONE),
                )
            )
        current += timedelta(days=1)
    return tuple(windows)


def patient_windows(row: dict[str, str]) -> tuple[Interval, ...]:
    first = date.fromisoformat(row["availability_start_date"])
    last = date.fromisoformat(row["availability_end_date"])
    start_at = time.fromisoformat(row["daily_start_time"])
    end_at = time.fromisoformat(row["daily_end_time"])
    if last < first or end_at <= start_at:
        raise ValueError(f"{row['request_id']}: invalid availability window")
    windows: list[Interval] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            windows.append(
                Interval(
                    datetime.combine(current, start_at, tzinfo=TIMEZONE),
                    datetime.combine(current, end_at, tzinfo=TIMEZONE),
                )
            )
        current += timedelta(days=1)
    if not windows:
        raise ValueError(f"{row['request_id']}: availability contains no working day")
    return tuple(windows)


def phases_for(procedure_code: str, difficulty: str) -> tuple[ProcedurePhase, ...]:
    try:
        template = PROCEDURE_PHASES[procedure_code]
    except KeyError as error:
        raise ValueError(f"unknown procedure code: {procedure_code}") from error
    phases: list[ProcedurePhase] = []
    for index, (role, base_minutes) in enumerate(template, 1):
        minutes = base_minutes
        if difficulty == "complex" and role == "doctor":
            minutes = round((base_minutes * 1.5) / 5) * 5
        phases.append(
            ProcedurePhase(
                f"{role}-{index}",
                f"{role.title()} phase",
                role,
                timedelta(minutes=minutes),
            )
        )
    return tuple(phases)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as input_file:
        rows = list(csv.DictReader(input_file))
    if not rows:
        raise ValueError("input CSV contains no appointment requests")
    request_ids = [row.get("request_id", "") for row in rows]
    if any(not item for item in request_ids) or len(set(request_ids)) != len(request_ids):
        raise ValueError("request_id values must be present and unique")
    patient_refs = [row.get("patient_ref", "") for row in rows]
    if any(not item for item in patient_refs) or len(set(patient_refs)) != len(patient_refs):
        raise ValueError("patient_ref values must be present and unique")
    for row in rows:
        if row.get("status") != "requested" or row.get("locked", "").lower() != "false":
            raise ValueError(f"{row['request_id']}: input must be an unlocked request")
        if row.get("allow_reserved_block_override", "").lower() != "false":
            raise ValueError(f"{row['request_id']}: synthetic replay cannot bypass reserved capacity")
        received_at = datetime.fromisoformat(row.get("request_received_at", ""))
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError(f"{row['request_id']}: request_received_at must include a timezone")
    return sorted(
        rows,
        key=lambda row: (datetime.fromisoformat(row["request_received_at"]), row["request_id"]),
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def validate_locked_schedule(
    appointments: list[Appointment],
    reservations: list[ResourceReservation],
    equipment_reservations: list[EquipmentReservation],
    locked_originals: dict[str, Interval],
) -> list[str]:
    failures: list[str] = []
    for appointment in appointments:
        if not appointment.locked:
            failures.append(f"{appointment.id}: confirmed appointment is not locked")
        if locked_originals.get(appointment.id) != appointment.interval:
            failures.append(f"{appointment.id}: locked appointment moved")
    for index, first in enumerate(appointments):
        for second in appointments[index + 1 :]:
            if not first.interval.overlaps(second.interval):
                continue
            if first.patient_id == second.patient_id:
                failures.append(f"{first.id}/{second.id}: patient overlap")
            if first.room_id == second.room_id:
                failures.append(f"{first.id}/{second.id}: room overlap")
    for index, first in enumerate(reservations):
        for second in reservations[index + 1 :]:
            if first.provider_id == second.provider_id and first.interval.overlaps(second.interval):
                failures.append(f"{first.appointment_id}/{second.appointment_id}: provider overlap")
    for index, first in enumerate(equipment_reservations):
        for second in equipment_reservations[index + 1 :]:
            if first.unit_id == second.unit_id and first.interval.overlaps(second.interval):
                failures.append(f"{first.appointment_id}/{second.appointment_id}: equipment overlap")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_rows(args.input)
    first_day = min(date.fromisoformat(row["availability_start_date"]) for row in rows)
    last_day = max(date.fromisoformat(row["availability_end_date"]) for row in rows)
    availability = work_windows(first_day, last_day)
    procedure_codes = frozenset(PROCEDURE_PHASES)
    doctors = tuple(
        Doctor(
            id=doctor_code,
            display_name=f"Doctor {number}",
            qualified_procedure_codes=procedure_codes,
            availability=availability,
            provider_id=f"provider-{doctor_code.lower()}",
            max_active_visits=3,
        )
        for number, doctor_code in enumerate(("DR-PATEL", "DR-LEE", "DR-MARTINEZ"), 1)
    )
    providers = tuple(
        Provider(f"hygienist-{number}", f"Hygienist {number}", "hygienist", availability)
        for number in range(1, 6)
    ) + tuple(
        Provider(f"assistant-{number}", f"Assistant {number}", "assistant", availability)
        for number in range(1, 5)
    )
    rooms = (
        Room("room-1", "General Operatory 1", procedure_codes, availability),
        Room("room-2", "General Operatory 2", procedure_codes, availability),
        Room("room-3", "Hygiene Operatory 3", frozenset({"exam", "cleaning", "emergency"}), availability),
        Room("room-4", "Hygiene Operatory 4", frozenset({"exam", "cleaning", "emergency"}), availability),
        Room("room-5", "Hygiene Operatory 5", frozenset({"exam", "cleaning", "emergency"}), availability),
        Room("room-6", "Exam Operatory 1", frozenset({"exam", "filling", "crown", "crown-seat", "root-canal", "emergency"}), availability),
        Room("room-7", "Exam Operatory 2", frozenset({"exam", "filling", "crown", "crown-seat", "root-canal", "emergency"}), availability),
        Room("room-8", "Surgical Suite", frozenset({"extraction", "implant", "emergency"}), availability),
    )
    unit_counts = {"xray": 2, "scanner": 1, "microscope": 1, "surgical-kit": 2, "implant-kit": 1}
    equipment_units = tuple(
        EquipmentUnit(
            id=f"{equipment_id}:{number}",
            equipment_id=equipment_id,
            display_name=f"{equipment_id.replace('-', ' ').title()} {number}",
            unit_number=number,
            availability=availability,
        )
        for equipment_id, count in unit_counts.items()
        for number in range(1, count + 1)
    )

    appointments: list[Appointment] = []
    reservations: list[ResourceReservation] = []
    equipment_reservations: list[EquipmentReservation] = []
    locked_originals: dict[str, Interval] = {}
    results: list[dict[str, object]] = []
    waits: list[float] = []
    scheduled_by_procedure: Counter[str] = Counter()
    scheduled_by_doctor: Counter[str] = Counter()
    unscheduled_by_procedure: Counter[str] = Counter()
    scheduled_production_cents = 0
    started = wall_time.perf_counter()
    horizon_end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=TIMEZONE)

    for row in rows:
        windows = patient_windows(row)
        phases = phases_for(row["procedure_code"], row["difficulty"])
        minutes = int(sum((phase.duration for phase in phases), timedelta(0)).total_seconds() // 60)
        if minutes != int(row["scheduled_minutes"]):
            raise ValueError(f"{row['request_id']}: scheduled_minutes does not match procedure phases")
        equipment = PROCEDURE_EQUIPMENT.get(row["procedure_code"])
        request = SchedulingRequest(
            id=row["request_id"],
            patient_id=row["patient_ref"],
            procedure_code=row["procedure_code"],
            duration=timedelta(minutes=minutes),
            patient_availability=windows,
            preferred_intervals=windows,
            preferred_doctor_id=row["preferred_doctor_code"] or None,
            established_doctor_id=row["established_doctor_code"] or None,
            phases=phases,
            priority=row["priority"],
            required_equipment=(equipment,) if equipment else (),
            allow_reserved_block_override=False,
        )
        recommendation = recommend_slots(
            request,
            doctors,
            rooms,
            appointments,
            horizon_end=horizon_end,
            grid_minutes=30,
            limit=5,
            providers=providers,
            reservations=reservations,
            equipment_units=equipment_units,
            equipment_reservations=equipment_reservations,
        )
        base_result = {
            "request_id": row["request_id"],
            "patient_ref": row["patient_ref"],
            "procedure_code": row["procedure_code"],
            "difficulty": row["difficulty"],
            "priority": row["priority"],
            "expected_production_cents": int(row["expected_production_cents"]),
        }
        if not recommendation.candidates:
            unscheduled_by_procedure[row["procedure_code"]] += 1
            results.append(
                {
                    **base_result,
                    "result": "unscheduled",
                    "doctor_id": "",
                    "doctor_name": "",
                    "room_id": "",
                    "room_name": "",
                    "starts_at": "",
                    "ends_at": "",
                    "wait_days": "",
                    "locked": "false",
                    "blocking_reason": "; ".join(recommendation.blocking_reasons),
                }
            )
            continue

        chosen = recommendation.candidates[0]
        appointment_id = f"SIM-APT-{row['request_id'].removeprefix('SIM-REQ-')}"
        appointment = Appointment(
            id=appointment_id,
            patient_id=row["patient_ref"],
            doctor_id=chosen.doctor_id,
            room_id=chosen.room_id,
            interval=chosen.interval,
            locked=True,
        )
        appointments.append(appointment)
        locked_originals[appointment_id] = appointment.interval
        reservations.extend(
            ResourceReservation(appointment_id, phase.provider_id, phase.interval)
            for phase in chosen.phases
            if phase.provider_id
        )
        equipment_reservations.extend(
            EquipmentReservation(appointment_id, unit_id, chosen.interval)
            for unit_id in chosen.equipment_unit_ids
        )
        wait_days = (chosen.interval.start - windows[0].start).total_seconds() / 86400
        waits.append(wait_days)
        scheduled_by_procedure[row["procedure_code"]] += 1
        scheduled_by_doctor[chosen.doctor_id] += 1
        scheduled_production_cents += int(row["expected_production_cents"])
        results.append(
            {
                **base_result,
                "result": "scheduled",
                "doctor_id": chosen.doctor_id,
                "doctor_name": chosen.doctor_name,
                "room_id": chosen.room_id,
                "room_name": chosen.room_name,
                "starts_at": chosen.interval.start.isoformat(),
                "ends_at": chosen.interval.end.isoformat(),
                "wait_days": round(wait_days, 2),
                "locked": "true",
                "blocking_reason": "",
            }
        )

    failures = validate_locked_schedule(
        appointments, reservations, equipment_reservations, locked_originals
    )
    scheduled_count = len(appointments)
    report = {
        "input_file": str(args.input),
        "input_rows": len(rows),
        "simulation_timezone": str(TIMEZONE),
        "scheduled": scheduled_count,
        "unscheduled": len(rows) - scheduled_count,
        "schedule_rate_percent": round(100 * scheduled_count / len(rows), 1),
        "confirmed_and_locked": scheduled_count,
        "locked_appointments_moved": sum(
            1 for item in appointments if locked_originals[item.id] != item.interval
        ),
        "mean_wait_days": round(statistics.mean(waits), 2) if waits else 0,
        "p95_wait_days": round(percentile(waits, 0.95), 2),
        "scheduled_production_cents": scheduled_production_cents,
        "scheduled_by_procedure": dict(sorted(scheduled_by_procedure.items())),
        "unscheduled_by_procedure": dict(sorted(unscheduled_by_procedure.items())),
        "scheduled_by_doctor": dict(sorted(scheduled_by_doctor.items())),
        "runtime_seconds": round(wall_time.perf_counter() - started, 3),
        "invariant_failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Schedule results: {args.output}")
    print(f"Simulation report: {args.report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
