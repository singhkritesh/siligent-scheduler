# Project Memory

## Purpose

Siligent Scheduler is a fully on-premises dental appointment scheduling system.
It combines clinician-approved scheduling policy, a deterministic constraint
optimizer, optional local-model intake assistance, transactional database guards,
and explicit human confirmation. Runtime internet access is prohibited. A clean
installation defaults to deterministic intake rules and requires no Ollama.

## Non-Negotiable Product Behavior

- Search a rolling 365-day horizon in the configured practice timezone.
- Add new patients and requests incrementally against current availability.
- Treat every confirmed appointment as locked.
- Move a locked appointment only through an authorized, exact, single-use
  rescheduling permission consumed in the same database transaction.
- Recover a cancelled future slot only as a localized vacancy chain: preview
  later unfulfilled visits for that exact doctor, room, and start; move one
  named patient only after exact permission; then continue from the one slot
  that move released. Never rerun or rewrite the wider calendar.
- Keep the language model limited to structured intake normalization.
- Let deterministic constraints and database guards decide feasibility.
- Operate from versioned reference defaults without requiring historical
  practice data; local observations may only propose future refinements.
- Keep ePHI, audit data, prompts, and operational telemetry on systems controlled
  by the practice.

## Application Shape

- `frontend/`: same-origin browser UI with no remote assets.
- `backend/`: HTTPS API, authentication, authorization, workflows, transactions,
  and audit orchestration.
- `optimizer/`: deterministic phase/resource feasibility, ranking, explanations,
  property tests, and annual simulations.
- `database/`: PostgreSQL migrations, reference configuration, and invariant
  tests.
- Optional host-local Ollama: approved pretrained intake assistance. It is not
  exposed to workstations and does not write appointments. The core rules
  profile makes no inference call.
- `deploy/` and `docs/deployment/`: offline artifacts, compatibility, setup,
  recovery, and release guidance.

## Lifecycle Commands

Connected first installation or idempotent upgrade:

```bash
./install.sh --without-llm
```

Read-only compatibility audit:

```bash
./install.sh --check --without-llm
```

Optional local-model installation:

```bash
./install.sh --check --with-local-model
./install.sh --with-local-model
```

Signed offline bundle installation:

```bash
./install.sh --offline --without-llm
```

Prepare without starting or rebuilding:

```bash
./start.sh --prepare-only
```

Daily start, health check, and safe stop:

```bash
./start.sh
./verify.sh
./stop.sh
```

Controlled local rebuild from preloaded artifacts:

```bash
./build.sh
```

## Setup and Docker Behavior

- `install.sh` is the supported installer. Connected mode may install missing
  prerequisites, retrieve pinned images and Python dependencies, and optionally
  install Ollama during an approved internet-enabled maintenance window.
- Offline mode verifies a signed/checksummed bundle and imports its images
  without network access. An unsigned override exists only for development.
- Setup is idempotent. It appends newly introduced `.env.example` keys without
  replacing installation-specific values.
- `setup.sh --check` is non-mutating. It validates the repository, shell syntax,
  host/architecture, Docker, Compose, disk/memory, configuration, the approved
  artifact manifest, imported image architecture, TLS files, and Compose model.
  It checks Ollama and the model identifier only for the local-model profile.
- `setup.sh` itself remains offline and never installs or downloads anything. It
  is the shared configuration and validation engine used after connected builds
  or offline image imports.
- `start.sh` never pulls or builds implicitly. `--build` is an explicit local,
  network-disabled rebuild; `--prepare-only` performs validation without start.
- PostgreSQL is isolated on an internal network. The API is read-only except for
  its tmpfs and database connection, drops Linux capabilities, and uses TLS.
- A model-enabled API can reach only the host-local model bridge; the rules
  profile does not call it. Production also requires host-firewall outbound denial.
- `stop.sh` removes containers and networks but preserves the database volume.
- Existing installations receive a pre-upgrade PostgreSQL backup, and the prior
  API image is retained under a timestamped rollback tag before change.
- `verify.sh` checks health, local images, PostgreSQL exposure, recorded image
  identity, and API-container public-internet egress.
- Setup installs a health-aware desktop launcher on macOS, Linux, WSL2, or Git
  Bash unless `--no-launcher` is selected. Launcher failures are written to
  `.runtime/desktop-launcher.log` without PHI.

## Supported Compatibility Baseline

- macOS on 64-bit Intel or Apple Silicon with Docker Desktop; Ollama is optional.
- 64-bit Linux on x86 or ARM with Docker Engine/Compose; Ollama is optional.
- Windows 10/11 through Docker Desktop using WSL2 or Git Bash, with host-local
  Ollama optional and reachable through `host.docker.internal` when selected.
- Exact image architecture, Docker licensing, operating-system support, model
  memory, host firewall, storage encryption, and practice-network TLS must be
  validated on deployment hardware.

