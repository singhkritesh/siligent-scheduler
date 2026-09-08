# Offline Deployment Runbook

## Release bundle contents

The build environment may retrieve approved source dependencies, but production
must not. Transfer a versioned core release bundle containing:

- OCI container-image archive for every service
- `docker-compose.yml` and configuration schema
- Database migrations and rollback notes inside the API image
- SHA-256 manifest and detached signature
- Software bill of materials
- Dependency and vulnerability review
- Release notes, known limitations, and restore compatibility

When local-model assistance is approved, transfer a separate local-AI pack
containing the approved Ollama runtime, the pinned model artifact, its identifier
and digest, license evidence, and model validation record. The core scheduler
does not require this pack.

Do not place production secrets, private keys, PHI, or database snapshots in the
release bundle.

## Controlled import

1. Receive the bundle on approved media.
2. Record custody and release identifier.
3. Scan the media on the designated inspection system.
4. Verify the signature and every manifest hash.
5. Import images with `docker load`; do not use `docker pull`.
6. Confirm imported image IDs against the signed manifest.
7. Run `./install.sh --offline --without-llm` for the core rules profile, or
   `./install.sh --offline --with-local-model` only after verifying and importing
   the optional AI pack.
8. Install the practice-issued internal TLS certificate and protected key.
9. Verify host firewall default-deny outbound rules.
10. Run local health, authorization, scheduling, audit, backup, and restoration
    acceptance tests before making the release available to staff.

## Startup and shutdown

`./install.sh --offline` verifies the bundle signature and every file hash,
imports the OCI images, checks image architecture, creates or upgrades `.env`,
stores the selected profile, starts the stack, verifies runtime egress denial,
and installs a desktop launcher. `./setup.sh` remains the offline shared
configuration engine. `./build.sh` builds the application image from its pinned,
already-imported base with build networking disabled. `./start.sh` verifies the named images exist
locally and invokes Compose with `--no-build --pull never`. It creates random
local secrets on first use and refuses placeholder values. `./stop.sh` stops
containers without deleting volumes.

Never run `docker compose down -v` against production. Volume deletion is not a
normal uninstallation or upgrade operation.

Build a platform-specific release on a controlled build workstation:

```bash
./scripts/build_offline_bundle.sh \
  --platform linux/amd64 \
  --signing-key /approved/release-signing-key.pem
```

The signing key is never copied into the bundle. The builder includes a public
verification key, checksums, resolved image IDs, Python/OS dependency inventory,
license metadata, and an SPDX SBOM. `--unsigned-development` is available only
for non-production testing and must be explicitly accepted at install time.
`scripts/build_windows_offline_bundle.sh` produces the equivalent Windows AMD64
ZIP with the PowerShell wrappers included.

The desktop launcher opens an already healthy UI without restarting it. If the
stack is stopped, it starts Docker when supported, runs the validated daily
startup, waits for offline health, writes failures to
`.runtime/desktop-launcher.log`, and then opens the local HTTPS address.

## Production networking

- Expose only the application's internal TLS port.
- Do not expose PostgreSQL or the local model to practice workstations.
- Restrict workstation access to approved practice network segments.
- Deny container and host outbound internet traffic.
- Use an approved internal DNS name and certificate trust chain.
- Provide local time synchronization; scheduling correctness depends on accurate
  time and timezone configuration.

## Update and rollback

Updates use the same signed-media process. The installer starts the existing
database if necessary, creates a pre-upgrade backup, and retains the previous API
image under a timestamped rollback tag before importing replacements. Retain
those artifacts until acceptance tests pass. A rollback must never discard
appointment or audit records created after an update; schema compatibility and
data migration require release-specific instructions.
