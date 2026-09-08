#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="bundle-verify"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

BUNDLE_DIR="${1:-$ROOT_DIR}"
MANIFEST="$BUNDLE_DIR/SHA256SUMS"
[[ -f "$MANIFEST" ]] || siligent_fail "SHA256SUMS is missing from $BUNDLE_DIR."

verified=0
while IFS= read -r line; do
  [[ "$line" =~ ^([a-fA-F0-9]{64})[[:space:]][[:space:]](.+)$ ]] \
    || siligent_fail "Invalid SHA256SUMS entry: $line"
  expected="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
  relative="${BASH_REMATCH[2]#./}"
  [[ "$relative" != /* && "$relative" != *'..'* ]] \
    || siligent_fail "Unsafe manifest path: $relative"
  [[ -f "$BUNDLE_DIR/$relative" ]] || siligent_fail "Bundle file is missing: $relative"
  actual="$(siligent_sha256 "$BUNDLE_DIR/$relative")"
  [[ "$actual" == "$expected" ]] || siligent_fail "Checksum mismatch: $relative"
  verified=$((verified + 1))
done <"$MANIFEST"
(( verified >= 10 )) || siligent_fail 'The release manifest is unexpectedly small.'

if [[ -f "$BUNDLE_DIR/SHA256SUMS.sig" ]]; then
  [[ -f "$BUNDLE_DIR/RELEASE-PUBLIC-KEY.pem" ]] \
    || siligent_fail 'Bundle signature exists but RELEASE-PUBLIC-KEY.pem is missing.'
  openssl dgst -sha256 -verify "$BUNDLE_DIR/RELEASE-PUBLIC-KEY.pem" \
    -signature "$BUNDLE_DIR/SHA256SUMS.sig" "$MANIFEST" >/dev/null \
    || siligent_fail 'Release signature verification failed.'
  siligent_info 'Release signature verified.'
elif [[ "${ALLOW_UNSIGNED_DEVELOPMENT_BUNDLE:-false}" != "true" ]]; then
  siligent_fail 'This bundle is unsigned. Production installation requires SHA256SUMS.sig.'
else
  siligent_warn 'Unsigned development bundle accepted by explicit override.'
fi
siligent_info "Verified $verified release files."
