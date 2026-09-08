#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="bundle-build"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

OUTPUT_DIR="$ROOT_DIR/offline-bundles"
VERSION="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
case "$(uname -m)" in
  x86_64|amd64) PLATFORM="linux/amd64" ;;
  arm64|aarch64) PLATFORM="linux/arm64" ;;
  *) PLATFORM="linux/unsupported" ;;
esac
SIGNING_KEY=""
UNSIGNED_DEVELOPMENT=false
ALLOW_DIRTY=false
SOURCE_REVISION=""
ARCHIVE_FORMAT="tar.gz"

usage() {
  printf '%s\n' \
    'Usage: ./scripts/build_offline_bundle.sh [options]' \
    '  --output DIR                  Output directory.' \
    '  --version VALUE               Override VERSION.' \
    '  --platform linux/amd64|linux/arm64' \
    '  --archive-format tar.gz|zip    Archive format; Windows deployments use zip.' \
    '  --source-revision VALUE        Required for signed builds without Git metadata.' \
    '  --signing-key PEM             Sign SHA256SUMS and include the public key.' \
    '  --allow-dirty                 Permit an explicitly marked dirty development source.' \
    '  --unsigned-development        Explicitly build a non-production test bundle.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) [[ $# -ge 2 ]] || siligent_fail '--output requires a directory.'; OUTPUT_DIR="$2"; shift ;;
    --version) [[ $# -ge 2 ]] || siligent_fail '--version requires a value.'; VERSION="$2"; shift ;;
    --platform) [[ $# -ge 2 ]] || siligent_fail '--platform requires a value.'; PLATFORM="$2"; shift ;;
    --archive-format) [[ $# -ge 2 ]] || siligent_fail '--archive-format requires a value.'; ARCHIVE_FORMAT="$2"; shift ;;
    --source-revision) [[ $# -ge 2 ]] || siligent_fail '--source-revision requires a value.'; SOURCE_REVISION="$2"; shift ;;
    --signing-key) [[ $# -ge 2 ]] || siligent_fail '--signing-key requires a file.'; SIGNING_KEY="$2"; shift ;;
    --allow-dirty) ALLOW_DIRTY=true ;;
    --unsigned-development) UNSIGNED_DEVELOPMENT=true ;;
    -h|--help) usage; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done

case "$PLATFORM" in linux/amd64|linux/arm64) ;; *) siligent_fail 'Supported bundle platforms are linux/amd64 and linux/arm64.' ;; esac
case "$ARCHIVE_FORMAT" in tar.gz|zip) ;; *) siligent_fail 'Archive format must be tar.gz or zip.' ;; esac
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || siligent_fail 'Version may contain only letters, digits, dots, underscores, and hyphens.'
[[ -n "$SIGNING_KEY" || "$UNSIGNED_DEVELOPMENT" == "true" ]] \
  || siligent_fail 'Production bundles require --signing-key; use --unsigned-development only for tests.'
[[ -z "$SIGNING_KEY" || -f "$SIGNING_KEY" ]] || siligent_fail 'The signing key is unreadable.'

for command_name in docker tar; do siligent_have "$command_name" || siligent_fail "$command_name is required."; done
if [[ "$ARCHIVE_FORMAT" == "zip" ]]; then siligent_have zip || siligent_fail 'zip is required for a ZIP release.'; fi
docker info >/dev/null 2>&1 || siligent_fail 'Docker is not ready.'

dirty_build=false
if git -C "$ROOT_DIR" rev-parse HEAD >/dev/null 2>&1; then
  [[ -n "$SOURCE_REVISION" ]] || SOURCE_REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
    dirty_build=true
    [[ "$ALLOW_DIRTY" == "true" || "$UNSIGNED_DEVELOPMENT" == "true" ]] \
      || siligent_fail 'Refusing a signed release from a dirty worktree. Commit it or use an explicitly non-production option.'
  fi
elif [[ -n "$SIGNING_KEY" && -z "$SOURCE_REVISION" ]]; then
  siligent_fail 'Signed builds without Git metadata require --source-revision.'
fi
[[ -n "$SOURCE_REVISION" ]] || SOURCE_REVISION="unavailable"
[[ "$SOURCE_REVISION" =~ ^[A-Za-z0-9._-]+$ ]] \
  || siligent_fail 'Source revision may contain only letters, digits, dots, underscores, and hyphens.'

# shellcheck disable=SC1091
source "$ROOT_DIR/.env" 2>/dev/null || source "$ROOT_DIR/.env.example"
images=("${DATABASE_IMAGE:-postgres:16-alpine}" "${API_IMAGE:-siligent-scheduler-api:local}")
expected_arch="${PLATFORM#linux/}"
for image in "${images[@]}"; do
  docker image inspect "$image" >/dev/null 2>&1 || siligent_fail "Required image is missing: $image"
  actual_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
  [[ "$actual_arch" == "$expected_arch" ]] || siligent_fail "$image is $actual_arch, expected $expected_arch. Build on the target architecture or use buildx --load."
done

safe_version="${VERSION//[^A-Za-z0-9._-]/-}"
bundle_name="Siligent-Scheduler-${safe_version}-${expected_arch}"
mkdir -p "$OUTPUT_DIR"
stage="$(mktemp -d "${TMPDIR:-/tmp}/siligent-bundle.XXXXXX")"
bundle_dir="$stage/$bundle_name"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$bundle_dir/images" "$bundle_dir/DEPENDENCIES"

