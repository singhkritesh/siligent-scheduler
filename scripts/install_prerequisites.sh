#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SILIGENT_COMPONENT="prerequisites"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/common.sh"

ASSUME_YES=false
INSTALL_OLLAMA=false

usage() {
  printf '%s\n' \
    'Usage: ./scripts/install_prerequisites.sh [--yes] [--with-local-model]' \
    '' \
    'Installs missing prerequisites during an approved connected install window.' \
    'It never runs during normal application startup.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES=true ;;
    --with-local-model) INSTALL_OLLAMA=true ;;
    -h|--help) usage; exit 0 ;;
    *) siligent_fail "Unknown option: $1" ;;
  esac
  shift
done
export SILIGENT_ASSUME_YES="$ASSUME_YES"

platform="$(siligent_host_platform)"
[[ "$platform" != "unsupported" ]] || siligent_fail "Unsupported host: $(uname -s)."

install_homebrew() {
  siligent_have brew && return 0
  siligent_confirm 'Homebrew is required to install missing macOS prerequisites. Install it from the official repository?' \
    || siligent_fail 'Homebrew installation was declined.'
  siligent_have curl || siligent_fail 'curl is required to bootstrap Homebrew.'
  installer="$(mktemp "${TMPDIR:-/tmp}/siligent-homebrew.XXXXXX")"
  trap 'rm -f "$installer"' EXIT
  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
  NONINTERACTIVE=1 /bin/bash "$installer"
  rm -f "$installer"
  trap - EXIT
  if [[ -x /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
  siligent_have brew || siligent_fail 'Homebrew installed but is not available on PATH. Open a new terminal and rerun install.sh.'
}

install_macos() {
  local packages=()
  siligent_have curl || packages+=(curl)
  siligent_have openssl || packages+=(openssl@3)
  if (( ${#packages[@]} > 0 )); then
    install_homebrew
    siligent_confirm "Install required macOS packages: ${packages[*]}?" \
      || siligent_fail 'Required package installation was declined.'
    brew install "${packages[@]}"
  fi
  if ! siligent_have docker; then
    install_homebrew
    siligent_confirm 'Docker Desktop is required. Install it with Homebrew?' \
      || siligent_fail 'Docker Desktop installation was declined.'
    brew install --cask docker
  fi
  if [[ "$INSTALL_OLLAMA" == "true" ]] && ! siligent_have ollama; then
    install_homebrew
    siligent_confirm 'The optional local-model profile was selected. Install Ollama?' \
      || siligent_fail 'Ollama installation was declined.'
    brew install ollama
  fi
}

install_linux() {
  local sudo_command=()
  local current_uid
  current_uid="$(id -u)"
  local needs_packages=false
  for required in curl openssl docker; do siligent_have "$required" || needs_packages=true; done
  docker compose version >/dev/null 2>&1 || needs_packages=true
  if [[ "$current_uid" -ne 0 ]]; then
    if [[ "$needs_packages" == "true" ]]; then
      siligent_have sudo || siligent_fail 'sudo is required to install Linux system packages.'
      sudo_command=(sudo)
    elif siligent_have sudo; then
      sudo_command=(sudo)
    fi
  fi
  if [[ "$needs_packages" == "true" ]]; then
    siligent_confirm 'Install missing Linux prerequisites using the host package manager?' \
      || siligent_fail 'Required package installation was declined.'
  fi
  if siligent_have apt-get; then
    if [[ "$needs_packages" == "true" ]]; then
      "${sudo_command[@]}" apt-get update
      "${sudo_command[@]}" apt-get install -y ca-certificates curl openssl
      if ! siligent_have docker; then
        "${sudo_command[@]}" apt-get install -y docker.io
      fi
      if ! docker compose version >/dev/null 2>&1; then
        "${sudo_command[@]}" apt-get install -y docker-compose-v2 \
          || "${sudo_command[@]}" apt-get install -y docker-compose-plugin
      fi
    fi
  elif siligent_have dnf; then
    [[ "$needs_packages" == "false" ]] \
      || "${sudo_command[@]}" dnf install -y ca-certificates curl openssl moby-engine docker-compose-plugin
  elif siligent_have pacman; then
    [[ "$needs_packages" == "false" ]] \
      || "${sudo_command[@]}" pacman -Syu --needed --noconfirm ca-certificates curl openssl docker docker-compose
  elif [[ "$needs_packages" == "true" ]]; then
    siligent_fail 'Supported connected installation requires apt-get, dnf, or pacman on Linux.'
  fi
  if ! docker info >/dev/null 2>&1 && siligent_have systemctl \
    && (( ${#sudo_command[@]} > 0 || current_uid == 0 )); then
    "${sudo_command[@]}" systemctl enable --now docker || true
  fi
  if ! docker info >/dev/null 2>&1 && [[ "$current_uid" -ne 0 ]]; then
    "${sudo_command[@]}" usermod -aG docker "${USER:?USER is required}"
    siligent_fail 'Docker was installed and your account was added to its group. Sign out and back in, then rerun install.sh.'
  fi
  if [[ "$INSTALL_OLLAMA" == "true" ]] && ! siligent_have ollama; then
    siligent_confirm 'The optional local-model profile was selected. Install Ollama from its official installer?' \
      || siligent_fail 'Ollama installation was declined.'
    installer="$(mktemp "${TMPDIR:-/tmp}/siligent-ollama.XXXXXX")"
    trap 'rm -f "$installer"' EXIT
    curl -fsSL https://ollama.com/install.sh -o "$installer"
    sh "$installer"
    rm -f "$installer"
    trap - EXIT
  fi
}

install_windows() {
  siligent_have powershell.exe || siligent_fail 'Windows PowerShell is required.'
  local script="$ROOT_DIR/deploy/windows/preflight.ps1"
  local windows_script
  if siligent_is_wsl; then windows_script="$(wslpath -w "$script")"; else windows_script="$(cygpath -w "$script")"; fi
  local args=(-InstallMissing)
  [[ "$ASSUME_YES" == "true" ]] && args+=(-AcceptInstall)
  [[ "$INSTALL_OLLAMA" == "true" ]] && args+=(-WithLocalModel)
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$windows_script" "${args[@]}"
  export PATH="/c/Program Files/Docker/Docker/resources/bin:/mnt/c/Program Files/Docker/Docker/resources/bin:$PATH"
  if siligent_is_wsl && { ! siligent_have curl || ! siligent_have openssl; }; then
    siligent_have apt-get || siligent_fail 'WSL requires apt-get to install curl and OpenSSL.'
    siligent_have sudo || siligent_fail 'sudo is required for WSL prerequisite installation.'
    siligent_confirm 'Install missing WSL userland prerequisites?' \
      || siligent_fail 'WSL prerequisite installation was declined.'
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl openssl
  fi
}

case "$platform" in
  macos) install_macos ;;
  linux) install_linux ;;
  windows-wsl2|windows-git-bash) install_windows ;;
esac

for command_name in docker curl openssl awk sed grep; do
  siligent_have "$command_name" || siligent_fail "$command_name is still unavailable after prerequisite installation."
done
docker compose version >/dev/null 2>&1 || siligent_fail 'Docker Compose v2 is still unavailable.'
siligent_info 'Required connected-install prerequisites are available.'
