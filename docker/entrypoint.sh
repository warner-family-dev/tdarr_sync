#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
LOG_FILE_PATH="${LOG_FILE:-/logs/tdarr_sync.log}"
DATA_DIR="${STATE_DB_FILE:-/data/sonarr_tdarr_state.db}"

group_name="appgroup"
user_name="appuser"

# Ensure group exists with requested PGID
if ! getent group "${PGID}" >/dev/null 2>&1; then
  if getent group "${group_name}" >/dev/null 2>&1; then
    groupmod -g "${PGID}" "${group_name}"
  else
    groupadd -g "${PGID}" "${group_name}"
  fi
else
  group_name="$(getent group "${PGID}" | cut -d: -f1)"
fi

# Ensure user exists with requested PUID/PGID
if ! id -u "${user_name}" >/dev/null 2>&1; then
  useradd -u "${PUID}" -g "${PGID}" -M -d /app -s /usr/sbin/nologin "${user_name}"
else
  usermod -u "${PUID}" "${user_name}"
  usermod -g "${PGID}" "${user_name}"
fi

ensure_path() {
  local path="$1"
  if [ -n "${path}" ]; then
    mkdir -p "${path}"
    chown "${PUID}:${PGID}" "${path}"
  fi
}

ensure_path "/logs"
ensure_path "/data"

# Touch log file and ensure ownership
if [ -n "${LOG_FILE_PATH}" ]; then
  mkdir -p "$(dirname "${LOG_FILE_PATH}")"
  touch "${LOG_FILE_PATH}"
  chown "${PUID}:${PGID}" "${LOG_FILE_PATH}"
fi

# Ensure directory owning the DB file (if path is a file)
if [ -n "${DATA_DIR}" ]; then
  mkdir -p "$(dirname "${DATA_DIR}")"
  chown -R "${PUID}:${PGID}" "$(dirname "${DATA_DIR}")"
fi

exec gosu "${PUID}:${PGID}" "$@"
