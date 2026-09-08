#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="restore"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

ASSUME_YES=false
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES=true ;;
    -h|--help) printf 'Usage: ./restore.sh [--yes] BACKUP.dump\n'; exit 0 ;;
    -*) siligent_fail "Unknown option: $1" ;;
    *) [[ -z "$BACKUP_FILE" ]] || siligent_fail 'Provide exactly one backup file.'; BACKUP_FILE="$1" ;;
  esac
  shift
done
[[ -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]] || siligent_fail 'A readable PostgreSQL custom-format backup is required.'
[[ -f "$ROOT_DIR/.env" ]] || siligent_fail '.env is missing.'
export SILIGENT_ASSUME_YES="$ASSUME_YES"

if [[ -f "$BACKUP_FILE.sha256" ]]; then
  expected="$(awk 'NR == 1 {print $1}' "$BACKUP_FILE.sha256")"
  actual="$(siligent_sha256 "$BACKUP_FILE")"
  [[ "$actual" == "$expected" ]] || siligent_fail 'Backup checksum verification failed.'
else
  siligent_warn 'No companion checksum was found for this backup.'
fi

siligent_confirm 'Restore will replace the current scheduler database. Continue?' \
  || siligent_fail 'Restore was cancelled.'
siligent_info 'Creating a safety backup of the current database before restore...'
"$ROOT_DIR/backup.sh" --destination "$ROOT_DIR/backups/pre-restore"

# shellcheck disable=SC1091
set -a; source "$ROOT_DIR/.env"; set +a
siligent_compose stop api
siligent_info 'Restoring PostgreSQL data...'
siligent_compose exec -T database pg_restore \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-privileges <"$BACKUP_FILE"
siligent_compose up -d --no-build --pull never api
"$ROOT_DIR/scripts/healthcheck.sh" --wait 120
siligent_info 'Restore completed and application health passed.'
