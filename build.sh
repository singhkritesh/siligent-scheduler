#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
ARTIFACT_MANIFEST="$ROOT_DIR/deploy/OFFLINE_ARTIFACTS.env"
MODE="offline"
MODE_SELECTED=false
BUILD_BUNDLE=false
BUNDLE_ARGS=()
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.11.15-slim-trixie@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff}"

usage() {
  printf '%s\n' \
    'Usage: ./build.sh [options]' \
    '  --offline                  Build from the approved preloaded base (default).' \
    '  --connected                Retrieve the Python base and pinned dependencies.' \
    '  --bundle                   Package images after a successful build.' \
    '  --output DIR               Bundle output directory.' \
    '  --version VALUE            Bundle version override.' \
    '  --platform linux/ARCH      Bundle platform.' \
    '  --archive-format FORMAT    tar.gz or zip.' \
    '  --source-revision VALUE    Release revision when Git metadata is absent.' \
    '  --signing-key PEM          Sign a production bundle.' \
    '  --allow-dirty              Allow an explicitly marked dirty source.' \
    '  --unsigned-development     Create a non-production unsigned bundle.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) [[ "$MODE_SELECTED" == "false" ]] || { printf '[build][error] Choose one build mode.\n' >&2; exit 1; }; MODE="offline"; MODE_SELECTED=true ;;
    --connected) [[ "$MODE_SELECTED" == "false" ]] || { printf '[build][error] Choose one build mode.\n' >&2; exit 1; }; MODE="connected"; MODE_SELECTED=true ;;
    --bundle) BUILD_BUNDLE=true ;;
    --output|--version|--platform|--signing-key|--archive-format|--source-revision)
      [[ $# -ge 2 ]] || { printf '[build][error] %s requires a value.\n' "$1" >&2; exit 1; }
      BUNDLE_ARGS+=("$1" "$2")
      shift
      ;;
    --unsigned-development|--allow-dirty) BUNDLE_ARGS+=("$1") ;;
    -h|--help) usage; exit 0 ;;
    *) printf '[build][error] Unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
  shift
done

if [[ "$BUILD_BUNDLE" == "false" && ${#BUNDLE_ARGS[@]} -gt 0 ]]; then
  printf '[build][error] Bundle options require --bundle.\n' >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || {
  printf "[build][error] Docker is required.\n" >&2
  exit 1
}

[[ -f "$ARTIFACT_MANIFEST" ]] || {
  printf "[build][error] The approved offline artifact manifest is missing.\n" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$ARTIFACT_MANIFEST"

[[ "$PYTHON_BASE_IMAGE" == "$APPROVED_CONNECTED_PYTHON_BASE_REFERENCE" ]] || {
  printf '[build][error] PYTHON_BASE_IMAGE does not match the approved connected-build reference.\n' >&2
  exit 1
}
if command -v shasum >/dev/null 2>&1; then
  requirements_hash="$(shasum -a 256 "$ROOT_DIR/requirements.runtime.lock" | awk '{print $1}')"
else
  requirements_hash="$(sha256sum "$ROOT_DIR/requirements.runtime.lock" | awk '{print $1}')"
fi
[[ "$requirements_hash" == "$APPROVED_RUNTIME_REQUIREMENTS_SHA256" ]] || {
  printf '[build][error] requirements.runtime.lock does not match the approved manifest.\n' >&2
  exit 1
}

api_image="siligent-scheduler-api:local"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  api_image="${API_IMAGE:-$api_image}"
fi

if [[ "$MODE" == "connected" ]]; then
  printf "[build] Building %s during the approved connected install window...\n" "$api_image"
  docker build --pull=true --network=default --provenance=false \
    --build-arg "PYTHON_BASE_IMAGE=$PYTHON_BASE_IMAGE" \
    -f "$ROOT_DIR/backend/Dockerfile.connected" -t "$api_image" "$ROOT_DIR"
  docker pull "$APPROVED_DATABASE_IMAGE"
else
  dockerfile_base="$(awk 'toupper($1) == "FROM" {print $2; exit}' "$ROOT_DIR/backend/Dockerfile")"
  [[ "$dockerfile_base" == "$APPROVED_API_BASE_REFERENCE" ]] || {
    printf "[build][error] backend/Dockerfile does not use the approved API base.\n" >&2
    exit 1
  }
  docker image inspect "$APPROVED_API_BASE_LOCAL_TAG" >/dev/null 2>&1 || {
    printf "[build][error] The approved local base image %s is missing.\n" "$APPROVED_API_BASE_LOCAL_TAG" >&2
    exit 1
  }
  printf "[build] Building %s using local artifacts only...\n" "$api_image"
  docker build --pull=false --network=none --provenance=false \
    -f "$ROOT_DIR/backend/Dockerfile" -t "$api_image" "$ROOT_DIR"
fi
printf "[build] Application image is ready: %s\n" "$api_image"

if [[ "$BUILD_BUNDLE" == "true" ]]; then
  if (( ${#BUNDLE_ARGS[@]} > 0 )); then
    "$ROOT_DIR/scripts/build_offline_bundle.sh" "${BUNDLE_ARGS[@]}"
  else
    "$ROOT_DIR/scripts/build_offline_bundle.sh"
  fi
fi
