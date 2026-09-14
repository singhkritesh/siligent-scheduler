#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="verify"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

SKIP_EGRESS=false
WAIT_SECONDS=30
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-egress) SKIP_EGRESS=true ;;
    --wait) [[ $# -ge 2 ]] || siligent_fail '--wait requires seconds.'; WAIT_SECONDS="$2"; shift ;;
    -h|--help) printf 'Usage: ./verify.sh [--wait SECONDS] [--skip-egress]\n'; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done

"$ROOT_DIR/scripts/healthcheck.sh" --wait "$WAIT_SECONDS"
siligent_compose config --quiet

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env"
set +a
for service in database api; do
  running_image_id="$(siligent_compose images -q "$service")"
  [[ -n "$running_image_id" ]] || siligent_fail "No running image is associated with $service."
  if [[ "$service" == "database" ]]; then configured_image="${DATABASE_IMAGE:-postgres@sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416}";
  else configured_image="${API_IMAGE:-siligent-scheduler-api:local}"; fi
  configured_image_id="$(docker image inspect "$configured_image" --format '{{.Id}}')"
  [[ "${running_image_id#sha256:}" == "${configured_image_id#sha256:}" ]] \
    || siligent_fail "$service is running a different image than the installed release. Run ./start.sh and verify again."
done

if [[ "$SKIP_EGRESS" == "false" ]]; then
  "$ROOT_DIR/scripts/verify_no_egress.sh"
else
  siligent_warn 'Egress verification was skipped; this installation is not production-accepted.'
fi

record_file="$ROOT_DIR/.runtime/install-record.env"
if [[ -f "$ROOT_DIR/.runtime/install-record.pending.env" ]]; then
  record_file="$ROOT_DIR/.runtime/install-record.pending.env"
fi
if [[ -f "$record_file" ]]; then
  installed_id="$(sed -n 's/^api_image_id=//p' "$record_file" | tail -n 1)"
  current_id="$(docker image inspect siligent-scheduler-api:local --format '{{.Id}}')"
  [[ -z "$installed_id" || "$installed_id" == "$current_id" ]] \
    || siligent_fail 'The installed API image differs from the recorded installation image.'
fi
if [[ -f "$ROOT_DIR/RELEASE-MANIFEST.json" ]]; then
  "$ROOT_DIR/scripts/verify_imported_images.sh" "$ROOT_DIR/RELEASE-MANIFEST.json"
fi
siligent_info 'Runtime verification passed.'
