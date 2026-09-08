# Product, Data Use, and Success Metrics

## Purpose

This guide explains what the application does, which data it uses, how local
operational data can refine scheduling policy, and how a practice should measure
whether the product is successful. It supplements the technical architecture,
operator procedure, security baseline, and production-readiness checklist.

The application is operational from versioned reference configuration. A
historical practice export is not required to install, search, recommend, or
book. Before real-patient use, clinical and operations owners must validate or
edit the reference procedure, resource, capacity, and safety policy in Practice
setup.

## Product Outcome

Given an authorized scheduling request containing patient identity, procedure,
scheduling context, date/time availability, and optional preferences, the
application returns ranked feasible combinations of doctor, room, supporting
resources, and timeslot. An authorized staff member reviews and confirms one
option. The application searches a rolling 365-day horizon and evaluates every
new request against the latest calendar state.

Deterministic rules convert recognized condition text into an allowlisted set of
scheduling tags. An optional local language model may add allowlisted tags and
confidence when that deployment profile is enabled. It does not diagnose, choose
treatment, decide feasibility, or write an appointment. Deterministic constraints
and transaction-time PostgreSQL guards remain authoritative.

## Data Required to Operate

The product needs current configuration and the data for the scheduling action;
it does not need historical performance data.

| Data category | Examples | Why it is used | Required? |
| --- | --- | --- | --- |
| Approved practice configuration | Timezone, hours, closures, providers, qualifications, rooms, equipment, procedure phases, durations, buffers, supervision limits | Defines capacity and hard constraints | Reference values are installed; practice validation is required before real-patient use |
| Current request | Patient identity, procedure, minimum condition context, date range, daily availability, complexity and preferences | Creates the request and searches for suitable times | Yes, only the fields needed for the workflow |
| Current calendar state | Confirmed appointments, phases, rooms, equipment reservations, leave, shift overrides, and reserved procedure blocks | Prevents conflicts and protects existing commitments or intentionally held capacity | Yes; generated and maintained by normal operation |
| Workforce identity and authorization | Unique account, role, session and approval actor | Enforces least privilege and attributes protected actions | Yes for authenticated use |
| Historical duration observations | De-identified procedure/provider/date/scheduled/actual/outcome rows | May improve future standard and complex duration proposals | No |
| Optional simulation requests | Opaque request/patient references, controlled procedure/condition codes, complexity, priority, availability, optional doctor codes and advisory estimates | Replays representative demand against current policy and capacity without booking | No |
| External or cloud data | Cloud inference, telemetry, remote analytics, internet-hosted assets | Not used | No; prohibited at runtime |

## How Data Is Used

### Scheduling and confirmation

1. Staff enters or selects the patient and supplies the procedure, minimum
   condition context, availability, and preferences.
2. Deterministic intake rules, optionally assisted by the approved local model,
   propose allowlisted scheduling tags and confidence. Staff reviews the
   normalized context when required.
3. The optimizer combines the request with approved configuration and current
   calendar state.
4. Hard constraints reject unsafe or impossible candidates. Soft objectives rank
   only the candidates that remain feasible.
5. The UI displays doctor, start/end time, room, phase/resource plan, and
   explanation.
6. Confirmation rechecks live database state and writes the appointment,
   reservations, status history, and audit event atomically.

### Protected procedure capacity

An administrator may reserve a future dentist/time interval for a named
procedure and optionally an operatory and required equipment unit. The record
contains resource identifiers, start/end, reason, optional release time, status,
and actor—not patient data. The optimizer permits only a fully contained,
resource-matching appointment during normal search. Creating a block is rejected
if capacity is already occupied, so no booked patient is moved.

Administrators and clinicians can request explicitly labeled override candidates.
Confirming one requires acknowledgement and a reason. The server creates an
expiring single-use authorization for the exact recommendation and PostgreSQL
rechecks and consumes it transactionally. Block creation, fulfillment, release,
automatic release, and override authorization are append-only audit events.

### Daily operations and analytics

