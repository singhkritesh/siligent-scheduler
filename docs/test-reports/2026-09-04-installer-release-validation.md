# Installer and Release Validation — 2026-09-04

## Scope

This pass implemented and tested the installation/release structure modeled on
the mature `my_work/dental-audio-privacy-pipeline-work` application while keeping
the scheduler's persistent PostgreSQL, appointment-lock, optional-model, TLS,
and runtime-offline requirements.

## Implemented

- Connected and signed-offline modes behind `install.sh`.
- Missing-prerequisite installation for macOS, common Linux package managers,
  and Windows winget/PowerShell.
- Digest-pinned Python base and exact Python runtime lock.
- Connected and offline build modes in `build.sh`.
- Pre-upgrade database backup and timestamped rollback API image.
- Runtime image identity, health, database exposure, and egress verification.
- Guarded backup, restore, and non-destructive uninstall commands.
- Offline image export, file checksums, signatures, release/image manifest,
  dependency and license inventory, and SBOM release gate.
- Windows install, start, stop, verify, launch, preflight, and optional firewall
  policy wrappers sharing the checked Bash lifecycle.

## Tests executed

- 36 backend/frontend/lifecycle unit and contract tests passed after the final
  installer additions, including valid-signature and tamper-rejection coverage.
- 15 deterministic optimizer tests passed.
- Bash syntax validation passed for every lifecycle script.
- PowerShell parser validation passed for every Windows script using the local
  PowerShell container.
- Read-only installer preflight passed on macOS arm64 with Docker 29.6.1 and
  Compose 5.3.0.
- Connected image build passed using the pinned Python 3.11.15 base digest and
  exact runtime lock.
- Connected installation passed end to end while preserving the saved optional
  local-model profile.
- A second install created a valid PostgreSQL custom-format pre-upgrade dump and
  retained the previous API image under a rollback tag.
- Live API scheduling smoke passed.
- Isolated empty-database first-use scheduling passed and its synthetic Docker
  volume was removed after the test.
- Host-local Ollama remained reachable from the API at its local endpoint.
- ARM64 development bundle construction passed. Its final manifest verified 116 files,
  sensitive-path inspection found no `.env`, certificate, backup, or runtime
  directory, and an intentional file modification was rejected.
- A completely isolated offline installation generated new local secrets and
  TLS material, imported and verified both images, started on a separate port,
  created a PostgreSQL backup, restored it, and returned healthy. Its temporary
  containers, networks, database volume, configuration, and backup were removed.

## Defect found and resolved

The original application bridge option did not prevent Docker Desktop egress.
Changing the published-port network to Docker `internal` blocked public egress
but also made the local HTTPS port unavailable on the tested Docker Desktop
host. The unusable topology was reverted. The final workflow treats connected
installation as staged, requires IT to close the approved internet window and
apply the authoritative host/container egress policy, and then requires a
non-skipped `./verify.sh` before production activation.

## Remaining production evidence

- Create the production bundle with an externally controlled signing key.
- Generate the final SPDX SBOM using an approved `syft` or Docker SBOM tool.
- Approve vulnerability, dependency-license, Docker licensing, and model-license
  disposition.
- Apply target-host storage encryption, practice TLS, backup encryption, time,
  access, monitoring, and egress controls.
- Run the non-skipped activation gate, restoration exercise, browser/accessibility
  acceptance, and practice configuration sign-off on each target platform.

Software tests and packaging controls support, but do not independently establish,
HIPAA compliance.
