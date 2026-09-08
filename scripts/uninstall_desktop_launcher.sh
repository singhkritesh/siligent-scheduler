#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$(uname -s)" in
  Darwin)
    app="$HOME/Applications/Siligent Scheduler.app"
    desktop="$HOME/Desktop/Siligent Scheduler.app"
    if [[ -L "$desktop" && "$(readlink "$desktop")" == "$app" ]]; then rm -f "$desktop"; fi
    if [[ -d "$app/Contents/Resources/Scripts" ]] \
      && osadecompile "$app/Contents/Resources/Scripts/main.scpt" 2>/dev/null | grep -Fq "$ROOT_DIR/scripts/launch_ui.sh"; then
      rm -rf "$app"
    fi
    ;;
  Linux)
    if [[ -n "${WSL_INTEROP:-}" ]] || { [[ -r /proc/sys/kernel/osrelease ]] && grep -qi microsoft /proc/sys/kernel/osrelease; }; then
      script="$ROOT_DIR/deploy/windows/uninstall-scheduler-shortcut.ps1"
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$script")"
    else
      rm -f "$HOME/.local/share/applications/siligent-scheduler.desktop"
      rm -f "$HOME/Desktop/Siligent Scheduler.desktop"
      rm -f "$HOME/.local/share/siligent-scheduler/launch"
      rmdir "$HOME/.local/share/siligent-scheduler" 2>/dev/null || true
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*)
    script="$ROOT_DIR/deploy/windows/uninstall-scheduler-shortcut.ps1"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$script")"
    ;;
esac
printf '[uninstall] Recognized Siligent desktop launcher removed where supported.\n'
