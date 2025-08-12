#!/usr/bin/env python3
"""
sonarr_tdarr_sync.py

- Copies files from your main media tree (BASE_DIR) to TDARR_INPUT_DIR when those files belong
  to a Sonarr series tagged with SONARR_TAG_NAME.
- Preserves relative path (relative to BASE_DIR).
- When Tdarr outputs transcoded files into TDARR_OUTPUT_DIR, the script moves them back to the
  original location inside BASE_DIR (overwriting the original file). Optionally makes a timestamped backup.
- Sends Telegram alerts on errors.

Requires:
- requests
- python-dotenv
"""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import requests
from pathlib import Path
import shutil
import sqlite3
import time
import os
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -------------------- CONFIG from ENV --------------------
try:
    SONARR_URL = os.environ["SONARR_URL"]
    SONARR_API_KEY = os.environ["SONARR_API_KEY"]
    SONARR_TAG_NAME = os.environ.get("SONARR_TAG_NAME", "")

    BASE_DIR = Path(os.environ["BASE_DIR"]).resolve()
    TDARR_INPUT_DIR = Path(os.environ["TDARR_INPUT_DIR"]).resolve()
    TDARR_OUTPUT_DIR = Path(os.environ["TDARR_OUTPUT_DIR"]).resolve()

    # New vars for path translation
    SONARR_BASE_PATH = Path(os.environ.get("SONARR_BASE_PATH", "/tv"))
    LOCAL_MOUNT_BASE_PATH = Path(os.environ.get("LOCAL_MOUNT_BASE_PATH", "/mnt/media-videos"))

    # Update: Use RENAME_ORIGINAL_FILES instead of MAKE_BACKUP_BEFORE_OVERWRITE
    RENAME_ORIGINAL_FILES = os.environ.get("RENAME_ORIGINAL_FILES", "True").lower() in ("true", "1", "yes")
    BACKUP_SUFFIX = os.environ.get("BACKUP_SUFFIX", ".orig")

    # New vars for moving/deleting renamed original files
    MOVE_ORIGINAL_FILES = os.environ.get("MOVE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    MOVE_ORIGINAL_FILES_DEST = Path(os.environ.get("MOVE_ORIGINAL_FILES_DEST", "/mnt/originals_archive"))
    DELETE_ORIGINAL_FILES = os.environ.get("DELETE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    DELETE_ORIGINAL_FILES_DAYS = int(os.environ.get("DELETE_ORIGINAL_FILES_DAYS", "30"))

    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    LOG_FILE = os.environ.get("LOG_FILE", "/var/log/sonarr_tdarr_sync/sonarr_tdarr_sync.log")
    LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))
    LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 3))

    # Use STATE_DB_FILE from .env or default
    STATE_DB_FILE = Path(os.environ.get("STATE_DB_FILE", "sonarr_tdarr_state.db")).resolve()

except KeyError as e:
    print(f"Missing required environment variable: {e}")
    exit(1)
# ----------------------------------------------------------

# create log directory if needed
log_path = Path(LOG_FILE)
log_path.parent.mkdir(parents=True, exist_ok=True)

# ---------- Logging ----------
logger = logging.getLogger("sonarr_tdarr_sync")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)


def telegram_send_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram bot token or chat ID not configured; skipping Telegram notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Sent Telegram notification.")
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)


def report_error_and_exit(msg: str, exc: Exception = None):
    logger.error(msg)
    if exc:
        logger.error("Exception: %s", exc)
    telegram_send_message(f"❗ *sonarr_tdarr_sync.py error:*\n{msg}\n{exc if exc else ''}")
    exit(1)


def sonarr_get(endpoint: str, params: Dict = None) -> requests.Response:
    if params is None:
        params = {}
    params["apikey"] = SONARR_API_KEY
    url = SONARR_URL.rstrip("/") + "/api/v3" + endpoint
    logger.debug("Calling Sonarr: %s params=%s", url, params)
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r


def find_tag_id(tag_name: str) -> int:
    if not tag_name:
        logger.info("No SONARR_TAG_NAME specified, will process all series (no tag filtering).")
        return None
    logger.info("Looking up Sonarr tags to find tag '%s'...", tag_name)
    try:
        resp = sonarr_get("/tag")
    except Exception as e:
        report_error_and_exit("Failed to get tags from Sonarr", e)
    tags = resp.json()
    for t in tags:
        if str(t.get("label", "")).lower() == tag_name.lower():
            logger.info("Found Sonarr tag '%s' -> id=%s", tag_name, t.get("id"))
            return int(t.get("id"))
    report_error_and_exit(f"Tag '{tag_name}' not found in Sonarr. Existing tags: {[t.get('label') for t in tags]}")


