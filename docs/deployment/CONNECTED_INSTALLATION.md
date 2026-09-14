# Connected Installation and Runtime-Offline Transition

Internet access is allowed only during an explicitly approved installation or
upgrade window. Normal application use remains fully on premises and does not
need or use the public internet.

## Install

Run the read-only audit, then the connected installer:

```bash
./install.sh --check --without-llm
./install.sh --connected --without-llm
```

Use `--yes` only in an approved automated deployment. Without it, the installer
asks before installing system packages. The installer supports Homebrew on
macOS; apt, dnf, or pacman on Linux; and winget plus PowerShell on Windows.
Docker, Compose, curl, OpenSSL, CA certificates, and timezone data are installed
only when missing. Linux Docker group changes may require sign-out and a rerun.

The connected application build retrieves the selected Python base image and
the exact versions in `requirements.runtime.lock`. The PostgreSQL image remains
digest-pinned. The resulting local application image identity is recorded in
`.runtime/install-record.env`.

## Optional local model

The default rules profile does not install Ollama:

```bash
./install.sh --connected --without-llm
```

Only an explicitly selected local-model profile installs Ollama and retrieves
the approved model during the installation window:

```bash
./install.sh --connected --with-local-model
```

The model can normalize structured intake tags but cannot confirm appointments,
relax constraints, or write to the database.

## Transition to runtime

Connected installation first confirms application health, local image
availability, PostgreSQL non-exposure, and recorded image identity while the
approved download window remains open. It reports the installation as staged.
IT must then close that window, apply the approved host/container egress policy,
and run `./verify.sh`. That production activation gate additionally proves that
the API container cannot connect to a public test address. If policy is already
active, `./install.sh --connected --finalize-runtime` performs the gate inline.
`start.sh` thereafter uses `--no-build --pull never`. There are no remote
frontend assets, telemetry, cloud APIs, update checks, or runtime package downloads.

Production IT must additionally apply and verify the approved host firewall
policy. The Windows package includes an optional administrator-controlled
Docker Desktop policy. Because it affects all Docker workloads, it is never
enabled silently.

## Upgrade

A detected existing installation is backed up before image replacement. The
previous API image is retained with a timestamped rollback tag. Configuration
upgrades append new defaults without replacing local values. After migration,
the complete runtime verification gate must pass before staff access resumes.

## Approved replacement installation

Use this only when the practice has approved destruction of the existing local
scheduler database, configuration, certificates, and backups:

```bash
./install.sh --fresh --yes --connected --without-llm
```

The fresh workflow invokes the guarded purge before configuration, build, and
startup. It removes only product-owned scheduler paths and resources, including
conflicting `.runtime`, `.env`, and `certs` paths, then creates a new empty
database and a new administrator credential. It is not an upgrade or repair
command for a production installation that must retain data.
