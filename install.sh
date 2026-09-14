#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="install"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

MODE="auto"
ASSUME_YES=false
CHECK_ONLY=false
PROFILE="preserve"
PROFILE_EXPLICIT=false
NO_START=false
NO_LAUNCHER=false
ALLOW_UNSIGNED=false
FINALIZE_RUNTIME=false
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.11.15-slim-trixie@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff}"

usage() {
  printf '%s\n' \
    'Usage: ./install.sh [options]' \
    '' \
    'Supported first-install and idempotent upgrade entry point.' \
    '' \
    '  --connected          Permit prerequisite, image, dependency, and model downloads.' \
    '  --offline            Require images and manifests from this extracted bundle.' \
    '  --check              Read-only compatibility audit; install nothing.' \
    '  --yes                Approve prerequisite installation non-interactively.' \
    '  --without-llm        Install the default deterministic-rules profile.' \
    '  --with-local-model   Install and validate approved host-local Ollama assistance.' \
    '  --no-start           Install without starting services.' \
    '  --no-launcher        Skip desktop launcher creation.' \
    '  --finalize-runtime   Require public-internet egress denial before success.' \
    '  --allow-unsigned-development-bundle  Accept an unsigned offline development bundle.' \
    '  -h, --help           Show this help.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --connected) [[ "$MODE" != "offline" ]] || siligent_fail 'Choose connected or offline, not both.'; MODE="connected" ;;
    --offline) [[ "$MODE" != "connected" ]] || siligent_fail 'Choose connected or offline, not both.'; MODE="offline" ;;
    --check) CHECK_ONLY=true ;;
    --yes) ASSUME_YES=true ;;
    --without-llm) [[ "$PROFILE_EXPLICIT" == "false" ]] || siligent_fail 'Choose one intake profile.'; PROFILE="without-llm"; PROFILE_EXPLICIT=true ;;
    --with-local-model) [[ "$PROFILE_EXPLICIT" == "false" ]] || siligent_fail 'Choose one intake profile.'; PROFILE="with-local-model"; PROFILE_EXPLICIT=true ;;
    --no-start) NO_START=true ;;
    --no-launcher) NO_LAUNCHER=true ;;
    --finalize-runtime) FINALIZE_RUNTIME=true ;;
    --allow-unsigned-development-bundle) ALLOW_UNSIGNED=true ;;
    -h|--help) usage; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done

if [[ "$MODE" == "auto" ]]; then
  if [[ -d "$ROOT_DIR/images" && -f "$ROOT_DIR/SHA256SUMS" ]]; then MODE="offline"; else MODE="connected"; fi
fi

setup_args=()
case "$PROFILE" in
  without-llm) setup_args+=(--without-llm) ;;
  with-local-model) setup_args+=(--with-local-model) ;;
  preserve) ;;
esac
[[ "$NO_START" == "true" ]] && setup_args+=(--no-start)
[[ "$NO_LAUNCHER" == "true" ]] && setup_args+=(--no-launcher)

