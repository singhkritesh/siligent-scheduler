#!/usr/bin/env bash
set -Eeuo pipefail

# Shared lifecycle helpers.
SILIGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

siligent_info() { printf '[%s] %s\n' "${SILIGENT_COMPONENT:-lifecycle}" "$1"; }
siligent_warn() { printf '[%s][warn] %s\n' "${SILIGENT_COMPONENT:-lifecycle}" "$1" >&2; }
siligent_fail() { printf '[%s][error] %s\n' "${SILIGENT_COMPONENT:-lifecycle}" "$1" >&2; exit 1; }
siligent_have() { command -v "$1" >/dev/null 2>&1; }

siligent_is_wsl() {
  [[ -n "${WSL_INTEROP:-}" ]] \
    || { [[ -r /proc/sys/kernel/osrelease ]] \
      && grep -qi microsoft /proc/sys/kernel/osrelease; }
}

siligent_host_platform() {
  case "$(uname -s)" in
    Darwin) printf 'macos\n' ;;
    Linux) if siligent_is_wsl; then printf 'windows-wsl2\n'; else printf 'linux\n'; fi ;;
    MINGW*|MSYS*|CYGWIN*) printf 'windows-git-bash\n' ;;
    *) printf 'unsupported\n' ;;
  esac
}

siligent_confirm() {
  local prompt="$1"
  if [[ "${SILIGENT_ASSUME_YES:-false}" == "true" ]]; then return 0; fi
  [[ -t 0 ]] || siligent_fail "$prompt Re-run with --yes to approve this non-interactively."
  local answer
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]]
}

siligent_compose() {
  local env_file="$SILIGENT_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    docker compose --env-file "$env_file" -f "$SILIGENT_ROOT/docker-compose.yml" "$@"
  else
    docker compose --env-file "$SILIGENT_ROOT/.env.example" -f "$SILIGENT_ROOT/docker-compose.yml" "$@"
  fi
}

siligent_sha256() {
  if siligent_have shasum; then shasum -a 256 "$1" | awk '{print $1}';
  elif siligent_have sha256sum; then sha256sum "$1" | awk '{print $1}';
  else siligent_fail 'A SHA-256 utility (shasum or sha256sum) is required.'; fi
}
