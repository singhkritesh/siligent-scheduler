#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="image-verify"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

MANIFEST="${1:-$ROOT_DIR/RELEASE-MANIFEST.json}"
[[ -f "$MANIFEST" ]] || siligent_fail "Release image manifest is missing: $MANIFEST"

verified=0
while IFS='|' read -r image expected_id; do
  [[ -n "$image" && -n "$expected_id" ]] || continue
  actual_id="$(docker image inspect "$image" --format '{{.Id}}' 2>/dev/null || true)"
  [[ -n "$actual_id" ]] || siligent_fail "Imported image is missing: $image"
  [[ "${actual_id#sha256:}" == "${expected_id#sha256:}" ]] \
    || siligent_fail "Imported image ID mismatch: $image"
  verified=$((verified + 1))
done < <(
  sed -n 's/.*"name": "\([^"]*\)", "id": "\([^"]*\)".*/\1|\2/p' "$MANIFEST"
)
(( verified >= 2 )) || siligent_fail 'The release image manifest did not contain the expected images.'
siligent_info "Verified $verified imported image identities."
