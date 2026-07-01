# Tdarr Sync

Tdarr Sync moves tagged media from Sonarr and Radarr into Tdarr, then restores Tdarr's completed output back to the original library path.

The current implementation supports Sonarr and Radarr as sources. The routing model is source-based, so more *arr-style sources can be added later by extending the source adapter code, route schema, and path mapping logic.

## What It Does

1. Reads Sonarr and Radarr items from their APIs.
2. Finds items with configured tags.
3. Copies matching files into a Tdarr input folder without changing the originals.
4. Tracks copied files in SQLite so the same file is not queued repeatedly.
5. Watches the Tdarr output folder.
6. Restores completed files back to the matching Sonarr or Radarr library path.
7. Archives the replaced original file, then optionally deletes old archived originals after the retention window.

The normal deployment is Docker Compose with three services:

| Service | Purpose |
| --- | --- |
| `api` | FastAPI service for dashboard data, settings, manual sync triggers, restore jobs, and database cleanup. |
| `web` | Next.js dashboard. |
| `worker` | One-shot sync runner used manually or by cron through the `manual` Compose profile. |

## Implementation Checklist

Use this sequence for a new install.

### 1. Prepare Host Folders

Create host folders for:

| Host folder | Used for |
| --- | --- |
| Sonarr library | Source TV files. |
| Radarr library | Source movie files. |
| Tdarr input | Files copied by Tdarr Sync and watched by Tdarr. |
| Tdarr output | Completed files written by Tdarr. |
| Archive | Originals moved aside before replacement. |
| Data | SQLite DB, runtime routing settings, and sync progress JSON. |
| Logs | Shared service log. |

The containers default to `PUID=1000` and `PGID=1000`. Make the data, log, Tdarr input, Tdarr output, archive, and media folders writable by that user/group or update `PUID`/`PGID` in `.env`.

### 2. Configure `.env`

Copy the sample file:

```bash
cp .env.example .env
```

Set these first:

```env
TZ=America/Chicago
PUID=1000
PGID=1000
API_AUTH_TOKEN=replace-with-a-long-random-token
```

Set host mounts:

```env
SONARR_LIBRARY_MOUNT=/mnt/media/tv
RADARR_LIBRARY_MOUNT=/mnt/media/movies
HOST_TDARR_INPUT=/mnt/tdarr/input
HOST_TDARR_OUTPUT=/mnt/tdarr/output
HOST_ARCHIVE_DIR=/mnt/tdarr/archive
TDARR_SYNC_DATA_DIR=./data
TDARR_SYNC_LOG_DIR=./logs
```

Set the in-container paths. These defaults match `docker-compose.yml`:

```env
BASE_DIR=/media/library
RADARR_LOCAL_MOUNT_BASE_PATH=/media/radarr_library
TDARR_INPUT_DIR=/media/tdarr/input
TDARR_OUTPUT_DIR=/media/tdarr/output
MOVE_ORIGINAL_FILES_DEST=/media/archive
```

Set the source API credentials:

```env
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=replace-me
RADARR_URL=http://radarr:7878
RADARR_API_KEY=replace-me
```

Set source path mappings. These map the paths returned by Sonarr/Radarr to the paths visible inside the Tdarr Sync containers:

```env
SONARR_BASE_PATH=/mnt/media/tv
LOCAL_MOUNT_BASE_PATH=/media/library
RADARR_BASE_PATH=/mnt/media/movies
RADARR_LOCAL_MOUNT_BASE_PATH=/media/radarr_library
```

If Sonarr reports files under `/tv` but the container sees the same files under `/media/library`, set `SONARR_BASE_PATH=/tv` and `LOCAL_MOUNT_BASE_PATH=/media/library`. Radarr works the same way with `RADARR_BASE_PATH` and `RADARR_LOCAL_MOUNT_BASE_PATH`.

### 3. Start the Stack

```bash
docker compose up -d --build
```

Open the dashboard:

```text
http://localhost:3000
```

The API health endpoint is public:

```text
http://localhost:8000/health
```

All other API endpoints require:

```text
Authorization: Bearer <API_AUTH_TOKEN>
```

### 4. Enable Tdarr API Access

Tdarr Sync needs Tdarr API access for queue and worker status in the dashboard.

In Tdarr, enable API key authentication, copy the API key, then enter it in the Tdarr Sync dashboard settings.

### 5. Configure Routing In The Dashboard

