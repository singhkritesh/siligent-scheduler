# Simplified Scheduling and Simulation Validation

## Scope

This change reduced the basic scheduling workflow while retaining the existing
clinical, resource, lock, privacy, and audit controls.

- Patient scheduling now uses three steps: patient and treatment, optional
  preferences, and opening selection.
- The default request assumption is that the patient can accept any feasible
  opening in the rolling 365-day horizon. Staff can disable the assumption and
  enter an explicit date and daily-time window.
- Legacy API clients that supply explicit date/time fields and omit the new flag
  continue to use those fields.
- Doctor procedure blocks can be created once or weekly through a selected date.
  Each occurrence is exact and audited; the full series fails atomically on a
  qualification, working-hours, leave, closure, appointment, block, or horizon
  conflict.
- Simulation uploads require only `request_id`, `patient_ref`, and
  `procedure_code`. Existing advanced columns remain supported.

## Verification evidence

| Check | Result |
| --- | --- |
| Backend, request, parser, service, lifecycle, and UI contract tests | 63 passed |
| Deterministic optimizer tests | 15 passed |
| Python compilation and JavaScript syntax | Passed |
| Offline image build from pinned local artifacts with build network disabled | Passed |
| Live HTTPS smoke test | Passed |
| Any-opening request without patient dates | Passed with feasible candidates |
| Three-column CSV preview and isolated simulation run | Passed; no live-calendar writes |
| Protected-block creation, nonmatching denial, authorized override, and release | Passed |
| Locked confirmation, protected reschedule, vacancy recovery, waitlist, walk-in, reports, and audit | Passed |

The live smoke suite now uses a unique synthetic patient namespace per run so
repeat execution cannot collide with prior confirmed synthetic appointments.

## Deployment observation

Application health, local HTTPS access, database isolation, offline responses,
and local image identity passed. The public-egress probe failed on the tested
Docker Desktop host because its published-port bridge still routes outbound
traffic despite the no-masquerade option. Making that bridge Docker-internal
blocked public egress but also made the local HTTPS port unreachable, so that
topology was not retained. Production activation therefore still requires the
documented authoritative host or container firewall deny rule followed by a
successful, non-skipped `./verify.sh` run.

The in-app browser connection was unavailable during this pass. Source-level UI
contracts, live API workflows, and local HTTPS rendering availability were
verified, but interactive browser and accessibility acceptance remains a
deployment gate.
