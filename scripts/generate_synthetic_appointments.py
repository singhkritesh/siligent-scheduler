#!/usr/bin/env python3
"""Generate privacy-safe appointment requests for optimizer simulations.

The output contains synthetic identifiers and controlled condition tags only.
It intentionally contains no names, medical record numbers, or free-text notes.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_SEED = 20260905
DEFAULT_START_DATE = date(2026, 10, 5)
DEFAULT_OUTPUT = Path("data/synthetic/synthetic_appointment_requests_100.csv")
TIMEZONE = ZoneInfo("America/New_York")

PROCEDURES = {
    "exam": {
        "weight": 18,
        "production_cents": 12500,
        "condition_tags": ("routine_preventive", "new_patient_exam", "localized_sensitivity"),
        "phases": (("assistant", 10), ("doctor", 20), ("assistant", 10)),
    },
    "cleaning": {
        "weight": 22,
        "production_cents": 17500,
        "condition_tags": ("routine_preventive", "periodontal_maintenance"),
        "phases": (("hygienist", 40), ("doctor", 10), ("hygienist", 10)),
    },
    "filling": {
        "weight": 18,
        "production_cents": 32500,
        "condition_tags": ("localized_decay", "restoration_repair", "localized_sensitivity"),
        "phases": (("assistant", 10), ("doctor", 30), ("assistant", 30), ("room", 10)),
    },
    "crown": {
        "weight": 10,
        "production_cents": 135000,
        "condition_tags": ("fractured_tooth", "large_restoration", "crown_preparation"),
        "phases": (("assistant", 10), ("doctor", 60), ("assistant", 30), ("room", 15)),
    },
    "crown-seat": {
        "weight": 5,
        "production_cents": 0,
        "condition_tags": ("lab_return", "crown_seating"),
        "phases": (("assistant", 10), ("doctor", 20), ("assistant", 10)),
    },
    "root-canal": {
        "weight": 7,
        "production_cents": 155000,
        "condition_tags": ("endodontic_pain", "pulpal_diagnosis"),
        "phases": (("assistant", 10), ("doctor", 90), ("assistant", 15)),
    },
    "extraction": {
        "weight": 7,
        "production_cents": 65000,
        "condition_tags": ("non_restorable_tooth", "surgical_need"),
        "phases": (("assistant", 15), ("doctor", 60), ("assistant", 15)),
    },
    "implant": {
        "weight": 5,
        "production_cents": 275000,
        "condition_tags": ("implant_planned", "surgical_need"),
        "phases": (("assistant", 10), ("doctor", 80), ("assistant", 20), ("room", 10)),
    },
    "emergency": {
        "weight": 8,
        "production_cents": 19500,
        "condition_tags": ("urgent_pain", "swelling", "dental_trauma"),
        "phases": (("assistant", 10), ("doctor", 30), ("assistant", 20)),
    },
}

FIELDNAMES = (
    "request_id",
    "patient_ref",
    "request_received_at",
    "procedure_code",
    "condition_tag",
    "difficulty",
    "priority",
    "availability_start_date",
    "availability_end_date",
    "daily_start_time",
    "daily_end_time",
    "preferred_doctor_code",
    "established_doctor_code",
    "request_source",
    "scheduled_minutes",
    "expected_production_cents",
    "status",
    "locked",
    "allow_reserved_block_override",
)


def weekday_dates(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def phase_minutes(procedure_code: str, difficulty: str) -> int:
    total = 0
    for role, minutes in PROCEDURES[procedure_code]["phases"]:
        if difficulty == "complex" and role == "doctor":
            minutes = round((minutes * 1.5) / 5) * 5
        total += minutes
    return total


def build_rows(row_count: int, seed: int, start_date: date) -> list[dict[str, object]]:
    randomizer = random.Random(seed)
    service_days = weekday_dates(start_date, max(20, (row_count + 4) // 5))
    procedure_codes = list(PROCEDURES)
    procedure_weights = [int(PROCEDURES[code]["weight"]) for code in procedure_codes]
    doctor_codes = ("DR-PATEL", "DR-LEE", "DR-MARTINEZ")
    time_windows = (
        (time(8), time(12)),
        (time(8), time(17)),
        (time(9), time(15)),
        (time(10), time(16)),
        (time(12), time(17)),
    )
    rows: list[dict[str, object]] = []

    for index in range(1, row_count + 1):
        procedure_code = randomizer.choices(
            procedure_codes, weights=procedure_weights, k=1
        )[0]
        difficulty = "complex" if randomizer.random() < 0.2 else "standard"
        if procedure_code == "emergency":
            priority = "urgent"
        else:
            priority = randomizer.choices(
                ("routine", "priority", "urgent"), weights=(82, 15, 3), k=1
            )[0]

        first_available = randomizer.choice(service_days)
        search_days = {"urgent": 2, "priority": 7, "routine": 14}[priority]
        last_available = first_available + timedelta(days=search_days)
        daily_start, daily_end = randomizer.choice(time_windows)
        preferred_doctor = randomizer.choice(doctor_codes) if randomizer.random() < 0.4 else ""
        established_doctor = randomizer.choice(doctor_codes) if randomizer.random() < 0.45 else ""
        if preferred_doctor and established_doctor and randomizer.random() < 0.7:
            established_doctor = preferred_doctor
        lead_days = randomizer.randint(1, 21)
        received_day = first_available - timedelta(days=lead_days)
        received_at = datetime.combine(
            received_day,
            time(randomizer.randint(8, 16), randomizer.choice((0, 15, 30, 45))),
            tzinfo=TIMEZONE,
        )
        procedure = PROCEDURES[procedure_code]

        rows.append(
            {
                "request_id": f"SIM-REQ-{index:03d}",
                "patient_ref": f"SIM-PAT-{index:03d}",
                "request_received_at": received_at.isoformat(),
                "procedure_code": procedure_code,
                "condition_tag": randomizer.choice(procedure["condition_tags"]),
                "difficulty": difficulty,
                "priority": priority,
                "availability_start_date": first_available.isoformat(),
                "availability_end_date": last_available.isoformat(),
                "daily_start_time": daily_start.strftime("%H:%M"),
                "daily_end_time": daily_end.strftime("%H:%M"),
                "preferred_doctor_code": preferred_doctor,
                "established_doctor_code": established_doctor,
                "request_source": randomizer.choices(
                    ("phone", "front_desk", "patient_portal", "walk_in"),
                    weights=(45, 30, 20, 5),
                    k=1,
                )[0],
                "scheduled_minutes": phase_minutes(procedure_code, difficulty),
                "expected_production_cents": procedure["production_cents"],
                "status": "requested",
                "locked": "false",
                "allow_reserved_block_override": "false",
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START_DATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rows < 1 or args.rows > 5000:
        raise SystemExit("--rows must be between 1 and 5000")
    rows = build_rows(args.rows, args.seed, args.start_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {len(rows)} synthetic appointment requests: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
