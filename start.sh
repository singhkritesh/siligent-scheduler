#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
ARTIFACT_MANIFEST="$ROOT_DIR/deploy/OFFLINE_ARTIFACTS.env"
BUILD_IMAGE=false
PREPARE_ONLY=false

print_info() {
  printf "[start] %s\n" "$1"
}

print_error() {
  printf "[start][error] %s\n" "$1" >&2
}

die() {
  print_error "$1"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD_IMAGE=true ;;
    --prepare-only) PREPARE_ONLY=true ;;
    -h|--help)
      printf '%s\n' \
        'Usage: ./start.sh [--build] [--prepare-only]' \
        '  --build         Rebuild the API image from approved local artifacts.' \
        '  --prepare-only  Validate configuration and artifacts without starting.'
      exit 0
      ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || die "Docker is required and must be installed from the approved offline bundle."
docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is required and must be installed offline."
command -v curl >/dev/null 2>&1 || die "curl is required for local health checks."

if [[ ! -f "$ENV_FILE" || ! -f "$ROOT_DIR/certs/server.crt" || ! -f "$ROOT_DIR/certs/server.key" ]]; then
  "$ROOT_DIR/scripts/initialize-local-config.sh"
fi

# Add future defaults without replacing installation-specific values.
"$ROOT_DIR/scripts/initialize-local-config.sh"

if grep -Eq '(^|=)CHANGE_ME' "$ENV_FILE"; then
  die ".env still contains a CHANGE_ME placeholder. Refusing to start with unsafe secrets."
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

if [[ "${LOCAL_MODEL_ENABLED:-false}" == "true" ]]; then
  case "${LOCAL_MODEL_URL:-}" in
    http://host.docker.internal:*|https://host.docker.internal:*|http://127.0.0.1:*|https://127.0.0.1:*|http://localhost:*|https://localhost:*) ;;
    *) die "LOCAL_MODEL_URL must use an approved local host endpoint." ;;
  esac
  [[ -f "$ARTIFACT_MANIFEST" ]] \
    || die "The approved offline artifact manifest is missing."
  # shellcheck disable=SC1090
  source "$ARTIFACT_MANIFEST"
  [[ "${LOCAL_MODEL_ID:-}" == "$APPROVED_LOCAL_MODEL_ID" ]] \
    || die "LOCAL_MODEL_ID does not match the approved offline manifest."
  if command -v ollama >/dev/null 2>&1; then
    ollama_command="ollama"
  elif command -v ollama.exe >/dev/null 2>&1; then
    ollama_command="ollama.exe"
  else
    die "The local model is enabled but Ollama is unavailable. Run ./setup.sh --check."
  fi
  installed_model_id="$(
    "$ollama_command" list 2>/dev/null \
      | awk -v model="${LOCAL_MODEL_ID:-}" 'NR > 1 && $1 == model {print $2; exit}'
  )"
  [[ "$installed_model_id" == "$APPROVED_LOCAL_MODEL_OLLAMA_ID" ]] \
    || die "The configured local model is missing or does not match the approved identifier."
  print_info "Intake normalization: approved host-local model (${LOCAL_MODEL_ID})."
else
  print_info "Intake normalization: deterministic rules (Ollama not required)."
fi

if [[ "$BUILD_IMAGE" == "true" ]]; then
  "$ROOT_DIR/build.sh"
fi

required_images=(
  "${DATABASE_IMAGE:-postgres@sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416}"
  "${API_IMAGE:-siligent-scheduler-api:local}"
)

missing_images=()
for image in "${required_images[@]}"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    missing_images+=("$image")
  fi
done

if (( ${#missing_images[@]} > 0 )); then
  print_error "Required offline images are missing:"
  for image in "${missing_images[@]}"; do
    printf "  - %s\n" "$image" >&2
  done
  die "Import and verify the approved offline release bundle before starting."
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet \
  || die "Docker Compose configuration validation failed."

if [[ "$PREPARE_ONLY" == "true" ]]; then
  print_info "Configuration and approved offline artifacts are ready."
  exit 0
fi

print_info "Starting the air-gapped application stack..."
(
  cd "$ROOT_DIR"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up \
    -d --no-build --pull never --remove-orphans
)

"$ROOT_DIR/scripts/healthcheck.sh" --wait 60
print_info "Scheduler is ready at https://127.0.0.1:${UI_PORT:-8443}"
(
  cd "$ROOT_DIR"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
)