See `docs/deployment/COMPATIBILITY.md` for the acceptance matrix. Compatibility
is not claimed until `./install.sh --check`, application health, scheduling smoke,
backup restoration, and browser acceptance pass on the target machine.

## Current Functional Coverage

- Unique staff accounts and role-based authorization.
- Role-aware Home workspaces, task-based navigation, and optional local
  contextual guidance for every primary page.
- Patient intake with staff-confirmed deterministic normalization and optional
  local-model tag assistance.
- Four-step scheduling from privacy-safe existing-patient lookup through
  treatment, acceptable availability, recommendation review, and locked
  confirmation.
- Phased dentist/hygienist/assistant scheduling across shared rooms.
- Provider qualification, shifts, cover, leave, closures, buffers, supervision
  limits, equipment units, patient availability, emergency capacity, and locked
  bookings as hard constraints.
- Qualification effective dates are checked against every candidate date, and
  same-day candidate generation excludes elapsed practice time.
- Doctor/procedure/date/time capacity blocks with optional room/equipment-unit
  binding, immutable history, automatic/manual release, and exact audited
  administrator/clinician overrides.
- Ranked recommendations with deterministic explanations.
- Transactional confirmation and exact protected rescheduling.
- Focused cancellation recovery that advances later confirmed visits one at a
  time, requires patient permission for every exact move, rejects stale or
  reused offers, preserves the cancelled source record, and records append-only
  chain steps without a global optimization rerun.
- Today's schedule and current-date walk-ins, with ordered check-in, seating,
  completion, cancellation, and no-show transitions enforced by the API.
- ASAP waitlist, contact attempts, incentives, and compatible-opening recovery.
- Linked lab-return visits and optional duration refinement from de-identified
  completed-visit observations or imported history, with an evidence threshold
  and explicit approval.
- Annual calendar, production and operational analytics, configuration, and
  append-only audit history.
- De-identified CSV/XLSX scheduling simulation with schema validation, preview,
  deterministic chronological replay against a read-only live snapshot,
  downloadable row/report results, invariant checks, and no live calendar writes.
- Segmented administrative workspaces for people, availability, resources,
  clinical rules, and optional duration recommendations, with summary-first
  progressive disclosure.

## Data Use and Success Measurement

- Approved configuration, the current request, current calendars, and existing
  appointments drive scheduling. Historical performance data is optional.
- Normal use creates local operational and audit records. Descriptive analytics
  use aggregated local records; they do not weaken constraints or determine
  clinical care.
- Completed visits may create de-identified timing observations with no patient
  identifier or appointment link. The default evidence threshold is 20 eligible
  observations before median/p90 duration proposals are staged.
- Practice observations do not train or fine-tune the local intake model.
  Calibration is deterministic, prospective, versioned, approval-gated, and
  never changes existing confirmed appointments.
- Product success is measured with non-negotiable safety/privacy guardrails plus
  locally approved scheduling, reliability, model-quality, calibration,
  adoption, and governance targets.

See `docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md` for formulas, starting targets,
measurement conditions, and review cadence.

## Validation Status

The current audit passed 59 backend/lifecycle tests, 15 optimizer tests, Python,
JavaScript, and shell validation, the transactional database invariant suite,
the live TLS API workflow, a 100-request simulation, the focused vacancy flow,
and a rendered headless-browser login/navigation check. The browser run found no
JavaScript exceptions, CSP violations, duplicate identifiers, or runtime inline
styles. Validation includes reserved-capacity creation, exclusion,
exact override, fulfillment, release, and a two-step cancellation vacancy chain.
Vacancy validation preserved the cancelled source, required explicit patient
permission, rejected a denied move and stale offer reuse, advanced only the
selected later visits, stopped cleanly, and completed its focused database/API
work without a global calendar rerun on the development host. Practice-device
manual accessibility and workstation acceptance remain production gates.
Practice-specific clinical/operational configuration, security infrastructure,
backup restoration, offline release evidence, and organizational safeguards also
require approval before real patient use.

The connected installer and idempotent upgrade path have also passed on an Apple
Silicon host. Validation covered the digest-pinned Python base, dependency lock,
pre-upgrade PostgreSQL dump, retained rollback image, live API workflow, isolated
empty-database first-use scheduling, Windows PowerShell parsing, development
bundle construction, checksum verification, and deliberate tamper rejection.
The egress activation gate correctly fails while the validation workstation
retains public internet access. Production activation therefore remains blocked
until host/container egress denial is applied and the full `./verify.sh` passes.

## Safety and Compliance Boundary

Do not claim that software alone is HIPAA compliant. The practice must supply and
document risk analysis, workforce authorization, training, physical safeguards,
facility/device controls, incident response, contingency operations, retention,
backup, restoration, access review, and periodic evaluation.

Do not place patient names, conditions, appointment details, access tokens,
database contents, or raw prompts in logs, fixtures, screenshots, release
bundles, or repository files.
