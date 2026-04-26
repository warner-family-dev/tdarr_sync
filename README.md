# Tdarr Sync (Sonarr/Radarr ➜ Tdarr ➜ Library)

Sync media from Sonarr and Radarr libraries to Tdarr for transcoding, then restore the transcoded files back to their original locations — safely.  
The project now ships as a dockerised stack with a REST API and dashboard so you can deploy, monitor, and trigger runs without SSHing into the host.

> Repo: <https://github.com/warner-family-dev/tdarr_sync>

---

## Highlights

- **Copy phase:** Files from Sonarr series and Radarr movies are copied by route rules (`source + tag -> flow`) into Tdarr input subfolders. Originals are untouched.
- **Restore phase:** When Tdarr outputs a transcoded file into `TDARR_OUTPUT_DIR`, Tdarr Sync moves it back into `BASE_DIR`, archiving any original with the configured suffix/location first.
- **Retention-aware archives:** Archived originals are “touched” to now so retention windows respect when they were replaced, not the media’s production date.
- **Container-first:** `docker-compose.yml` starts the API and dashboard, plus an optional manual runner profile for cron-driven syncs.
- **Observability:** REST endpoints expose sync state and processed history; the Next.js dashboard surfaces metrics, recent activity, and a one-click manual trigger.
- **UI settings:** Configure Tdarr server URL, Tdarr API key, and route mappings from the dashboard (persisted in `/data/runtime_settings.json`).
- **Notification hooks:** Optional Telegram alerts for failures, plus rotating log files kept under `/logs`.

---

## Architecture Overview

| Service | Image | Port | Responsibility |
| --- | --- | --- | --- |
| `worker` (manual profile) | `docker/tdarr.Dockerfile` | – | Runs `tdarr_sync.py` once when invoked (cron or ad-hoc) and writes logs/DB state. |
| `api` | `docker/tdarr.Dockerfile` | `API_PORT` (default `8000`) | FastAPI layer for health, metrics, history, and manual sync triggers. Shares the same code/data/log mounts and media volumes as the runner so manual runs can access the library. |
| `web` | `web/Dockerfile` | `WEB_PORT` (default `3000`) | Next.js dashboard that talks to the API. |

Shared volumes:

- `${TDARR_SYNC_DATA_DIR}` → mounted at `/data` (stores `sonarr_tdarr_state.db`)
- `${TDARR_SYNC_LOG_DIR}` → mounted at `/logs` (rotating logs for API/runner)
- Media mounts provided via `SONARR_LIBRARY_MOUNT`, `RADARR_LIBRARY_MOUNT`, `HOST_TDARR_INPUT`, `HOST_TDARR_OUTPUT`, and optional `HOST_ARCHIVE_DIR`

---

## Quick Start (Docker Compose)

1. Copy the sample environment file and adjust it for your host paths and timezone:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env`:
   - Set `TZ` to your preferred timezone (e.g. `America/Chicago`).
   - Point `SONARR_LIBRARY_MOUNT`, `RADARR_LIBRARY_MOUNT`, `HOST_TDARR_INPUT`, `HOST_TDARR_OUTPUT`, and `HOST_ARCHIVE_DIR` at real host directories.
   - Fill in Sonarr/Radarr credentials (`SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`).
   - If you mount an archive folder, ensure it exists and is writable.
   - Create the `TDARR_SYNC_DATA_DIR` and `TDARR_SYNC_LOG_DIR` directories on the host and make sure they’re owned by the user `PUID`/`PGID` (defaults to `1000:1000`).
3. Bring the stack up:
   ```bash
   docker compose up -d --build
   ```
4. Visit the dashboard at `http://localhost:${WEB_PORT}` (defaults to `3000`).  
   Health is available at `http://localhost:${API_PORT}/health` (defaults to `8000`). Other API endpoints require `Authorization: Bearer $API_AUTH_TOKEN`.
5. Check logs when needed:
   ```bash
   docker compose logs -f api
   ```
6. In the top-right header control (`branch (commit-date) | Settings`), open **Settings** and define your tag-to-flow routes (for both Sonarr and Radarr). Tdarr server URL/IP and API key are managed there.
7. Starting with `v2.2.0`, Tdarr API-key auth must be enabled in Tdarr before routing features work. Tdarr ships with API keys disabled by default, so enable it in Tdarr first, then paste the key into **Settings**.

