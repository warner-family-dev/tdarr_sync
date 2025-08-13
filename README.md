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
```
---

## .env File

- An example .env is included, and should be used to store all sensitive information.
### Notes
- Tag filter: Only series with SONARR_TAG_NAME are processed. Leave empty to process all series.
- Path translation: Files Sonarr reports under `SONARR_BASE_PATH` are mapped to your actual mount at `LOCAL_MOUNT_BASE_PATH`.
- Example: /tv/TV/Show/Season 01/Episode.mkv → /mnt/video/TV/Show/Season 01/Episode.mkv.
- Archive on restore: Originals are archived only when a transcoded file is being restored over them.
- Retention: The sweeper deletes archived originals only inside `MOVE_ORIGINAL_FILES_DEST` that end with `BACKUP_SUFFIX`. Newly archived files are “touched” to now so they aren’t deleted immediately.
- If `MOVE_ORIGINAL_FILES=False`, backups remain alongside the originals (still suffixed). The sweeper does not act on in-place backups — only on files within MOVE_ORIGINAL_FILES_DEST.

---

## Database

The script uses a small SQLite DB (default sonarr_tdarr_state.db) to remember which source files have already been copied to Tdarr input.

- To create the DB structure explicitly, run the included helper:

````bash
python3 create_db.py
````
> Tip: If you ever want to reprocess files from the copy phase, you can delete the DB or remove specific rows. (Do not edit while the script runs.)

---

## Usage

Run once (foreground):
````bash
python3 tdarr_sync.py
````
Dry run (no writes; logs actions):
````bash
python3 tdarr_sync.py --dry-run
````
Copy only (skip restore of Tdarr outputs for this run):
````bash
python3 tdarr_sync.py --skip-restore
````
Typical cadence:

1) Copy phase runs every hour (or more frequently).

2) Restore phase runs in the same job: whenever a completed file is found in `TDARR_OUTPUT_DIR`, it is restored.

3) After restore, the sweeper runs to enforce retention on the archive tree.

---

## Scheduling
### cron (Linux)
Example: run every 30 minutes with logs handled by the script:
````bash
*/30 * * * * cd /path/to/tdarr_sync && /path/to/.venv/bin/python3 tdarr_sync.py >> /var/log/cron-tdarr_sync.log 2>&1
````
### systemd (Linux)
`/etc/systemd/system/tdarr-sync.service`:
````
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
````
````bash
sudo systemctl daemon-reload
sudo systemctl enable --now tdarr-sync.service
journalctl -u tdarr-sync.service -f
````
----
## Logging & Alerts
- Rotating log at `LOG_FILE` (default max 10 MB x `LOG_BACKUP_COUNT`).
- Telegram errors: set `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_TOKEN`) and `TELEGRAM_CHAT_ID`.

---
## How backups are named & cleaned
- On restore, if destination exists:
    - The original is renamed to `<name><BACKUP_SUFFIX>` (e.g., `Episode.mkv.orig`).
    - If that exists, a unique variant is created: `<name>.<epoch><BACKUP_SUFFIX>` to keep `BACKUP_SUFFIX` at the end (so the sweeper recognizes it).
- If `MOVE_ORIGINAL_FILES=True`, the renamed backup is moved to:
````
MOVE_ORIGINAL_FILES_DEST/<relative/path/under/BASE_DIR>/Episode.mkv.orig
````
And it is touched to “now” so `DELETE_ORIGINAL_FILES_DAYS` starts counting from archive time.
- The sweeper removes files in the archive tree that end with `BACKUP_SUFFIX` and are older than `DELETE_ORIGINAL_FILES_DAYS` (or immediately if set to 0).

---
## Common pitfalls & troubleshooting
### - “.db is tracked by Git”:
`.gitignore` only affects untracked files. If your DB was committed earlier:
````bash
git rm --cached sonarr_tdarr_state.db
echo "sonarr_tdarr_state.db" >> .gitignore
git commit -m "chore(gitignore): untrack local state DB"
````
### - Wrong path mapping:
If the script can’t find source files, verify that `SONARR_BASE_PATH` actually matches your Sonarr paths and that `LOCAL_MOUNT_BASE_PATH` points to the correct local mount.
### - Permissions:
Ensure the script’s user can read `BASE_DIR` and write into `TDARR_INPUT_DIR`, `TDARR_OUTPUT_DIR`, and (if used) `MOVE_ORIGINAL_FILES_DEST`.
### - Tdarr outputs never restore:
Confirm Tdarr is writing to `TDARR_OUTPUT_DIR` using the same relative structure. Drop a test file mirroring a real relative path to validate the restore step.
### - Backups not deleting:
The sweeper acts only in MOVE_ORIGINAL_FILES_DEST and only on files ending with BACKUP_SUFFIX. Ensure those two conditions are met.

----
## Development
Conventional commits are encouraged `(e.g., feat(sync): archive originals only after restore)`.
Changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

### Quick Dev Loop
````bash
# Dry run
python3 tdarr_sync.py --dry-run

# Simulate restore
mkdir -p "$TDARR_OUTPUT_DIR/Show/Season 01"
cp /path/to/sample.mkv "$TDARR_OUTPUT_DIR/Show/Season 01/Episode.mkv"
python3 tdarr_sync.py
````
----
## Security Notes
- Never commit your .env file. Use .gitignore.
- Consider using read-only Sonarr API keys scoped to your instance.

## Roadmap / Ideas
- Optional SQLite tracking of archived files for richer retention/reporting.
- Parallelism for large copy sets (with rate limits).
- Health endpoint or metrics export.