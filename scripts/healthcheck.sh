#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
WAIT_SECONDS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait)
      [[ $# -ge 2 ]] || { printf '[health][error] --wait requires seconds.\n' >&2; exit 1; }
      WAIT_SECONDS="$2"
      shift
      ;;
    -h|--help) printf 'Usage: ./scripts/healthcheck.sh [--wait SECONDS]\n'; exit 0 ;;
    *) printf '[health][error] Unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
  shift
done

[[ "$WAIT_SECONDS" =~ ^[0-9]+$ ]] \
  || { printf '[health][error] --wait must be a non-negative integer.\n' >&2; exit 1; }
[[ -f "$ENV_FILE" ]] \
  || { printf '[health][error] .env is missing. Run ./setup.sh first.\n' >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

UI_PORT="${UI_PORT:-8443}"
BASE_URL="https://127.0.0.1:${UI_PORT}"
DEADLINE=$((SECONDS + WAIT_SECONDS))
COMPOSE_ARGS=(--env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml")

command -v docker >/dev/null 2>&1 || { printf '[health][error] Docker is unavailable.\n' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { printf '[health][error] curl is unavailable.\n' >&2; exit 1; }

while true; do
  response="$(curl --fail --silent --show-error --insecure --max-time 5 "$BASE_URL/health" 2>/dev/null || true)"
  services_ready="true"
  for service in database api; do
    container_id="$(cd "$ROOT_DIR" && docker compose "${COMPOSE_ARGS[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      services_ready="false"
      continue
    fi
    running="$(docker inspect -f '{{.State.Running}}' "$container_id")"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    if [[ "$running" != "true" || ( "$health" != "none" && "$health" != "healthy" ) ]]; then
      services_ready="false"
    fi
  done
  if [[ "$response" == *'"status":"ok"'* \
    && "$response" == *'"mode":"offline"'* \
    && "$services_ready" == "true" ]]; then
    break
  fi
  if (( SECONDS >= DEADLINE )); then
    printf '[health][error] Application did not become healthy at %s.\n' "$BASE_URL" >&2
    (cd "$ROOT_DIR" && docker compose "${COMPOSE_ARGS[@]}" ps) >&2 || true
    exit 1
  fi
  sleep 2
done

for service in database api; do
  container_id="$(cd "$ROOT_DIR" && docker compose "${COMPOSE_ARGS[@]}" ps -q "$service")"
  [[ -n "$container_id" ]] || { printf '[health][error] %s container is missing.\n' "$service" >&2; exit 1; }
  running="$(docker inspect -f '{{.State.Running}}' "$container_id")"
  [[ "$running" == "true" ]] || { printf '[health][error] %s container is not running.\n' "$service" >&2; exit 1; }
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
  if [[ "$health" != "none" && "$health" != "healthy" ]]; then
    printf '[health][error] %s container health is %s.\n' "$service" "$health" >&2
    exit 1
  fi
done

printf '[health] Scheduler healthy: %s\n' "$BASE_URL"
printf '[health] Offline API response verified.\n'
printf '[health] Database and API containers are running and healthy.\n'