def get_series_with_tag(tag_id: int) -> List[Dict]:
    logger.info("Fetching all series from Sonarr...")
    try:
        resp = sonarr_get("/series")
    except Exception as e:
        report_error_and_exit("Failed to get series from Sonarr", e)
    series_list = resp.json()
    if tag_id is None:
        # No tag filter; return all series
        return series_list
    tagged = [s for s in series_list if tag_id in (s.get("tags") or [])]
    logger.info("Found %d series with tag_id=%d", len(tagged), tag_id)
    return tagged


def get_episode_files_for_series(series_id: int) -> List[Dict]:
    logger.debug("Fetching episode files for seriesId=%s", series_id)
    try:
        resp = sonarr_get("/episodefile", params={"seriesId": series_id})
    except Exception as e:
        report_error_and_exit(f"Failed fetching episode files for series {series_id}", e)
    return resp.json()


def build_relative_path(full_path: str, base_dir: Path) -> Path:
    try:
        p = Path(full_path)
        rel = p.relative_to(base_dir)
        return rel
    except Exception as e:
        report_error_and_exit(f"Failed to build relative path for {full_path} relative to {base_dir}", e)


def translate_path(sonarr_path: str) -> Path:
    """
    Translate Sonarr file path (SONARR_BASE_PATH) to local mounted base path (LOCAL_MOUNT_BASE_PATH).
    If the path doesn't start with SONARR_BASE_PATH, returns it as Path unchanged.
    """
    p = Path(sonarr_path)
    try:
        if p.is_absolute() and p.parts[:len(SONARR_BASE_PATH.parts)] == SONARR_BASE_PATH.parts:
            # Replace SONARR_BASE_PATH prefix with LOCAL_MOUNT_BASE_PATH
            relative = p.relative_to(SONARR_BASE_PATH)
            local_path = LOCAL_MOUNT_BASE_PATH.joinpath(relative)
            return local_path
        else:
            # Path does not start with SONARR_BASE_PATH, return as-is
            return p
    except Exception as e:
        logger.warning(f"Failed to translate path '{sonarr_path}': {e}")
        return p


def safe_copy_to_tdarr(src: Path, dest_root: Path, base_dir: Path, dry_run=False) -> Path:
    rel = build_relative_path(str(src), base_dir)
    dest = dest_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("[DRY RUN] Would copy: %s -> %s", src, dest)
        return dest

    logger.info("Copying: %s -> %s", src, dest)
    shutil.copy2(str(src), str(dest))
    return dest


