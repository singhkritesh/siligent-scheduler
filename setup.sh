#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
EXAMPLE_ENV_FILE="$ROOT_DIR/.env.example"
ARTIFACT_MANIFEST="$ROOT_DIR/deploy/OFFLINE_ARTIFACTS.env"
CHECK_ONLY=false
START_APP=true
BUILD_IMAGE=true
INSTALL_LAUNCHER=true
LOCAL_MODEL_PROFILE="preserve"
HOST_OS=""
HOST_ARCH=""
HOST_PLATFORM=""
DOCKER_TIMEOUT_SECONDS="${DOCKER_TIMEOUT_SECONDS:-20}"

log() { printf "[setup] %s\n" "$1"; }
warn() { printf "[setup][warn] %s\n" "$1" >&2; }
fail() { printf "[setup][error] %s\n" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  printf '%s\n' \
    'Usage: ./setup.sh [options]' \
    '' \
    'Validate, configure, build, and optionally start the offline scheduler.' \
    '' \
    'Options:' \
    '  --check             Run a detailed read-only compatibility audit.' \
    '  --without-llm       Use deterministic intake rules; Ollama is not required.' \
    '  --with-local-model  Require the approved host-local Ollama model.' \
    '  --no-start          Prepare and build without starting the stack.' \
    '  --skip-build        Reuse the already imported application image.' \
    '  --no-launcher       Do not install or refresh the desktop launcher.' \
    '  -h, --help          Show this help.' \
    '' \
    'New installations default to --without-llm. Existing installations preserve' \
    'their saved mode unless an explicit profile option is supplied.' \
    'This installer never downloads packages, images, or model artifacts.'
}

is_wsl() {
  [[ -n "${WSL_INTEROP:-}" ]] \
    || { [[ -r /proc/sys/kernel/osrelease ]] \
      && grep -qi microsoft /proc/sys/kernel/osrelease; }
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  "$@" &
  local command_pid=$!
  (
    sleep "$timeout_seconds"
    kill "$command_pid" 2>/dev/null || true
  ) &
  local timer_pid=$!
  local status=0
  if wait "$command_pid"; then status=0; else status=$?; fi
  kill "$timer_pid" 2>/dev/null || true
  wait "$timer_pid" 2>/dev/null || true
  return "$status"
}

parse_args() {
  local profile_selected="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check) CHECK_ONLY=true; BUILD_IMAGE=false; START_APP=false ;;
      --without-llm)
        [[ "$profile_selected" == "false" ]] \
          || fail "Choose only one of --without-llm or --with-local-model."
        LOCAL_MODEL_PROFILE="without-llm"
        profile_selected="true"
        ;;
      --with-local-model)
        [[ "$profile_selected" == "false" ]] \
          || fail "Choose only one of --without-llm or --with-local-model."
        LOCAL_MODEL_PROFILE="with-local-model"
        profile_selected="true"
        ;;
      --no-start) START_APP=false ;;
      --skip-build) BUILD_IMAGE=false ;;
      --no-launcher) INSTALL_LAUNCHER=false ;;
      -h|--help) usage; exit 0 ;;
      *) fail "Unknown option: $1" ;;
    esac
    shift
  done
}

detect_host() {
  HOST_OS="$(uname -s)"
  HOST_ARCH="$(uname -m)"
  case "$HOST_OS" in
    Darwin) HOST_PLATFORM="macos" ;;
    Linux)
      if is_wsl; then HOST_PLATFORM="windows-wsl2"; else HOST_PLATFORM="linux"; fi
      ;;
    MINGW*|MSYS*|CYGWIN*) HOST_PLATFORM="windows-git-bash"; HOST_OS="Windows" ;;
    *) fail "Unsupported host operating system: $HOST_OS" ;;
  esac
  case "$HOST_ARCH" in
    x86_64|amd64|arm64|aarch64) ;;
    *) fail "Unsupported host architecture: $HOST_ARCH" ;;
  esac
  log "Detected host: $HOST_PLATFORM ($HOST_ARCH)"
}

