#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="image-import"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

IMAGE_DIR="${1:-$ROOT_DIR/images}"
[[ -d "$IMAGE_DIR" ]] || siligent_fail "Offline image directory is missing: $IMAGE_DIR"
shopt -s nullglob
archives=("$IMAGE_DIR"/*.tar)
shopt -u nullglob
(( ${#archives[@]} > 0 )) || siligent_fail "No Docker image archives were found in $IMAGE_DIR."

for archive in "${archives[@]}"; do
  siligent_info "Importing $(basename "$archive")..."
  docker load --input "$archive"
done
siligent_info 'Offline container images imported.'
