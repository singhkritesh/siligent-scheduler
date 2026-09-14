# Architecture Overview

## Trust boundary

The complete application operates on practice-controlled infrastructure. The
production host denies outbound traffic. Workstations connect over the approved
internal network to a TLS endpoint; no browser asset requires internet access.

```text
Practice workstation
        |
        | internal TLS
        v
API + static application UI
        |
        +-------------------+
        v                   v
 PostgreSQL     Rules + optional local Ollama
        |
        +---- embedded deterministic optimizer
        |
        v
Encrypted, tested offline backups
```

## Decision ownership

The system separates language understanding from scheduling authority:

1. Deterministic rules propose structured condition tags. When enabled, the
   local model may add allowlisted tags and confidence.
2. Server-side validation limits output to an approved vocabulary.
3. A staff member confirms normalized intake before booking.
4. Clinician-approved policy supplies priority, procedure phases, standard and
   complex duration, qualifications, production value, equipment, emergency
   capacity, and safety rules.
5. The optimizer applies hard constraints and ranks feasible slots.
6. The API rechecks current database state inside the booking transaction before
   confirming the selected recommendation.

The model never writes appointments and cannot weaken a hard constraint.

## Data principles

- PostgreSQL is the only system of record.
- Store timestamps in UTC and retain the practice timezone for interpretation.
- Use opaque identifiers between services when names are unnecessary.
- When enabled, send the local model only the minimum intake text needed for
  normalization. The default rules profile makes no inference request.
- Do not train or fine-tune the intake model on operational PHI. Current local
  data refinement is a deterministic duration-policy calibration, not model
  training.
- Scheduling requires approved configuration and current workflow data, not a
  historical practice export.
- Keep de-identified duration observations separate from patient and appointment
  records; do not store a patient identifier or appointment link in calibration
  evidence.
- Use synthetic data in fixtures, demonstrations, screenshots, and automated
  tests.

## Data-use pipeline

1. Reference procedure and resource policy makes a clean installation usable.
2. The current request, live availability, and locked bookings form the
   optimizer snapshot.
3. Deterministic rules, optionally assisted by the local model, propose
   allowlisted intake tags; staff review and deterministic policy control their
   use.
4. PostgreSQL records the confirmed appointment, resources, lifecycle, and audit
   evidence.
5. Local analytics aggregate operational records for descriptive metrics.
6. Eligible completed visits may add de-identified duration observations.
7. After the configured evidence threshold, median and p90 calculations stage a
   policy proposal; human approval is required and only future schedules use an
   approved version.

### Isolated batch simulation

The Insights simulation is a separate, non-booking path for de-identified CSV
or XLSX request files. The server rejects direct-identifier and free-text
columns, formulas, unsupported fields, out-of-horizon dates, duplicate request
IDs, locked inputs, and reserved-capacity override requests. Uploaded file
content and per-row results are held only for the request and are not persisted.

After an explicit preview and run action, the service opens a repeatable-read
transaction and loads one consistent snapshot of approved procedure policy,
providers, qualifications, hours, leave, daily overrides, closures, rooms,
equipment, emergency capacity, reserved procedure blocks, production targets,
production credit, and held/confirmed visits. Requests are replayed in received
order. Each chosen hypothetical visit is locked in memory, including its phase,
room, equipment, and production-credit effects, before the next request is
evaluated. Uploaded duration and production estimates are advisory; configured
policy values replace them.

The response contains proposed placements and aggregate feasibility, wait, and
production measures. Only a minimum PHI-free audit event is written. The path
has no operation that inserts, updates, cancels, or moves a live appointment.

The complete field boundaries, measurement formulas, and recommended pilot
targets are defined in `docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md`.

## Phased resources and concurrency

A visit is an ordered set of clinical phases. Each phase requires a dentist,
hygienist, assistant, or room-only turnover interval. The patient and operatory
remain reserved for the full visit; individual providers are reserved only for
their phases. A dentist can therefore move between rooms while assistant-led or
hygienist-led work continues, but two dentist phases can never overlap.

Recommendations are advisory until confirmed. Confirmation opens a database
transaction and materializes the exact phase plan. PostgreSQL exclusion
constraints reject provider, patient, and room collisions. A stale
recommendation fails rather than weakening a constraint.

Each dentist also has a clinician-approved maximum number of simultaneous active
patient visits. The optimizer filters above-capacity candidates, and a
transaction-serialized database trigger enforces the same limit at confirmation.
Equipment is expanded into numbered units and reserved for the exact visit
interval; exclusion constraints prevent double use.

## Operational workflows

- Two protected 30-minute emergency opportunities are held late each weekday
  for each dentist and released near the block according to policy.
- Cancellations and no-shows release phase reservations and report compatible
  ASAP-waitlist demand.
- A future cancellation may open a focused vacancy chain. Each preview pins the
  optimizer to the exact open doctor, room, and start; each transaction moves
  only one later unfulfilled visit after that patient authorizes the exact
  change. The released old slot becomes the next vacancy, and the wider schedule
  is never rerun.
- Procedure production credit is split by clinician-approved role policy and
  compared with provider targets on the daily board.
- Crown preparation automatically creates a linked lab-return item with a
  configurable minimum and maximum lead time.
- Standard and complex cases use separate phase durations.
- Daily shift overrides replace recurring hours for that date and can identify
  the provider covering an absent teammate.
- Doctor procedure blocks protect a doctor/time interval and optional room or
  equipment unit for a named procedure. They may be created once or as exact
  weekly occurrences, and are accepted only inside the doctor’s working hours
  without leave or closure conflicts. Normal search treats nonmatching use as
  infeasible. An administrator/clinician override is explicit, reasoned,
  short-lived, single-use, exact-scope, and transactionally rechecked.
- Walk-ins use the same hard-constraint search, then move through explicit
  check-in and seating states on the daily board.
- Waitlist contact attempts retain channel, outcome, and any recorded incentive.
- Versioned reference procedure defaults make scheduling operational
  without historical data. Completed visits may add de-identified local timing
  observations, and optional imports may add prior history. After the configured
  evidence threshold is met, the system stages a calibration recommendation;
  only an administrator or clinician can approve it for future scheduling.

## Failure behavior

- If the model is unavailable, staff may enter structured fields manually.
- If the optimizer is unavailable, the system does not auto-book; staff may view
  calendars and follow an authorized manual workflow.
- If a recommendation becomes stale, confirmation fails safely and requests a
  new search.
- If a vacancy offer expires, its chain version changes, or its appointment no
  longer matches the captured lock/resource/time snapshot, the move fails
  without changing either appointment.
- If a simulation file is invalid, the whole upload is rejected before replay;
  no partial result is applied to the calendar.
- If the audit write fails, the protected state-changing transaction fails.
- If backups or security monitoring are unhealthy, administrators receive a
  local alert; no alert payload is sent to an external service.
