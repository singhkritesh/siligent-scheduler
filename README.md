# Siligent Scheduler

Siligent Scheduler is a fully on-premises dental appointment scheduling system.
It combines clinician-approved scheduling policy, a deterministic constraint
optimizer, and a locally hosted intake-normalization model. Runtime internet
access is prohibited.

## Current status

The repository contains a runnable production-candidate application with unique
staff accounts, patient intake with deterministic normalization and optional
local-model assistance, phased
multi-room optimization, ranked appointment recommendations, a daily clinical
operations board, production targets, an ASAP waitlist, emergency capacity,
linked lab-return visits, a rolling twelve-month calendar, explicit rescheduling
authorization, daily rota and cover overrides, configurable dentist supervision
limits and procedure preferences, governed doctor/procedure/date/time capacity
blocks with exact authorized overrides, equipment-unit reservations, patient
check-in/seating and walk-in flow, de-identified duration calibration with
clinician approval, a de-identified CSV/XLSX batch scheduling simulation,
operational analytics, resource administration, and
append-only audit history. Administrators can add dentists and support providers,
link a dentist to a unique clinician account, deactivate or reactivate staff
without moving booked care, and permanently delete only unused inactive staff
records after a dependency review.

The reference configuration represents three general dentists, five hygienists,
four assistants, and eight shared operatories. Procedure phases, complex-case
durations, production values, emergency blocks, targets, staffing, and lab lead
times are clinician-controlled policy and must be validated with the practice
before production acceptance.

The application is usable immediately from versioned reference procedure and
phase durations; historical practice data is not a startup dependency. Completed
visits accumulate de-identified local timing evidence, and an optional import can
add prior history. Only after the configured evidence threshold is met does the
system stage a calibration recommendation, and no recommendation changes policy
without explicit clinician or administrator approval.

## Installation and compatibility audit

Use the supported lifecycle workflow so host, artifact, configuration, model,
TLS, and Compose problems are detected before the running stack is changed:

```bash
./install.sh --check --without-llm
./install.sh --connected --without-llm
```

`./install.sh --check` is read-only. Connected installation may install missing
host prerequisites and retrieve pinned images and dependencies during an
approved internet-enabled installation window. It then preserves existing
installation values, builds the runtime image, starts the stack, verifies health
and records installed image identities. After IT closes the internet window and
applies the approved egress policy, `./verify.sh` is the mandatory production
activation gate. `--finalize-runtime` enforces that gate inside the connected
installer when the policy is already active. Daily runtime never downloads
dependencies or images.

For an air-gapped installation from a signed release bundle:

```bash
./install.sh --offline --without-llm
```

The deterministic-rules profile is the default for a new installation and does
not require Ollama. If the separately approved local-AI pack is present, IT may
select it explicitly:

```bash
./install.sh --check --with-local-model
./install.sh --connected --with-local-model
```

The local model is never installed or pulled unless explicitly selected.
Installation creates a **Siligent Scheduler** desktop launcher;
use `--no-launcher` only on a managed server without a desktop session.

To deliberately replace an existing local scheduler installation with a new,
empty one, use the explicit fresh-install mode. It removes this scheduler's
database volume, local configuration, certificates, backups, launcher, and
product API images before running the normal install/setup workflow. It never
runs implicitly during an update:

```bash
./install.sh --fresh --yes --connected --without-llm
```

Prepare or validate without starting:

```bash
./install.sh --no-start
./start.sh --prepare-only
```

See [project memory](MEMORY.md), [production readiness](PRODUCTION_READINESS.md),
[host compatibility](docs/deployment/COMPATIBILITY.md), and the
[operator SOP](docs/operations/OPERATOR_SOP.md). The [product, data-use, and
success-metrics guide](docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md) defines what
data is required, how local observations refine future policy, and how a pilot
or production deployment should be measured.

## Non-negotiable behavior

