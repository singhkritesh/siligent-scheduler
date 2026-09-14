from __future__ import annotations

import unittest
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.main import (
    AppointmentStatusBody,
    ProviderCreateBody,
    RecommendationBody,
    UserCreateBody,
    weekly_block_occurrences,
)
from backend.scheduling import _future_patient_windows, _limit_to_effective_dates
from optimizer.siligent_optimizer import Interval


class RequestValidationTests(unittest.TestCase):
    def test_database_identifier_errors_have_safe_http_handlers(self) -> None:
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("psycopg.errors.InvalidTextRepresentation", source)
        self.assertIn("psycopg.errors.ForeignKeyViolation", source)
        self.assertNotIn("content={\"detail\": str(", source)

    def test_required_text_is_trimmed_before_minimum_length_validation(self) -> None:
        with self.assertRaises(ValidationError):
            ProviderCreateBody(staff_code="   ", display_name="Valid Name", role="assistant")
        with self.assertRaises(ValidationError):
            AppointmentStatusBody(status="cancelled", reason="   ")

    def test_user_identity_is_trimmed_without_altering_password(self) -> None:
        body = UserCreateBody(
            username="  scheduler.one  ",
            display_name="  Scheduler One  ",
            role="scheduler",
            password=" pass phrase ",
        )
        self.assertEqual(body.username, "scheduler.one")
        self.assertEqual(body.display_name, "Scheduler One")
        self.assertEqual(body.password, " pass phrase ")

    def test_recommendation_rejects_whitespace_only_patient_identifiers(self) -> None:
        with self.assertRaises(ValidationError):
            RecommendationBody(
                patient_name="   ",
                medical_record_number="MR-1",
                procedure_code="exam",
                date_from=date(2026, 9, 8),
                date_to=date(2026, 9, 8),
                time_from=time(8),
                time_to=time(17),
            )

    def test_recommendation_defaults_to_any_opening_without_patient_dates(self) -> None:
        body = RecommendationBody(
            patient_name="Example Patient",
            medical_record_number="MR-1",
            procedure_code="exam",
        )
        self.assertIsNone(body.patient_always_available)
        self.assertIsNone(body.date_from)
        self.assertIsNone(body.time_from)

    def test_request_models_reject_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            AppointmentStatusBody(
                status="cancelled",
                reason="Patient requested cancellation",
                unreviewed_override=True,
            )

    def test_qualification_dates_limit_daily_availability(self) -> None:
        timezone = ZoneInfo("America/New_York")
        windows = tuple(
            Interval(
                datetime(2026, 9, day, 8, tzinfo=timezone),
                datetime(2026, 9, day, 17, tzinfo=timezone),
            )
            for day in (8, 9, 10)
        )
        limited = _limit_to_effective_dates(windows, date(2026, 9, 9), date(2026, 9, 9))
        self.assertEqual([item.start.date() for item in limited], [date(2026, 9, 9)])

    def test_same_day_patient_windows_never_start_in_the_past(self) -> None:
        timezone = ZoneInfo("America/New_York")
        now = datetime(2026, 9, 8, 10, 7, tzinfo=timezone)
        windows = _future_patient_windows(
            date(2026, 9, 8), date(2026, 9, 9), time(8), time(17), timezone, now
        )
        self.assertEqual(windows[0].start, now)
        self.assertEqual(windows[1].start, datetime(2026, 9, 9, 8, tzinfo=timezone))

    def test_elapsed_same_day_window_is_removed(self) -> None:
        timezone = ZoneInfo("America/New_York")
        windows = _future_patient_windows(
            date(2026, 9, 8), date(2026, 9, 8), time(8), time(9), timezone,
            datetime(2026, 9, 8, 10, tzinfo=timezone),
        )
        self.assertEqual(windows, ())

    def test_weekly_doctor_blocks_preserve_local_time_across_dst(self) -> None:
        timezone = ZoneInfo("America/New_York")
        occurrences = weekly_block_occurrences(
            datetime(2026, 10, 30, 9, tzinfo=timezone),
            datetime(2026, 10, 30, 12, tzinfo=timezone),
            None,
            date(2026, 11, 13),
        )
        self.assertEqual(len(occurrences), 3)
        self.assertEqual([item[0].hour for item in occurrences], [9, 9, 9])
        self.assertEqual([item[0].utcoffset().total_seconds() for item in occurrences], [-14400, -18000, -18000])


if __name__ == "__main__":
    unittest.main()