def init_db():
    conn = sqlite3.connect(STATE_DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            file_path TEXT PRIMARY KEY,
            processed_at INTEGER
        )
    """)
    conn.commit()
    return conn


def is_processed(conn, file_path: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM processed_files WHERE file_path = ?", (file_path,))
    return c.fetchone() is not None


def mark_processed(conn, file_path: str):
    c = conn.cursor()
    now = int(time.time())
    c.execute("INSERT OR REPLACE INTO processed_files (file_path, processed_at) VALUES (?, ?)", (file_path, now))
    conn.commit()


def handle_original_file(file_path: Path):
    """
    Rename the original file by appending BACKUP_SUFFIX if RENAME_ORIGINAL_FILES=True,
    then optionally move it to MOVE_ORIGINAL_FILES_DEST if MOVE_ORIGINAL_FILES=True.
    """
    if not RENAME_ORIGINAL_FILES:
        return

    orig_path = file_path.with_name(file_path.name + BACKUP_SUFFIX)
    logger.info("Renaming original file %s -> %s", file_path, orig_path)
    try:
        file_path.rename(orig_path)
    except Exception as e:
        report_error_and_exit(f"Failed to rename original file {file_path} to {orig_path}", e)

    if MOVE_ORIGINAL_FILES:
        try:
            rel_path = orig_path.relative_to(BASE_DIR)
            move_dest = MOVE_ORIGINAL_FILES_DEST.joinpath(rel_path)
            move_dest.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Moving renamed original file %s -> %s", orig_path, move_dest)
            shutil.move(str(orig_path), str(move_dest))
        except Exception as e:
            report_error_and_exit(f"Failed to move original file {orig_path} to {MOVE_ORIGINAL_FILES_DEST}", e)


def cleanup_old_originals():
    """
    Delete .original files older than DELETE_ORIGINAL_FILES_DAYS in MOVE_ORIGINAL_FILES_DEST directory,
    if DELETE_ORIGINAL_FILES=True.
    """
    if not DELETE_ORIGINAL_FILES:
        return

    if not MOVE_ORIGINAL_FILES_DEST.exists() or not MOVE_ORIGINAL_FILES_DEST.is_dir():
        logger.warning(f"MOVE_ORIGINAL_FILES_DEST path {MOVE_ORIGINAL_FILES_DEST} does not exist or is not a directory.")
        return

    cutoff_time = time.time() - (DELETE_ORIGINAL_FILES_DAYS * 86400) if DELETE_ORIGINAL_FILES_DAYS > 0 else 0

    for root, _, files in os.walk(MOVE_ORIGINAL_FILES_DEST):
        for fname in files:
            if not fname.endswith(BACKUP_SUFFIX):
                continue
            fpath = Path(root) / fname
            try:
                mtime = fpath.stat().st_mtime
                if DELETE_ORIGINAL_FILES_DAYS == 0 or mtime < cutoff_time:
                    logger.info("Deleting original file: %s", fpath)
                    fpath.unlink()
            except Exception as e:
                logger.error("Failed to delete original file %s: %s", fpath, e)


def process_sonarr_to_tdarr(dry_run=False):
    conn = init_db()  # Initialize DB connection
    tag_id = find_tag_id(SONARR_TAG_NAME)
    series_list = get_series_with_tag(tag_id)
    if not series_list:
        logger.info("No series found with tag '%s' (id=%s). Nothing to copy.", SONARR_TAG_NAME, tag_id)
        conn.close()
        return

    for s in series_list:
        series_id = s.get("id")
        series_title = s.get("title")
        logger.info("Processing series: %s (id=%s)", series_title, series_id)
        episode_files = get_episode_files_for_series(series_id)
        for ef in episode_files:
            path = ef.get("path") or ef.get("relativePath")
            if not path:
                logger.warning("Skipping episodeFile without path: %s", ef)
                continue

            src = translate_path(path)

            if not src.exists():
                logger.warning("Skips non-existent file: %s", src)
                continue

            src_str = str(src.resolve())
            if is_processed(conn, src_str):
                logger.info("Skipping already processed file: %s", src_str)
                continue

            try:
                safe_copy_to_tdarr(src=src, dest_root=TDARR_INPUT_DIR, base_dir=BASE_DIR, dry_run=dry_run)
                mark_processed(conn, src_str)
                if not dry_run:
                    handle_original_file(src)
            except Exception as e:
                report_error_and_exit(f"Failed to copy {src} to tdarr input", e)

    conn.close()
    if not dry_run:
        cleanup_old_originals()


def move_tdarr_output_back(dry_run=False):
    if not TDARR_OUTPUT_DIR.exists():
        logger.info("Tdarr output dir %s does not exist - skipping.", TDARR_OUTPUT_DIR)
        return

    logger.info("Scanning Tdarr output dir: %s", TDARR_OUTPUT_DIR)

    for out_path in TDARR_OUTPUT_DIR.rglob("*"):
        if out_path.is_dir():
            continue
        try:
            rel = out_path.relative_to(TDARR_OUTPUT_DIR)
        except Exception:
            logger.error("File %s is not inside tdarr output dir %s - skipping.", out_path, TDARR_OUTPUT_DIR)
            continue

        dest = BASE_DIR.joinpath(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dry_run:
            logger.info("[DRY RUN] Would move: %s -> %s", out_path, dest)
            continue

        if dest.exists() and RENAME_ORIGINAL_FILES:
            ts = int(time.time())
            backup_path = dest.with_name(dest.name + BACKUP_SUFFIX + f".{ts}")
            logger.info("Backing up existing destination %s -> %s", dest, backup_path)
            shutil.move(str(dest), str(backup_path))

        logger.info("Moving transcoded file back: %s -> %s", out_path, dest)
        try:
            shutil.move(str(out_path), str(dest))
        except Exception as e:
            report_error_and_exit(f"Failed to move {out_path} -> {dest}", e)


def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Sync Sonarr-tagged media to Tdarr input, restore from Tdarr output.")
    p.add_argument("--dry-run", action="store_true", help="Don't perform any writes, just log actions.")
    p.add_argument("--skip-restore", action="store_true", help="Do not process Tdarr output -> BaseDir (only copy into TDARR input).")
    return p.parse_args()


def main():
    args = parse_args()
    logger.info("Starting sonarr_tdarr_sync (dry_run=%s)", args.dry_run)

    try:
        process_sonarr_to_tdarr(dry_run=args.dry_run)
        if not args.skip_restore:
            move_tdarr_output_back(dry_run=args.dry_run)
    except Exception as e:
        report_error_and_exit("Unhandled error in main execution", e)

    logger.info("Finished run.")


if __name__ == "__main__":
    main()
# End of file