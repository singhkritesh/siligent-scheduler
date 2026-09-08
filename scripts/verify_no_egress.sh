#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="egress-check"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

[[ -f "$ROOT_DIR/.env" ]] || siligent_fail '.env is missing. Run install.sh first.'

probe='import socket
s=socket.socket()
s.settimeout(4)
reachable=s.connect_ex(("1.1.1.1",443)) == 0
s.close()
raise SystemExit(23 if reachable else 0)'

set +e
siligent_compose exec -T api python -c "$probe" >/dev/null 2>&1
status=$?
set -e
case "$status" in
  0) siligent_info 'API container cannot reach the public internet.' ;;
  23) siligent_fail 'API container can reach the public internet. Apply the approved host/container egress policy before production use.' ;;
  *) siligent_fail 'The API-container egress probe could not be completed.' ;;
esac

database_id="$(siligent_compose ps -q database)"
[[ -n "$database_id" ]] || siligent_fail 'Database container is unavailable.'
published_ports="$(docker inspect --format '{{json .NetworkSettings.Ports}}' "$database_id")"
[[ "$published_ports" == '{}' || "$published_ports" == 'null' ]] \
  || siligent_fail 'PostgreSQL exposes a host port.'
siligent_info 'PostgreSQL has no published host port.'