- Schedule recommendations cover a rolling one-year horizon.
- New patients are evaluated against the latest availability as they arrive.
- Confirmed appointments are locked and cannot be moved without explicit,
  authorized permission.
- Provider qualifications, phased doctor/hygienist/assistant work, operating
  hours, leave, closures, rooms, equipment, procedure duration, emergency
  capacity, and existing bookings are hard constraints.
- A qualification is enforced on the candidate appointment date, not merely
  because it overlaps some portion of a multi-day search. Same-day searches
  cannot return elapsed times.
- Walk-ins are limited to the current practice date. Check-in and seating are
  limited to that scheduled date; completion requires seating, and no-show is
  unavailable before the visit starts or after the patient arrives.
- Administrators can reserve a future doctor/time interval for one procedure,
  optionally including a room and equipment unit. Nonmatching requests cannot
  use it unless an administrator or clinician explicitly authorizes the exact
  override with a reason; creating a block never moves an existing appointment.
- The local model structures intake information; the optimizer decides whether a
  slot is feasible.
- Versioned reference defaults make the scheduler operational before any local
  history exists; calibration data may refine future policy but is never required
  to search or book.
- No PHI or application telemetry is sent outside the practice environment.
- A staff departure never reslots a confirmed appointment. Inactive staff are
  excluded from future searches; permanent deletion is allowed only when no
  protected historical or clinical dependencies exist, and the audit evidence is
  retained.

## How the application uses data

Scheduling uses approved practice configuration, the current request, current
availability, and existing locked appointments. Historical performance data is
not required. Normal operations create local appointment, status, resource,
waitlist, and audit records. Aggregated views use those records for descriptive
operational analytics.

Completed visits may contribute de-identified timing observations that contain
no patient identifier and no link back to an appointment. After at least 20
eligible observations by default, deterministic median and 90th-percentile
calculations may stage standard and complex duration proposals. The data does
not retrain the intake language model, proposals never auto-apply, and approved
changes affect only future scheduling policy.

## Success metrics

Safety and privacy are non-negotiable guardrails: the targets are zero
unauthorized appointment moves, zero resource conflicts, zero external PHI
transfers, zero patient identifiers in calibration data, and 100% audit coverage
for protected changes. Pilot outcomes additionally track recommendation
acceptance, staff handling time, feasible-search rate, waitlist recovery,
booking lead time, patient wait, local response latency, uptime, model fallback,
calibration error, adoption, and governance completion.

Targets, formulas, exclusions, owners, and review cadence are defined in the
[product, data-use, and success-metrics guide](docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md).
They are recommended acceptance targets, not claims about current production
performance.

See [the architecture overview](docs/architecture/OVERVIEW.md), [the scheduling
domain specification](docs/architecture/SCHEDULING_DOMAIN.md), [the security
baseline](docs/hipaa/SECURITY_BASELINE.md), and [the offline deployment
runbook](docs/deployment/OFFLINE_DEPLOYMENT.md).

## Runtime services

| Service | Responsibility |
| --- | --- |
| `api` | Internal TLS UI/API, authentication, workflows, audit, and the embedded deterministic optimizer |
| `database` | PostgreSQL system of record |
| Optional local Ollama | Preloaded intake-tag assistance on the same on-premises host; absent in the default rules profile |

Only the API's TLS port is exposed. PostgreSQL is isolated on an internal Docker
network. The application bridge disables IP masquerading where the Docker host
supports it, while the host firewall provides the authoritative egress boundary.
A model-enabled API may reach only the approved host-local Ollama endpoint; the
rules profile makes no inference call. Production must also enforce host-firewall
egress denial.

## Offline startup

For this local workstation build, ensure the approved `siligent-api` base image
and pinned PostgreSQL image are present. Ollama and the configured model are
required only for `--with-local-model`. No start or build command downloads an
artifact.

```bash
./build.sh
./start.sh
./verify.sh
```