if [[ "$CHECK_ONLY" == "true" ]]; then
  siligent_info "Read-only $MODE installation audit."
  if [[ "$MODE" == "offline" ]]; then
    [[ "$ALLOW_UNSIGNED" == "true" ]] && export ALLOW_UNSIGNED_DEVELOPMENT_BUNDLE=true
    "$ROOT_DIR/scripts/verify_bundle.sh" "$ROOT_DIR"
  fi
  if (( ${#setup_args[@]} > 0 )); then
    exec "$ROOT_DIR/setup.sh" --check "${setup_args[@]}"
  fi
  exec "$ROOT_DIR/setup.sh" --check
fi

if [[ "$MODE" == "offline" ]]; then
  command -v docker >/dev/null 2>&1 || siligent_fail 'Docker is required for an offline installation.'
  docker compose version >/dev/null 2>&1 || siligent_fail 'Docker Compose v2 is required for an offline installation.'
  docker info >/dev/null 2>&1 || siligent_fail 'Docker is installed but not ready.'
  [[ "$ALLOW_UNSIGNED" == "true" ]] && export ALLOW_UNSIGNED_DEVELOPMENT_BUNDLE=true
  "$ROOT_DIR/scripts/verify_bundle.sh" "$ROOT_DIR"
else
  prerequisite_args=()
  [[ "$ASSUME_YES" == "true" ]] && prerequisite_args+=(--yes)
  [[ "$PROFILE" == "with-local-model" ]] && prerequisite_args+=(--with-local-model)
  if (( ${#prerequisite_args[@]} > 0 )); then
    "$ROOT_DIR/scripts/install_prerequisites.sh" "${prerequisite_args[@]}"
  else
    "$ROOT_DIR/scripts/install_prerequisites.sh"
  fi

  if ! docker info >/dev/null 2>&1; then
    if [[ "$(uname -s)" == "Darwin" && -d /Applications/Docker.app ]]; then open -a Docker >/dev/null 2>&1 || true; fi
    if [[ "$(siligent_host_platform)" == windows-* ]]; then
      powershell.exe -NoProfile -Command "Start-Process (Join-Path \$env:ProgramFiles 'Docker\\Docker\\Docker Desktop.exe')" >/dev/null 2>&1 || true
    fi
    siligent_info 'Waiting for Docker to become ready...'
    deadline=$((SECONDS + 180))
    until docker info >/dev/null 2>&1; do
      (( SECONDS < deadline )) || siligent_fail 'Docker did not become ready within three minutes.'
      sleep 2
    done
  fi

fi

# An existing installation is backed up before image tags or schema state can
# change. The previous application image is retained under a rollback tag.
if [[ -f "$ROOT_DIR/.runtime/install-record.env" && -f "$ROOT_DIR/.env" ]]; then
  siligent_info 'Existing installation detected; preparing the database for a pre-upgrade backup...'
  database_was_running=false
  if [[ -n "$(docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/docker-compose.yml" ps --status running -q database)" ]]; then
    database_was_running=true
  fi
  docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/docker-compose.yml" \
    up -d --no-build --pull never database
  "$ROOT_DIR/backup.sh" --destination "$ROOT_DIR/backups/pre-upgrade"
  if [[ "$database_was_running" == "false" ]]; then
    docker compose --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/docker-compose.yml" stop database
  fi
  old_api_id="$(docker image inspect siligent-scheduler-api:local --format '{{.Id}}' 2>/dev/null || true)"
  if [[ -n "$old_api_id" ]]; then
    rollback_tag="siligent-scheduler-api:rollback-$(date -u '+%Y%m%dT%H%M%SZ')"
    docker image tag "$old_api_id" "$rollback_tag"
    siligent_info "Retained previous API image as $rollback_tag"
  fi
fi

if [[ "$MODE" == "offline" ]]; then
  "$ROOT_DIR/scripts/import_offline_images.sh" "$ROOT_DIR/images"
  "$ROOT_DIR/scripts/verify_imported_images.sh" "$ROOT_DIR/RELEASE-MANIFEST.json"
else

  # shellcheck disable=SC1091
  source "$ROOT_DIR/deploy/OFFLINE_ARTIFACTS.env"
  siligent_info 'Building the application and retrieving pinned install-time artifacts...'
  PYTHON_BASE_IMAGE="$PYTHON_BASE_IMAGE" "$ROOT_DIR/build.sh" --connected

  if [[ "$PROFILE" == "with-local-model" ]]; then
    if siligent_have ollama; then ollama_command=ollama; elif siligent_have ollama.exe; then ollama_command=ollama.exe; else siligent_fail 'Ollama was selected but is unavailable.'; fi
    if ! "$ollama_command" list >/dev/null 2>&1; then
      case "$(siligent_host_platform)" in
        macos)
          if siligent_have brew && brew list ollama >/dev/null 2>&1; then brew services start ollama >/dev/null;
          elif [[ -d /Applications/Ollama.app ]]; then open -a Ollama >/dev/null; fi
          ;;
        linux)
          if siligent_have systemctl; then
            if [[ "$(id -u)" -eq 0 ]]; then systemctl enable --now ollama;
            elif siligent_have sudo; then sudo systemctl enable --now ollama; fi
          fi
          ;;
        windows-*)
          powershell.exe -NoProfile -Command "Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden" >/dev/null 2>&1 || true
          ;;
      esac
      deadline=$((SECONDS + 90))
      until "$ollama_command" list >/dev/null 2>&1; do
        (( SECONDS < deadline )) || siligent_fail 'Ollama was installed but its local service did not become ready.'
        sleep 2
      done
    fi
    siligent_info "Retrieving the approved optional local model: $APPROVED_LOCAL_MODEL_ID"
    "$ollama_command" pull "$APPROVED_LOCAL_MODEL_ID"
  fi
fi

mkdir -p "$ROOT_DIR/.runtime"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi
{
  printf 'version=%s\n' "$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
  printf 'installed_at_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf 'installation_mode=%s\n' "$MODE"
  if [[ -f "$ROOT_DIR/.env" ]]; then
    configured_model="$(sed -n 's/^LOCAL_MODEL_ENABLED=//p' "$ROOT_DIR/.env" | tail -n 1)"
    if [[ "$configured_model" == "true" ]]; then printf 'profile=with-local-model\n'; else printf 'profile=without-llm\n'; fi
  else
    printf 'profile=%s\n' "$PROFILE"
  fi
  printf 'host=%s/%s\n' "$(uname -s)" "$(uname -m)"
  printf 'docker_version=%s\n' "$(docker version --format '{{.Client.Version}}')"
  printf 'compose_version=%s\n' "$(docker compose version --short)"
  printf 'openssl_version=%s\n' "$(openssl version | awk '{print $2}')"
  if command -v ollama >/dev/null 2>&1; then printf 'ollama_version=%s\n' "$(ollama --version 2>/dev/null | awk 'END {print $NF}')"; fi
  if command -v ollama.exe >/dev/null 2>&1; then printf 'ollama_version=%s\n' "$(ollama.exe --version 2>/dev/null | awk 'END {print $NF}')"; fi
  docker image inspect siligent-scheduler-api:local --format 'api_image_id={{.Id}}'
  docker image inspect "${DATABASE_IMAGE:-postgres:16-alpine}" --format 'database_image_id={{.Id}}'
  if docker image inspect "$PYTHON_BASE_IMAGE" >/dev/null 2>&1; then
    docker image inspect "$PYTHON_BASE_IMAGE" --format 'connected_base_image_id={{.Id}}'
  fi
} >"$ROOT_DIR/.runtime/install-record.pending.env"
chmod 600 "$ROOT_DIR/.runtime/install-record.pending.env"

if (( ${#setup_args[@]} > 0 )); then
  "$ROOT_DIR/setup.sh" --skip-build "${setup_args[@]}"
else
  "$ROOT_DIR/setup.sh" --skip-build
fi
if [[ "$NO_START" == "false" ]]; then
  if [[ "$MODE" == "offline" || "$FINALIZE_RUNTIME" == "true" ]]; then
    "$ROOT_DIR/verify.sh"
  else
    "$ROOT_DIR/verify.sh" --skip-egress
    siligent_warn 'Connected installation is staged, not production-activated.'
    siligent_warn 'Close the approved internet window, apply host/container egress denial, then run ./verify.sh.'
  fi
fi
mv "$ROOT_DIR/.runtime/install-record.pending.env" "$ROOT_DIR/.runtime/install-record.env"
siligent_info 'Installation completed. Normal startup does not download or update artifacts.'
