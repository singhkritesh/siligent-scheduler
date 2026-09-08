# Simulation and End-to-End Test Report

Date: 2026-08-19  
Environment: local on-premises Docker stack, PostgreSQL 16, local Ollama
`qwen3.5:4b`

## Year-horizon simulation

The deterministic simulation used seed `20260819` and a 365-day horizon.

| Measure | Result |
| --- | ---: |
| New synthetic patients | 220 |
| Pre-existing locked appointments | 90 |
| Deliberately infeasible requests | 20 |
| Successfully scheduled | 200 |
| Correctly rejected | 20 |
| Unexpected unscheduled requests | 0 |
| Recommendations returned | 1,000 |
| Mean wait | 0.01 days |
| 95th percentile wait | 0.04 days |
| Runtime | 5.409 seconds |
| Invariant failures | 0 |

The deliberately infeasible cases were root-canal requests with only a 60-minute
availability window for a 115-minute appointment. They were rejected rather
than weakening the procedure-duration constraint.

Validation covered the one-year boundary, doctor and room working hours,
qualification, patient/doctor/room overlap, exclusive equipment overlap, and
immutability of the 90 locked appointments.

## Live HTTPS API workflow

Passed:

- Health and offline-mode response
- Administrator authentication and secure session cookie
- Catalog and practice-resource retrieval
- Local `qwen3.5:4b` intake normalization
- Rejection of booking before staff confirms normalized intake
- Ranked recommendation generation
- Transactional confirmed booking
- Locked-appointment reschedule preview
- Exact replacement-slot authorization with recorded reason
- One-time reschedule-permission consumption
- Dashboard refresh and audit evidence

The smoke test used only the synthetic medical-record number
`SYNTHETIC-E2E-001`. Four synthetic confirmed appointments remain in the local
development database as validation evidence.

## Database invariants

The rollback-only PostgreSQL invariant suite passed against the live database:

- Unauthorized confirmed-appointment move rejected
- Exact authorized move accepted
- Reschedule permission consumed
- Overlapping appointment rejected
- Audit-event update rejected
- Audit-event deletion rejected

## UI delivery checks

- HTTPS GET returned status 200 and 9,987 bytes.
- Login, scheduler, year-calendar, audit, and reschedule surfaces were present.
- The JavaScript bundle passed syntax validation.
- CSP, MIME-sniffing protection, frame denial, no-referrer policy, and restricted
  browser-permission headers were present.

The in-app browser runtime exposed no available browser backend in this session,
so an automated click-through UI pass could not be performed. This is a test
environment limitation, not an application failure. A browser click-through and
visual/responsive check remains required before production acceptance.

