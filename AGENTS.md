# Siligent Scheduler Engineering Guide

IMPORTANT: `AGENTS.md` and `CLAUDE.md` must remain byte-for-byte identical. Any
change to one must be made to the other in the same change.

This file applies to the entire repository.

## Project context

Read `MEMORY.md` before substantive changes. It records the stable product
purpose, lifecycle commands, architecture, offline deployment behavior,
compatibility assumptions, safety boundaries, and known release gates.

## Operational entry points

- First-time connected installation or idempotent upgrade: `./install.sh`
- Signed offline-bundle installation: `./install.sh --offline`
- Read-only compatibility audit: `./install.sh --check`
- Configuration-only compatibility entry point: `./setup.sh`
- Daily start: `./start.sh`
- Validate without starting: `./start.sh --prepare-only`
- Controlled local rebuild: `./build.sh`
- Operational and egress verification: `./verify.sh`
- Database backup and guarded restore: `./backup.sh`, `./restore.sh`
- Safe shutdown preserving database volumes: `./stop.sh`
- Controlled irreversible local disposal: `./purge.sh --yes`

## Product invariants

- The application is fully on premises and must work without internet access.
- Do not add runtime cloud APIs, telemetry, analytics, CDNs, remote fonts, remote
  license checks, or automatic downloads.
- Electronic protected health information (ePHI) stays on systems controlled by
  the dental practice.
- Minimize PHI everywhere. Never place patient names, conditions, appointment
  details, access tokens, or database contents in application logs.
- A confirmed appointment is locked. It may be moved only in the same database
  transaction that records explicit permission from an authorized user.
- Audit events are append-only. Corrections create new events; they do not edit
  or delete prior events.
- The scheduling horizon is a rolling year, calculated in the practice's local
  timezone. Persist timestamps in UTC and retain the originating timezone.
- The local language model may normalize intake text. It must not directly book
  an appointment or replace clinician-approved urgency and procedure rules.
- The deterministic optimizer is the authority for resource feasibility.

## Architecture boundaries

- `frontend/`: presentation and user interaction only.
- `backend/`: authentication, authorization, transactions, APIs, and audit
  orchestration.
- `optimizer/`: deterministic constraints, scoring, explanations, and solver
  tests. It does not write appointments directly.
- `local-model/`: local-only inference adapter and structured-output validation.
- `database/`: schema, migrations, seed reference data, and database tests.
- `deploy/`: offline deployment manifests and configuration templates.
- `docs/`: architecture, threat model, compliance evidence, and runbooks.

## Security requirements

- Deny outbound network access in production at both the host firewall and
  container-network layers.
- Use unique authenticated accounts and role-based authorization. Never add a
  shared scheduler account.
- Require TLS on the practice network and encryption for database volumes and
  backups. Keep encryption keys outside the repository.
- Store secrets outside images and source control. `.env` is local-only.
- Use parameterized database queries and server-side validation.
- Record authentication, patient-record access, schedule recommendations,
  booking, cancellation, permission, rescheduling, export, and administrative
  events without recording unnecessary PHI in the audit payload.
- Pin every dependency and container image. Offline release bundles must include
  checksums and an SBOM and must be verified before installation.

## Scheduling requirements

- Hard constraints include doctor qualification, working hours, leave, closures,
  procedure duration, buffers, rooms, equipment, patient restrictions, resource
  non-overlap, and locked appointments.
- Soft objectives include clinical priority from approved policy, wait time,
  continuity, patient preference, workload balance, overtime, and calendar
  fragmentation.
- Return ranked recommendations with constraint-based explanations.
- If no feasible slot exists, return the blocking constraints. Never silently
  weaken a hard constraint.
- Hypothetical rescheduling is a preview until every affected locked appointment
  has explicit authorization.

## Development workflow

- Keep production runtime network-independent. Internet access is permitted only
  during an explicit installation or upgrade window. Connected installs must
  pin and inventory dependencies and pass the no-egress runtime verification.
- Use `./install.sh`, `./start.sh`, `./verify.sh`, and `./stop.sh` for
  installation and lifecycle operations. Do not replace their validation with
  ad hoc Docker commands in operator documentation.
- Run focused tests for changed code and add regression tests for every scheduling
  or authorization bug.
- Treat optimizer property tests, concurrent-booking tests, audit tests, backup
  restoration tests, and security checks as release gates.
- Do not claim the software alone is "HIPAA compliant." Document the implemented
  safeguards and the operational controls the practice must supply.
