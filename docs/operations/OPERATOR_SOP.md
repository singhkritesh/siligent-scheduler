# Scheduler Operator Standard Operating Procedure

## First Installation

For a connected installation window, IT runs:

```bash
./install.sh --check --without-llm
./install.sh --connected --without-llm
```

For a signed offline bundle, use `./install.sh --offline --without-llm`.
The default profile does not install or require Ollama. IT may explicitly use
`./install.sh --with-local-model` during a connected installation or after an
approved local-AI pack is present. Internet access is removed or denied for the
application runtime after installation verification.

Store the displayed initial administrator password in the approved password
manager. Replace the generated development certificate with the practice-issued
certificate before production use.

## Daily Start

Use the **Siligent Scheduler** desktop icon installed by setup. It opens a healthy
application without restarting it; otherwise it starts the validated local stack
and waits for health. IT may use the equivalent command:

```bash
./start.sh
```

Open the displayed HTTPS address. Do not bypass a certificate warning in
production; ask IT to repair the internal certificate trust.

## Confirm Health

```bash
./verify.sh
```

A successful result confirms the offline API response, running database/API
containers, no PostgreSQL host port, recorded application image, and API
public-internet egress denial. It does not prove optional-model quality, backup
recoverability, host storage encryption, or complete HIPAA compliance.

## Daily Scheduling Rules

- Begin on **Home** and follow the role-specific action queue. Use **Today** for
  arrival, seating, outcome, walk-in, and protected rescheduling work; use
  **Calendar** to review month or annual appointment density.
- In **Schedule patient**, complete the four steps in order: find the existing
  patient or enter a new identity, select treatment, set acceptable availability,
  then compare feasible openings. Search the patient directory before creating a
  new identity to reduce duplicate records.
- Use **About this page** when a workspace or safety consequence is unclear. The
  guidance is optional and does not expose help content to an external service.
- Review patient identity, procedure, scheduling context, and normalized intake.
- Treat recommendations as options until one is explicitly confirmed.
- Never move a confirmed appointment through direct editing or database access.
- Use the protected reschedule workflow, select the exact replacement, provide a
  meaningful reason, and acknowledge the change.
- Record cancellation, no-show, completion, walk-in, and waitlist outcomes using
  their supported actions so capacity and audit history remain correct.
- A walk-in means the patient is onsite: search it only for the current practice
  date. The optimizer removes elapsed same-day time automatically. Check in and
  seat patients only on their scheduled practice date, record completion only
  after seating, and record no-show only after the scheduled start when the
  patient has not arrived.
- After recording an eligible future cancellation, use **Review later visits**
  only when you intend to work that exact opening. The system does not rerun the
  day or year automatically.
- In **Focused vacancy recovery**, review the displayed current vacancy and
  choose **Find eligible later visits**. Contact one displayed patient. Do not
  apply a move until that named patient accepts the exact earlier date and time.
  Record the permission channel and note, check both acknowledgements, and apply
  the one move. The patient’s former full slot becomes the next displayed
  vacancy. Repeat only through the same review/permission steps, or choose
  **Finish recovery**. Never interpret an ASAP opt-in as permission for a
  specific move; exact confirmation is still required.
- Treat a recommendation labeled **Authorized override required** as an
  exception. Only an administrator or clinician may search for and confirm it;
  they must record a meaningful reason and approve the exact doctor, procedure,
  room, and time shown. The approval cannot move another appointment.
- Use the versioned reference durations immediately for setup and validation; do not delay
  scheduling because historical timing data is unavailable. Before real-patient
  use, the practice must approve or edit those reference values in Settings. Treat locally
  generated or imported calibration results as optional proposals until an
  authorized reviewer approves them.
- Do not enter unnecessary clinical narrative into scheduling or contact notes.

## Administrative Workspace

- Use **Settings > Team and access** for support providers and unique user
  accounts.
- Use **Settings > Availability** for reserved procedure blocks, provider leave,
  daily overrides, and full-practice closures.
- To protect procedure capacity, create a reserved block with the dentist,
  procedure, start/end time, operational reason, and optional eligible room,
  required equipment unit, or automatic release time. The system rejects a block
  that intersects a held or confirmed appointment.
- Release an active block through its **Release** action and record the reason.
  Do not attempt to edit or delete block history. Fulfilled, released, and
  automatically released blocks remain available as audit evidence.
- Use **Settings > Rooms and equipment** for physical capacity and procedure
  equipment requirements.
- Use **Settings > Procedure rules** only with the required clinical approval for
  supervision, preferences, and procedure phases.
- Use **Settings > Duration recommendations** for optional de-identified local
  evidence. Reference defaults remain active without an import.
- Review the current summary before expanding any add or edit form. A successful
  change remains visible in the activity banner and is recorded in the audit log.

## Batch Scheduling Simulation

Use **Insights > Simulation** to test a de-identified set of incoming requests
without changing the practice calendar.

1. Download the blank CSV template from the page, or prepare a CSV/XLSX workbook
   whose first worksheet uses the displayed schema. Use opaque values such as
   `PAT-001` for `patient_ref`; never include a name, MRN, date of birth, phone,
   email, address, condition narrative, or notes.
