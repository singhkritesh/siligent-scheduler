#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

print_info() {
  printf "[stop] %s\n" "$1"
}

print_error() {
  printf "[stop][error] %s\n" "$1" >&2
}

command -v docker >/dev/null 2>&1 || {
  print_error "Docker is unavailable. Nothing was changed."
  exit 1
}

docker compose version >/dev/null 2>&1 || {
  print_error "The Docker Compose plugin is unavailable. Nothing was changed."
  exit 1
}

compose_args=(-f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  compose_args=(--env-file "$ENV_FILE" "${compose_args[@]}")
fi

print_info "Stopping the application stack while preserving database volumes..."
(
  cd "$ROOT_DIR"
  docker compose "${compose_args[@]}" down --remove-orphans "$@"
)

print_info "Shutdown complete. Patient and audit data volumes were preserved."

