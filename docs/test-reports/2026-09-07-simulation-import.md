# Simulation Import Acceptance Report — 2026-09-07

## Scope

Acceptance covered the authenticated CSV/XLSX upload workflow, validation and
preview, deterministic chronological replay, downloads contract, and isolation
from the live appointment calendar. All data was synthetic and de-identified.

## Automated evidence

- Parser tests accepted valid UTF-8 CSV and a minimal XLSX first worksheet.
- Validation rejected direct-identifier columns, formula cells, unsupported or
  unlabeled data columns, duplicate/invalid identifiers, invalid controlled
  values, dates outside the rolling horizon, availability before request receipt,
  exhausted arrival windows, pre-locked rows, and override flags.
- Authorization testing rejected an unauthenticated upload, and the live privacy
  test rejected a direct-identifier column before preview.
- Optimizer regression tests passed with locked-visit and resource constraints.
- The complete local regression run passed 46 backend/lifecycle tests and 15
  optimizer tests.
- A live authenticated test previewed and ran 100 synthetic requests: 100 were
  placed, 0 were unplaced, 0 invariant failures occurred, and the live
  appointment payload remained byte-for-byte equivalent before and after the run
  (41 appointments). A separate same-day case verified that a proposed start was
  not earlier than request receipt.
- Measured server-side run time was 6.738 seconds on the development host;
  optimizer replay time was 6.721 seconds. This is development evidence, not a
  production performance guarantee.
- PHI-free `simulation.previewed` and `simulation.completed` audit events were
  present; uploaded rows and results were not persisted.

## Remaining deployment acceptance

The in-app browser service was unavailable in this test environment, so rendered
desktop/mobile visual inspection and assistive-technology review remain required
on the target deployment. Practice policy, hardware performance, certificate,
egress, backup/restore, access review, privacy/security risk assessment, and
organizational HIPAA safeguards remain separate go-live gates.

## Known product boundary

The implemented screen produces one optimized hypothetical schedule and gross
configured production for that scenario. It does not yet perform paired
baseline-versus-optimized comparison, calculate incremental accommodated demand,
apply attendance/collection realization assumptions, or annualize a value/TAM
estimate. Historical records must be de-identified and date-shifted into the
current horizon before upload. These are value-study features, not scheduling
safety defects, and should not be inferred from the current output.
