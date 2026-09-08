"""Typed inputs and outputs for deterministic scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_aware(self.start, "interval start")
        _require_aware(self.end, "interval end")
        if self.end <= self.start:
            raise ValueError("interval end must be after start")

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Doctor:
    id: str
    display_name: str
    qualified_procedure_codes: frozenset[str]
    availability: tuple[Interval, ...]
    provider_id: str | None = None
    procedure_preference: int = 0
    production_gap_cents: int = 0
    protected_intervals: tuple[Interval, ...] = ()
    max_active_visits: int = 3


@dataclass(frozen=True)
class Provider:
    id: str
    display_name: str
    role: str
    availability: tuple[Interval, ...]
    active: bool = True


@dataclass(frozen=True)
class ProcedurePhase:
    code: str
    name: str
    role: str
    duration: timedelta

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise ValueError("phase duration must be positive")


@dataclass(frozen=True)
class ResourceReservation:
    appointment_id: str
    provider_id: str
    interval: Interval
    locked: bool = True


@dataclass(frozen=True)
class EquipmentUnit:
    id: str
    equipment_id: str
    display_name: str
    unit_number: int
    availability: tuple[Interval, ...]


@dataclass(frozen=True)
class EquipmentReservation:
    appointment_id: str
    unit_id: str
    interval: Interval


@dataclass(frozen=True)
class ReservedProcedureBlock:
    id: str
    doctor_id: str
    procedure_code: str
    interval: Interval
    room_id: str | None = None
    equipment_unit_id: str | None = None


@dataclass(frozen=True)
class ScheduledPhase:
    code: str
    name: str
    role: str
    provider_id: str | None
    provider_name: str | None
    interval: Interval


@dataclass(frozen=True)
class Room:
    id: str
    display_name: str
    supported_procedure_codes: frozenset[str]
    availability: tuple[Interval, ...]


@dataclass(frozen=True)
class Appointment:
    id: str
    patient_id: str
    doctor_id: str
    room_id: str | None
    interval: Interval
    equipment_ids: frozenset[str] = field(default_factory=frozenset)
    active: bool = True
    locked: bool = True


@dataclass(frozen=True)
class SchedulingRequest:
    id: str
    patient_id: str
    procedure_code: str
    duration: timedelta
    patient_availability: tuple[Interval, ...]
    required_equipment_ids: frozenset[str] = field(default_factory=frozenset)
    preferred_intervals: tuple[Interval, ...] = ()
    preferred_doctor_id: str | None = None
    established_doctor_id: str | None = None
    phases: tuple[ProcedurePhase, ...] = ()
    priority: str = "routine"
    required_equipment: tuple[tuple[str, int], ...] = ()
    allow_reserved_block_override: bool = False

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise ValueError("duration must be positive")
        if not self.patient_availability:
            raise ValueError("at least one patient availability interval is required")


@dataclass(frozen=True)
class Candidate:
    doctor_id: str
    doctor_name: str
    room_id: str
    room_name: str
    interval: Interval
    score: int
    explanation: tuple[str, ...]
    phases: tuple[ScheduledPhase, ...] = ()
    equipment_unit_ids: tuple[str, ...] = ()
    reserved_block_ids: tuple[str, ...] = ()
    requires_reserved_block_override: bool = False


@dataclass(frozen=True)
class OptimizationResult:
    candidates: tuple[Candidate, ...]
    blocking_reasons: tuple[str, ...]