check_repository() {
  local required
  for required in \
    AGENTS.md CLAUDE.md MEMORY.md README.md PRODUCTION_READINESS.md \
    .env.example docker-compose.yml install.sh setup.sh build.sh start.sh stop.sh \
    verify.sh backup.sh restore.sh uninstall.sh VERSION requirements.runtime.lock \
    deploy/OFFLINE_ARTIFACTS.env deploy/windows/install-scheduler-shortcut.ps1 \
    deploy/windows/uninstall-scheduler-shortcut.ps1 \
    scripts/initialize-local-config.sh \
    scripts/healthcheck.sh scripts/install_desktop_launcher.sh \
    scripts/uninstall_desktop_launcher.sh scripts/launch_ui.sh \
    scripts/install_prerequisites.sh scripts/verify_bundle.sh \
    scripts/import_offline_images.sh scripts/verify_imported_images.sh \
    scripts/build_offline_bundle.sh scripts/build_windows_offline_bundle.sh \
    scripts/verify_no_egress.sh scripts/lib/common.sh \
    backend/Dockerfile backend/Dockerfile.connected database/migrations; do
    [[ -e "$ROOT_DIR/$required" ]] || fail "Required repository item is missing: $required"
  done
  cmp -s "$ROOT_DIR/AGENTS.md" "$ROOT_DIR/CLAUDE.md" \
    || fail "AGENTS.md and CLAUDE.md must be byte-for-byte identical."
  bash -n \
    "$ROOT_DIR/install.sh" "$ROOT_DIR/setup.sh" "$ROOT_DIR/build.sh" "$ROOT_DIR/start.sh" \
    "$ROOT_DIR/stop.sh" "$ROOT_DIR/verify.sh" "$ROOT_DIR/backup.sh" \
    "$ROOT_DIR/restore.sh" "$ROOT_DIR/uninstall.sh" \
    "$ROOT_DIR/scripts/initialize-local-config.sh" \
    "$ROOT_DIR/scripts/healthcheck.sh" \
    "$ROOT_DIR/scripts/install_desktop_launcher.sh" \
    "$ROOT_DIR/scripts/uninstall_desktop_launcher.sh" \
    "$ROOT_DIR/scripts/launch_ui.sh" "$ROOT_DIR/scripts/install_prerequisites.sh" \
    "$ROOT_DIR/scripts/verify_bundle.sh" "$ROOT_DIR/scripts/import_offline_images.sh" \
    "$ROOT_DIR/scripts/verify_imported_images.sh" \
    "$ROOT_DIR/scripts/build_offline_bundle.sh" \
    "$ROOT_DIR/scripts/build_windows_offline_bundle.sh" \
    "$ROOT_DIR/scripts/verify_no_egress.sh" \
    "$ROOT_DIR/scripts/lib/common.sh" \
    || fail "A lifecycle shell script failed syntax validation."
}

check_commands() {
  local command_name
  for command_name in docker curl openssl awk sed grep; do
    have "$command_name" || fail "$command_name is required from the approved offline host bundle."
  done
  have shasum || have sha256sum \
    || fail "shasum or sha256sum is required for artifact verification."
  docker compose version >/dev/null 2>&1 \
    || fail "Docker Compose v2 is required and did not respond."
}

check_docker() {
  run_with_timeout "$DOCKER_TIMEOUT_SECONDS" docker info >/dev/null 2>&1 \
    || fail "Docker did not respond within ${DOCKER_TIMEOUT_SECONDS} seconds. Start Docker and rerun setup."
  local docker_major
  docker_major="$(docker version --format '{{.Client.Version}}' | cut -d. -f1)"
  [[ "$docker_major" =~ ^[0-9]+$ ]] || fail "Could not determine the Docker client version."
  (( docker_major >= 24 )) || fail "Docker 24 or newer is required."
  log "Docker ready: $(docker --version) / $(docker compose version --short)"
}

