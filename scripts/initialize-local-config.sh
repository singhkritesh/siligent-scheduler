#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
CERT_DIR="$ROOT_DIR/certs"

command -v openssl >/dev/null 2>&1 || {
  printf "[setup][error] openssl is required from the approved offline system image.\n" >&2
  exit 1
}

if [[ ! -f "$ENV_FILE" ]]; then
  database_password="$(openssl rand -hex 32)"
  admin_password="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  temporary_file="$(mktemp "$ROOT_DIR/.env.tmp.XXXXXX")"
  trap 'rm -f "$temporary_file"' EXIT
  sed \
    -e "s/CHANGE_ME_USE_A_LONG_RANDOM_SECRET/$database_password/" \
    -e "s/CHANGE_ME_USE_A_DIFFERENT_LONG_RANDOM_SECRET/$admin_password/" \
    "$ROOT_DIR/.env.example" > "$temporary_file"
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$ENV_FILE"
  trap - EXIT
  printf "[setup] Created protected local configuration.\n"
  printf "[setup] Initial username: admin\n"
  printf "[setup] Initial password: %s\n" "$admin_password"
  printf "[setup] Store this password in the practice's approved password manager.\n"
else
  added="false"
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Z][A-Z0-9_]*= ]] || continue
    key="${line%%=*}"
    if grep -Eq "^${key}=" "$ENV_FILE"; then
      continue
    fi
    if [[ "$added" == "false" ]]; then
      printf '\n# Added from .env.example during an idempotent configuration upgrade.\n' >>"$ENV_FILE"
      added="true"
    fi
    printf '%s\n' "$line" >>"$ENV_FILE"
  done <"$ROOT_DIR/.env.example"
  chmod 600 "$ENV_FILE"
  if [[ "$added" == "true" ]]; then
    printf "[setup] Added new configuration keys without changing existing local values.\n"
  fi
fi

if [[ -e "$CERT_DIR" && ! -d "$CERT_DIR" ]]; then
  printf '[setup][error] %s exists but is not a directory. Rename that file, then rerun setup; no application or database data was changed.\n' "$CERT_DIR" >&2
  exit 1
fi
mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT_DIR/server.crt" || ! -f "$CERT_DIR/server.key" ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 30 \
    -subj "/CN=localhost/O=Siligent Local Development" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" >/dev/null 2>&1
  chmod 600 "$CERT_DIR/server.key"
  chmod 644 "$CERT_DIR/server.crt"
  printf "[setup] Created a 30-day local development certificate.\n"
  printf "[setup][warn] Replace it with the practice-issued certificate before production use.\n"
fi
