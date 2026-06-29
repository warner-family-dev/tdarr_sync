#!/usr/bin/env sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
LOG_FILE_PATH="${LOG_FILE:-/logs/tdarr_sync.log}"

ensure_path() {
  path="$1"
  if [ -n "${path}" ]; then
    mkdir -p "${path}"
    chown "${PUID}:${PGID}" "${path}"
  fi
}

ensure_path /logs

if [ -n "${LOG_FILE_PATH}" ]; then
  mkdir -p "$(dirname "${LOG_FILE_PATH}")"
  touch "${LOG_FILE_PATH}"
  chown "${PUID}:${PGID}" "${LOG_FILE_PATH}"
fi

exec su-exec "${PUID}:${PGID}" "$@"