check_resources() {
  local available_kb
  available_kb="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $4}')"
  local required_kb=$((10 * 1024 * 1024))
  [[ "$available_kb" =~ ^[0-9]+$ ]] || fail "Could not determine free disk space."
  (( available_kb >= required_kb )) \
    || fail "At least 10 GB of free disk space is required for images, model files, database growth, and backups."
  local docker_memory
  docker_memory="$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)"
  if [[ "${LOCAL_MODEL_ENABLED:-false}" == "true" \
    && "$docker_memory" =~ ^[0-9]+$ ]] \
    && (( docker_memory < 6 * 1024 * 1024 * 1024 )); then
    warn "Docker exposes less than 6 GB of memory. The core scheduler can run, but local-model performance must be validated."
  fi
}

config_source() {
  if [[ -f "$ENV_FILE" ]]; then printf '%s\n' "$ENV_FILE"; else printf '%s\n' "$EXAMPLE_ENV_FILE"; fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary_file
  temporary_file="$(mktemp "$ROOT_DIR/.env.profile.XXXXXX")"
  if grep -Eq "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" '
      index($0, key "=") == 1 { print key "=" value; next }
      { print }
    ' "$ENV_FILE" >"$temporary_file"
  else
    cp "$ENV_FILE" "$temporary_file"
    printf '\n%s=%s\n' "$key" "$value" >>"$temporary_file"
  fi
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$ENV_FILE"
}

persist_selected_profile() {
  [[ "$CHECK_ONLY" == "false" ]] || return 0
  case "$LOCAL_MODEL_PROFILE" in
    without-llm)
      set_env_value LOCAL_MODEL_ENABLED false
      log "Selected deterministic intake rules; Ollama is not required."
      ;;
    with-local-model)
      set_env_value LOCAL_MODEL_ENABLED true
      log "Selected the approved host-local intake model."
      ;;
    preserve) ;;
    *) fail "Internal error: unsupported local model profile." ;;
  esac
}

load_config() {
  local source_file
  source_file="$(config_source)"
  set -a
  # shellcheck disable=SC1090
  source "$source_file"
  set +a
  case "$LOCAL_MODEL_PROFILE" in
    without-llm) export LOCAL_MODEL_ENABLED=false ;;
    with-local-model) export LOCAL_MODEL_ENABLED=true ;;
    preserve) ;;
    *) fail "Internal error: unsupported local model profile." ;;
  esac
}

check_config() {
  [[ -f "$EXAMPLE_ENV_FILE" ]] || fail ".env.example is missing."
  if [[ -f "$ENV_FILE" ]]; then
    grep -Eq '(^|=)CHANGE_ME' "$ENV_FILE" \
      && fail ".env contains an unsafe CHANGE_ME placeholder. Run setup without --check or repair the protected configuration."
    if [[ "$HOST_PLATFORM" != "windows-git-bash" ]]; then
      local mode
      mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
      [[ "$mode" == "600" ]] || warn ".env permissions are $mode; 600 is recommended."
    fi
  elif [[ "$CHECK_ONLY" == "true" ]]; then
    warn ".env does not exist yet; setup will create it without overwriting future local values."
  fi
  load_config
  if [[ "${LOCAL_MODEL_ENABLED:-false}" == "true" ]]; then
    case "${LOCAL_MODEL_URL:-}" in
      http://host.docker.internal:*|https://host.docker.internal:*|http://127.0.0.1:*|https://127.0.0.1:*|http://localhost:*|https://localhost:*) ;;
      *) fail "LOCAL_MODEL_URL must resolve to an approved local host endpoint." ;;
    esac
  fi
  [[ "${SCHEDULING_HORIZON_DAYS:-}" =~ ^[0-9]+$ ]] \
    && (( SCHEDULING_HORIZON_DAYS >= 365 )) \
    || fail "SCHEDULING_HORIZON_DAYS must be an integer of at least 365."
  docker compose --env-file "$(config_source)" -f "$ROOT_DIR/docker-compose.yml" config --quiet \
    || fail "Docker Compose configuration validation failed."
}

