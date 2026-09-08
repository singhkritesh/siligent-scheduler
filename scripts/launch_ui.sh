#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_FILE="$RUNTIME_DIR/desktop-launcher.log"
LOCK_DIR="$RUNTIME_DIR/desktop-launcher.lock"

mkdir -p "$RUNTIME_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

HOST_OS="$(uname -s)"
WINDOWS_HOST=false
WINDOWS_SHELL=""
case "$HOST_OS" in
  MINGW*|MSYS*|CYGWIN*)
    WINDOWS_HOST=true
    export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"
    ;;
  Linux)
    if [[ -n "${WSL_INTEROP:-}" ]] \
      || { [[ -r /proc/sys/kernel/osrelease ]] && grep -qi microsoft /proc/sys/kernel/osrelease; }; then
      WINDOWS_HOST=true
      WINDOWS_SHELL="wsl"
      export PATH="/usr/lib/wsl/lib:/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH"
    fi
    ;;
esac

ui_port() {
  local value
  value="$(sed -n 's/^UI_PORT=\([0-9][0-9]*\)$/\1/p' "$ROOT_DIR/.env" 2>/dev/null | head -n 1)"
  printf '%s\n' "${value:-8443}"
}

open_browser() {
  local url="$1"
  if [[ "$HOST_OS" == "Darwin" ]]; then
    open "$url"
  elif [[ "$WINDOWS_HOST" == "true" ]]; then
    powershell.exe -NoProfile -Command "Start-Process '$url'" >/dev/null
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1
  elif command -v gio >/dev/null 2>&1; then
    gio open "$url" >/dev/null 2>&1
  else
    return 1
  fi
}

show_error() {
  if [[ "$HOST_OS" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
    osascript -e \
      'display alert "Siligent Scheduler could not start" message "Review .runtime/desktop-launcher.log in the scheduler folder." as critical' \
      >/dev/null 2>&1 || true
  elif [[ "$WINDOWS_HOST" == "true" ]] && command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command \
      "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Review .runtime\\desktop-launcher.log in the scheduler folder.','Siligent Scheduler could not start','OK','Error')" \
      >/dev/null 2>&1 || true
  elif command -v zenity >/dev/null 2>&1; then
    zenity --error --title="Siligent Scheduler could not start" \
      --text="Review .runtime/desktop-launcher.log in the scheduler folder." \
      >/dev/null 2>&1 || true
  fi
}

app_is_healthy() {
  local response
  response="$(curl -kfsS --max-time 3 "$1/health" 2>/dev/null || true)"
  [[ "$response" == *'"status":"ok"'* && "$response" == *'"mode":"offline"'* ]]
}

rotate_log() {
  local size=0
  if [[ -f "$LOG_FILE" ]]; then
    size="$(wc -c <"$LOG_FILE" 2>/dev/null || printf '0')"
    size="${size//[[:space:]]/}"
  fi
  if [[ "$size" =~ ^[0-9]+$ ]] && (( size > 1048576 )); then
    mv -f "$LOG_FILE" "$LOG_FILE.previous"
  fi
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    return 0
  fi
  local owner_pid=""
  [[ -r "$LOCK_DIR/pid" ]] && owner_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$owner_pid" =~ ^[0-9]+$ ]] && kill -0 "$owner_pid" 2>/dev/null; then
    return 1
  fi
  rm -f "$LOCK_DIR/pid" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || return 1
  mkdir "$LOCK_DIR"
  printf '%s\n' "$$" >"$LOCK_DIR/pid"
}

docker_ready() {
  if [[ "$WINDOWS_SHELL" == "wsl" ]] && command -v timeout >/dev/null 2>&1; then
    timeout 10 docker info >/dev/null 2>&1
  else
    docker info >/dev/null 2>&1
  fi
}

wait_for_docker() {
  docker_ready && return 0
  if [[ "$HOST_OS" == "Darwin" && -d /Applications/Docker.app ]]; then
    open -a Docker >/dev/null 2>&1 || return 1
  elif [[ "$WINDOWS_HOST" == "true" ]]; then
    powershell.exe -NoProfile -Command \
      "Start-Process (Join-Path \$env:ProgramFiles 'Docker\\Docker\\Docker Desktop.exe')" \
      >/dev/null 2>&1 || return 1
  else
    return 1
  fi
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    docker_ready && return 0
    sleep 2
  done
  return 1
}

main() {
  local url="https://127.0.0.1:$(ui_port)"
  if app_is_healthy "$url"; then
    open_browser "$url" || true
    return 0
  fi
  if ! acquire_lock; then
    local attempt
    for attempt in $(seq 1 60); do
      if app_is_healthy "$url"; then
        open_browser "$url" || true
        return 0
      fi
      [[ -d "$LOCK_DIR" ]] || break
      sleep 2
    done
    show_error
    return 1
  fi
  trap 'rm -f "$LOCK_DIR/pid" 2>/dev/null || true; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  rotate_log
  {
    printf '\n[%s] Desktop launch requested.\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    command -v docker >/dev/null 2>&1 \
      || { printf '[launcher][error] Docker is not installed or is not on PATH.\n'; return 1; }
    wait_for_docker \
      || { printf '[launcher][error] Docker did not become ready.\n'; return 1; }
    "$ROOT_DIR/start.sh"
  } >>"$LOG_FILE" 2>&1 || { show_error; return 1; }
  if ! app_is_healthy "$url"; then
    printf '[launcher][error] Startup returned without a healthy UI at %s.\n' "$url" >>"$LOG_FILE"
    show_error
    return 1
  fi
  open_browser "$url" || {
    printf '[launcher][error] No supported browser opener was found for %s.\n' "$url" >>"$LOG_FILE"
    show_error
    return 1
  }
}

main "$@"
