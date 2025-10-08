# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
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

## [2.0.0] - 2025-10-08
### Added
- Docker-first deployment with `docker-compose.yml`, shared volumes, and `.env.example`.
- FastAPI service exposing health, metrics, processed file history, and manual sync trigger endpoints.
- Next.js dashboard (`web/`) that surfaces status, metrics, and a one-click sync trigger.
- Worker service wrapper that schedules `tdarr_sync.py` inside the container and respects interval/dry-run settings.

### Changed
- README restructured around the new containerised architecture while retaining legacy CLI guidance.
- Consolidated service logging into a single shared `tdarr_sync.log` with service-prefixed entries.

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

[Unreleased]: https://github.com/keatre/tdarr_sync/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/keatre/tdarr_sync/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/keatre/tdarr_sync/compare/v1.0.0...v1.1.0
