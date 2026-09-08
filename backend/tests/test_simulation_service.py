from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from backend.simulation_service import _validate_hypothetical_schedule
from optimizer.siligent_optimizer import Appointment, Interval


class SimulationInvariantTests(unittest.TestCase):
    def test_validation_checks_hypothetical_against_snapshot_appointments(self) -> None:
        start = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
        live = Appointment(
            "live-1", "patient-live", "doctor-1", "room-1",
            Interval(start, start + timedelta(hours=1)), locked=True,
        )
        hypothetical = Appointment(
            "simulation:req-1", "patient-sim", "doctor-2", "room-1",
            Interval(start + timedelta(minutes=30), start + timedelta(hours=2)), locked=True,
        )
        failures = _validate_hypothetical_schedule(
            [live, hypothetical],
            [],
            [],
            {live.id: live.interval, hypothetical.id: hypothetical.interval},
            {hypothetical.id},
        )
        self.assertTrue(any("room overlap" in failure for failure in failures))

    def test_existing_hold_is_not_mislabeled_as_unlocked_simulation_result(self) -> None:
        start = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
        held = Appointment(
            "held-1", "patient-live", "doctor-1", "room-1",
            Interval(start, start + timedelta(hours=1)), locked=False,
        )
        failures = _validate_hypothetical_schedule(
            [held], [], [], {held.id: held.interval}, set()
        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