Sync does not auto-run. Use the dashboard’s “Trigger Sync” button for an on-demand run — enable **Select** to choose specific series/seasons — or hit `POST /sync/run` directly with the configured bearer token.

### Scheduling with cron (Docker)

Use the manual runner profile so cron can launch a one-off sync container on your schedule.

```bash
# Every 30 minutes
*/30 * * * * cd /path/to/tdarr_sync && docker compose --profile manual run --rm worker
```

---

## Configuration

Everything runs from `.env` — the file is not checked into Git (see `.env.example` for defaults).

### Host mounts

| Variable | Description |
| --- | --- |
| `SONARR_LIBRARY_MOUNT` | Writable mount for Sonarr library media. Mounted in containers at `/media/library`. |
| `RADARR_LIBRARY_MOUNT` | Writable mount for Radarr library media. Mounted in containers at `/media/radarr_library`. |
| `HOST_LIBRARY_MOUNT` | Backward-compatible fallback if `SONARR_LIBRARY_MOUNT` is unset. |
| `HOST_TDARR_INPUT` | Writable mount where Tdarr watches for incoming jobs. |
| `HOST_TDARR_OUTPUT` | Writable mount where Tdarr drops transcoded outputs. |
| `HOST_ARCHIVE_DIR` | (Optional) Writable mount used when `MOVE_ORIGINAL_FILES=true`. |
| `TDARR_SYNC_DATA_DIR` | Where the SQLite DB is stored on the host (defaults to `./data`). |
| `TDARR_SYNC_LOG_DIR` | Where logs are stored on the host (defaults to `./logs`). |

### Core service variables

- `TZ` — propagated to all containers; controls timestamps and log formatting.
- `STATE_DB_FILE` — path inside the containers for the SQLite DB (default `/data/sonarr_tdarr_state.db`).
- `RUNTIME_SETTINGS_FILE` — JSON file persisted in `/data` which stores UI-managed routing settings (Tdarr server/IP, API key, tag/flow routes).
- `SYNC_PROGRESS_FILE` — JSON progress snapshot written by active sync runs and read by the API/dashboard (default `/data/sync_progress.json`).
- `LOG_FILE` — path to the shared log (defaults to `/logs/tdarr_sync.log`).
- `API_AUTH_TOKEN` — required shared bearer token for every API endpoint except `/health`; use a long random value.
- `API_CORS_ALLOW_ALL` — defaults to `false`; keep disabled unless you understand the exposure.
- `API_CORS_ALLOW_ORIGINS` — comma-separated browser origins allowed to call the API directly; defaults to `http://localhost:3000`.
- `NEXT_BACKEND_ORIGIN` — (optional) explicit URL the server-side web proxy should forward to; defaults to the in-cluster `http://api:8000`.
- `APP_GIT_VERSION`, `APP_GIT_COMMIT_DATE`, `APP_GIT_COMMIT_SHA` — optional metadata shown in the top-right header label. If unset, the API attempts to read git info directly (including a `.git` metadata fallback in Docker builds).
- Sonarr/Radarr paths mirror the script environment (`BASE_DIR`, `TDARR_INPUT_DIR`, `TDARR_OUTPUT_DIR`, `SONARR_BASE_PATH`, `LOCAL_MOUNT_BASE_PATH`, `RADARR_BASE_PATH`, `RADARR_LOCAL_MOUNT_BASE_PATH`, etc.).

### Manual sync controls

- `SYNC_DRY_RUN` — pass `--dry-run` to the script so runs never mutate files.

### Optional integrations

- Telegram: set `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_TOKEN`) and `TELEGRAM_CHAT_ID`.
- `PUID`/`PGID`: passed to all services via Compose to match host permissions.

---

## Web Dashboard (`web/`)

