"""Deterministic full-practice simulation for phased multi-room scheduling."""

from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, time as clock_time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from siligent_optimizer import (  # noqa: E402
    Appointment,
    Doctor,
    Interval,
    ProcedurePhase,
    Provider,
    ResourceReservation,
    Room,
    SchedulingRequest,
    recommend_slots,
)

SEED = 20260823
PROCEDURES = {
    "exam": (("assistant", 10), ("doctor", 20), ("assistant", 10)),
    "cleaning": (("hygienist", 40), ("doctor", 10), ("hygienist", 10)),
    "filling": (("assistant", 10), ("doctor", 30), ("assistant", 30), ("room", 10)),
    "crown": (("assistant", 10), ("doctor", 60), ("assistant", 30), ("room", 15)),
    "root-canal": (("assistant", 10), ("doctor", 90), ("assistant", 15)),
    "extraction": (("assistant", 15), ("doctor", 60), ("assistant", 15)),
    "implant": (("assistant", 10), ("doctor", 80), ("assistant", 20), ("room", 10)),
    "emergency": (("assistant", 10), ("doctor", 30), ("assistant", 20)),
}


def working_windows(start: date, days: int) -> tuple[Interval, ...]:
    windows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.weekday() < 5:
            windows.append(
                Interval(
                    datetime.combine(day, clock_time(8), tzinfo=UTC),
                    datetime.combine(day, clock_time(17), tzinfo=UTC),
                )
            )
    return tuple(windows)


def phases_for(code: str) -> tuple[ProcedurePhase, ...]:
    return tuple(
        ProcedurePhase(f"{role}-{index}", f"{role.title()} phase", role, timedelta(minutes=minutes))
        for index, (role, minutes) in enumerate(PROCEDURES[code], 1)
    )


def validate(
    appointments: list[Appointment],
    reservations: list[ResourceReservation],
    locked: dict[str, Interval],
) -> list[str]:
    failures = []
    for appointment in appointments:
        if appointment.id in locked and appointment.interval != locked[appointment.id]:
            failures.append(f"{appointment.id}: locked visit moved")
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
                failures.append(f"{first.appointment_id}/{second.appointment_id}: provider phase overlap")
    return failures


def main() -> int:
    randomizer = random.Random(SEED)
    horizon_start = date(2026, 8, 24)
    horizon_days = 365
    availability = working_windows(horizon_start, horizon_days)
    procedure_codes = frozenset(PROCEDURES)
    doctors = [
        Doctor(
            id=f"doctor-{number}", display_name=f"Doctor {number}",
            qualified_procedure_codes=procedure_codes, availability=availability,
            provider_id=f"provider-doctor-{number}",
        )
        for number in range(1, 4)
    ]
    support = [
        Provider(f"hygienist-{number}", f"Hygienist {number}", "hygienist", availability)
        for number in range(1, 6)
    ] + [
        Provider(f"assistant-{number}", f"Assistant {number}", "assistant", availability)
        for number in range(1, 5)
    ]
    rooms = [
        Room(f"room-{number}", f"Operatory {number}", procedure_codes, availability)
        for number in range(1, 9)
    ]
    appointments: list[Appointment] = []
    reservations: list[ResourceReservation] = []
    locked: dict[str, Interval] = {}
    scheduled_by_procedure: Counter[str] = Counter()
    scheduled_by_doctor: Counter[str] = Counter()
    unexpected_unscheduled = 0
    intentionally_rejected = 0

    started = time.perf_counter()
    total_requests = 420
    for index in range(total_requests):
        code = randomizer.choices(
            list(PROCEDURES), weights=[20, 24, 18, 8, 6, 7, 4, 5], k=1
        )[0]
        phase_templates = phases_for(code)
        duration = sum((phase.duration for phase in phase_templates), timedelta(0))
        day_offset = randomizer.randrange(0, 335)
        window_start = horizon_start + timedelta(days=day_offset)
        search_days = 3 if code == "emergency" else 14
        windows = working_windows(window_start, search_days)
        deliberately_infeasible = index >= total_requests - 20
        if deliberately_infeasible:
            code = "root-canal"
            phase_templates = phases_for(code)
            duration = sum((phase.duration for phase in phase_templates), timedelta(0))
            day = next(day for day in (window_start + timedelta(days=n) for n in range(7)) if day.weekday() < 5)
            windows = (
                Interval(
                    datetime.combine(day, clock_time(12), tzinfo=UTC),
                    datetime.combine(day, clock_time(13), tzinfo=UTC),
                ),
            )
        request = SchedulingRequest(
            id=f"request-{index}", patient_id=f"patient-{index}", procedure_code=code,
            duration=duration, patient_availability=windows, phases=phase_templates,
            priority="urgent" if code == "emergency" else "routine",
        )
        result = recommend_slots(
            request, doctors, rooms, appointments,
            horizon_end=datetime.combine(horizon_start + timedelta(days=horizon_days), clock_time.min, tzinfo=UTC),
            grid_minutes=30, limit=3, providers=support, reservations=reservations,
        )
        if not result.candidates:
            if deliberately_infeasible:
                intentionally_rejected += 1
            else:
                unexpected_unscheduled += 1
            continue
        chosen = result.candidates[0]
        appointment_id = f"appointment-{index}"
        appointment = Appointment(
            id=appointment_id, patient_id=request.patient_id, doctor_id=chosen.doctor_id,
            room_id=chosen.room_id, interval=chosen.interval, locked=True,
        )
        appointments.append(appointment)
        reservations.extend(
            ResourceReservation(appointment_id, phase.provider_id, phase.interval)
            for phase in chosen.phases if phase.provider_id
        )
        if index < 60:
            locked[appointment_id] = chosen.interval
        scheduled_by_procedure[code] += 1
        scheduled_by_doctor[chosen.doctor_id] += 1

    whole_visit_doctor_overlaps = 0
    for index, first in enumerate(appointments):
        for second in appointments[index + 1 :]:
            if first.doctor_id == second.doctor_id and first.interval.overlaps(second.interval):
                whole_visit_doctor_overlaps += 1
    failures = validate(appointments, reservations, locked)
    result = {
        "seed": SEED,
        "horizon_days": horizon_days,
        "requests": total_requests,
        "preexisting_locked": len(locked),
        "scheduled": len(appointments),
        "deliberately_infeasible": 20,
        "correctly_rejected": intentionally_rejected,
        "unexpected_unscheduled": unexpected_unscheduled,
        "whole_visit_doctor_overlaps_safely_created": whole_visit_doctor_overlaps,
        "scheduled_by_procedure": dict(sorted(scheduled_by_procedure.items())),
        "scheduled_by_doctor": dict(sorted(scheduled_by_doctor.items())),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "invariant_failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if failures or unexpected_unscheduled or intentionally_rejected != 20 else 0


if __name__ == "__main__":
    raise SystemExit(main())
