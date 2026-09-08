#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER_PATH="$ROOT_DIR/scripts/launch_ui.sh"

[[ $# -eq 0 ]] || { printf '[launcher-install][error] This installer accepts no options.\n' >&2; exit 1; }

install_macos_launcher() {
  local desktop_dir="$HOME/Desktop"
  local applications_dir="$HOME/Applications"
  local app_dir="$applications_dir/Siligent Scheduler.app"
  local desktop_item="$desktop_dir/Siligent Scheduler.app"
  local source_file existing_source="" apple_path
  command -v osacompile >/dev/null 2>&1 \
    || { printf '[launcher-install][error] osacompile is required on macOS.\n' >&2; exit 1; }
  mkdir -p "$desktop_dir" "$applications_dir" "$ROOT_DIR/.runtime"
  if [[ -d "$app_dir" && -f "$app_dir/Contents/Resources/Scripts/main.scpt" ]]; then
    existing_source="$(osadecompile "$app_dir/Contents/Resources/Scripts/main.scpt" 2>/dev/null || true)"
  fi
  if [[ -e "$app_dir" || -L "$app_dir" ]]; then
    [[ "$existing_source" == *"$LAUNCHER_PATH"* ]] \
      || { printf '[launcher-install][error] Refusing to replace an unrecognized app at %s\n' "$app_dir" >&2; exit 1; }
    rm -rf "$app_dir"
  fi
  if [[ -e "$desktop_item" || -L "$desktop_item" ]]; then
    if [[ -L "$desktop_item" && "$(readlink "$desktop_item")" == "$app_dir" ]]; then
      rm -f "$desktop_item"
    else
      printf '[launcher-install][error] Refusing to replace an unrecognized desktop item at %s\n' "$desktop_item" >&2
      exit 1
    fi
  fi
  apple_path="${LAUNCHER_PATH//\\/\\\\}"
  apple_path="${apple_path//\"/\\\"}"
  source_file="$(mktemp "$ROOT_DIR/.runtime/scheduler-launcher.XXXXXX.applescript")"
  {
    printf 'property launcherPath : "%s"\n' "$apple_path"
    printf 'on run\n'
    printf '  do shell script "/bin/bash " & quoted form of launcherPath\n'
    printf 'end run\n'
    printf 'on reopen\n'
    printf '  do shell script "/bin/bash " & quoted form of launcherPath\n'
    printf 'end reopen\n'
  } >"$source_file"
  osacompile -o "$app_dir" "$source_file"
  rm -f "$source_file"
  xattr -cr "$app_dir"
  codesign --force --deep --sign - "$app_dir" >/dev/null
  ln -s "$app_dir" "$desktop_item"
  printf '[launcher-install] Desktop app: %s\n' "$desktop_item"
}

install_linux_launcher() {
  local desktop_dir="$HOME/Desktop"
  local applications_dir="$HOME/.local/share/applications"
  local wrapper_dir="$HOME/.local/share/siligent-scheduler"
  local wrapper="$wrapper_dir/launch"
  local application_file="$applications_dir/siligent-scheduler.desktop"
  local desktop_file="$desktop_dir/Siligent Scheduler.desktop"
  mkdir -p "$desktop_dir" "$applications_dir" "$wrapper_dir"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'exec /bin/bash %q\n' "$LAUNCHER_PATH"
  } >"$wrapper"
  chmod 700 "$wrapper"
  {
    printf '[Desktop Entry]\nType=Application\nName=Siligent Scheduler\n'
    printf 'Comment=Start the local dental scheduling application\n'
    printf 'Exec="%s"\nTerminal=false\nCategories=Office;Utility;\nStartupNotify=true\n' "$wrapper"
  } >"$application_file"
  cp "$application_file" "$desktop_file"
  chmod 700 "$application_file" "$desktop_file"
  command -v gio >/dev/null 2>&1 \
    && gio set "$desktop_file" metadata::trusted true >/dev/null 2>&1 || true
  printf '[launcher-install] Desktop launcher: %s\n' "$desktop_file"
}

install_windows_launcher() {
  local powershell_script="$ROOT_DIR/deploy/windows/install-scheduler-shortcut.ps1"
  local launcher_windows
  if [[ -n "${WSL_INTEROP:-}" ]] \
    || { [[ -r /proc/sys/kernel/osrelease ]] && grep -qi microsoft /proc/sys/kernel/osrelease; }; then
    export PATH="/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH"
    command -v wslpath >/dev/null 2>&1 \
      || { printf '[launcher-install][error] wslpath is required from WSL.\n' >&2; exit 1; }
    [[ -n "${WSL_DISTRO_NAME:-}" ]] \
      || { printf '[launcher-install][error] WSL_DISTRO_NAME is unavailable.\n' >&2; exit 1; }
    launcher_windows="$(wslpath -w "$LAUNCHER_PATH")"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$powershell_script")" \
      -Launcher "$launcher_windows" -WslDistribution "$WSL_DISTRO_NAME" -WslLauncher "$LAUNCHER_PATH"
  else
    command -v cygpath >/dev/null 2>&1 \
      || { printf '[launcher-install][error] cygpath is required from Git Bash.\n' >&2; exit 1; }
    launcher_windows="$(cygpath -w "$LAUNCHER_PATH")"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$powershell_script")" \
      -Launcher "$launcher_windows"
  fi
}

case "$(uname -s)" in
  Darwin) install_macos_launcher ;;
  Linux)
    if [[ -n "${WSL_INTEROP:-}" ]] \
      || { [[ -r /proc/sys/kernel/osrelease ]] && grep -qi microsoft /proc/sys/kernel/osrelease; }; then
      install_windows_launcher
    else
      install_linux_launcher
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*) install_windows_launcher ;;
  *) printf '[launcher-install][error] Unsupported desktop platform.\n' >&2; exit 1 ;;
esac
