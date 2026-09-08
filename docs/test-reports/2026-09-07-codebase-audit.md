# Codebase Audit and Regression Report — 2026-09-07

## Scope

This review covered the browser application, HTTPS API, authentication and role
authorization, deterministic scheduling adapter and optimizer, appointment
lifecycle, focused vacancy recovery, PostgreSQL guards, installer/lifecycle
scripts, and the documentation that describes current behavior. Tests used
synthetic or de-identified data only.

## Defects corrected

1. **Auditor PHI access:** calendar, dashboard, Today, and waitlist endpoints
   accepted every authenticated role even though the UI hid them from auditors.
   The API now requires administrator, scheduler, or clinician role, and the
   live test verifies HTTP 403 for an auditor while audit-log access remains
   available.
2. **Qualification effective-date leakage:** a dentist qualification overlapping
   any part of a multi-day search could be applied to every day in that search.
   Daily dentist availability is now restricted to the qualification's exact
   effective date range.
3. **Elapsed same-day slots:** searches beginning today could return times that
   had already passed. The scheduling adapter now truncates today's availability
   at the current practice time and removes a fully elapsed window.
4. **Invalid lifecycle transitions:** a future walk-in could be labeled onsite;
   future visits could be checked in; an unseated visit could be completed; and
   no-show could be recorded early or after arrival. Server rules and UI choices
   now enforce the ordered workflow.
5. **Configuration audit omissions:** creation of support providers and
   operatories, plus production-target changes, did not append protected audit
   evidence. These mutations now write minimum, PHI-free events in the same
   transaction.
6. **Duplicate and malformed input failures:** duplicate provider, room, or user
   identifiers could surface as internal errors, and malformed linked IDs could
   leak database parsing failures. Duplicate operations now return HTTP 409;
   invalid identifiers and stale references receive safe 422/409 responses.
7. **Whitespace validation:** whitespace-only names, codes, and reasons could
   pass length checks and become unusable or meaningless records. Human-entered
   request text is trimmed before validation; unknown fields are rejected.
8. **Practice-timezone drift:** date/time rendering and administrative
   `datetime-local` inputs used the workstation timezone. All displayed instants
   and local-time conversions now use the configured practice timezone, with a
   clear rejection for nonexistent daylight-saving times.
9. **CSP-blocked visuals:** phase widths and production progress used runtime
   inline styles that the application's own Content Security Policy blocks.
   CSP-safe classes and native progress elements now render the same information.
10. **UI validation/state gaps:** server minimum lengths were missing from
    several forms, outcome reason was not browser-required, duplicate DOM IDs
    were not regression-tested, and vacancy buttons could be re-enabled after a
    chain stopped or an approval reset. Client constraints and state restoration
    now mirror the server.
11. **Vacancy preview minimization:** candidate responses included an MRN unused
    by the interface, and failed exact-slot probes left closed temporary requests.
    The unused identifier is no longer returned and failed probe records are
    removed inside the preview transaction.

## Verification results

| Check | Result |
| --- | --- |
| Backend, frontend-contract, lifecycle, validation, import, and service tests | 59 passed |
| Deterministic optimizer tests | 15 passed |
| Python compilation | Passed |
| JavaScript syntax | Passed |
| Lifecycle shell syntax | Passed |
| PostgreSQL invariant suite | Passed; synthetic transaction rolled back |
| Installer compatibility audit | Passed; read-only |
| Live HTTPS API workflow | Passed, including auditor denial |
| Live de-identified simulation | 100/100 scheduled; zero live-calendar writes |
| Live focused vacancy recovery | Passed; two exact moves, stale offer rejected, chain stopped |
| Headless browser | Login, scheduler, and Today rendered; zero JS exceptions/CSP violations/duplicate IDs/runtime inline styles |
| API-container public egress | **Failed as designed while host policy is open** |

The simulation placement result is synthetic capacity evidence, not a forecast
of patient attendance, completed care, collection, or revenue.

## Remaining release gates

The application remains a controlled production candidate, not a HIPAA
certification or an authorization for real-patient use. Before production, the
deployment owner must apply host/container outbound denial and obtain a passing
non-skipped `./verify.sh`; replace the development certificate; replace the
development `admin`/`admin` credential with unique strong accounts; verify
encrypted storage/backups and restoration; approve practice configuration;
complete accessibility and workstation acceptance; and retain signed release,
SBOM, license, vulnerability, risk-analysis, training, and policy evidence.
