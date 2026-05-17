# Changelog
All notable changes to this project will be documented in this file.

## [2.2.3] - 2026-05-17
### Added
- Started v2.2.3 development changelog tracking.

### Changed
- Moved the active sync progress panel into a full-width dashboard pane between the summary cards and Recent Files.
- Updated Tdarr queue reporting to derive current queued/error counts from `FileJSONDB`; historical job error totals can be enabled from Settings and are hidden by default.

## [2.2.2] - 2026-04-26
### Added
- Added fail-closed API bearer-token authentication for every FastAPI endpoint except `/health`.
- Added a server-side Next.js `/tdarr-api/*` proxy that injects the API bearer token without exposing it to the browser.
- Added API authentication tests covering public health checks, missing tokens, invalid tokens, and valid-token access.
- Added a committed `web/package-lock.json` so web dependency installs are reproducible.

### Changed
- Tightened API CORS defaults so wildcard CORS is disabled by default and localhost is the default allowed browser origin.
- Bound the Docker Compose API port to `127.0.0.1` so direct FastAPI access is local-only by default.
- Updated the dashboard API client to always call the same-origin server-side proxy instead of using browser-visible API origins.
- Migrated the web app to Next.js 16, ESLint 9 flat config, and `npm ci` based Docker installs.
- Updated Python and web dependencies to patched versions and documented the new `API_AUTH_TOKEN`, `API_CORS_ALLOW_ALL`, and `API_CORS_ALLOW_ORIGINS` settings.

### Security
- Remediated known Python dependency vulnerabilities reported for `requests`, `python-dotenv`, and transitive `starlette`.
- Remediated known npm dependency vulnerabilities reported for Next.js, PostCSS, and related lint tooling dependencies.
- Removed browser exposure of backend API credentials by keeping the shared bearer token server-side only.

## [2.2.1] - 2026-04-26
### Added
- Added sync progress snapshots at `SYNC_PROGRESS_FILE` so active runs report phase, current item, counts, percent complete, skipped/failed totals, and best-effort ETA.
- Added Tdarr queue status to `/sync/status`, including reachability, queue/error counts, active workers, current worker file, worker progress, and ETA when available.
- Added dashboard progress and Tdarr queue panels to show what tdarr-sync and Tdarr are currently processing.

## [2.2.0] - 2026-02-13
### Added
- Added UI-managed routing settings (`/settings/routing`) so Tdarr server URL/IP, Tdarr API key, and ordered Sonarr/Radarr tag-to-flow routes are persisted in `/data/runtime_settings.json`.
- Added dashboard Routing Settings editor for managing route order, source, tag, flow name, and Tdarr input subdirectory.
- Added Radarr copy-phase support so tagged movies can be routed into Tdarr alongside Sonarr content.
- Added `/version` API endpoint and header label displaying git version + last commit date.
- Added dedicated Settings modal opened from the header and moved routing controls into that modal.
- Added API fallback parsing of `.git` metadata files so branch/date can resolve in Docker even when the `git` binary is unavailable.

### Changed
- Refactored copy/restore pipeline to support route-based input subfolders and source prefixes while preserving existing backup/retention behavior.
- Worker/API Docker mounts now include dedicated Sonarr and Radarr library mounts (`SONARR_LIBRARY_MOUNT`, `RADARR_LIBRARY_MOUNT`) with fallback compatibility.
- Updated docs and environment template for Radarr settings, runtime settings file, and route-driven workflows.
- Updated README to document that from `v2.2.0` onward Tdarr API keys must be enabled in Tdarr (disabled by default) before using UI routing/API-key features.
- Header control now renders on the right of `Tdarr Sync Dashboard` as `branch (commit-date) | Settings`, and only `Settings` opens the modal.
- Removed boxed styling from the header version/settings control so it displays as inline text.
- Updated `docker-compose.yml` so `web` waits for a healthy `api` service before startup, reducing transient DNS/proxy errors during restarts.
- Temporarily disabled `remux` tag routes in the sync pipeline so tagged files are skipped for copy and restore downstream handling.

## [2.0.4] - 2025-01-29
### Added
- Added Release Drafter, CI checks (Ruff/Pytest), and a local code-check script with logging to `logs/tdarr_sync_build.log`.

### Changed
- Hardened local checks/tests to run cleanly (PYTHONPATH handling, deps install, Pydantic compatibility, and mocked Sonarr calls).
- Updated README repo URL and removed remaining whiskey-db references.

### Removed

## [2.0.3] - 2025-01-29
### Added
- Dashboard trigger form now includes a **Select** toggle that opens a modal for choosing series/seasons before starting a sync.
- `/sync/run` accepts structured selection payloads and passes them to the worker via the new `TDARR_SYNC_SELECTION` environment hook.