- Built with Next.js 14 + React 18.
- Dark theme, responsive layout, quick stats panel.
- Shows live sync status, last/next run timestamps, database size, and the 25 most recent processed files.
- Shows the active tdarr-sync phase, current title/path, progress bar, item counts, skipped/failed counts, and best-effort ETA.
- Shows Tdarr queue reachability, active worker details, queue/error counts, worker progress, and worker ETA when Tdarr API settings are configured.
- Provides a manual trigger form with dry-run and per-series/season selection options.
- Top-right **Settings** window includes Tdarr server URL/IP, Tdarr API key, and ordered Sonarr/Radarr tag-to-flow rules.
- Top-right header label shows the running git version and last commit date in `branch (commit-date) | Settings` format.
- Proxies all `/tdarr-api/*` requests to `NEXT_BACKEND_ORIGIN` (or `http://api:8000` in Docker) and injects `API_AUTH_TOKEN` server-side so the browser never receives it.

---

## REST API (`api/`)

All endpoints return JSON. `/health` is public; every other endpoint requires `Authorization: Bearer $API_AUTH_TOKEN`.

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Liveness probe. |
| `/version` | GET | Returns git/version metadata used by the top-right header label. |
| `/config` | GET | Sanitised snapshot of active configuration (no secrets exposed). |
| `/processed-files?limit=50&offset=0` | GET | Recent processed files ordered by newest first. |
| `/metrics/summary` | GET | Aggregate counts and database metadata. |
| `/sync/status` | GET | Current/manual sync status, progress snapshot, and Tdarr queue/worker status when configured. |
| `/sync/run?dry_run=true` | POST | Trigger an immediate sync. Accepts `dry_run` via query or JSON body and supports structured selections (see below). Returns `409` if a run is already in-flight. |
| `/settings/routing` | GET/PUT | Read/update UI-managed Tdarr server settings and ordered Sonarr/Radarr tag-to-flow routes. |

**Selection payload:** send `POST /sync/run` with a JSON body like:

```json
{
  "dry_run": false,
  "selections": [
    { "series_id": 1234, "seasons": [1, 2] },
    { "series_id": 5678 }
  ]
}
```

A missing `seasons` field (or `null`) means “all seasons” for that series.

The API shares the same `/data` and `/logs` volumes as the runner so you can inspect state via HTTP without accessing the host filesystem.

---

## Sync Behaviour

Under the hood Tdarr Sync drives `tdarr_sync.py`, so all original guarantees remain:

- **Copy phase:** evaluates ordered route rules (`source + tag`) from `RUNTIME_SETTINGS_FILE`, then mirrors matching Sonarr/Radarr media into `TDARR_INPUT_DIR/<input_subdir>/<source_prefix>/...`.
- **Restore phase:** watches `TDARR_OUTPUT_DIR`, resolves routed outputs back to the correct Sonarr or Radarr local mount, archives the original to `<filename><BACKUP_SUFFIX>` (optionally moving to `MOVE_ORIGINAL_FILES_DEST`), then replaces it with the transcoded output.
- **Retention:** after each restore the sweeper deletes archived originals older than `DELETE_ORIGINAL_FILES_DAYS` (when enabled) and only inside the archive tree.
- **State tracking:** the SQLite DB prevents duplicate copies by remembering every file that has been queued to Tdarr.
- **Notifications:** failures log to `/logs/tdarr_sync.log` and optionally send a Telegram alert.
- **Targeted runs:** setting the `TDARR_SYNC_SELECTION` environment variable to the same JSON structure the API accepts limits the copy phase to the chosen series/seasons (used by the dashboard’s Select mode).
---

## Database & Logging

- Database file: `${TDARR_SYNC_DATA_DIR}/sonarr_tdarr_state.db` (or whatever you set `STATE_DB_FILE` to). Use the bundled `create_db.py` if you want to pre-create the schema.
- All services emit to a shared log at `/logs/tdarr_sync.log`; each line is prefixed with `[WORKER]`, `[API]`, or `[WEB]` so you can filter quickly.
- Bind-mount these directories into your backup strategy if you rely on historical logs.

---

## Manual CLI Usage (Optional)

If you prefer running the script without Docker, the legacy workflow still lives in `tdarr_sync.py`.

### Requirements

- Python 3.8+
- `pip install requests python-dotenv`
- Copy `.env.example` → `.env` and configure it exactly as you would for Docker (the environment variables are shared).

### Commands

