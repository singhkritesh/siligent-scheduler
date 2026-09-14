# Scheduler User Training Manual

## Purpose and audience

This guide trains authorized dental-practice users to schedule, review, and
maintain appointments in the local Siligent Scheduler application. It describes
the supported user interface and the safety rules that preserve appointment,
resource, and audit integrity. It does not replace the practice's clinical
policy, privacy training, or downtime procedure.

## Before users begin

- Use an individual account with the role assigned by the administrator. Do not
  share credentials.
- Open the local HTTPS address or the installed desktop launcher. Report a
  production certificate warning to IT rather than bypassing it.
- Confirm the practice date and local time shown by the application before
  scheduling or changing a same-day visit.
- Enter only information needed to schedule and coordinate care. Do not place
  unnecessary clinical narrative in contact notes.

## Main workspaces

- **Home** presents role-specific work and the most useful next actions.
- **Schedule patient** is the guided workflow for a new request or a future
  booking.
- **Today** is for arrival, seating, completion, no-show, cancellation,
  walk-in, and protected rescheduling work on the current practice date.
- **Calendar** displays scheduled capacity and the annual planning view.
- **Insights** contains local reporting and the de-identified simulation tool.
- **Settings** is restricted to authorized administrative configuration.

Select **About this page** whenever a page's purpose or consequence is unclear.
This optional help remains local to the application.

## Schedule a patient

1. Search the patient directory before creating a new identity. This reduces
   duplicate records.
2. Select the clinician-approved procedure and confirm the scheduling details.
   The procedure rules determine required phases, duration, qualified clinicians,
   rooms, equipment, and support-provider needs.
3. Record only genuine patient date or time limits. Leave **Patient can take any
   available opening** selected when there is no restriction.
4. Review the ranked feasible recommendations. Each option reflects doctor
   qualifications, working hours, leave, closures, resource availability,
   buffers, and existing locked appointments.
5. Confirm the selected option only after checking the patient, procedure,
   doctor, date, and time. Confirmation locks the appointment.

If no opening is feasible, review the displayed blocking constraints. Do not
work around a hard constraint through direct calendar or database changes.

## Protect confirmed appointments

A confirmed appointment is locked. Do not edit a confirmed booking directly.
Use the protected reschedule flow in **Today**, choose the exact replacement,
record a meaningful reason, and obtain the required authorization. The system
records the permission and change in the audit history.

For an eligible future cancellation, **Focused vacancy recovery** may offer
later, unfulfilled visits for the exact freed doctor, room, and start time. It
does not reoptimize the full calendar. Contact one named patient, obtain consent
for that exact earlier slot, record the permission channel and note, then apply
one move. Repeat only from the newly released vacancy, or finish recovery.

## Work the current day

- Use **Today** to check in and seat appointments only on their scheduled
  practice date.
- Record completion after seating. Record a no-show only after the scheduled
  start when the patient has not arrived.
- Search walk-ins only for the current date. Elapsed same-day slots are excluded
  automatically.
- Record cancellations through the supported action so availability and audit
  history stay correct.

## Administrative configuration

Authorized administrators manage dentists, hygienists, assistants, individual
accounts, availability, rooms, equipment, procedure rules, and protected doctor
procedure blocks in **Settings**. A provider must be qualified and active before
the optimizer can use that resource in a new recommendation.

Use inactive status for staff who have historical records. Permanent deletion is
available only for inactive, unused records without linked appointments,
accounts, blocks, recommendations, or other scheduling evidence. Existing
appointments and audit history are not deleted to resolve staffing changes.

## Simulation and reporting

Use **Insights > Simulation** only with de-identified CSV or XLSX requests. The
simulator reads a current capacity snapshot and creates no live appointments.
Do not upload patient names, MRNs, dates of birth, addresses, phone numbers,
emails, condition narratives, or notes. Download results only to approved local
storage.

## Escalate immediately

Stop and contact the administrator or IT when a recommendation appears to
conflict, an appointment looks moved without authorization, a certificate or
health warning appears, a protected block appears incorrect, local data appears
outside approved storage, or an unauthorized access, export, or disclosure is
suspected.

## Quick reference

- New booking: **Schedule patient**.
- Same-day status or reschedule: **Today**.
- Capacity review: **Calendar**.
- De-identified planning test: **Insights > Simulation**.
- Staff, rules, rooms, equipment, and blocks: **Settings**.
- Task-specific help: **About this page**.