2. Select the file and choose **Validate and preview**. Validation is all-or-none.
   Resolve any rejected column, code, duplicate, date, status, or formula before
   proceeding. Review row count, date range, procedure mix, and the count of
   uploaded estimates replaced by current approved policy.
3. Choose **Run simulation** only after the preview is correct. The replay reads
   live policy and capacity once, processes requests by `request_received_at`,
   and locks each hypothetical placement before evaluating the next request.
4. Review scheduled/unscheduled totals, feasibility rate, wait, production,
   invariants, and the per-request doctor, room, start, and end time. Download
   result CSV and report JSON only to approved local storage.
5. Treat results as planning evidence, not appointments. The simulation cannot
   create, confirm, cancel, move, or reslot a live booking. Schedule accepted
   work through **Schedule patient**, where current capacity is checked again.

Uploads are limited to 5 MB and 1,000 request rows and must remain within the
rolling scheduling horizon. CSV must be UTF-8. XLSX formulas are rejected and
only the first worksheet is read. Include a timezone offset in
`request_received_at`; the simulator never places a visit before that timestamp.
Historical demand must first be de-identified and date-shifted into the current
rolling horizon. Uploaded content and row results are not saved
by the server; a minimum audit entry records that a preview or run occurred.

## Duration Evidence and Calibration

- Do not wait for historical timing data before using the scheduler. Approved
  reference policy remains active while evidence accumulates.
- Record check-in, seating, completion, cancellation, and no-show outcomes
  accurately; valid completion timing may produce a de-identified duration
  observation.
- Calibration data contains no patient identifier and no appointment link. Do
  not add names, MRNs, dates of birth, condition text, phone numbers, or free-text
  notes to an import.
- Treat an import as optional local evidence. Use only the documented restricted
  columns and review rejected rows rather than altering validation controls.
- A recommendation is available only after the approved evidence threshold. An
  administrator or clinician must review sample size and proposed standard and
  complex durations, record a reason, and explicitly approve or reject it.
- Calibration never changes an existing confirmed appointment. Escalate any
  indication of automatic application or rescheduling immediately.

## Success-Metric Review

- Review safety and privacy exceptions immediately: unauthorized moves,
  resource conflicts, missing protected-action audit evidence, external data
  transfer, or patient data found in logs/calibration all have a target of zero.
- During a pilot, review recommendation acceptance, staff handling time,
  feasible-search rate, waitlist recovery, booking lead time, patient wait,
  response latency, model fallback, and adoption weekly.
- Review calibration validity and prospective error only after sufficient
  comparable data exists. Do not approve a policy change because a dashboard
  number changed without reviewing sample size, data quality, and operational
  context.
- Use the formulas and initial targets in
  `docs/PRODUCT_DATA_AND_SUCCESS_METRICS.md`; deployment owners must approve
  final thresholds and document exclusions.

## Safe Shutdown

```bash
./stop.sh
```

This stops the stack and preserves the database volume. Do not add a volume
deletion option to routine shutdown instructions.

## Backup, Restore, and Uninstall

Create a protected backup with `./backup.sh --destination APPROVED_PATH`. The
dump and configuration copy contain sensitive data and must be moved to approved
encrypted storage. Restore with `./restore.sh BACKUP.dump`; restoration requires
explicit confirmation and automatically creates a current-state safety backup.

`./uninstall.sh` stops services and removes the recognized desktop launcher. It
does not delete PostgreSQL volumes, configuration, certificates, images, or
backups. Retention and secure disposal remain separate IT-controlled procedures.

## After Restart, Update, or Restore

1. Run the health check.
2. Verify the practice date, local time, timezone, and certificate.
3. Confirm the current-day calendar and a non-mutating recommendation search.
4. Review local alerts and audit availability.
5. After restore, follow the approved reconciliation procedure before normal use.

## Escalate to IT

- Health check fails or a container remains unhealthy.
- Certificate warning appears in production.
- A model-enabled installation reports that its approved local model is missing
  or unavailable. Rules-only installations do not require Ollama.
- `./verify.sh` or `scripts/verify_no_egress.sh` reports that the API container
  can reach a public address. Do not activate production until IT applies the
  authoritative host/container deny policy and the non-skipped check passes.
- The desktop launcher reports a failure; provide IT with
  `.runtime/desktop-launcher.log`, after verifying that it contains no manually
  added sensitive information.
- Clock, timezone, disk, database, audit, or backup health is abnormal.
- A recommendation conflicts during confirmation more than once.
- A reserved block is missing, appears to overlap an existing appointment, is
  used by a nonmatching request without an audited override, or fails to release
  at the configured policy time.
- An appointment appears to have moved without the protected workflow.
- A vacancy recovery step shows the wrong doctor/room/start, moves more than the
  selected patient, accepts a stale option, lacks exact patient permission, or
  appears to have rerun other bookings.
- Any suspected unauthorized access, export, disclosure, or loss occurs.