```bash
# Full run (copy + restore + sweep)
python3 tdarr_sync.py

# Dry run (logs actions without making changes)
python3 tdarr_sync.py --dry-run

# Copy-only run (skip restore for this invocation)
python3 tdarr_sync.py --skip-restore
```

> Tip: add `--interactive` when running locally to pick series via a TTY prompt. Containerized runs disable prompts by default to stay non-interactive.

### Scheduling examples

**cron**

```bash
*/30 * * * * cd /path/to/tdarr_sync && /path/to/.venv/bin/python3 tdarr_sync.py >> /var/log/cron-tdarr_sync.log 2>&1
```

**systemd**

```
[Unit]
Description=Tdarr Sync (Sonarr ➜ Tdarr ➜ Library)
After=network-online.target

[Service]
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/path/to/tdarr_sync
ExecStart=/path/to/.venv/bin/python3 tdarr_sync.py
Restart=on-failure
User=media
Group=media

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tdarr-sync.service
journalctl -u tdarr-sync.service -f
```

---

## How Backups Are Named & Cleaned

- On restore, if the destination exists it becomes `<name><BACKUP_SUFFIX>` (for example `Episode.mkv.orig`).
- If that filename already exists, Tdarr Sync appends an epoch timestamp **before** the suffix to keep clean sweeper matches (e.g. `Episode.1700000000.orig`).
- With `MOVE_ORIGINAL_FILES=true`, the renamed file moves to:

```
MOVE_ORIGINAL_FILES_DEST/<relative/path/under/BASE_DIR>/Episode.mkv.orig
```

- Archived files have their mtime updated to “now” so retention windows start when the file was replaced.
- The sweeper removes files ending with `BACKUP_SUFFIX` inside `MOVE_ORIGINAL_FILES_DEST` once they exceed `DELETE_ORIGINAL_FILES_DAYS` (set `0` to delete immediately).

---

## Restore Dashboard Workflow

- Submitting the **Restore Originals** modal now schedules a background restore job. The UI shows the job id and live status until it completes.
- When the job finishes successfully the modal populates the restore summary; failures surface the error and keep processed markers intact so you can retry.
- Poll job state directly via the API: `GET /restore/jobs/<job_id>` returns `pending`, `running`, `succeeded`, or `failed` together with the final payload.
- Need a blocking call? Pass `wait_for_completion=true` in the JSON body for `/restore/run` to wait for completion (useful for CLI automation).

---

## Troubleshooting

- **Database missing / schema errors** — the API warns if the DB file is absent. Run Tdarr Sync once (or `python3 create_db.py`) to create it.
- **Mount paths wrong** — double-check `SONARR_LIBRARY_MOUNT`, `RADARR_LIBRARY_MOUNT`, `HOST_TDARR_INPUT`, `HOST_TDARR_OUTPUT`, and in-container equivalents (`BASE_DIR`, `RADARR_LOCAL_MOUNT_BASE_PATH`, etc.).
- **Permissions** — if files appear as root-owned on the host, set `PUID`/`PGID` in `.env` to match your media user/group.
- **Tdarr outputs never restore** — verify Tdarr writes to the mounted `HOST_TDARR_OUTPUT` with the same relative structure the script expects.
- **Backups not deleting** — the sweeper only touches `MOVE_ORIGINAL_FILES_DEST` and only files ending with the backup suffix.

---

## Development

- Install Python deps for the sync/API locally:
  ```bash
  pip install -r requirements/base.txt
  ```
- Boot the API locally:
  ```bash
  uvicorn api.main:app --reload
  ```
- Frontend development:
  ```bash
  cd web
  npm install
  npm run dev
  ```
- Compose can be used for full-stack dev with live reload by mounting the repository instead of copying — tweak `docker-compose.override.yml` as needed.

Conventional commits are encouraged. The changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and we aim for [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Security Notes

- Never commit your `.env` (already ignored).
- Prefer scoped Sonarr API keys and read-only Telegram bots.
- Place the stack behind a reverse proxy with TLS if you expose the dashboard beyond your LAN.

---

## Roadmap / Ideas

- Optional Prometheus metrics export.
- Tdarr queue introspection for richer status cards.
- Role-based access control for the dashboard/API.
