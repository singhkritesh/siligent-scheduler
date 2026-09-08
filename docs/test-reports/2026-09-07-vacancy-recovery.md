# Localized Vacancy Recovery Acceptance Report — 2026-09-07

## Scope

Acceptance covered the cancellation-triggered, permission-gated cascade in
which one later confirmed appointment may fill one exact vacancy and its former
slot becomes the next vacancy. All records used were synthetic.

## Safety and workflow evidence

- Recording a future cancellation preserved the cancelled source appointment
  and returned an eligible released slot; it did not run optimization.
- Starting recovery captured the exact doctor, room, start, and end and reported
  `global_schedule_rerun: false`.
- Candidate previews considered only later confirmed, not checked-in or seated
  appointments and used the normal optimizer with the doctor, room, and start
  pinned to the current vacancy.
- A move with patient permission unchecked was rejected without changing the
  calendar.
- Two successive exact moves were applied. Each used the existing short-lived,
  single-use reschedule permission and released only the selected appointment’s
  former slot.
- Reuse of the first offer after its chain version advanced was rejected.
- Stopping the chain invalidated remaining offers; a later preview attempt was
  rejected.
- The cancelled source, both moved appointment identifiers, permission methods,
  and vacancy transitions were present in append-only chain/audit evidence.

## Database hardening

Migration `0017_vacancy_recovery_guard_hardening.sql` independently verifies
that every inserted step matches the active chain, current open offer, moved
appointment, released slot, and consumed exact reschedule permission. Offers,
terminal chains, and recorded steps cannot be edited or deleted through normal
database writes.

## Automated results

- Backend, lifecycle, parser, and frontend contract tests: 48 passed.
- Optimizer regression/property tests: 15 passed.
- Live two-step vacancy recovery: passed, including negative permission,
  stale-offer, and stopped-chain cases.
- Database timestamps show the isolated synthetic fixture and complete live
  recovery sequence finished in about 0.30 seconds on the development host;
  both focused candidate previews were below the 5-second acceptance threshold.

## Remaining deployment acceptance

These results do not by themselves authorize production use. Target-hardware
performance, rendered browser/accessibility review, concurrency/load testing,
practice policy, workforce training, certificate trust, egress enforcement,
backup restoration, security risk assessment, and organizational HIPAA
safeguards remain deployment gates.
