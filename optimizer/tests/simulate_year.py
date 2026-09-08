"""Deterministic, synthetic year-horizon scheduling simulation."""

from __future__ import annotations

import json
import random
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
    Interval,
    Room,
    SchedulingRequest,
    recommend_slots,
)


SEED = 20260819
PATIENT_COUNT = 220
DELIBERATELY_INFEASIBLE = 20
TIMEZONE = ZoneInfo("America/New_York")

PROCEDURES = {
    "exam": (timedelta(minutes=40), frozenset({"xray"})),
    "cleaning": (timedelta(minutes=60), frozenset()),
    "filling": (timedelta(minutes=80), frozenset()),
    "crown": (timedelta(minutes=115), frozenset()),
    "root-canal": (timedelta(minutes=115), frozenset({"microscope"})),
    "extraction": (timedelta(minutes=90), frozenset({"surgical-kit"})),
    "emergency": (timedelta(minutes=60), frozenset()),
}

QUALIFICATIONS = {
    "doctor-general-a": frozenset({"exam", "cleaning", "filling", "crown", "emergency"}),
    "doctor-general-b": frozenset({"exam", "cleaning", "filling", "crown", "emergency"}),
    "doctor-endo": frozenset({"exam", "root-canal", "emergency"}),
    "doctor-surgery": frozenset({"exam", "extraction", "emergency"}),
}

ROOM_SUPPORT = {
    "room-1": frozenset(PROCEDURES),
    "room-2": frozenset(PROCEDURES),
    "room-surgery": frozenset({"exam", "extraction", "emergency"}),
}


def next_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def work_windows(start: date, end: date) -> tuple[Interval, ...]:
    windows = []
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


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile)))
    return ordered[index]


def validate_schedule(
    appointments: list[Appointment],
    doctors: dict[str, Doctor],
    rooms: dict[str, Room],
    locked_originals: dict[str, Interval],
    horizon_end: datetime,
) -> list[str]:
    failures: list[str] = []
    for appointment in appointments:
        if appointment.interval.end > horizon_end:
            failures.append(f"{appointment.id}: beyond horizon")
        if not any(window.contains(appointment.interval) for window in doctors[appointment.doctor_id].availability):
            failures.append(f"{appointment.id}: outside doctor availability")
        if appointment.room_id and not any(
            window.contains(appointment.interval) for window in rooms[appointment.room_id].availability
        ):
            failures.append(f"{appointment.id}: outside room availability")
        original = locked_originals.get(appointment.id)
        if original is not None and original != appointment.interval:
            failures.append(f"{appointment.id}: locked appointment moved")

    for index, first in enumerate(appointments):
        for second in appointments[index + 1 :]:
            if not first.interval.overlaps(second.interval):
                continue
            if first.patient_id == second.patient_id:
                failures.append(f"{first.id}/{second.id}: patient overlap")
            if first.doctor_id == second.doctor_id:
                failures.append(f"{first.id}/{second.id}: doctor overlap")
            if first.room_id and first.room_id == second.room_id:
                failures.append(f"{first.id}/{second.id}: room overlap")
            if first.equipment_ids & second.equipment_ids:
                failures.append(f"{first.id}/{second.id}: equipment overlap")
    return failures