Normal use produces appointment status, check-in, seating, completion,
cancellation, no-show, waitlist-contact, resource, and production-credit events.
The local analytics view aggregates these records for utilization, attendance,
patient wait, booking lead time, production, and provider workload. Analytics
remain descriptive: they do not diagnose patients, deny care, or bypass approved
policy.

### Optional duration refinement

Completed visits can create a de-identified duration observation containing only
the procedure/provider context, service date, scheduled duration, observed chair
time, and outcome. The calibration record contains no patient identifier and no
link back to an appointment. A practice may also import the same restricted
fields from an approved local CSV; unexpected fields and direct identifiers are
rejected.

The refinement process is deterministic, not language-model fine-tuning:

1. Reference standard and complex durations remain active from first use.
2. Eligible local observations accumulate without blocking scheduling.
3. Until the configured minimum is reached—20 observations by default—the UI
   reports that evidence is still accumulating and produces no recommendation.
4. At the threshold, the median observed duration proposes the standard value
   and the 90th percentile proposes the complex value, rounded to five minutes.
5. The proposal is staged with its sample size and evidence. It is never applied
   automatically.
6. An administrator or clinician reviews the evidence, supplies an approval
   reason, and chooses whether to apply it prospectively.
7. Applying a proposal creates a new policy version and audit evidence. Existing
   confirmed appointments remain unchanged.

Practice data is not used to retrain the pretrained intake model. Any future
model training or fine-tuning would be a separate, explicitly approved project
with its own privacy review, validation plan, data governance, and deployment
evidence.

### Optional demand simulation

The simulation accepts de-identified CSV or XLSX requests and is independent of
duration calibration. It works with synthetic demand, a locally de-identified
and date-shifted historical request extract, or a controlled prospective scenario.
Availability must be mapped into the current rolling horizon. Patient names,
MRNs, dates of birth, contact details, addresses, raw conditions, notes,
unapproved fields, and workbook formulas are rejected.

The replay uses current approved procedure durations and production values,
regardless of uploaded estimates, plus the live provider/room/equipment calendar,
qualifications, closures, protected capacity, production targets, and existing
held or confirmed visits. Requests are ordered by received time and each proposed
placement consumes hypothetical capacity before the next request is evaluated.
No visit can start before its `request_received_at` timestamp. Reported booking
lead is measured from request receipt to proposed start; availability delay is
measured from the first acceptable patient time to proposed start.
The calculation is deterministic for the same file, configuration, calendar
snapshot, application version, and clock-sensitive emergency-release state.

Simulation output estimates what the scheduler can place under those assumptions;
it does not predict arrival, acceptance, cancellation, no-show, completion, or
payment. `scheduled_production_cents` is configured gross production associated
with feasible placements, not realized revenue. A value study must report those
assumptions separately and may apply approved realization scenarios after export.
The server does not persist the uploaded file or row results and does not write
appointments; it records only a minimum PHI-free preview/run audit event.

## Data Protection and Governance

- All application data remains on practice-controlled infrastructure.
- Runtime internet access, cloud inference, telemetry, remote fonts, content
  delivery networks, and automatic downloads are prohibited.
- Patient information and raw condition text must not appear in application
  logs, calibration rows, screenshots, support bundles, or external alerts.
- Audit records use actor and opaque entity identifiers with minimum structured
  change metadata; they exclude unnecessary clinical narrative.
- Confirmed appointments cannot move without an exact, short-lived, single-use
  permission tied to the actor, old slot, new slot, and reason.
- Retention, legal hold, encrypted backup, restoration, archival, and disposal
  schedules are practice-owned controls and must be documented before go-live.

## Success Measurement Framework

Success metrics are local operational measures, not inputs required to make the
application run. A practice should record a pre-rollout baseline when one exists,
then evaluate a controlled pilot and steady-state production. Targets below are
recommended starting points for acceptance; clinical, operations, privacy, and
IT owners must approve final targets for the deployment.

Do not combine unlike populations. Report scheduling metrics by procedure,
priority, location, provider role, and time period where volume permits. Suppress
small groups according to approved privacy policy. Never rank or disadvantage a
patient using a protected characteristic.

### Safety, privacy, and control guardrails