### Changed
- Manual sync trigger on the dashboard calls the API directly and surfaces inline success/error feedback instead of relying on a server action.
- Docker deployment no longer auto-runs syncs on a timer; scheduling is now cron-driven via the manual runner profile or direct CLI calls.
- Removed auto-run scheduling variables from the environment configuration template to match manual-only execution.

### Removed
- Deleted the `dev-docs/` directory and its contents after they were committed by mistake.

---

## [2.0.2] - 2025-10-14
### Added
- Password-protected “Restore Originals” workflow on the dashboard with modal series selection (supports ranges and comma lists) and detailed results.
- Restore Originals modal now supports per-season targeting so you can roll back individual seasons without touching the rest of a series.
- FastAPI `/restore/series` and `/restore/run` endpoints that validate the admin password, restore archived originals, archive transcoded files, and purge matching SQLite entries.

### Changed
- `.env.example` advertises the required `RESTORE_ADMIN_PASSWORD` variable for enabling the restore feature.
- Dashboard API calls now flow through a Next.js rewrite (`/tdarr-api/*`) so browsers can reach the FastAPI service without hard-coding container hostnames.
- Restore modal shows a live in-progress bar while a restore job is running so users have visible feedback during longer operations.
- `/restore/run` now accepts async submissions by default, returning a job id while the restore executes in the background; use the new `/restore/jobs/{job_id}` endpoint to poll status.
- Dashboard restore workflow polls job status and surfaces success/failure without relying on the Next.js proxy timeout, so long-running restores finish reliably.
- Restore API emits detailed job lifecycle logging (start, completion, failures) to help diagnose future issues.
- Hardened restore endpoint to tolerate Sonarr episode payloads without `seasonNumber` so season-level restores no longer crash the API.
- Restore process now leaves SQLite markers intact whenever any series reports errors, preventing accidental data loss on partial failures.
- Additional guards ensure malformed Sonarr episode entries and unexpected per-series exceptions no longer crash restores; failures are surfaced in the response instead of dropping the API connection.

---

## [2.0.1] - 2025-10-08
### Added
- Dashboard auto-refresh that polls `/sync/status` and reloads automatically when sync state changes.

### Changed
- Default deployment disables interactive CLI prompts (`INTERACTIVE`) so container runs are fully headless; pass `--interactive` only for manual CLI runs.
- Worker/API/web logging now respects the configured `TZ`, and the web logger writes timestamps in the same zone.
- API service mounts the Sonarr/Tdarr media directories, enabling web-triggered syncs to reuse library paths.
- Docker entrypoint ensures `/logs` and `/data` (and their contents) are owned by `PUID`/`PGID`.

### Fixed
- Consolidated log writer guarantees all `[WORKER]`, `[API]`, and `[WEB]` entries land in `tdarr_sync.log`.
- Next.js build passes after moving the server action to its own module and tightening SyncStatus types for auto-refresh.
- Web-triggered runs no longer fail due to missing TTYs; interactive prompts are skipped when none is available.

---

## [2.0.0] - 2025-10-08
### Added
- Docker-first deployment with `docker-compose.yml`, shared volumes, and `.env.example`.
- FastAPI service exposing health, metrics, processed file history, and manual sync trigger endpoints.
- Next.js dashboard (`web/`) that surfaces status, metrics, and a one-click sync trigger.
- Worker service wrapper that schedules `tdarr_sync.py` inside the container and respects interval/dry-run settings.

### Changed
- README restructured around the new containerised architecture while retaining legacy CLI guidance.
- Consolidated service logging into a single shared `tdarr_sync.log` with service-prefixed entries.

---

## [1.1.0] - 2025-08-12
### Changed
- **Archive originals only after a successful restore from `TDARR_OUTPUT_DIR`.**
  - No rename/move/delete during copy-to-Tdarr phase.
  - On restore: rename existing original with `BACKUP_SUFFIX`, optionally move it under `MOVE_ORIGINAL_FILES_DEST`, then restore the transcoded file.
  - Run deletion sweeper post-restore if `DELETE_ORIGINAL_FILES` is enabled.
- Kept SQLite `processed_files` logic intact.
- **No `.env` changes.** Behavior timing only.

### Why
- Prevents premature archival if Tdarr never outputs a file.
- Keeps library intact until a confirmed transcoded replacement exists.

### Notes
- If you relied on immediate archival, be aware this is now deferred.
- Existing `.orig` files remain; sweeper only affects items under `MOVE_ORIGINAL_FILES_DEST`.

[2.2.3]: https://github.com/keatre/tdarr_sync/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/keatre/tdarr_sync/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/keatre/tdarr_sync/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/keatre/tdarr_sync/compare/v2.0.4...v2.2.0
[2.0.4]: https://github.com/keatre/tdarr_sync/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/keatre/tdarr_sync/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/keatre/tdarr_sync/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/keatre/tdarr_sync/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/keatre/tdarr_sync/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/keatre/tdarr_sync/compare/v1.0.0...v1.1.0
