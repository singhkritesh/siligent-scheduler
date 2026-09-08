#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="backup"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

DESTINATION="$ROOT_DIR/backups"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination) [[ $# -ge 2 ]] || siligent_fail '--destination requires a directory.'; DESTINATION="$2"; shift ;;
    -h|--help) printf 'Usage: ./backup.sh [--destination DIRECTORY]\n'; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done

[[ -f "$ROOT_DIR/.env" ]] || siligent_fail '.env is missing.'
# shellcheck disable=SC1091
set -a; source "$ROOT_DIR/.env"; set +a
mkdir -p "$DESTINATION"
chmod 700 "$DESTINATION"
timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
backup_file="$DESTINATION/siligent-scheduler-$timestamp.dump"
config_file="$DESTINATION/siligent-scheduler-$timestamp.env"

database_id="$(siligent_compose ps -q database)"
[[ -n "$database_id" ]] || siligent_fail 'Database is not running. Start the scheduler before backing up.'
siligent_info 'Creating a consistent PostgreSQL backup...'
siligent_compose exec -T database pg_dump \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --format=custom --no-owner --no-privileges >"$backup_file"
[[ -s "$backup_file" ]] || siligent_fail 'The database backup is empty.'
cp "$ROOT_DIR/.env" "$config_file"
chmod 600 "$backup_file" "$config_file"
siligent_sha256 "$backup_file" >"$backup_file.sha256"
chmod 600 "$backup_file.sha256"
siligent_info "Backup created: $backup_file"
siligent_warn 'The backup and configuration contain sensitive data. Move them to approved encrypted storage.'