| ID | Metric and formula | Initial success threshold | Review cadence |
| --- | --- | --- | --- |
| SAFE-01 | Unauthorized confirmed-appointment moves | `0` | Immediate alert and monthly review |
| SAFE-02 | Confirmed patient, room, provider-phase, or equipment overlaps | `0` | Immediate alert and daily review |
| SAFE-03 | Bookings created by weakening or bypassing a hard constraint | `0` | Every release and monthly review |
| SAFE-04 | Protected state changes with complete append-only audit evidence / all protected state changes | `100%` | Daily exception review |
| SAFE-05 | Nonmatching appointments using reserved capacity without a valid exact override | `0` | Immediate alert and daily review |
| PRIV-01 | Patient or condition data transmitted outside the approved local boundary | `0` | Continuous control and quarterly test |
| PRIV-02 | Patient identifiers or raw condition text found in logs or calibration records | `0` | Every release and monthly scan |
| CAL-01 | Calibration proposals created below the approved evidence threshold | `0` | Every proposal |
| CAL-02 | Calibration proposals applied without an authorized reasoned approval | `0` | Every proposal |

Any guardrail breach is a release or operational incident, not a tradeoff against
efficiency metrics.

### Product and scheduling outcomes

| ID | Metric and formula | Recommended pilot target | Interpretation |
| --- | --- | --- | --- |
| PROD-01 | Top-five recommendation acceptance = confirmed from displayed candidates / searches with at least one candidate | `>= 70%` after four representative weeks | Indicates whether ranking and configuration produce useful options |
| PROD-02 | Median staff handling time from request creation to confirmation | `<= 2 minutes`, or at least `25%` below approved baseline | Measures workflow efficiency; exclude cases awaiting patient response |
| PROD-03 | Feasible-search rate = searches returning at least one option / valid searches | Establish baseline, then improve without relaxing hard constraints | Primarily exposes capacity or configuration gaps |
| PROD-04 | Cancellation recovery = eligible cancelled capacity filled through the supported waitlist or focused vacancy-chain flow / eligible cancelled capacity | At least `20%` improvement over baseline after eight weeks | Report waitlist fills and permissioned later-visit moves separately; never count an unauthorized move |
| PROD-05 | Median booking lead time by priority and procedure | Improve against baseline while meeting urgent-policy windows | Must be segmented; a single blended value is misleading |
| PROD-06 | Patient wait = seated time minus check-in time | At least `10%` improvement over baseline without higher overtime or safety events | Operational outcome, not a clinical-quality measure |
| PROD-07 | Eligible bookings performed through supported audited workflows | `>= 95%` after rollout | Detects shadow scheduling and adoption gaps |
| PROD-08 | Reserved blocks fulfilled by the intended procedure or deliberately released / terminal reserved blocks | Establish baseline, then set a practice-approved target | Measures whether protected capacity policy is useful; report overrides separately |
| PROD-09 | Simulation placement rate = simulated requests with a feasible placement / valid simulated requests | Establish a constrained baseline; compare scenarios without weakening guardrails | Capacity-planning measure only; not a forecast of completed care |
| PROD-10 | Incremental feasible production = configured production for scenario placements not feasible in the approved baseline | Report weekly and annualized values with realization assumptions and confidence bounds | Do not label gross production as revenue or TAM |

### Reliability and performance

| ID | Metric and formula | Initial success threshold | Measurement condition |
| --- | --- | --- | --- |
| REL-01 | Availability during approved clinic hours | `>= 99.5%` monthly, excluding approved maintenance | Measure from a local PHI-free health monitor |
| REL-02 | Successful confirmations / valid non-conflicting confirmation attempts | `>= 99.5%` | Report stale/conflict rejections separately because safe rejection is expected |
| REL-03 | Completed scheduled backup jobs and successful restoration exercises | `100%` backup completion; `100%` quarterly restore exercises | Evidence must include reconciliation, not only archive creation |
| PERF-01 | Recommendation response latency | Local p95 `<= 5 seconds` for the approved representative workload | Validate on target hardware and report model time separately |
| PERF-02 | Confirmation transaction latency | Local p95 `<= 2 seconds` absent a deliberate concurrency conflict | Includes database recheck and audit write |
| PERF-03 | Annual-view load latency | Local p95 `<= 2 seconds` for the approved practice-scale dataset | Test across the rolling 365-day horizon |
| PERF-04 | Focused vacancy candidate-preview latency | Local p95 `<= 5 seconds` for the approved practice-scale dataset | Measure each exact-vacancy step separately; exclude patient contact time and never broaden into a global rerun |

