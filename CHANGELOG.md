# Changelog
All notable changes to this project will be documented in this file.

## [2.0.4] - 2025-01-29
### Added
- Added Release Drafter workflow and config to maintain a draft release for every PR and update on main merges.
- Added CI workflow to run Ruff and Pytest on PRs and pushes to `main`.

### Changed
- GitHub workflow now blocks dev-only docs changes (`dev-docs/**`, `ROADMAP.md`) on both pull requests and direct pushes to `main`.
- Ruff cleanup: removed unused imports and adjusted test imports to satisfy linting.

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

[Unreleased]: https://github.com/keatre/tdarr_sync/compare/v2.0.2...HEAD
[2.0.2]: https://github.com/keatre/tdarr_sync/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/keatre/tdarr_sync/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/keatre/tdarr_sync/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/keatre/tdarr_sync/compare/v1.0.0...v1.1.0
