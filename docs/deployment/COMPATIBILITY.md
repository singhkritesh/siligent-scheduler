# Host Compatibility and Preflight

## Why the Compatibility Layer Exists

Most installation failures occur before application code runs: Docker is not
ready, the wrong architecture is imported, Compose is outdated, configuration
is incomplete, a selected local model is missing, certificates are invalid, or storage
is too small. The supported workflow detects these conditions before changing
the running stack.

Run:

```bash
./install.sh --check --without-llm
```

The command is read-only. It does not create configuration, certificates,
images, containers, volumes, or model files.

## Compatibility Matrix

| Host | Container runtime | Intake profiles | Status and notes |
| --- | --- | --- | --- |
| Apple Silicon macOS | Docker Desktop, arm64-compatible images | Rules by default; optional native Ollama | Supported baseline; amd64 emulation is warned and requires performance acceptance |
| Intel macOS | Docker Desktop, amd64 images | Rules by default; optional native Ollama | Supported baseline; performance must be measured on target hardware |
| Linux x86_64 | Docker Engine and Compose v2 | Rules by default; optional host Ollama | Supported baseline; `host.docker.internal` is mapped explicitly |
| Linux arm64 | Docker Engine and Compose v2 | Rules by default; optional host Ollama | Conditional on arm64 release images and acceptable performance |
| Windows 10/11 WSL2 | Docker Desktop Linux containers | Rules by default; optional Windows/WSL-reachable Ollama | Supported through WSL2 Bash after Docker Desktop integration is enabled |
| Windows Git Bash | Docker Desktop Linux containers | Rules by default; optional Windows Ollama | Supported baseline; host tools must be available on Git Bash `PATH` |

Windows Server, Windows containers, 32-bit hosts, and unsupported architectures
are not part of the baseline. Windows 10 deployments must remain within their
vendor-supported lifecycle and organizational patch policy.

## What Preflight Verifies

- Required repository files and identical agent instruction files.
- Bash syntax for every lifecycle entry point.
- Supported operating system and 64-bit architecture.
- Docker availability, engine response, version, and Compose v2.
- Minimum free disk and a model-memory warning threshold.
- Existing `.env` safety, permissions, horizon, and local-only model URL.
- Compose interpolation and configuration validity.
- Imported database/application images or the approved local build base.
- Linux-container architecture compatibility for every imported image.
- Approved references from `deploy/OFFLINE_ARTIFACTS.env`.
- Installed local model when inference is enabled.
- Certificate/key readability and upcoming certificate expiry.

## Offline Artifact Compatibility

Connected installation may install required host packages and retrieve pinned
container/Python artifacts during an approved internet-enabled window. It must
record resolved image identities and dependency inventory before the runtime
offline gate is applied.

The offline core release bundle must include architecture-compatible database and
application images and their immutable digests,
an SBOM, license inventory, vulnerability disposition, configuration schema,
migrations, rollback notes, and signatures/checksums. Setup refuses to retrieve a
missing item from the internet. The separately installable local-AI pack adds the
approved Ollama runtime, model artifact, model identifier, license, and validation
record; it is not required for the deterministic-rules profile.

## Upgrade Compatibility

`scripts/initialize-local-config.sh` appends new keys from `.env.example` while
preserving every existing installation value. A release must never rename or
remove a key without documented migration logic. Database migration and rollback
compatibility are release-specific; back up and prove restoration before schema
change.

## Acceptance on Every Target Host

1. Run the read-only preflight.
2. Run a connected installation or verify and import the approved signed offline bundle.
3. Run the installer and record the generated local credentials securely.
4. Replace the development certificate before production.
5. Run `./verify.sh`; verify host-firewall egress denial and internal time/DNS.
6. Run operational health, annual simulation, database invariants, and API smoke.
7. Complete browser, accessibility, backup restoration, restart recovery, and
   downtime reconciliation tests.
