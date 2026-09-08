# Production Readiness

## Deployment Baseline

Use the lifecycle workflow instead of ad hoc Docker commands:

```bash
./install.sh --check --without-llm
./install.sh --connected --without-llm
./verify.sh
```

The compatibility audit is read-only. A connected installation may install
missing prerequisites and retrieve pinned dependencies only during an approved
installation or maintenance window. It creates or upgrades protected local
configuration, records image identities, starts the stack, verifies health, and
reports a staged connected installation. After the approved installation window
closes, `./verify.sh` must prove public-internet egress denial before production
activation. Daily operation does not perform downloads, pulls, update checks, or
telemetry.

The core release defaults to deterministic intake rules. The optional local-AI
profile is installed with `./install.sh --with-local-model`; connected mode may
install Ollama and retrieve the approved model during the installation window.
Offline mode requires the separately approved local-AI pack. Installation creates a
health-aware desktop launcher unless `--no-launcher` is selected.

## Supported Host Baseline

- 64-bit macOS with Docker Desktop; host-local Ollama is optional.
- 64-bit Linux with Docker Engine and Compose v2; host-local Ollama is optional.
- Windows 10/11 through a current Docker Desktop WSL2 backend, launched from
  WSL2 or Git Bash; host-local Ollama is optional.

Docker 24 or newer, Compose v2, `curl`, `openssl`, 10 GB of free disk, and
adequate memory for the selected profile are required. The six-GB model-memory
warning applies only when local inference is enabled. Target hardware must be
tested with its selected profile and representative annual scheduling load.

## Security Defaults

- HTTPS is mandatory. First setup creates a short-lived development certificate
  only to make local acceptance possible; production requires a practice-issued
  certificate and internal trust chain.
- Configuration secrets are generated locally in `.env` with restrictive
  permissions and are not included in images or release bundles.
- Runtime image pulling, dependency downloads, telemetry, and cloud inference
  are disabled.
- PostgreSQL has no host port and runs on an internal Compose network.
- The production activation gate fails if the API container can reach a public
  address. Host firewall policy is authoritative because an internal-only Docker
  network prevents local port publication on supported Docker Desktop hosts.
- The API container is read-only, uses tmpfs for temporary files, drops all
  capabilities, and cannot gain new privileges.
- Production requires host-firewall outbound denial in addition to the internal
  Compose network controls.
- The unauthenticated health response exposes only process/database health and
  offline mode; it does not expose patient, queue, model, path, or schedule data.

## Operational Requirements

- Use unique staff accounts and replace the bootstrap administrator password
  according to approved access policy.
- Validate facility timezone, internal time synchronization, DNS, and TLS.
- Encrypt host storage and all backup media; keep keys outside the repository.
- Monitor database, disk, audit, certificate, time, backup, and application
  health locally without patient data in alerts.
- Define recovery objectives and demonstrate encrypted backup restoration.
- Retain the prior verified application image until migration acceptance passes.
- Never delete the database volume as a normal stop, update, or uninstall action.
- Run the health check after host restart, patching, certificate replacement,
  model change, restore, or application update.

## Required Production Acceptance

1. `./install.sh --check` and `./verify.sh` pass on the exact target host.
2. Approved core-image hashes, licenses, SBOM, signatures, vulnerability
   disposition, and chain of custody are recorded. Model evidence is additionally
   required when the local-AI profile is selected.
3. Practice-issued TLS, host egress denial, storage encryption, unique accounts,
   access review, and audit review are verified.
4. Clinical owners approve procedures, phases, durations, qualifications,
   buffers, supervision, equipment, urgency, and linked-visit rules.
5. Operations owners approve staffing, hours, cover, rooms, emergency capacity,
   waitlist, production targets, and rescheduling policy.
6. Annual simulation, optimizer properties, database invariants, concurrent
   confirmation, locked rescheduling, API smoke, and restored-database tests pass.
7. Desktop and mobile browser, keyboard/accessibility, and practice-workstation
   acceptance pass.
8. Downtime, incident, backup, restoration, retention, and secure disposal
   procedures are approved and exercised.
9. Success-metric definitions, owners, local measurement sources, baseline
   period, thresholds, review cadence, and escalation rules are approved using
   `docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md`.

## Production Success Gates

Safety and privacy metrics are release guardrails, not optimization targets:
zero unauthorized appointment moves, zero resource overlaps, zero hard-constraint
bypasses, zero external PHI transfers, zero patient identifiers in logs or
calibration evidence, and complete audit evidence for every protected change.

Initial local service objectives are 99.5% availability during approved clinic
hours, 99.5% valid non-conflicting confirmation success, 100% scheduled backup
completion and quarterly restore-test success, p95 recommendation latency of no
more than five seconds, p95 confirmation latency of no more than two seconds,
and p95 annual-view latency of no more than two seconds on representative target
hardware. The practice may approve stricter targets after pilot measurement.

Operational success should compare a controlled pilot with a documented
baseline. Recommended starting measures include top-five recommendation
acceptance, request-to-confirm handling time, feasible-search rate, waitlist
recovery, booking lead time, patient wait, supported-workflow adoption, model
fallback, and prospective calibration error. These are measurement targets, not
current production-performance claims.

## Current Release Blockers

The application is suitable for controlled staging. Real patient use remains
blocked until the required production acceptance above is completed. Software
features and automated tests do not independently establish HIPAA compliance.

Historical performance data is not a production-start prerequisite. The
scheduler operates from approved default procedure policies. De-identified local
observations and optional historical imports may refine those policies later,
subject to the evidence threshold, human approval, audit, and rollback process.

The connected installer, live upgrade backup, rollback-image retention, clean
synthetic installation, and unsigned development bundle have passed on the
current Apple Silicon validation host. A production bundle is still blocked
until an externally controlled release key signs it, a supported SBOM tool
produces the final image SBOM, vulnerability/license disposition is approved,
and the target host passes the non-skipped egress verification after its install
window is closed.

## Latest Engineering Verification (2026-09-07)

The current source passed 59 backend/lifecycle tests, 15 optimizer tests, Python
compilation, JavaScript syntax validation, shell syntax validation, the
transactional PostgreSQL invariant suite, the live TLS API workflow, a live
100-request de-identified simulation, and the live two-step focused-vacancy
workflow. A headless browser login/navigation/render check found no JavaScript
exceptions, CSP violations, duplicate DOM identifiers, or runtime inline styles.

This audit corrected server-side auditor access to PHI-bearing endpoints,
effective-date enforcement for dentist qualifications, past same-day slot
generation, invalid walk-in and patient-flow transitions, missing configuration
audit events, unsafe malformed-identifier failures, timezone-dependent UI
display/input conversion, CSP-blocked visual styles, validation mismatches, and
vacancy-preview state/debris issues. Details and exact evidence are recorded in
`docs/test-reports/2026-09-07-codebase-audit.md`.

The public-egress probe still fails on this development Docker Desktop host.
This is the expected production activation gate—not a passing result—and real
patient use remains blocked until the target host's authoritative outbound-deny
policy is applied and `./verify.sh` passes without `--skip-egress`. The current
development `admin`/`admin` credential and development certificate must also be
replaced before any real-patient deployment.
