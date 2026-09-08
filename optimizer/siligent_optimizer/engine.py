"""Incremental candidate generation for one scheduling request.

Lower scores are better. Hard constraints are filtered before scoring, so a
candidate returned by this module is feasible against the supplied snapshot.
The API must recheck feasibility transactionally when a user confirms a slot.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from .models import (
    Appointment,
    Candidate,
    Doctor,
    EquipmentReservation,
    EquipmentUnit,
    Interval,
    OptimizationResult,
    ProcedurePhase,
    Provider,
    ReservedProcedureBlock,
    ResourceReservation,
    Room,
    ScheduledPhase,
    SchedulingRequest,
)


def _ceil_to_grid(value: datetime, grid_minutes: int) -> datetime:
    utc_value = value.astimezone(UTC)
    minute_offset = utc_value.minute % grid_minutes
    seconds_present = utc_value.second != 0 or utc_value.microsecond != 0
    minutes_to_add = (grid_minutes - minute_offset) % grid_minutes
    if minutes_to_add == 0 and seconds_present:
        minutes_to_add = grid_minutes
    rounded = utc_value.replace(second=0, microsecond=0) + timedelta(
        minutes=minutes_to_add
    )
    return rounded.astimezone(value.tzinfo)


def _is_contained(interval: Interval, windows: Iterable[Interval]) -> bool:
    return any(window.contains(interval) for window in windows)


def _has_conflict(
    candidate: Interval,
    request: SchedulingRequest,
    doctor: Doctor,
    room: Room,
    appointments: Iterable[Appointment],
    *,
    phase_mode: bool,
) -> bool:
    for appointment in appointments:
        if not appointment.active or not appointment.interval.overlaps(candidate):
            continue
        if appointment.patient_id == request.patient_id:
            return True
        if not phase_mode and appointment.doctor_id == doctor.id:
            return True
        if appointment.room_id == room.id:
            return True
        if request.required_equipment_ids & appointment.equipment_ids:
            return True
    return False


def _provider_is_available(
    provider_id: str,
    interval: Interval,
    availability: Iterable[Interval],
    reservations: Iterable[ResourceReservation],
    assigned: Iterable[ScheduledPhase],
) -> bool:
    if not _is_contained(interval, availability):
        return False
    if any(item.interval.overlaps(interval) for item in reservations):
        return False
    return not any(
        item.provider_id == provider_id and item.interval.overlaps(interval)
        for item in assigned
    )


def _within_active_visit_capacity(
    candidate: Interval,
    doctor: Doctor,
    appointments: Iterable[Appointment],
) -> bool:
    """Enforce the practice's room-per-dentist supervision policy.

    Clinical provider conflicts remain phase based. This separate constraint
    limits the number of patients whose visits a dentist supervises at once.
    """
    overlaps = [
        item for item in appointments
        if item.active and item.doctor_id == doctor.id and item.interval.overlaps(candidate)
    ]
    active = 1 + sum(
        1 for item in overlaps
        if item.interval.start <= candidate.start < item.interval.end
    )
    if active > doctor.max_active_visits:
        return False
    events: list[tuple[datetime, int]] = []
    for item in overlaps:
        if candidate.start < item.interval.start < candidate.end:
            events.append((item.interval.start, 1))
        if candidate.start < item.interval.end < candidate.end:
            events.append((item.interval.end, -1))
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        if active > doctor.max_active_visits:
            return False
    return True


def _assign_equipment(
    candidate: Interval,
    request: SchedulingRequest,
    doctor: Doctor,
    room: Room,
    units: Iterable[EquipmentUnit],
    reservations: Iterable[EquipmentReservation],
    reserved_blocks: Iterable[ReservedProcedureBlock],
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    if not request.required_equipment:
        return (), ()
    reserved_by_unit: dict[str, list[EquipmentReservation]] = {}
    for reservation in reservations:
        reserved_by_unit.setdefault(reservation.unit_id, []).append(reservation)
    selected: list[str] = []
    override_block_ids: set[str] = set()
    for equipment_id, quantity in request.required_equipment:
        eligible: list[tuple[int, EquipmentUnit, tuple[str, ...]]] = []
        for unit in units:
            if unit.equipment_id != equipment_id or not _is_contained(candidate, unit.availability):
                continue
            if any(
                reservation.interval.overlaps(candidate)
                for reservation in reserved_by_unit.get(unit.id, ())
            ):
                continue
            unit_blocks = tuple(
                block for block in reserved_blocks
                if block.equipment_unit_id == unit.id and block.interval.overlaps(candidate)
            )
            conflicts = tuple(
                block.id for block in unit_blocks
                if not _reserved_block_matches(block, request, doctor, room, candidate)
            )
            if conflicts and not request.allow_reserved_block_override:
                continue
            matches = any(
                _reserved_block_matches(block, request, doctor, room, candidate)
                for block in unit_blocks
            )
            eligible.append((0 if matches else 1, unit, conflicts))
        eligible.sort(key=lambda item: (item[0], item[1].unit_number, item[1].id))
        if len(eligible) < quantity:
            return None
        for _, unit, conflicts in eligible[:quantity]:
            selected.append(unit.id)
            override_block_ids.update(conflicts)
    return tuple(selected), tuple(sorted(override_block_ids))


def _reserved_block_matches(
    block: ReservedProcedureBlock,
    request: SchedulingRequest,
    doctor: Doctor,
    room: Room,
    candidate: Interval,
) -> bool:
    return (
        block.doctor_id == doctor.id
        and block.procedure_code == request.procedure_code
        and block.interval.contains(candidate)
        and (block.room_id is None or block.room_id == room.id)
    )


def _reserved_block_conflicts(
    candidate: Interval,
    request: SchedulingRequest,
    doctor: Doctor,
    room: Room,
    reserved_blocks: Iterable[ReservedProcedureBlock],
) -> tuple[str, ...]:
    return tuple(sorted(
        block.id for block in reserved_blocks
        if block.interval.overlaps(candidate)
        and (block.doctor_id == doctor.id or (block.room_id is not None and block.room_id == room.id))
        and not _reserved_block_matches(block, request, doctor, room, candidate)
    ))


def _schedule_phases(
    start: datetime,
    request: SchedulingRequest,
    doctor: Doctor,
    providers: Iterable[Provider],
    reservations_by_provider: dict[str, tuple[ResourceReservation, ...]],
    availability_by_provider_day: dict[str, dict[object, tuple[Interval, ...]]],
) -> tuple[ScheduledPhase, ...] | None:
    phases = request.phases or (
        ProcedurePhase("doctor", "Doctor treatment", "doctor", request.duration),
    )
    support = tuple(provider for provider in providers if provider.active)
    scheduled: list[ScheduledPhase] = []
    cursor = start
    for phase in phases:
        interval = Interval(cursor, cursor + phase.duration)
        provider_id: str | None = None
        provider_name: str | None = None
        if phase.role == "doctor":
            provider_id = doctor.provider_id or doctor.id
            provider_name = doctor.display_name
            if not _provider_is_available(
                provider_id,
                interval,
                availability_by_provider_day.get(provider_id, {}).get(interval.start.date(), ()),
                reservations_by_provider.get(provider_id, ()),
                scheduled,
            ):
                return None
        elif phase.role in {"assistant", "hygienist"}:
            eligible = sorted(
                (item for item in support if item.role == phase.role),
                key=lambda item: (item.display_name, item.id),
            )
            chosen = next(
                (
                    item
                    for item in eligible
                    if _provider_is_available(
                        item.id,
                        interval,
                        availability_by_provider_day.get(item.id, {}).get(interval.start.date(), ()),
                        reservations_by_provider.get(item.id, ()),
                        scheduled,
                    )
                ),
                None,
            )
            if chosen is None:
                return None
            provider_id = chosen.id
            provider_name = chosen.display_name
        scheduled.append(
            ScheduledPhase(
                code=phase.code,
                name=phase.name,
                role=phase.role,
                provider_id=provider_id,
                provider_name=provider_name,
                interval=interval,
            )
        )
        cursor = interval.end
    return tuple(scheduled)


def _score_candidate(
    candidate: Interval,
    request: SchedulingRequest,
    doctor: Doctor,
    scheduled_load_minutes: int = 0,
    overall_load_minutes: int = 0,
) -> tuple[int, tuple[str, ...]]:
    search_start = min(window.start for window in request.patient_availability)
    wait_minutes = max(
        0,
        int((candidate.start.astimezone(UTC) - search_start.astimezone(UTC)).total_seconds() // 60),
    )
    wait_weight = {"urgent": 4, "priority": 2}.get(request.priority, 1)
    score = wait_minutes * wait_weight
    explanation = ["earliest feasible placement"]

    if request.preferred_intervals and _is_contained(
        candidate, request.preferred_intervals
    ):
        score -= 720
        explanation.append("matches a preferred time")

    if request.preferred_doctor_id:
        if doctor.id == request.preferred_doctor_id:
            score -= 1440
            explanation.append("matches the requested doctor")
        else:
            score += 1440

    if request.established_doctor_id and doctor.id == request.established_doctor_id:
        score -= 360
        explanation.append("maintains doctor continuity")

    priority_bonus = {"urgent": 2880, "priority": 720, "routine": 0, "manual_review": 0}
    score -= priority_bonus.get(request.priority, 0)
    if request.priority in {"urgent", "priority"}:
        explanation.append(f"prioritizes {request.priority} clinical policy")

    score -= doctor.procedure_preference * 10
    if doctor.procedure_preference > 0:
        explanation.append("matches dentist procedure preference")

    score -= min(max(doctor.production_gap_cents, 0) // 100, 1000)
    if doctor.production_gap_cents > 0:
        explanation.append("supports the provider production target")

    score += scheduled_load_minutes * 2
    score += overall_load_minutes // 4
    if scheduled_load_minutes:
        explanation.append("balances the dentist's daily workload")

    explanation.append("satisfies doctor, patient, room, and equipment constraints")
    return score, tuple(explanation)


def recommend_slots(
    request: SchedulingRequest,
    doctors: Iterable[Doctor],
    rooms: Iterable[Room],
    appointments: Iterable[Appointment],
    *,
    horizon_end: datetime,
    grid_minutes: int = 30,
    limit: int = 5,
    providers: Iterable[Provider] = (),
    reservations: Iterable[ResourceReservation] = (),
    equipment_units: Iterable[EquipmentUnit] = (),
    equipment_reservations: Iterable[EquipmentReservation] = (),
    reserved_blocks: Iterable[ReservedProcedureBlock] = (),
) -> OptimizationResult:
    """Return ranked feasible candidates from a current calendar snapshot."""

    if horizon_end.tzinfo is None or horizon_end.utcoffset() is None:
        raise ValueError("horizon_end must be timezone-aware")
    if grid_minutes <= 0 or 60 % grid_minutes != 0:
        raise ValueError("grid_minutes must be a positive divisor of 60")
    if limit <= 0:
        raise ValueError("limit must be positive")

    doctor_list = sorted(doctors, key=lambda item: item.id)
    room_list = sorted(rooms, key=lambda item: item.id)
    appointment_list = tuple(appointments)
    provider_list = tuple(providers)
    reservation_list = tuple(reservations)
    equipment_unit_list = tuple(equipment_units)
    equipment_reservation_list = tuple(equipment_reservations)
    reserved_block_list = tuple(reserved_blocks)
    appointments_by_patient: dict[str, list[Appointment]] = {}
    appointments_by_doctor: dict[str, list[Appointment]] = {}
    appointments_by_room: dict[str, list[Appointment]] = {}
    for appointment in appointment_list:
        appointments_by_patient.setdefault(appointment.patient_id, []).append(appointment)
        appointments_by_doctor.setdefault(appointment.doctor_id, []).append(appointment)
        if appointment.room_id:
            appointments_by_room.setdefault(appointment.room_id, []).append(appointment)
    reservations_by_provider: dict[str, list[ResourceReservation]] = {}
    for reservation in reservation_list:
        reservations_by_provider.setdefault(reservation.provider_id, []).append(reservation)

    def by_day(windows: Iterable[Interval]) -> dict[object, tuple[Interval, ...]]:
        grouped: dict[object, list[Interval]] = {}
        for window in windows:
            grouped.setdefault(window.start.date(), []).append(window)
        return {day: tuple(items) for day, items in grouped.items()}

    doctor_windows = {doctor.id: by_day(doctor.availability) for doctor in doctor_list}
    room_windows = {room.id: by_day(room.availability) for room in room_list}
    availability_by_provider_day = {
        provider.id: by_day(provider.availability) for provider in provider_list
    }
    for doctor in doctor_list:
        availability_by_provider_day[doctor.provider_id or doctor.id] = doctor_windows[doctor.id]
    frozen_reservations = {
        provider_id: tuple(items) for provider_id, items in reservations_by_provider.items()
    }
    provider_total_load = {
        provider_id: sum(
            int((item.interval.end - item.interval.start).total_seconds() // 60)
            for item in items
        )
        for provider_id, items in frozen_reservations.items()
    }
    candidates: list[Candidate] = []

    qualified_doctors = [
        doctor
        for doctor in doctor_list
        if request.procedure_code in doctor.qualified_procedure_codes
    ]
    suitable_rooms = [
        room
        for room in room_list
        if request.procedure_code in room.supported_procedure_codes
    ]

    if not qualified_doctors:
        return OptimizationResult((), ("no doctor is qualified for the procedure",))
    if not suitable_rooms:
        return OptimizationResult((), ("no room supports the procedure",))

    for patient_window in sorted(request.patient_availability):
        if patient_window.start >= horizon_end:
            continue
        for doctor in qualified_doctors:
            for doctor_window in doctor_windows[doctor.id].get(patient_window.start.date(), ()):
                common_start = max(patient_window.start, doctor_window.start)
                common_end = min(patient_window.end, doctor_window.end, horizon_end)
                duration = sum(
                    (phase.duration for phase in request.phases), timedelta(0)
                ) or request.duration
                if common_end - common_start < duration:
                    continue
                for room in suitable_rooms:
                    for room_window in room_windows[room.id].get(patient_window.start.date(), ()):
                        start = _ceil_to_grid(max(common_start, room_window.start), grid_minutes)
                        end_limit = min(common_end, room_window.end)
                        while start + duration <= end_limit:
                            interval = Interval(start, start + duration)
                            if request.procedure_code != "emergency" and any(
                                protected.overlaps(interval)
                                for protected in doctor.protected_intervals
                            ):
                                start += timedelta(minutes=grid_minutes)
                                continue
                            block_conflicts = _reserved_block_conflicts(
                                interval, request, doctor, room, reserved_block_list
                            )
                            if block_conflicts and not request.allow_reserved_block_override:
                                start += timedelta(minutes=grid_minutes)
                                continue
                            if not _has_conflict(
                                interval,
                                request,
                                doctor,
                                room,
                                tuple(appointments_by_patient.get(request.patient_id, ()))
                                + tuple(appointments_by_room.get(room.id, ()))
                                + (() if request.phases else tuple(appointments_by_doctor.get(doctor.id, ())))
                                + (appointment_list if request.required_equipment_ids else ()),
                                phase_mode=bool(request.phases),
                            ) and _within_active_visit_capacity(
                                interval, doctor, appointments_by_doctor.get(doctor.id, ())
                            ):
                                equipment_plan = _assign_equipment(
                                    interval, request, doctor, room, equipment_unit_list,
                                    equipment_reservation_list, reserved_block_list,
                                )
                                if equipment_plan is None:
                                    start += timedelta(minutes=grid_minutes)
                                    continue
                                equipment_unit_ids, equipment_block_conflicts = equipment_plan
                                all_block_conflicts = tuple(sorted(set(block_conflicts) | set(equipment_block_conflicts)))
                                scheduled_phases = _schedule_phases(
                                    start,
                                    request,
                                    doctor,
                                    provider_list,
                                    frozen_reservations,
                                    availability_by_provider_day,
                                )
                                if scheduled_phases is None:
                                    start += timedelta(minutes=grid_minutes)
                                    continue
                                score, explanation = _score_candidate(
                                    interval,
                                    request,
                                    doctor,
                                    sum(
                                        int((item.interval.end - item.interval.start).total_seconds() // 60)
                                        for item in frozen_reservations.get(doctor.provider_id or doctor.id, ())
                                        if item.interval.start.date() == interval.start.date()
                                    ),
                                    provider_total_load.get(doctor.provider_id or doctor.id, 0),
                                )
                                if all_block_conflicts:
                                    explanation += ("requires an authorized reserved-block override",)
                                elif any(
                                    _reserved_block_matches(block, request, doctor, room, interval)
                                    for block in reserved_block_list
                                ):
                                    explanation += ("matches a reserved doctor and procedure block",)
                                candidates.append(
                                    Candidate(
                                        doctor_id=doctor.id,
                                        doctor_name=doctor.display_name,
                                        room_id=room.id,
                                        room_name=room.display_name,
                                        interval=interval,
                                        score=score,
                                        explanation=explanation,
                                        phases=scheduled_phases,
                                        equipment_unit_ids=equipment_unit_ids,
                                        reserved_block_ids=all_block_conflicts,
                                        requires_reserved_block_override=bool(all_block_conflicts),
                                    )
                                )
                            start += timedelta(minutes=grid_minutes)

    candidates.sort(
        key=lambda item: (
            item.score,
            item.interval.start.astimezone(UTC),
            item.doctor_id,
            item.room_id,
        )
    )

    # A slot can be discovered through overlapping availability windows. Preserve
    # deterministic order while removing duplicates.
    unique_candidates: list[Candidate] = []
    seen: set[tuple[str, str, datetime, datetime]] = set()
    for candidate in candidates:
        identity = (
            candidate.doctor_id,
            candidate.room_id,
            candidate.interval.start,
            candidate.interval.end,
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_candidates.append(candidate)
        if len(unique_candidates) == limit:
            break

    if not unique_candidates:
        return OptimizationResult(
            (),
            (
                "no feasible slot satisfies the supplied availability and existing appointments",
            ),
        )

    return OptimizationResult(tuple(unique_candidates), ())
