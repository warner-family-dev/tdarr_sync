# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=20
ARG S6_OVERLAY_VERSION=3.2.1.0

FROM node:${NODE_VERSION}-bookworm-slim AS web-deps
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci

FROM web-deps AS web-builder
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/ ./
RUN npm run build

FROM node:${NODE_VERSION}-bookworm-slim AS node-runtime

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG TARGETARCH
ARG S6_OVERLAY_VERSION

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     NODE_ENV=production     NEXT_TELEMETRY_DISABLED=1     TZ=UTC     PUID=1000     PGID=1000     STATE_DB_FILE=/config/sonarr_tdarr_state.db     RUNTIME_SETTINGS_FILE=/config/runtime_settings.json     SYNC_PROGRESS_FILE=/config/sync_progress.json     LOG_FILE=/logs/tdarr_sync.log     NEXT_BACKEND_ORIGIN=http://127.0.0.1:8000     S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0     S6_BEHAVIOUR_IF_STAGE2_FAILS=2

RUN apt-get update &&     apt-get install -y --no-install-recommends       ca-certificates       bash       curl       gosu       libstdc++6       xz-utils &&     rm -rf /var/lib/apt/lists/* &&     case "${TARGETARCH:-amd64}" in       amd64) s6_arch="x86_64" ;;       arm64) s6_arch="aarch64" ;;       *) echo "Unsupported TARGETARCH: ${TARGETARCH:-unset}" >&2; exit 1 ;;     esac &&     curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz"       | tar -C / -Jxpf - &&     curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${s6_arch}.tar.xz"       | tar -C / -Jxpf -

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements/base.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip &&     pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app
COPY --from=web-builder --chown=1000:1000 /build/web/.next/standalone /app/web
COPY --from=web-builder --chown=1000:1000 /build/web/.next/static /app/web/.next/static
COPY --from=web-builder --chown=1000:1000 /build/web/public /app/web/public
COPY --from=web-builder --chown=1000:1000 /build/web/scripts /app/web/scripts

COPY docker/root/ /
RUN chmod +x       /usr/local/bin/tdarr-sync-entrypoint       /usr/local/bin/tdarr-sync-init       /etc/cont-init.d/10-tdarr-sync-init       /etc/s6-overlay/s6-rc.d/api/run       /etc/s6-overlay/s6-rc.d/web/run &&     mkdir -p /config /data /logs /media/library /media/radarr_library /media/tdarr/input /media/tdarr/output /media/archive &&     chown -R 1000:1000 /app /config /data /logs

EXPOSE 3000 8000
ENTRYPOINT ["/usr/local/bin/tdarr-sync-entrypoint"]
CMD ["/init"]
