# Staff Lifecycle and Permanent Deletion Validation

## Scope

This change adds administrator-only lifecycle controls for dentists, hygienists,
and assistants in **Settings > Team and access**. It also adds an optional
dentist-to-clinician-account link and a narrow permanent-deletion workflow for
unused, inactive staff records.

## Safety behavior

- Deactivation removes a staff member from future scheduling searches. It never
  cancels, moves, reslots, or changes an existing appointment.
- A dentist with future locked appointments requires an explicit acknowledgement.
  Protected procedure blocks must be deliberately released before the dentist
  can be deactivated; releasing a block does not move an appointment.
- A hygienist or assistant with future appointment phases also requires an
  explicit acknowledgement before deactivation.
- Deactivating a linked dentist disables the linked clinician account and revokes
  its active sessions. Reactivating the dentist does not reactivate the account
  or recreate released blocks.
- Permanent deletion requires an explicit confirmation and reason. The staff
  record must be inactive and have no linked account, appointment or phase
  records, protected blocks, recommendations, waitlist records, duration
  observations, production credit, rescheduling artifacts, or comparable
  protected dependencies.
- For an eligible record, only related configuration is removed: working hours,
  leave, shifts, qualifications, preferences, and targets. Appointment and audit
  evidence are never deleted. The action writes a new append-only audit event.

## Database guard

Migration `0018_doctor_and_account_lifecycle.sql` adds an optional user-to-provider
link and a database trigger. A linked account must use the clinician role and
must link to a doctor provider. This prevents a UI or API client from associating
another workforce role with a dentist account.

## Validation performed

| Check | Result |
| --- | --- |
| Backend and lifecycle unit tests | 65 passed |
| Optimizer tests | 15 passed |
| Python and JavaScript syntax checks | Passed |
| Staged-diff whitespace check | Passed |
| Live TLS smoke workflow | Passed on the local development stack |

The live workflow created synthetic disposable support-provider and dentist
records, confirmed that active records cannot be deleted, deactivated eligible
records, permanently deleted them, and verified that a dentist with a linked
account, future confirmed appointment, and protected block cannot be deleted.
It also verified the required acknowledgement, explicit block release, account
status behavior, appointment lock preservation, and append-only lifecycle audit
events.

## Production boundary

This validation used synthetic data only. Before production activation, the
practice must complete its configuration review, access and workforce controls,
backup/restore validation, device and volume encryption controls, host and
container outbound-egress denial, and the full deployment verification on target
hardware. These safeguards support a HIPAA compliance program; software alone
does not establish compliance.