### Intake-model and refinement quality

| ID | Metric and formula | Initial success threshold | Guardrail |
| --- | --- | --- | --- |
| AI-01 | Schema-valid allowlisted model outputs / evaluated inputs | `>= 99%` on the approved de-identified validation set | Invalid output must fall back locally and never book |
| AI-02 | Recall for approved urgent sentinel cases | `100%` on the safety-critical sentinel set | False urgent escalation is reviewed separately; staff remains responsible for clinical triage |
| AI-03 | Local-model fallback rate during normal operation | `< 1%` after environment stabilization | Track model unavailable, timeout, invalid JSON, and disallowed tag separately |
| CAL-03 | Eligible completed visits producing valid de-identified observations / eligible completed visits | `>= 95%` | Invalid/missing timing is excluded rather than guessed |
| CAL-04 | Median absolute duration error after approved calibration versus the prior policy on a later holdout period | At least `10%` improvement before broad rollout | Use prospective holdout data; do not evaluate on the same samples used to propose the change |
| CAL-05 | Share of comparable visits completed within the approved complex-duration estimate | Target band `85%–95%` | Lower suggests underestimation; higher may indicate excess padding |

### Adoption and governance

| ID | Metric and formula | Initial success threshold | Review cadence |
| --- | --- | --- | --- |
| ADOPT-01 | Scheduling staff completing workflow, privacy, downtime, and protected-reschedule training | `100%` before access to real patient data | Before go-live and annually |
| ADOPT-02 | Active scheduling users using the product for eligible work | `>= 90%` by the end of the controlled rollout | Weekly during pilot |
| ADOPT-03 | Scheduler usability rating | `>= 4.0/5` with documented qualitative feedback | Pilot midpoint and close |
| GOV-01 | Procedure/resource/policy changes with named owner, reason, effective date, and audit record | `100%` | Monthly |
| GOV-02 | Scheduled access, audit, restore, model, calibration, and risk reviews completed on time | `100%` | Monthly or quarterly as assigned |

## Measurement Plan

1. Approve metric definitions, exclusions, target hardware, clinic-hour window,
   owners, and final thresholds before the pilot.
2. Capture a de-identified operational baseline where feasible. Lack of a
   historical baseline does not block product startup; the first controlled
   weeks can establish it.
3. Run a synthetic-data acceptance test for all safety, privacy, constraint,
   performance, and recovery metrics before real-patient use.
4. For a simulation study, freeze and identify the configuration/calendar
   snapshot and application version; run the baseline and proposed scenario on
   the same de-identified demand, verify zero invariant failures and zero live
   calendar changes, then report weekly results before annualizing. State demand,
   acceptance, no-show, completion, collection, seasonality, and capacity-change
   assumptions explicitly.
5. Review guardrails continuously and operational/product metrics weekly during
   the pilot.
6. Compare like periods and populations, document changes in staffing or policy,
   and avoid attributing every outcome change to the scheduler.
7. Approve, reject, or revise configuration and calibration proposals through
   the governed workflow. Never change policy directly from a dashboard number.
8. At pilot close, record the decision, evidence, known limitations, owners, and
   follow-up dates.

## Related Documentation

- `README.md` — application overview and lifecycle entry points.
- `docs/architecture/OVERVIEW.md` — trust boundary and decision ownership.
- `docs/architecture/SCHEDULING_DOMAIN.md` — detailed scheduling rules.
- `docs/operations/OPERATOR_SOP.md` — supported operator workflow.
- `docs/hipaa/SECURITY_BASELINE.md` — technical and organizational safeguards.
- `PRODUCTION_READINESS.md` — go-live acceptance requirements and blockers.
