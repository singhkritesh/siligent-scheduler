# Production Redesign Verification Report

Date: 2026-08-23  
Environment: local air-gapped Docker stack, PostgreSQL 16, local Ollama
`qwen3.5:4b`

## Practice-scale phased simulation

Deterministic seed: `20260823`

| Measure | Result |
| --- | ---: |
| Rolling horizon | 365 days |
| Incremental requests | 420 |
| Pre-existing locked visits | 60 |
| Successfully scheduled | 400 |
| Deliberately infeasible | 20 |
| Correctly rejected | 20 |
| Unexpected unscheduled | 0 |
| Invariant failures | 0 |
| Safe whole-visit dentist overlaps | 47 |
| Doctor distribution | 132 / 136 / 132 |
| Runtime | 67.552 seconds |

The 47 whole-visit overlaps demonstrate the intended multi-room behavior: the
same dentist had overlapping patient visits, but no dentist-required phase
overlapped. Provider phases, rooms, and patients had zero collisions. The 20
infeasible cases had only 60 minutes available for a 115-minute root canal and
were rejected without weakening duration policy.

## Unit and regression tests

Eleven deterministic optimizer tests passed, including:

- Locked visits are neither moved nor overlapped.
- Patient, room, and equipment conflicts are hard constraints.
- A dentist can move between rooms when dentist phases do not overlap.
- A hygiene visit fails safely without an available hygienist.
- Emergency capacity cannot be consumed by routine work.
- A fourth concurrent supervised visit is rejected when a dentist's configured
  active-room limit is three.
- A scarce equipment unit delays a candidate until that exact unit is free.
- Preference ranking, horizon enforcement, qualification blockers, and timezone
  validation remain enforced.

The original annual simulation also passed: 220 requests, 90 locked visits, 200
scheduled, 20 deliberately infeasible and correctly rejected, and zero invariant
failures. Its runtime improved from 5.409 to 2.446 seconds after resource indexes
were added.

## Live HTTPS workflow

The expanded authenticated workflow passed against the running application:

- Offline health response and secure administrator session
- Three dentists, five hygienists, four assistants, and at least eight rooms
- Local `qwen3.5:4b` intake normalization with staff confirmation
- Phase-aware recommendation, transactional confirmation, and production credit
- Operations-board phase continuity from visit start through visit end
- Exact locked-visit rescheduling authorization and phase replacement
- ASAP waitlist creation and hygienist-backed cleaning match
- Complex crown duration longer than standard policy
- Automatic linked crown-seat lab return with a 14–30 day window
- Completion workflow and resource release
- Practice configuration retrieval and append-only audit evidence
- Numbered equipment-unit allocation for crown treatment
- Configurable dentist supervision cap, procedure preference, and dated rota
  override
- Waitlist phone-attempt and incentive tracking
- Walk-in recommendation, confirmation, check-in, and seating
- Smoothed local attendance-risk display
- De-identified historical duration import that remains staged until clinician
  approval
- Chair utilization, no-show/cancellation, patient wait, production, and
  provider revenue-per-booked-hour analytics

## Database gates

The rollback-only invariant suite passed on both the upgraded live database and a
new temporary database created from all migrations. It verified:

- Unauthorized confirmed-visit movement is rejected.
- Exact rescheduling permission is single use.
- Confirmed phase edits require the exact consumed appointment permission.
- Overlapping provider phases are rejected even when whole visits use different
  rooms.
- Patient and room overlaps are rejected.
- A database trigger transactionally rejects visits above the dentist's active
  room supervision limit, closing the optimizer/confirmation race window.
- Equipment unit numbers cannot exceed configured quantity, unit times cannot
  overlap, and confirmed equipment changes require the exact consumed
  reschedule permission.
- Configuration cannot lower equipment quantity below an actively reserved unit
  or lower a dentist's supervision cap below current concurrent visits.
- Audit-event updates and deletes are rejected.

The clean test database was removed after verification. The live patient-data
volume was preserved.

## Defects found and corrected during verification

1. Waitlist matching passed a waitlist UUID as the procedure UUID, causing every
   provider to appear unqualified. The adapter now passes the procedure record.
2. Year-scale phase matching repeatedly scanned every reservation and availability
   window. Resource/day indexes now bound candidate checks to relevant data.
3. Dentist tie-breaking skewed annual workload. Global and daily phase load are
   now scoring inputs; the simulation distribution improved to 132 / 136 / 132.
4. Practice-local day queries used database date conversion in several reports.
   Dashboard, calendar, production, and cancellation matching now use explicit
   practice-timezone boundaries.
5. Phase authorization originally checked only for a setting value. It now
   verifies an exact, unrevoked, consumed reschedule permission for that visit.
6. The first live completion regression exposed that older workflows can close a
   visit without check-in timestamps. The flow constraint now preserves that
   compatibility while still enforcing check-in-before-seat and timestamp order.
7. Dentist room capacity was initially enforced only while generating candidates.
   A transaction-serialized database trigger now enforces the same policy during
   confirmation and rescheduling.

## Visual test status

HTML, CSS, JavaScript, served-asset, and DOM-contract validation passed. The
in-app browser service
reported no available browser backend, so an automated rendered desktop/mobile
interaction pass could not be executed in this environment. This is an
environmental test limitation and remains a production-acceptance gate.
