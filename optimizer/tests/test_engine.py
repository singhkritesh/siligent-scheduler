from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from siligent_optimizer import (  # noqa: E402
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


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2027, 1, day, hour, minute, tzinfo=UTC)


class RecommendSlotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doctor = Doctor(
            id="doctor-1",
            display_name="Dr. Synthetic",
            qualified_procedure_codes=frozenset({"exam"}),
            availability=(Interval(at(4, 9), at(4, 17)),),
        )
        self.room = Room(
            id="room-1",
            display_name="Room One",
            supported_procedure_codes=frozenset({"exam"}),
            availability=(Interval(at(4, 9), at(4, 17)),),
        )
        self.request = SchedulingRequest(
            id="request-1",
            patient_id="patient-new",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 17)),),
        )

    def test_locked_appointment_is_not_moved_or_overlapped(self) -> None:
        locked = Appointment(
            id="appointment-locked",
            patient_id="patient-existing",
            doctor_id=self.doctor.id,
            room_id=self.room.id,
            interval=Interval(at(4, 9), at(4, 10)),
            locked=True,
        )

        result = recommend_slots(
            self.request,
            [self.doctor],
            [self.room],
            [locked],
            horizon_end=at(5, 0),
        )

        self.assertTrue(result.candidates)
        self.assertEqual(result.candidates[0].interval, Interval(at(4, 10), at(4, 11)))
        self.assertEqual(locked.interval, Interval(at(4, 9), at(4, 10)))

    def test_patient_conflict_blocks_slot_even_with_other_resources(self) -> None:
        other_doctor = Doctor(
            id="doctor-2",
            display_name="Dr. Other",
            qualified_procedure_codes=frozenset({"exam"}),
            availability=(Interval(at(4, 9), at(4, 11)),),
        )
        other_room = Room(
            id="room-2",
            display_name="Room Two",
            supported_procedure_codes=frozenset({"exam"}),
            availability=(Interval(at(4, 9), at(4, 11)),),
        )
        patient_booking = Appointment(
            id="appointment-patient",
            patient_id=self.request.patient_id,
            doctor_id="unrelated-doctor",
            room_id="unrelated-room",
            interval=Interval(at(4, 9), at(4, 10)),
        )

        result = recommend_slots(
            self.request,
            [other_doctor],
            [other_room],
            [patient_booking],
            horizon_end=at(5, 0),
        )

        self.assertEqual(result.candidates[0].interval.start, at(4, 10))

    def test_preference_can_outweigh_earliest_slot(self) -> None:
        request = SchedulingRequest(
            id="request-preference",
            patient_id="patient-new",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 17)),),
            preferred_intervals=(Interval(at(4, 13), at(4, 15)),),
        )

        result = recommend_slots(
            request,
            [self.doctor],
            [self.room],
            [],
            horizon_end=at(5, 0),
        )

        self.assertEqual(result.candidates[0].interval.start, at(4, 13))
        self.assertIn("matches a preferred time", result.candidates[0].explanation)

    def test_horizon_excludes_later_availability(self) -> None:
        result = recommend_slots(
            self.request,
            [self.doctor],
            [self.room],
            [],
            horizon_end=at(4, 9),
        )

        self.assertFalse(result.candidates)
        self.assertTrue(result.blocking_reasons)

    def test_unqualified_doctor_returns_specific_blocker(self) -> None:
        doctor = Doctor(
            id="doctor-unqualified",
            display_name="Dr. Unqualified",
            qualified_procedure_codes=frozenset({"root-canal"}),
            availability=self.doctor.availability,
        )

        result = recommend_slots(
            self.request,
            [doctor],
            [self.room],
            [],
            horizon_end=at(5, 0),
        )

        self.assertEqual(
            result.blocking_reasons,
            ("no doctor is qualified for the procedure",),
        )

    def test_timezone_naive_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            Interval(datetime(2027, 1, 4, 9), datetime(2027, 1, 4, 10))

    def test_dentist_can_move_between_rooms_when_doctor_phases_do_not_overlap(self) -> None:
        assistant = Provider(
            id="assistant-1",
            display_name="Assistant One",
            role="assistant",
            availability=(Interval(at(4, 9), at(4, 17)),),
        )
        phased_request = SchedulingRequest(
            id="phased-request",
            patient_id="new-patient",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 12)),),
            phases=(
                ProcedurePhase("prep", "Assistant preparation", "assistant", timedelta(minutes=10)),
                ProcedurePhase("exam", "Doctor examination", "doctor", timedelta(minutes=20)),
                ProcedurePhase("finish", "Assistant finish", "assistant", timedelta(minutes=30)),
            ),
        )
        existing_doctor_phase = ResourceReservation(
            appointment_id="other-visit",
            provider_id=self.doctor.id,
            interval=Interval(at(4, 10), at(4, 10, 20)),
        )
        other_visit = Appointment(
            id="other-visit",
            patient_id="other-patient",
            doctor_id=self.doctor.id,
            room_id="other-room",
            interval=Interval(at(4, 9, 30), at(4, 10, 30)),
        )

        result = recommend_slots(
            phased_request,
            [self.doctor],
            [self.room],
            [other_visit],
            horizon_end=at(5, 0),
            providers=[assistant],
            reservations=[existing_doctor_phase],
        )

        self.assertEqual(result.candidates[0].interval.start, at(4, 9))
        self.assertEqual(result.candidates[0].phases[1].interval, Interval(at(4, 9, 10), at(4, 9, 30)))

    def test_hygiene_visit_requires_an_available_hygienist(self) -> None:
        request = SchedulingRequest(
            id="hygiene-request",
            patient_id="new-patient",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 10)),),
            phases=(
                ProcedurePhase("clean", "Hygiene care", "hygienist", timedelta(minutes=40)),
                ProcedurePhase("check", "Doctor check", "doctor", timedelta(minutes=10)),
                ProcedurePhase("finish", "Hygiene finish", "hygienist", timedelta(minutes=10)),
            ),
        )

        result = recommend_slots(
            request, [self.doctor], [self.room], [], horizon_end=at(5, 0)
        )

        self.assertFalse(result.candidates)
        self.assertTrue(result.blocking_reasons)

    def test_emergency_reserve_is_protected_from_routine_requests(self) -> None:
        protected_doctor = Doctor(
            id=self.doctor.id,
            display_name=self.doctor.display_name,
            qualified_procedure_codes=frozenset({"exam", "emergency"}),
            availability=self.doctor.availability,
            protected_intervals=(Interval(at(4, 16), at(4, 17)),),
        )
        request = SchedulingRequest(
            id="late-request",
            patient_id="new-patient",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 16), at(4, 17)),),
        )

        result = recommend_slots(
            request, [protected_doctor], [self.room], [], horizon_end=at(5, 0)
        )

        self.assertFalse(result.candidates)

    def test_reserved_block_accepts_only_matching_doctor_procedure_and_interval(self) -> None:
        block = ReservedProcedureBlock(
            id="block-1",
            doctor_id=self.doctor.id,
            procedure_code="exam",
            interval=Interval(at(4, 10), at(4, 11)),
        )
        result = recommend_slots(
            self.request, [self.doctor], [self.room], [], horizon_end=at(5, 0),
            reserved_blocks=[block],
        )

        self.assertEqual(result.candidates[0].interval, Interval(at(4, 9), at(4, 10)))
        matching = next(item for item in result.candidates if item.interval.start == at(4, 10))
        self.assertFalse(matching.requires_reserved_block_override)
        self.assertIn("matches a reserved doctor and procedure block", matching.explanation)

    def test_reserved_block_rejects_a_different_procedure(self) -> None:
        doctor = Doctor(
            id=self.doctor.id,
            display_name=self.doctor.display_name,
            qualified_procedure_codes=frozenset({"exam", "filling"}),
            availability=(Interval(at(4, 9), at(4, 11)),),
        )
        room = Room(
            id=self.room.id,
            display_name=self.room.display_name,
            supported_procedure_codes=frozenset({"exam", "filling"}),
            availability=self.room.availability,
        )
        request = SchedulingRequest(
            id="filling-request", patient_id="patient-new", procedure_code="filling",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 10), at(4, 11)),),
        )
        block = ReservedProcedureBlock(
            id="block-1", doctor_id=doctor.id, procedure_code="exam",
            interval=Interval(at(4, 10), at(4, 11)),
        )

        result = recommend_slots(
            request, [doctor], [room], [], horizon_end=at(5, 0), reserved_blocks=[block]
        )

        self.assertFalse(result.candidates)

    def test_authorized_override_search_labels_the_conflicting_candidate(self) -> None:
        doctor = Doctor(
            id=self.doctor.id,
            display_name=self.doctor.display_name,
            qualified_procedure_codes=frozenset({"exam", "filling"}),
            availability=(Interval(at(4, 10), at(4, 11)),),
        )
        room = Room(
            id=self.room.id,
            display_name=self.room.display_name,
            supported_procedure_codes=frozenset({"exam", "filling"}),
            availability=(Interval(at(4, 10), at(4, 11)),),
        )
        request = SchedulingRequest(
            id="override-request", patient_id="patient-new", procedure_code="filling",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 10), at(4, 11)),),
            allow_reserved_block_override=True,
        )
        block = ReservedProcedureBlock(
            id="block-1", doctor_id=doctor.id, procedure_code="exam",
            interval=Interval(at(4, 10), at(4, 11)),
        )

        result = recommend_slots(
            request, [doctor], [room], [], horizon_end=at(5, 0), reserved_blocks=[block]
        )

        self.assertTrue(result.candidates[0].requires_reserved_block_override)
        self.assertEqual(result.candidates[0].reserved_block_ids, ("block-1",))

    def test_reserved_equipment_unit_is_preferred_for_a_matching_block(self) -> None:
        request = SchedulingRequest(
            id="equipment-block-request", patient_id="patient-new", procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 10), at(4, 11)),),
            required_equipment=(("scanner", 1),),
        )
        units = [
            EquipmentUnit("scanner:1", "scanner", "Scanner", 1, self.doctor.availability),
            EquipmentUnit("scanner:2", "scanner", "Scanner", 2, self.doctor.availability),
        ]
        block = ReservedProcedureBlock(
            id="block-equipment", doctor_id=self.doctor.id, procedure_code="exam",
            interval=Interval(at(4, 10), at(4, 11)), equipment_unit_id="scanner:2",
        )

        result = recommend_slots(
            request, [self.doctor], [self.room], [], horizon_end=at(5, 0),
            equipment_units=units, reserved_blocks=[block],
        )

        self.assertEqual(result.candidates[0].equipment_unit_ids, ("scanner:2",))

    def test_dentist_active_room_supervision_limit_is_hard(self) -> None:
        doctor = Doctor(
            id=self.doctor.id,
            display_name=self.doctor.display_name,
            qualified_procedure_codes=self.doctor.qualified_procedure_codes,
            availability=self.doctor.availability,
            max_active_visits=3,
        )
        assistant = Provider(
            id="assistant-capacity",
            display_name="Assistant Capacity",
            role="assistant",
            availability=(Interval(at(4, 9), at(4, 10)),),
        )
        request = SchedulingRequest(
            id="capacity-request",
            patient_id="new-patient",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 10)),),
            phases=(
                ProcedurePhase("prep", "Preparation", "assistant", timedelta(minutes=30)),
                ProcedurePhase("check", "Dentist check", "doctor", timedelta(minutes=30)),
            ),
        )
        active_visits = [
            Appointment(
                id=f"existing-{index}", patient_id=f"patient-{index}",
                doctor_id=doctor.id, room_id=f"other-room-{index}",
                interval=Interval(at(4, 9), at(4, 10)),
            )
            for index in range(3)
        ]

        result = recommend_slots(
            request, [doctor], [self.room], active_visits,
            horizon_end=at(5, 0), providers=[assistant],
        )

        self.assertFalse(result.candidates)

    def test_scarce_equipment_unit_is_reserved_without_overlap(self) -> None:
        request = SchedulingRequest(
            id="equipment-request",
            patient_id="new-patient",
            procedure_code="exam",
            duration=timedelta(minutes=60),
            patient_availability=(Interval(at(4, 9), at(4, 12)),),
            required_equipment=(("scanner", 1),),
        )
        unit = EquipmentUnit(
            id="scanner:1", equipment_id="scanner", display_name="Scanner",
            unit_number=1, availability=(Interval(at(4, 9), at(4, 17)),),
        )
        reservation = EquipmentReservation(
            appointment_id="existing", unit_id=unit.id,
            interval=Interval(at(4, 9), at(4, 10)),
        )

        result = recommend_slots(
            request, [self.doctor], [self.room], [], horizon_end=at(5, 0),
            equipment_units=[unit], equipment_reservations=[reservation],
        )

        self.assertEqual(result.candidates[0].interval.start, at(4, 10))
        self.assertEqual(result.candidates[0].equipment_unit_ids, ("scanner:1",))


if __name__ == "__main__":
    unittest.main()
