# Tdarr Sync (Sonarr ➜ Tdarr ➜ Library)

Sync media from a Sonarr library to Tdarr for transcoding, then restore the transcoded files back to their original locations — safely.

- **Copy phase:** Files from Sonarr series with a specific tag (e.g., `transcode`) are copied into `TDARR_INPUT_DIR` (preserving relative paths). **No originals are renamed/moved here.**
- **Restore phase:** When Tdarr outputs a transcoded file into `TDARR_OUTPUT_DIR`, it’s moved back into the library (`BASE_DIR`). If an original exists at the destination, it is first **archived** (renamed with `BACKUP_SUFFIX` and optionally moved to an archive folder), then the transcoded file replaces it.
- **Retention:** If archival to a separate folder is enabled, archived files are **“touched” to now** so deletion (by age) uses the time they were archived, not the media’s original timestamp.

> Repo: <https://github.com/keatre/tdarr_sync>

---

## Why this tool?

- Keep Sonarr free to download whatever it finds.
- Let Tdarr normalize everything to a consistent codec/resolution.
- **Safety first:** original files are only archived **after** a transcoded replacement is restored.
- **Retention that makes sense:** newly archived originals won’t be deleted immediately just because their content is old.

---

## Features

- Filters Sonarr series by a specified tag (e.g., `transcode`).
- Copies matched episode files into `TDARR_INPUT_DIR` mirroring the library structure.
- Restores completed transcodes from `TDARR_OUTPUT_DIR` back into `BASE_DIR`.
- Archives originals **only after successful restore**:
  - Renames to `<filename><BACKUP_SUFFIX>` (e.g., `Episode.mkv.orig`).
  - If configured, moves the renamed file under `MOVE_ORIGINAL_FILES_DEST` using the same relative path as in `BASE_DIR`.
  - **Touches** the archived file’s mtime to “now” so retention is measured from archive time.
- Periodic sweeper deletes archived originals older than `DELETE_ORIGINAL_FILES_DAYS` (if enabled).
- Tracks “already processed” sources in a lightweight SQLite DB so you don’t copy the same item repeatedly.
- Optional Telegram notifications on errors.

---

## Requirements

- Python **3.8+**
- Packages:
  - `requests`
  - `python-dotenv`
- A working Sonarr v3 instance and a Tdarr flow that writes completed outputs to a known directory.

Install Python deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv

---

## .env File

- An example .env is included, and should be used to store all sensitive information.
# Notes
- Tag filter: Only series with SONARR_TAG_NAME are processed. Leave empty to process all series.
- Path translation: Files Sonarr reports under SONARR_BASE_PATH are mapped to your actual mount at LOCAL_MOUNT_BASE_PATH.
- Example: /tv/TV/Show/Season 01/Episode.mkv → /mnt/video/TV/Show/Season 01/Episode.mkv.
- Archive on restore: Originals are archived only when a transcoded file is being restored over them.
- Retention: The sweeper deletes archived originals only inside MOVE_ORIGINAL_FILES_DEST that end with BACKUP_SUFFIX. Newly archived files are “touched” to now so they aren’t deleted immediately.
- If MOVE_ORIGINAL_FILES=False, backups remain alongside the originals (still suffixed). The sweeper does not act on in-place backups — only on files within MOVE_ORIGINAL_FILES_DEST.

