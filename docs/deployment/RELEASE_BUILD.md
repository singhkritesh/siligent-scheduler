# Release Bundle Build Procedure

Build releases only on an approved, patched workstation with access to the
reviewed source, approved images, vulnerability disposition, and release signing
key. Never build a production release from a workstation containing patient
data.

1. Run application tests, annual simulation, database invariants, and browser
   acceptance.
2. Build the connected image or import the approved image set.
3. Confirm the local database and API image architectures match the target.
4. Run the bundle builder with an external signing key:

```bash
./scripts/build_offline_bundle.sh \
  --version "$(tr -d '[:space:]' < VERSION)" \
  --platform linux/amd64 \
  --signing-key /approved/release-signing-key.pem
```

The builder exports images and packages the lifecycle scripts, application
source needed for validation, migrations, configuration template, Windows
wrappers, documentation, dependency inventories, license metadata, SBOM,
release manifest, SHA-256 manifest, signature, and public verification key. It
excludes `.env`, TLS keys, certificates, runtime logs, backups, database volumes,
and generated patient data.

The output archive receives a separate SHA-256 value for transfer custody. The
receiving organization must authenticate that outer value or the release public
key through an independent approved channel; a public key transported only
inside the same untrusted archive does not by itself establish provenance.

`--unsigned-development` creates a visibly marked testing bundle when no signing
key is available. It cannot be installed without a matching explicit development
override and is not eligible for production acceptance.

For a Windows AMD64 ZIP using the same manifest and signing controls:

```bash
./scripts/build_windows_offline_bundle.sh \
  --source-revision APPROVED_SOURCE_REVISION \
  --signing-key /approved/release-signing-key.pem
```

Signed builds fail when Git metadata is absent unless an approved source revision
is supplied. Dirty Git worktrees are rejected unless the bundle is explicitly
marked as development/non-production.