def main() -> int:
    randomizer = random.Random(SEED)
    simulation_start = next_weekday(date.today() + timedelta(days=1))
    horizon_last_day = simulation_start + timedelta(days=364)
    horizon_end = datetime.combine(
        horizon_last_day + timedelta(days=1), time.min, tzinfo=TIMEZONE
    )
    all_windows = work_windows(simulation_start, horizon_last_day)
    doctors = {
        doctor_id: Doctor(
            id=doctor_id,
            display_name=doctor_id.replace("-", " ").title(),
            qualified_procedure_codes=qualifications,
            availability=all_windows,
        )
        for doctor_id, qualifications in QUALIFICATIONS.items()
    }
    rooms = {
        room_id: Room(
            id=room_id,
            display_name=room_id.replace("-", " ").title(),
            supported_procedure_codes=support,
            availability=all_windows,
        )
        for room_id, support in ROOM_SUPPORT.items()
    }

    appointments: list[Appointment] = []
    locked_originals: dict[str, Interval] = {}
    weekdays = [window for window in all_windows[:90]]
    doctor_room_pairs = [
        ("doctor-general-a", "room-1"),
        ("doctor-general-b", "room-2"),
        ("doctor-surgery", "room-surgery"),
    ]
    for index, window in enumerate(weekdays):
        doctor_id, room_id = doctor_room_pairs[index % len(doctor_room_pairs)]
        start = window.start + timedelta(hours=1 + (index % 4))
        interval = Interval(start, start + timedelta(minutes=60))
        appointment = Appointment(
            id=f"locked-{index:03d}",
            patient_id=f"existing-patient-{index:03d}",
            doctor_id=doctor_id,
            room_id=room_id,
            interval=interval,
            locked=True,
        )
        appointments.append(appointment)
        locked_originals[appointment.id] = appointment.interval

    procedure_choices = list(PROCEDURES)
    scheduled_by_procedure: Counter[str] = Counter()
    scheduled_by_doctor: Counter[str] = Counter()
    unscheduled_by_procedure: Counter[str] = Counter()
    unexpected_unscheduled = 0
    waits_days: list[float] = []
    examined_candidates = 0
    started = wall_time.perf_counter()

    for index in range(PATIENT_COUNT):
        deliberately_infeasible = index >= PATIENT_COUNT - DELIBERATELY_INFEASIBLE
        procedure_code = "root-canal" if deliberately_infeasible else randomizer.choices(
            procedure_choices, weights=[24, 22, 18, 10, 9, 8, 9], k=1
        )[0]
        offset = randomizer.randint(0, 330)
        requested_start = next_weekday(simulation_start + timedelta(days=offset))
        search_days = 3 if procedure_code == "emergency" else randomizer.choice([7, 14, 21])
        requested_end = min(horizon_last_day, requested_start + timedelta(days=search_days))
        day_start = time(16) if deliberately_infeasible else randomizer.choice(
            [time(8), time(9), time(10), time(12)]
        )
        day_end = time(17) if deliberately_infeasible else randomizer.choice(
            [time(14), time(15), time(16), time(17)]
        )
        if day_end <= day_start:
            day_end = time(17)
        patient_windows = tuple(
            window
            for window in work_windows(requested_start, requested_end)
            if window.end.time() > day_start and window.start.time() < day_end
        )
        patient_windows = tuple(
            Interval(
                datetime.combine(window.start.date(), day_start, tzinfo=TIMEZONE),
                datetime.combine(window.start.date(), day_end, tzinfo=TIMEZONE),
            )
            for window in patient_windows
        )
        if not patient_windows:
            unscheduled_by_procedure[procedure_code] += 1
            if not deliberately_infeasible:
                unexpected_unscheduled += 1
            continue
        eligible_doctors = [
            doctor for doctor in doctors.values()
            if procedure_code in doctor.qualified_procedure_codes
        ]
        preferred_doctor = randomizer.choice(eligible_doctors).id if randomizer.random() < 0.35 else None
        duration, equipment_ids = PROCEDURES[procedure_code]
        request = SchedulingRequest(
            id=f"request-{index:03d}",
            patient_id=f"new-patient-{index:03d}",
            procedure_code=procedure_code,
            duration=duration,
            patient_availability=patient_windows,
            required_equipment_ids=equipment_ids,
            preferred_intervals=patient_windows,
            preferred_doctor_id=preferred_doctor,
        )
        result = recommend_slots(
            request,
            doctors.values(),
            rooms.values(),
            appointments,
            horizon_end=horizon_end,
            limit=5,
        )
        examined_candidates += len(result.candidates)
        if not result.candidates:
            unscheduled_by_procedure[procedure_code] += 1
            if not deliberately_infeasible:
                unexpected_unscheduled += 1
            continue
        choice = result.candidates[0]
        appointments.append(
            Appointment(
                id=f"scheduled-{index:03d}",
                patient_id=request.patient_id,
                doctor_id=choice.doctor_id,
                room_id=choice.room_id,
                interval=choice.interval,
                equipment_ids=equipment_ids,
                locked=True,
            )
        )
        scheduled_by_procedure[procedure_code] += 1
        scheduled_by_doctor[choice.doctor_id] += 1
        waits_days.append(
            (choice.interval.start - patient_windows[0].start).total_seconds() / 86400
        )

    runtime_seconds = wall_time.perf_counter() - started
    failures = validate_schedule(
        appointments, doctors, rooms, locked_originals, horizon_end
    )
    scheduled_count = sum(scheduled_by_procedure.values())
    unscheduled_count = sum(unscheduled_by_procedure.values())
    report = {
        "seed": SEED,
        "horizon_days": 365,
        "new_patients": PATIENT_COUNT,
        "deliberately_infeasible": DELIBERATELY_INFEASIBLE,
        "preexisting_locked": len(locked_originals),
        "scheduled": scheduled_count,
        "unscheduled": unscheduled_count,
        "unexpected_unscheduled": unexpected_unscheduled,
        "schedule_rate_percent": round(100 * scheduled_count / PATIENT_COUNT, 1),
        "mean_wait_days": round(statistics.mean(waits_days), 2) if waits_days else 0,
        "p95_wait_days": round(percentile(waits_days, 0.95), 2),
        "recommendations_returned": examined_candidates,
        "runtime_seconds": round(runtime_seconds, 3),
        "scheduled_by_procedure": dict(sorted(scheduled_by_procedure.items())),
        "unscheduled_by_procedure": dict(sorted(unscheduled_by_procedure.items())),
        "scheduled_by_doctor": dict(sorted(scheduled_by_doctor.items())),
        "invariant_failures": failures,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
