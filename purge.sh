#!/usr/bin/env bash
set -Eeuo pipefail

# Controlled disposal of this scheduler's local runtime. This is intentionally
# separate from stop.sh and uninstall.sh because it destroys the database volume.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="purge"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

ASSUME_YES=false
REMOVE_LOCAL_CONFIGURATION=false
REMOVE_BACKUPS=false

usage() {
  printf '%s\n' \
    'Usage: ./purge.sh --yes [--remove-local-configuration] [--remove-backups]' \
    '' \
    'Irreversibly removes this scheduler stack, its Docker networks, named' \
    'database volume, product-owned API image tags, desktop launcher, and runtime' \
    'state. It never removes the repository, shared Docker images, or backups by' \
    'default.' \
    '' \
    '  --yes                         Required explicit acknowledgement.' \
    '  --remove-local-configuration  Also remove .env and local TLS certificate/key files.' \
    '  --remove-backups               Also permanently remove ./backups.' \
    '  -h, --help                     Show this message.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES=true ;;
    --remove-local-configuration) REMOVE_LOCAL_CONFIGURATION=true ;;
    --remove-backups) REMOVE_BACKUPS=true ;;
    -h|--help) usage; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done

[[ "$ASSUME_YES" == "true" ]] || siligent_fail 'Purge is destructive. Re-run with --yes after completing the approved retention and disposal process.'
export SILIGENT_ASSUME_YES=true
siligent_confirm 'This permanently removes the scheduler database volume and local runtime. Continue?'

if siligent_have docker; then
  docker compose version >/dev/null 2>&1 || siligent_fail 'Docker Compose v2 is required to remove the scheduler stack safely.'
  docker info >/dev/null 2>&1 || siligent_fail 'Docker is installed but not ready. No local files were removed.'
  siligent_info 'Removing only this scheduler stack, its networks, and its named database volume...'
  siligent_compose down --volumes --remove-orphans

  api_image="$(awk -F= '/^API_IMAGE=/ {print substr($0, index($0, "=") + 1); exit}' "$ROOT_DIR/.env" 2>/dev/null || true)"
  api_image="${api_image:-siligent-scheduler-api:local}"
  if [[ "$api_image" == siligent-scheduler-api:* || "$api_image" == siligent-api:* ]]; then
    if docker image inspect "$api_image" >/dev/null 2>&1; then
      siligent_info "Removing product-owned application image: $api_image"
      docker image rm "$api_image" >/dev/null || siligent_warn "Could not remove $api_image because another container or tag still references it."
    fi
  else
    siligent_warn "Configured API image is not a recognized product-owned tag; it was preserved: $api_image"
  fi

  while IFS= read -r rollback_image; do
    [[ -n "$rollback_image" ]] || continue
    siligent_info "Removing retained scheduler rollback image: $rollback_image"
    docker image rm "$rollback_image" >/dev/null || siligent_warn "Could not remove $rollback_image because it is still referenced."
  done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' | awk '/^siligent-scheduler-api:rollback-/')
else
  siligent_warn 'Docker is not installed. No containers, networks, volumes, or images were present for this script to remove.'
fi

"$ROOT_DIR/scripts/uninstall_desktop_launcher.sh"
rm -rf "$ROOT_DIR/.runtime"

if [[ "$REMOVE_LOCAL_CONFIGURATION" == "true" ]]; then
  siligent_info 'Removing local scheduler configuration and TLS certificate/key files...'
  rm -f "$ROOT_DIR/.env"
  if [[ -e "$ROOT_DIR/certs" && ! -d "$ROOT_DIR/certs" ]]; then
    siligent_warn 'Removing a conflicting non-directory certificate path left by a failed installation.'
    rm -f "$ROOT_DIR/certs"
  elif [[ -d "$ROOT_DIR/certs" ]]; then
    find "$ROOT_DIR/certs" -maxdepth 1 -type f \( -name '*.crt' -o -name '*.key' -o -name '*.pem' \) -delete
  fi
fi

if [[ "$REMOVE_BACKUPS" == "true" ]]; then
  siligent_info 'Removing local scheduler backups...'
  rm -rf "$ROOT_DIR/backups"
fi

siligent_info 'Purge complete. Source files, offline bundles, shared Docker images, and any unselected local data were preserved.'
