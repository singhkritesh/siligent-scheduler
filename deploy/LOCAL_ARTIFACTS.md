# Local Artifact Manifest

The current workstation build was validated with these preloaded artifacts:

- PostgreSQL: `postgres@sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416`
- API base: `siligent-api@sha256:9efe1b01290d236b7c4c68ae9c69cc5a96930aa75593f67db7c417578b2896f6`
- Connected Python base: `python:3.11.15-slim-trixie@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff`
- Runtime requirements SHA-256: `82f4917782c259926782dff17676fb5b4e419dd498492bb5501527060361d231`
- Local model: `qwen3.5:4b`, local Ollama identifier `2a654d98e6fb`

The machine-readable, non-secret companion manifest is
`deploy/OFFLINE_ARTIFACTS.env`. `setup.sh` verifies the configured database
reference, the API base reference, and—only for model-enabled installations—the
local model name and Ollama identifier. The deterministic-rules installation
does not require the optional local-AI artifact pack.

The application image is built locally as `siligent-scheduler-api:local` with
Docker build networking disabled. A production release must export the resulting
image, record its OCI digest, generate an SBOM, sign the manifest, and verify the
bundle on import.

For a connected installation, `install.sh` instead uses
`backend/Dockerfile.connected` during the approved installation window. It
retrieves the configured Python base, installs the exact versions in
`requirements.runtime.lock`, and records the resulting runtime image ID. Normal
startup remains pull-free and network-independent. `setup.sh` retains the
preloaded-base path for controlled offline rebuilding.