check_images() {
  local phase="${1:-preflight}"
  local image
  local missing=()
  for image in "${DATABASE_IMAGE:-postgres:16-alpine}"; do
    docker image inspect "$image" >/dev/null 2>&1 || missing+=("$image")
  done
  if [[ "$phase" == "final" || "$BUILD_IMAGE" == "false" ]]; then
    image="${API_IMAGE:-siligent-scheduler-api:local}"
    docker image inspect "$image" >/dev/null 2>&1 || missing+=("$image")
  else
    docker image inspect siligent-api:latest >/dev/null 2>&1 \
      || missing+=("siligent-api:latest (approved local build base)")
  fi
  if (( ${#missing[@]} > 0 )); then
    printf '[setup][error] Missing approved offline artifacts:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    fail "Import and verify the approved offline release bundle; setup will not download missing artifacts."
  fi
  check_image_architecture "${DATABASE_IMAGE:-postgres:16-alpine}"
  if [[ "$phase" == "final" || "$BUILD_IMAGE" == "false" ]]; then
    check_image_architecture "${API_IMAGE:-siligent-scheduler-api:local}"
  else
    check_image_architecture "${APPROVED_API_BASE_LOCAL_TAG:-siligent-api:latest}"
  fi
}

expected_host_architecture() {
  case "$HOST_ARCH" in
    arm64|aarch64) printf 'arm64\n' ;;
    x86_64|amd64) printf 'amd64\n' ;;
    *) fail "Unsupported host architecture: $HOST_ARCH" ;;
  esac
}

check_image_architecture() {
  local image="$1"
  local image_architecture image_os host_architecture
  image_architecture="$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)"
  image_os="$(docker image inspect "$image" --format '{{.Os}}' 2>/dev/null || true)"
  [[ -n "$image_architecture" && -n "$image_os" ]] \
    || fail "Could not inspect the imported image platform for $image."
  [[ "$image_os" == "linux" ]] \
    || fail "The imported image $image targets $image_os; Linux containers are required."
  host_architecture="$(expected_host_architecture)"
  if [[ "$image_architecture" == "$host_architecture" ]]; then
    return 0
  fi
  if [[ "$host_architecture" == "arm64" && "$image_architecture" == "amd64" ]]; then
    warn "$image uses amd64 emulation on an arm64 host; target-host performance acceptance is required."
    return 0
  fi
  fail "The imported image $image targets $image_architecture but this host requires $host_architecture."
}

check_artifact_manifest() {
  [[ -f "$ARTIFACT_MANIFEST" ]] || fail "The offline artifact manifest is missing."
  # shellcheck disable=SC1090
  source "$ARTIFACT_MANIFEST"
  [[ "${DATABASE_IMAGE:-}" == "$APPROVED_DATABASE_IMAGE" ]] \
    || fail "DATABASE_IMAGE is not the approved release reference."
  local dockerfile_base
  dockerfile_base="$(awk 'toupper($1) == "FROM" {print $2; exit}' "$ROOT_DIR/backend/Dockerfile")"
  [[ "$dockerfile_base" == "$APPROVED_API_BASE_REFERENCE" ]] \
    || fail "backend/Dockerfile does not use the approved API base reference."
  local connected_base requirements_hash
  connected_base="$(sed -n 's/^ARG PYTHON_BASE_IMAGE=//p' "$ROOT_DIR/backend/Dockerfile.connected" | head -n 1)"
  [[ "$connected_base" == "$APPROVED_CONNECTED_PYTHON_BASE_REFERENCE" ]] \
    || fail "backend/Dockerfile.connected does not use the approved Python base reference."
  if have shasum; then
    requirements_hash="$(shasum -a 256 "$ROOT_DIR/requirements.runtime.lock" | awk '{print $1}')"
  else
    requirements_hash="$(sha256sum "$ROOT_DIR/requirements.runtime.lock" | awk '{print $1}')"
  fi
  [[ "$requirements_hash" == "$APPROVED_RUNTIME_REQUIREMENTS_SHA256" ]] \
    || fail "requirements.runtime.lock does not match the approved manifest."
  if [[ "${LOCAL_MODEL_ENABLED:-false}" == "true" ]]; then
    [[ "${LOCAL_MODEL_ID:-}" == "$APPROVED_LOCAL_MODEL_ID" ]] \
      || fail "LOCAL_MODEL_ID is not the approved release model."
  fi
}

