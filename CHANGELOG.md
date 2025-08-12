# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/keatre/tdarr_sync/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/keatre/tdarr_sync/compare/v1.0.0...v1.1.0
