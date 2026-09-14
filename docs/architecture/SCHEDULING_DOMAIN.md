# Scheduling Domain Specification

## Appointment lifecycle

```text
requested -> proposed -> held -> confirmed -> completed
                 |          |          |       \
                 v          v          v        -> no_show
              expired    released   cancelled
```

`confirmed`, `completed`, `cancelled`, and `no_show` appointment history is
immutable.
Cancelling creates a new state transition and audit event; it does not erase the
appointment record.

Operational transitions are ordered. Walk-ins are searched only on the current
practice date, and no same-day recommendation may start before the current
practice time. Check-in and seating may be recorded only on the scheduled
practice date. Seating requires check-in; completion requires seating; and a
no-show cannot be recorded before the scheduled start or after arrival. A
future confirmed visit may still be cancelled through the governed outcome
workflow.

## Locked appointment rule

A confirmed appointment has a lock version and remains a hard constraint for
every scheduling run. Moving it requires:

1. An authenticated user with rescheduling permission.
2. A documented reason.
3. Explicit acknowledgement of every affected appointment.
4. A short-lived permission record scoped to the exact proposed move.
5. A single database transaction that records the old slot, new slot,
   permission, actor, time, and resulting audit event.

A hypothetical scenario never changes the live calendar.

## Localized cancellation vacancy recovery

Cancelling a future visit releases its exact doctor, room, start, and end. It
does not trigger a new annual or daily schedule. An administrator or scheduler
may deliberately start a focused recovery chain for that cancelled source.

At each step the system considers only confirmed, future, unfulfilled
appointments whose current start is later than the current vacancy. Every
candidate must pass the normal qualification, hours, closure, phase-provider,
room, equipment, emergency-capacity, reserved-block, supervision, patient, and
collision constraints at the exact vacant doctor, room, and start. The current
appointment remains locked while the option is previewed.

Applying a candidate requires a permission channel, a reason, confirmation that
the named patient accepted the exact earlier date/time, and acknowledgement that
only this appointment will move. A short-lived offer and the normal exact
single-use reschedule permission are rechecked and consumed in one transaction.
The selected appointment moves into the vacancy; its former full slot becomes
the next vacancy. A shorter visit may leave unused tail capacity in the filled
slot, but that tail returns to ordinary availability and is not silently added
to the chain.

The chain may then preview again or stop. Offers are version-bound and cannot be
reused after any step. The source cancellation, offers, permissions, and
append-only step history remain auditable. No step may move a checked-in,
seated, completed, cancelled, or no-show visit, and no step recalculates or
rewrites appointments that were not explicitly selected.

## Hard constraints

- Doctor qualification for the procedure on the exact candidate date
- Dentist, hygienist, and assistant working hours, leave, and closures
- Ordered procedure phases with standard or complex duration
- Patient availability and approved deadline when the basic any-opening
  assumption is explicitly disabled
- Required room and equipment availability
- No overlap for the patient, room, provider phase, or exclusive equipment
- Configurable maximum simultaneous supervised visits per dentist
- Dated provider rota overrides, including off days and named cover
- Locked appointments and administrative holds
- Practice timezone, daylight-saving transitions, and rolling horizon
- Clinician-approved emergency capacity rules
- Linked-visit minimum and maximum lead times
- Active reserved procedure blocks for a doctor and interval, plus any selected
  room and numbered equipment unit

The optimizer must not return a recommendation that violates a hard constraint.
The API and database recheck dentist supervision and numbered equipment-unit
capacity transactionally so concurrent confirmations cannot exceed policy.

## Doctor procedure blocks

An authorized configuration user may protect future capacity for one doctor,
one procedure, and an exact timezone-aware interval. A block may be created once
or expanded into exact weekly occurrences through a selected date. Each
occurrence is a separate immutable, audited record. The entire series is rejected
atomically if any occurrence falls outside the doctor’s working hours,
qualification dates, rolling horizon, overlaps leave or a practice closure, or
conflicts with protected capacity. A block may also bind an
eligible room and a required numbered equipment unit. Block creation is rejected
when it overlaps a held or confirmed appointment; it never reslots an existing
appointment.

Normal searches treat every active, unexpired block as a hard constraint. A
matching request may use the block only when doctor and procedure match, the
appointment is fully contained in the interval, and any bound room/equipment
matches. A successful matching confirmation fulfills the block.

Administrators and clinicians may deliberately include conflicting blocks in an
override search. Such candidates are visibly labeled and cannot be confirmed
without a reason and explicit acknowledgement. Confirmation creates a
short-lived, single-use permission tied to the exact block, recommendation,
request, doctor, procedure, room, start, and end. PostgreSQL consumes that
permission while writing the appointment; changing any scoped value invalidates
it. Blocks are never edited or deleted: they transition from `active` to
`fulfilled` or `released`, and every transition is audited. An optional release
time restores normal capacity automatically when the application next evaluates
reserved capacity.

## Soft objectives

Weights are versioned practice policy, not hidden model behavior. Candidate
ranking may consider:

- Approved clinical priority and maximum wait target
- Patient preferences
- Continuity with the patient's established doctor
- Doctor and resource utilization
- Workload balance
- Provider production-target gap and dentist procedure preference
- Overtime avoidance
- Calendar fragmentation
- Fairness for patients with similar priority and wait time

Every recommendation includes a compact explanation derived from these factors.

## Rolling one-year horizon

The database stores recurring working patterns plus dated exceptions. The
optimizer materializes the requested portion of the rolling 365-day horizon in
the practice timezone and indexes availability and reservations by resource and
day. The UI can navigate the complete year without rewriting existing visits.

New patients are inserted into an unscheduled-request queue and evaluated against
the current calendar. Existing confirmed appointments remain fixed. The system
does not need to rebuild or rewrite the entire annual schedule for each arrival.
Cancellation recovery follows the same incremental principle: one exact vacancy
and one authorized later visit are evaluated per step.

The basic request assumes the patient can accept any feasible opening in the
rolling horizon. This removes unnecessary patient-window entry while preserving
provider, procedure-block, room, equipment, closure, leave, and lock constraints.
When a patient supplies real limits, staff disables the assumption and records
the explicit date and daily-time window.

## No-feasible-slot behavior

Return the binding constraints, the search window, and safe next actions, such as
expanding patient availability or selecting an approved equivalent resource.
Rescheduling locked appointments may be shown only as a clearly labeled preview
requiring separate authorization.
