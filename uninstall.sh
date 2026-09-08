#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SILIGENT_COMPONENT="uninstall"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

[[ $# -eq 0 ]] || siligent_fail 'Uninstall accepts no options. Data deletion is intentionally a separate IT-controlled procedure.'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  "$ROOT_DIR/stop.sh"
fi
"$ROOT_DIR/scripts/uninstall_desktop_launcher.sh"
siligent_info 'Application services and launcher were removed from daily use.'
siligent_info 'Database volumes, configuration, certificates, backups, images, and application files were preserved.'
siligent_info 'Follow the approved retention and secure-disposal procedure before deleting any of them.'