check_model() {
  [[ "${LOCAL_MODEL_ENABLED:-false}" == "true" ]] || {
    log "Intake profile: deterministic rules (no Ollama or model artifact required)."
    return
  }
  local ollama_command=""
  if have ollama; then ollama_command="ollama"; elif have ollama.exe; then ollama_command="ollama.exe"; else
    fail "The local model is enabled but Ollama is unavailable. Install it from the approved offline bundle or disable the model explicitly."
  fi
  local installed_model_id
  installed_model_id="$(
    "$ollama_command" list 2>/dev/null \
      | awk -v model="${LOCAL_MODEL_ID:-}" 'NR > 1 && $1 == model {print $2; exit}'
  )"
  [[ -n "$installed_model_id" ]] \
    || fail "The approved local model '${LOCAL_MODEL_ID:-unset}' is not installed. Setup will not download it."
  # shellcheck disable=SC1090
  source "$ARTIFACT_MANIFEST"
  [[ "$installed_model_id" == "$APPROVED_LOCAL_MODEL_OLLAMA_ID" ]] \
    || fail "The installed local model identifier does not match the approved offline manifest."
  log "Intake profile: approved host-local model (${LOCAL_MODEL_ID})."
}

check_certificates() {
  local certificate="$ROOT_DIR/certs/server.crt"
  local key="$ROOT_DIR/certs/server.key"
  if [[ ! -f "$certificate" || ! -f "$key" ]]; then
    if [[ "$CHECK_ONLY" == "true" ]]; then
      warn "TLS files do not exist yet; setup will create a development certificate. Replace it before production."
      return
    fi
    fail "TLS configuration was not created."
  fi
  openssl x509 -in "$certificate" -noout >/dev/null 2>&1 || fail "The TLS certificate is unreadable or invalid."
  openssl pkey -in "$key" -noout >/dev/null 2>&1 || fail "The TLS private key is unreadable or invalid."
  if ! openssl x509 -checkend 604800 -noout -in "$certificate" >/dev/null 2>&1; then
    warn "The TLS certificate expires within seven days. Replace it before relying on this installation."
  fi
}

run_preflight() {
  log "Step 1/5: Checking this computer and release structure"
  detect_host
  check_repository
  log "Step 2/5: Checking Docker"
  check_commands
  check_docker
  log "Step 3/5: Preparing and validating local configuration"
  if [[ "$CHECK_ONLY" == "false" ]]; then
    "$ROOT_DIR/scripts/initialize-local-config.sh"
    persist_selected_profile
  fi
  check_config
  check_resources
  check_artifact_manifest
  check_images preflight
  check_model
  check_certificates
}

main() {
  parse_args "$@"
  run_preflight
  if [[ "$CHECK_ONLY" == "true" ]]; then
    log "Compatibility audit passed. No files, images, containers, or services were changed."
    exit 0
  fi
  log "Step 4/5: Building, starting, and verifying the scheduler"
  if [[ "$BUILD_IMAGE" == "true" ]]; then "$ROOT_DIR/build.sh"; fi
  check_images final
  if [[ "$START_APP" == "true" ]]; then
    "$ROOT_DIR/start.sh"
    "$ROOT_DIR/scripts/healthcheck.sh" --wait 120
  else
    "$ROOT_DIR/start.sh" --prepare-only
  fi
  log "Step 5/5: Creating the desktop launcher"
  if [[ "$INSTALL_LAUNCHER" == "true" ]]; then
    "$ROOT_DIR/scripts/install_desktop_launcher.sh"
  else
    log "Desktop launcher installation was skipped by request."
  fi
  if [[ "$START_APP" == "true" ]]; then
    log "Setup complete. Use the Siligent Scheduler desktop icon or open https://127.0.0.1:${UI_PORT:-8443}"
  else
    log "Setup complete without starting the stack. Run ./start.sh when ready."
  fi
}

main "$@"