On first start, a protected `.env`, random administrator password, and 30-day
development certificate are generated locally. Record the displayed password.
Replace the certificate with the practice-issued internal certificate before
production use. The initial username is `admin`.

Stop the stack without removing patient-data volumes:

```bash
./stop.sh
```

Open `https://127.0.0.1:8443`. The development certificate is self-signed, so a
browser warning is expected until the practice certificate is installed.

The application opens on a role-aware **Home** workspace with the user's next
actions, operating metrics, and upcoming visits. Daily navigation is organized as
**Today**, **Schedule patient**, **ASAP waitlist**, and **Calendar**, followed by
**Reports**. Administrators receive segmented **Settings** workspaces for people,
availability, rooms and equipment, procedure rules, and optional duration
recommendations. Administrators and auditors receive **Audit log** according to
their role. Auditor credentials are denied at the server—not only hidden in the
UI—from dashboard, calendar, Today, waitlist, scheduling, simulation, settings,
and analytics endpoints that expose or operate on patient data.

**Simulation** under Insights accepts a de-identified `.csv` or `.xlsx` request
file, validates its schema, previews policy substitutions, and runs an explicit
in-memory chronological replay against one consistent read-only snapshot of live
configuration and capacity. It returns proposed doctor, room, start/end time,
wait, status, and production totals for download. The workflow cannot create,
cancel, move, or reslot a live appointment. Use opaque `patient_ref` values;
direct identifiers, free-text condition/notes fields, formulas, unsupported
columns, reserved-block overrides, and pre-locked input rows are rejected. A
blank local template is linked from the page. The basic schema requires only
`request_id`, `patient_ref`, and `procedure_code`. Missing availability defaults
to any opening in the current rolling horizon; the former advanced columns remain
supported for controlled scenarios.

**Schedule patient** is a three-step flow: identify the patient and treatment,
review optional preferences, and choose a fully feasible opening. The basic flow
assumes the patient can accept any opening in the rolling year. Staff can turn
that assumption off and enter a specific date/time window when needed. The final
review identifies the dentist, timeslot, supporting
resources, and lock consequence before confirmation. Every page has optional
**About this page** guidance describing its purpose, common tasks, access, and
safety rule. Administrators can create unique accounts,
add, deactivate, reactivate, and—only for unused inactive records—permanently
delete dentists, assistants, and hygienists. They can link a dentist to a
unique clinician account, add operatories, support providers, equipment and
full-practice closures, manage the daily rota, and record dated staff
unavailability. Clinician-controlled
configuration includes exact or weekly doctor procedure blocks, procedure phases
and standard/complex duration, production
value, dentist preference, supervision limits, and approval of de-identified
historical calibration recommendations.

`start.sh` uses `--no-build --pull never`; `build.sh` uses the pinned local base
with Docker networking disabled. Missing artifacts cause a safe failure.

Release engineers may use `./build.sh --connected` during an approved build
window or `./build.sh --connected --bundle --signing-key KEY.pem` to build and
package a signed release. These modes are not daily-runtime commands.

Create a database backup before operational changes with `./backup.sh`. A
guarded `./restore.sh BACKUP.dump` creates another safety backup before replacing
the current database. `./uninstall.sh` stops services and removes the recognized
launcher but deliberately preserves data, configuration, certificates, images,
and backups. For an approved irreversible local disposal, use
`./purge.sh --yes`; it removes this scheduler's containers, networks, named
database volume, product-owned API images, desktop launcher, and runtime state.
It preserves the repository, shared images, configuration, certificates, and
backups unless `--remove-local-configuration` and/or `--remove-backups` are
also supplied.

## Important compliance note

The application will implement safeguards that support the practice's HIPAA
compliance program. Software alone does not establish compliance. The practice
must also perform and document risk analysis, policies, workforce training,
physical safeguards, access reviews, incident response, contingency operations,
and periodic evaluations.