for file in VERSION install.sh setup.sh build.sh start.sh stop.sh verify.sh backup.sh restore.sh uninstall.sh \
  docker-compose.yml .env.example .dockerignore .gitignore AGENTS.md CLAUDE.md MEMORY.md \
  README.md PRODUCTION_READINESS.md requirements.runtime.lock; do
  cp "$ROOT_DIR/$file" "$bundle_dir/$file"
done
cp -R "$ROOT_DIR/backend" "$ROOT_DIR/frontend" "$ROOT_DIR/optimizer" "$ROOT_DIR/database" \
  "$ROOT_DIR/scripts" "$ROOT_DIR/deploy" "$ROOT_DIR/docs" "$bundle_dir/"
find "$bundle_dir" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$bundle_dir" -name '*.pyc' -type f -delete
find "$bundle_dir" -name '.DS_Store' -type f -delete

siligent_info 'Exporting runtime images...'
docker save --output "$bundle_dir/images/siligent-scheduler-images.tar" "${images[@]}"

api_id="$(docker image inspect "${images[1]}" --format '{{.Id}}')"
database_id="$(docker image inspect "${images[0]}" --format '{{.Id}}')"
{
  printf '{\n'
  printf '  "version": "%s",\n' "$VERSION"
  printf '  "source_revision": "%s",\n' "$SOURCE_REVISION"
  printf '  "dirty_build": %s,\n' "$dirty_build"
  printf '  "platform": "%s",\n' "$PLATFORM"
  printf '  "images": [\n'
  printf '    {"name": "%s", "id": "%s"},\n' "${images[0]}" "$database_id"
  printf '    {"name": "%s", "id": "%s"}\n' "${images[1]}" "$api_id"
  printf '  ]\n}\n'
} >"$bundle_dir/RELEASE-MANIFEST.json"

docker run --rm --pull never --entrypoint python "${images[1]}" -m pip list --format=freeze \
  >"$bundle_dir/DEPENDENCIES/python-runtime.txt"
docker run --rm --pull never --entrypoint python "${images[1]}" -c \
  'from importlib.metadata import distributions
for d in sorted(distributions(), key=lambda x: (x.metadata.get("Name") or "").lower()):
 print("%s\t%s\t%s" % (d.metadata.get("Name","unknown"), d.version, d.metadata.get("License-Expression") or d.metadata.get("License") or "review-required"))' \
  >"$bundle_dir/DEPENDENCIES/python-licenses.tsv"
docker run --rm --pull never --entrypoint dpkg-query "${images[1]}" -W '-f=${Package}=${Version}\n' \
  >"$bundle_dir/DEPENDENCIES/os-runtime.txt"
cp "$ROOT_DIR/requirements.runtime.lock" "$bundle_dir/DEPENDENCIES/requirements.runtime.lock"

if siligent_have syft; then
  syft "${images[1]}" -o spdx-json >"$bundle_dir/DEPENDENCIES/api-image.spdx.json"
elif docker sbom --help 2>&1 | grep -qE '(^Usage:.*docker sbom|Software Bill [Oo]f Materials)'; then
  docker sbom --format spdx-json "${images[1]}" >"$bundle_dir/DEPENDENCIES/api-image.spdx.json"
elif [[ "$UNSIGNED_DEVELOPMENT" == "true" ]]; then
  printf 'SBOM tool unavailable. This development bundle is not releasable.\n' \
    >"$bundle_dir/DEPENDENCIES/SBOM-NOT-GENERATED.txt"
else
  siligent_fail 'A production bundle requires syft or the Docker SBOM plugin.'
fi

if [[ "$UNSIGNED_DEVELOPMENT" == "true" ]]; then
  printf 'UNSIGNED DEVELOPMENT BUNDLE - NOT FOR PRODUCTION\n' >"$bundle_dir/UNSIGNED-DEVELOPMENT.txt"
fi

(
  cd "$bundle_dir"
  find . -type f ! -name SHA256SUMS ! -name SHA256SUMS.sig ! -name RELEASE-PUBLIC-KEY.pem -print \
    | LC_ALL=C sort \
    | while IFS= read -r file; do
        hash="$(siligent_sha256 "$file")"
        printf '%s  %s\n' "$hash" "$file"
      done
) >"$bundle_dir/SHA256SUMS"

if [[ -n "$SIGNING_KEY" ]]; then
  openssl dgst -sha256 -sign "$SIGNING_KEY" -out "$bundle_dir/SHA256SUMS.sig" "$bundle_dir/SHA256SUMS"
  openssl pkey -in "$SIGNING_KEY" -pubout -out "$bundle_dir/RELEASE-PUBLIC-KEY.pem"
else
  :
fi

if [[ "$ARCHIVE_FORMAT" == "zip" ]]; then
  archive="$OUTPUT_DIR/$bundle_name.zip"
  (cd "$stage" && zip -q -r "$archive" "$bundle_name")
else
  archive="$OUTPUT_DIR/$bundle_name.tar.gz"
  tar -C "$stage" -czf "$archive" "$bundle_name"
fi
siligent_sha256 "$archive" >"$archive.sha256"
siligent_info "Bundle created: $archive"
siligent_info "Outer checksum: $archive.sha256"
