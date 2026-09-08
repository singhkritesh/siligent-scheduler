# HIPAA-Oriented Security Baseline

This document is an engineering baseline, not a legal certification. The
practice's documented risk analysis determines the final reasonable and
appropriate safeguards.

Primary references:

- HHS Security Rule summary:
  https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html
- HHS risk-analysis guidance:
  https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis/index.html
- NIST SP 800-66 Revision 2:
  https://csrc.nist.gov/pubs/sp/800/66/r2/final

Copies of applicable guidance should be included in the practice's controlled
offline documentation set.

## Administrative safeguards supported by the system

- Unique roles and least-privilege permission definitions
- User provisioning, suspension, and access-review evidence
- Security incident and administrator activity records
- Configurable retention aligned with approved policy
- Documented release, backup, restoration, and emergency-operation procedures
- Periodic technical evaluation evidence and change history

The practice supplies workforce authorization, training, sanctions, risk
management decisions, facility procedures, and incident-response ownership.

## Technical safeguards

- Unique accounts; no shared scheduler login
- Local directory integration where approved, with a break-glass procedure
- Strong session management and inactivity timeout
- Role and patient-context authorization on every server request
- Server-side denial of patient schedule, operations, and waitlist APIs for the
  read-only auditor role; hiding navigation alone is never an authorization control
- TLS on the internal network
- Encryption for host storage and all backup media
- Append-only audit records with integrity verification
- Parameterized database access and strict structured-input validation
- Default-deny container privileges and outbound network controls
- Secrets and cryptographic keys stored outside source control and images
- Locally verified, pinned release artifacts with checksums and SBOM
- No runtime telemetry, cloud inference, CDN assets, or update checks

## Required audit events

- Authentication success and failure
- Account, role, and policy changes
- Provider, operatory, production-target, availability, and other scheduling
  configuration changes
- Patient record view, creation, and update
- Scheduling request and recommendation generation
- Appointment hold, confirmation, cancellation, and completion
- Rescheduling preview, permission, approval, denial, and execution
- Export, print, backup, restoration, and administrative access
- Security-control or audit-system failure

Audit payloads use opaque record identifiers when possible and exclude free-text
clinical notes, secrets, and full model prompts.

## Availability and contingency controls

- Encrypted backups with at least one offline or otherwise isolated copy
- Automated backup integrity verification
- Periodic documented restoration tests
- Defined recovery objectives approved by the practice
- Emergency-mode scheduling and read-only calendar procedure
- Local monitoring for disk, database, certificate, backup, and audit health
- Documented response for ransomware, hardware failure, fire, and loss of power

## Verification evidence

Each release should retain threat-model review, dependency inventory, SBOM,
artifact hashes, vulnerability-review disposition, automated test results,
authorization tests, audit-event tests, restore-test results, and practice
acceptance sign-off.