Open **Settings** in the Tdarr Sync dashboard and configure:

| Field | Meaning |
| --- | --- |
| Tdarr server URL | URL the API container can use to reach Tdarr. |
| Tdarr API key | Stored server-side only; it is not returned to the browser after save. |
| Source | `sonarr` or `radarr`. |
| Tag | The Sonarr/Radarr tag that selects files for this route. |
| Flow name | Human-readable flow label. Used to derive the input subfolder when `Input subdir` is blank. |
| Input subdir | Single safe folder name under `TDARR_INPUT_DIR`. |

Route order matters. The first matching tag for a source wins.

Current sources are `sonarr` and `radarr`. To support another source, the application would need a new source adapter, route source validation, copy logic, restore path resolution, and dashboard/API schema updates.

The tag `remux` is temporarily blocked by the sync pipeline. Any route using that tag is ignored for copy and restore handling until that block is removed.

### 6. Configure Tdarr Watch Folders

Tdarr Sync copies files into this structure:

```text
<TDARR_INPUT_DIR>/<input_subdir>/__sonarr_input__/<relative-library-path>
<TDARR_INPUT_DIR>/<input_subdir>/__radarr_input__/<relative-library-path>
```

Example:

```text
/media/tdarr/input/hevc-main/__sonarr_input__/Show/Season 01/Episode.mkv
/media/tdarr/input/movie-hevc/__radarr_input__/Movie (2024)/Movie.mkv
```

Configure Tdarr so the matching input folders are watched and completed files are written to `TDARR_OUTPUT_DIR` with the same relative path structure. Restore depends on that relative path to decide whether the output belongs back in the Sonarr or Radarr library.

### 7. Run A Dry Run

From the dashboard, trigger a sync with dry run enabled first. Or use the API:

```bash
curl -X POST \
  -H "Authorization: Bearer $API_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}' \
  http://127.0.0.1:8000/sync/run
```

Review logs:

```bash
docker compose logs -f api web
```

Shared log file:

```text
${TDARR_SYNC_LOG_DIR}/tdarr_sync.log
```

### 8. Run And Schedule Syncs

Manual run from the dashboard:

- Use **Trigger Sync** for all configured routes.
- Enable **Select** to choose specific Sonarr series/seasons.
- Radarr currently runs by route/tag, not by dashboard selection.

Cron example for regular one-shot syncs:

```cron
*/30 * * * * cd /path/to/tdarr_sync && docker compose --profile manual run --rm worker
```

## Runtime Behavior

### Copy Phase

- Loads UI routes from `/data/runtime_settings.json`.
- Falls back to `SONARR_TAG_NAME` and `RADARR_TAG_NAME` only when no UI routes exist.
- Reads Sonarr/Radarr items and tags through their APIs.
- Copies matching files into Tdarr input subfolders.
- Leaves source files untouched during copy.
- Stores copied file paths in SQLite to prevent duplicate queueing.

### Restore Phase

- Scans `TDARR_OUTPUT_DIR`.
- Resolves each output path back to Sonarr or Radarr using the route input folder and source prefix.
- Archives the current library file using `BACKUP_SUFFIX`.
- Moves the completed Tdarr output into the original library path.
- Removes processed DB markers only after successful restore operations that require cleanup.

### Archive Retention

When `MOVE_ORIGINAL_FILES=true`, replaced originals are moved under `MOVE_ORIGINAL_FILES_DEST` while preserving their relative path. Their modified time is touched to now so retention is based on replacement time.

When `DELETE_ORIGINAL_FILES=true`, archived originals ending in `BACKUP_SUFFIX` are deleted after `DELETE_ORIGINAL_FILES_DAYS`.

## Dashboard Features

The dashboard provides:

- Sync status and progress.
- Tdarr queue, worker, and node status when Tdarr API settings are configured.
- Manual sync trigger with dry-run support.
- Sonarr series/season selection for targeted copy runs.
- Routing settings for Sonarr/Radarr tags and Tdarr input subfolders.
- Processed-file metrics and recent history.
- Database record removal for selected TV, movie, season, episode, or folder records.
- Restore Originals workflow for replacing transcoded files with archived originals.

## Restore Originals

Restore Originals is protected by `RESTORE_ADMIN_PASSWORD`.

Set it in `.env` before using the dashboard restore workflow:

```env
RESTORE_ADMIN_PASSWORD=replace-with-a-strong-password
```

The restore workflow:

1. Lists Sonarr series and processed status.
2. Lets you select full series or specific seasons.
3. Restores archived originals back to the library.
4. Moves the transcoded file into an internal restored-transcodes archive.
5. Removes processed DB markers only after successful restore.

API endpoints for restore jobs:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/restore/series` | GET | List restore candidates. |
| `/restore/run` | POST | Start a restore job. |
| `/restore/jobs/{job_id}` | GET | Poll restore job state. |

## Database And Logs

| Item | Default path |
| --- | --- |
| SQLite DB | `/data/sonarr_tdarr_state.db` |
| Runtime settings | `/data/runtime_settings.json` |
| Sync progress | `/data/sync_progress.json` |
| Shared log | `/logs/tdarr_sync.log` |

Back up the host folders behind `TDARR_SYNC_DATA_DIR` and `TDARR_SYNC_LOG_DIR` if you need history.

## API Reference

`/health` is public. Every other endpoint requires the bearer token.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Liveness check. |
| `/version` | GET | Git/version metadata for the dashboard header. |
| `/config` | GET | Sanitized runtime configuration. |
| `/metrics/summary` | GET | Processed-file counts and DB metadata. |
| `/processed-files` | GET | Recent processed files. |
| `/processed-files/catalog` | GET | Grouped TV/movie/folder processed-record catalog. |
| `/processed-files/records` | GET | Lazy-loaded processed records for a catalog group. |
| `/processed-files/delete`, `/processed-files` | POST/DELETE | Remove processed DB markers. |
| `/sync/status` | GET | Sync state, progress, and Tdarr status. |
| `/sync/run` | POST | Trigger a sync. |
| `/settings/routing` | GET/PUT | Read/update Tdarr settings and routes. |
| `/restore/series` | GET | Restore candidate catalog. |
| `/restore/run` | POST | Start restore. |
| `/restore/jobs/{job_id}` | GET | Restore job status. |

Example targeted Sonarr sync request:

```json
{
  "dry_run": false,
  "selections": [
    { "series_id": 1234, "seasons": [1, 2] },
    { "series_id": 5678 }
  ]
}
```

A missing `seasons` field means all seasons for that series.

## Optional Manual CLI

Docker Compose is the supported deployment path. The Python script can still run directly for troubleshooting or legacy installs.

```bash
python3 -m pip install -r requirements/base.txt
cp .env.example .env
python3 tdarr_sync.py --dry-run
python3 tdarr_sync.py
python3 tdarr_sync.py --skip-restore
```

Use `--interactive` only from a real terminal. Containerized runs are intentionally non-interactive.

## Development

Run the full local check suite:

```bash
python3 dev-docs/code_check.py
```

Run components manually:

```bash
python3 -m pip install -r requirements/base.txt
uvicorn api.main:app --reload
```

```bash
cd web
npm install
npm run dev
```

Current frontend stack:

- Next.js 16
- React 19
- ESLint 9
- TypeScript 6

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API will not start | `API_AUTH_TOKEN` must be set to a non-placeholder value. |
| No files copied | Confirm routes exist, source tags exist, and the tag is not `remux`. |
| Sonarr/Radarr files not found | Fix `SONARR_BASE_PATH`/`LOCAL_MOUNT_BASE_PATH` or `RADARR_BASE_PATH`/`RADARR_LOCAL_MOUNT_BASE_PATH`. |
| Tdarr outputs do not restore | Confirm Tdarr writes completed files under `TDARR_OUTPUT_DIR` with the same relative path copied into input. |
| Permission errors | Match `PUID`/`PGID` to the host media user and fix ownership on mounted folders. |
| Logs missing | Confirm `TDARR_SYNC_LOG_DIR` exists and is writable by `PUID`/`PGID`. |
| Backups not deleting | Confirm `DELETE_ORIGINAL_FILES=true`, `BACKUP_SUFFIX`, and files are under `MOVE_ORIGINAL_FILES_DEST`. |

## Security Notes

- Do not commit `.env` or runtime data files.
- Rotate any credential that was ever committed or pasted into public logs.
- Keep `API_AUTH_TOKEN`, Sonarr/Radarr API keys, Tdarr API key, Telegram token, and restore password private.
- The Compose file binds the API to `127.0.0.1` by default. Put the dashboard behind TLS/auth if exposing it beyond a trusted LAN.
- Keep `API_CORS_ALLOW_ALL=false` unless you have a specific reason to expose the API cross-origin.
