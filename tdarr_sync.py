#!/usr/bin/env python3
"""
tdarr_sync.py

Workflow:
- Copy phase: copy Sonarr-tagged files from BASE_DIR into TDARR_INPUT_DIR (preserving relative paths).
  * NO renaming/moving of originals during copy.
- Restore phase: move transcoded files from TDARR_OUTPUT_DIR back into BASE_DIR.
  * If destination exists, rename it with BACKUP_SUFFIX and (optionally) move to MOVE_ORIGINAL_FILES_DEST.
  * When moved to archive, 'touch' its mtime to now so retention uses archive time (not content age).
- After restore, optionally sweep old archived originals based on DELETE_ORIGINAL_FILES settings.

No .env keys changed.
"""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

# -------------------- ENV --------------------
load_dotenv()

try:
    SONARR_URL = os.environ["SONARR_URL"]
    SONARR_API_KEY = os.environ["SONARR_API_KEY"]
    SONARR_TAG_NAME = os.environ.get("SONARR_TAG_NAME", "")

    BASE_DIR = Path(os.environ["BASE_DIR"]).resolve()
    TDARR_INPUT_DIR = Path(os.environ["TDARR_INPUT_DIR"]).resolve()
    TDARR_OUTPUT_DIR = Path(os.environ["TDARR_OUTPUT_DIR"]).resolve()

    SONARR_BASE_PATH = Path(os.environ.get("SONARR_BASE_PATH", "/tv"))
    LOCAL_MOUNT_BASE_PATH = Path(os.environ.get("LOCAL_MOUNT_BASE_PATH", "/mnt/media-videos"))

    RENAME_ORIGINAL_FILES = os.environ.get("RENAME_ORIGINAL_FILES", "True").lower() in ("true", "1", "yes")
    BACKUP_SUFFIX = os.environ.get("BACKUP_SUFFIX", ".orig")
    MOVE_ORIGINAL_FILES = os.environ.get("MOVE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    MOVE_ORIGINAL_FILES_DEST = Path(os.environ.get("MOVE_ORIGINAL_FILES_DEST", "/mnt/originals_archive"))
    DELETE_ORIGINAL_FILES = os.environ.get("DELETE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    DELETE_ORIGINAL_FILES_DAYS = int(os.environ.get("DELETE_ORIGINAL_FILES_DAYS", "30"))

    # Accept either TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN without requiring .env change
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    LOG_FILE = os.environ.get("LOG_FILE", "/var/log/sonarr_tdarr_sync/sonarr_tdarr_sync.log")
    LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))
    LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 3))

    STATE_DB_FILE = Path(os.environ.get("STATE_DB_FILE", "sonarr_tdarr_state.db")).resolve()
except KeyError as e:
    print(f"Missing required environment variable: {e}")
    raise SystemExit(1)

# -------------------- Logging --------------------
log_path = Path(LOG_FILE)
log_path.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("tdarr_sync")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

# -------------------- Helpers --------------------
def telegram_send_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured; skipping message.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Sent Telegram notification.")
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)

def report_error_and_exit(msg: str, exc: Exception = None):
    logger.error(msg)
    if exc:
        logger.exception(exc)
    telegram_send_message(f"❗ *tdarr_sync error:*\n{msg}\n{exc if exc else ''}")
    raise SystemExit(1)

def sonarr_get(endpoint: str, params: Dict = None) -> requests.Response:
    params = params or {}
    params["apikey"] = SONARR_API_KEY
    url = SONARR_URL.rstrip("/") + "/api/v3" + endpoint
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r

def find_tag_id(tag_name: str) -> Optional[int]:
    if not tag_name:
        logger.info("No SONARR_TAG_NAME specified; will process all series.")
        return None
    try:
        tags = sonarr_get("/tag").json()
    except Exception as e:
        report_error_and_exit("Failed to get tags from Sonarr", e)
    for t in tags:
        if str(t.get("label", "")).lower() == tag_name.lower():
            return int(t.get("id"))
    report_error_and_exit(f"Tag '{tag_name}' not found. Existing tags: {[t.get('label') for t in tags]}")

def get_series_with_tag(tag_id: Optional[int]) -> List[Dict]:
    try:
        series_list = sonarr_get("/series").json()
    except Exception as e:
        report_error_and_exit("Failed to get series from Sonarr", e)
    if tag_id is None:
        return series_list
    return [s for s in series_list if tag_id in (s.get("tags") or [])]

def get_episode_files_for_series(series_id: int) -> List[Dict]:
    try:
        return sonarr_get("/episodefile", params={"seriesId": series_id}).json()
    except Exception as e:
        report_error_and_exit(f"Failed fetching episode files for series {series_id}", e)

def translate_path(sonarr_path: str) -> Path:
    """Map Sonarr path rooted at SONARR_BASE_PATH to local path under LOCAL_MOUNT_BASE_PATH."""
    p = Path(sonarr_path)
    try:
        if p.is_absolute() and p.parts[:len(SONARR_BASE_PATH.parts)] == SONARR_BASE_PATH.parts:
            relative = p.relative_to(SONARR_BASE_PATH)
            return LOCAL_MOUNT_BASE_PATH.joinpath(relative)
        return p
    except Exception as e:
        logger.warning("Path translation failed for '%s': %s", sonarr_path, e)
        return p

def build_relative_path(full_path: Path, base_dir: Path) -> Path:
    try:
        return full_path.resolve().relative_to(base_dir.resolve())
    except Exception as e:
        report_error_and_exit(f"Failed to relativize '{full_path}' to '{base_dir}'", e)

def safe_copy_to_tdarr(src: Path, dest_root: Path, base_dir: Path, dry_run=False) -> Path:
    rel = build_relative_path(src, base_dir)
    dest = dest_root.joinpath(rel)
    if dry_run:
        logger.info("[COPY DRY] %s -> %s", src, dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("COPY: %s -> %s", src, dest)
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

# -------------------- Archive/Retention (AFTER restore only) --------------------
def _compute_backup_target(original: Path) -> Path:
    """
    Return a backup name that always ends with BACKUP_SUFFIX.
    If '<name><BACKUP_SUFFIX>' exists, append '.<epoch>' BEFORE the suffix:
      '<name>.<epoch><BACKUP_SUFFIX>'  (still endswith BACKUP_SUFFIX)
    """
    base = original.name
    candidate = original.with_name(base + BACKUP_SUFFIX)
    if not candidate.exists():
        return candidate
    # collision: add epoch before suffix but keep suffix at the end for sweeper
    epoch = str(int(time.time()))
    candidate = original.with_name(f"{base}.{epoch}{BACKUP_SUFFIX}")
    # very unlikely second collision; add a counter
    counter = 1
    while candidate.exists():
        candidate = original.with_name(f"{base}.{epoch}.{counter}{BACKUP_SUFFIX}")
        counter += 1
    return candidate

def archive_original_before_restore(file_path: Path) -> Optional[Path]:
    """
    If RENAME_ORIGINAL_FILES and destination exists, rename it with BACKUP_SUFFIX.
    If MOVE_ORIGINAL_FILES, move that backup into MOVE_ORIGINAL_FILES_DEST preserving path under BASE_DIR.
    When moved to archive, 'touch' the file to now so retention is based on archive time.
    Returns the final archived path (or None if nothing archived).
    """
    if not RENAME_ORIGINAL_FILES:
        return None
    if not file_path.exists():
        return None

    backup_on_site = _compute_backup_target(file_path)
    logger.info("ARCHIVE: rename original %s -> %s", file_path, backup_on_site)
    try:
        file_path.rename(backup_on_site)
    except Exception as e:
        report_error_and_exit(f"Failed to rename original '{file_path}' -> '{backup_on_site}'", e)

    archived_path = backup_on_site

    if MOVE_ORIGINAL_FILES:
        try:
            rel = backup_on_site.resolve().relative_to(BASE_DIR.resolve())
            dest = MOVE_ORIGINAL_FILES_DEST.joinpath(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            logger.info("ARCHIVE: move to archive %s -> %s", backup_on_site, dest)
            shutil.move(str(backup_on_site), str(dest))
            archived_path = dest
        except Exception as e:
            # If file isn't under BASE_DIR or move failed, keep it in place but continue
            logger.warning("ARCHIVE: move skipped (kept in place). Reason: %s", e)
            archived_path = backup_on_site

        # Touch archived file (in archive destination OR kept-in-place) to set mtime = archived_at (now)
        try:
            now = time.time()
            os.utime(archived_path, (now, now))
            logger.info("ARCHIVE: touched %s to now for correct retention", archived_path)
        except Exception as e:
            logger.warning("ARCHIVE: failed to touch %s: %s", archived_path, e)

    return archived_path

def cleanup_old_originals():
    """
    Delete backup-suffixed files older than DELETE_ORIGINAL_FILES_DAYS in MOVE_ORIGINAL_FILES_DEST,
    if DELETE_ORIGINAL_FILES=True. Uses file mtime which we set on archive (touch) so retention is correct.
    """
    if not DELETE_ORIGINAL_FILES:
        return
    if not MOVE_ORIGINAL_FILES_DEST.exists() or not MOVE_ORIGINAL_FILES_DEST.is_dir():
        logger.warning("SWEEP: archive dir %s missing; skipping sweep.", MOVE_ORIGINAL_FILES_DEST)
        return

    now = time.time()
    cutoff = now - (DELETE_ORIGINAL_FILES_DAYS * 86400) if DELETE_ORIGINAL_FILES_DAYS > 0 else 0

    deleted = 0
    scanned = 0
    for root, _, files in os.walk(MOVE_ORIGINAL_FILES_DEST):
        for fname in files:
            # Only consider files that end with BACKUP_SUFFIX (by design)
            if not fname.endswith(BACKUP_SUFFIX):
                continue
            scanned += 1
            fpath = Path(root) / fname
            try:
                mtime = fpath.stat().st_mtime
                if DELETE_ORIGINAL_FILES_DAYS == 0 or mtime < cutoff:
                    logger.info("SWEEP: deleting archived original: %s", fpath)
                    fpath.unlink(missing_ok=True)
                    deleted += 1
            except Exception as e:
                logger.warning("SWEEP: failed to handle %s: %s", fpath, e)
    logger.info("SWEEP: scanned=%d, deleted=%d", scanned, deleted)

# -------------------- Phases --------------------
def process_sonarr_to_tdarr(dry_run=False):
    conn = init_db()
    tag_id = find_tag_id(SONARR_TAG_NAME)
    series_list = get_series_with_tag(tag_id)
    if not series_list:
        logger.info("No series found to process.")
        conn.close()
        return

    for s in series_list:
        series_id = s.get("id")
        title = s.get("title")
        logger.info("SERIES: %s (id=%s)", title, series_id)
        for ef in get_episode_files_for_series(series_id):
            path = ef.get("path") or ef.get("relativePath")
            if not path:
                logger.warning("Skipping episode file with no path: %s", ef)
                continue
            src = translate_path(path)
            if not src.exists():
                logger.warning("Missing source file, skipping: %s", src)
                continue
            src_resolved = str(src.resolve())
            if is_processed(conn, src_resolved):
                logger.info("SKIP (already processed): %s", src)
                continue

            # COPY ONLY (no rename/move here)
            try:
                safe_copy_to_tdarr(src=src, dest_root=TDARR_INPUT_DIR, base_dir=BASE_DIR, dry_run=dry_run)
                if not dry_run:
                    mark_processed(conn, src_resolved)
            except Exception as e:
                report_error_and_exit(f"Copy failed {src} -> {TDARR_INPUT_DIR}", e)
    conn.close()

def move_tdarr_output_back(dry_run=False):
    if not TDARR_OUTPUT_DIR.exists():
        logger.info("Tdarr output dir does not exist: %s", TDARR_OUTPUT_DIR)
        return

    logger.info("RESTORE: scanning %s", TDARR_OUTPUT_DIR)
    for out_path in TDARR_OUTPUT_DIR.rglob("*"):
        if out_path.is_dir():
            continue
        try:
            rel = out_path.relative_to(TDARR_OUTPUT_DIR)
        except Exception:
            logger.warning("RESTORE: unexpected file outside output dir: %s", out_path)
            continue

        dest = BASE_DIR.joinpath(rel)
        if dry_run:
            logger.info("[RESTORE DRY] %s -> %s", out_path, dest)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)

        # If destination exists, archive original NOW (rename + optional move + touch)
        if dest.exists():
            archive_original_before_restore(dest)

        logger.info("RESTORE: move transcoded %s -> %s", out_path, dest)
        try:
            shutil.move(str(out_path), str(dest))
        except Exception as e:
            report_error_and_exit(f"Failed to move restored file {out_path} -> {dest}", e)

# -------------------- CLI --------------------
def parse_args():
    p = argparse.ArgumentParser(description="Sync Sonarr-tagged media to Tdarr and restore outputs.")
    p.add_argument("--dry-run", action="store_true", help="Log intended actions without writing.")
    p.add_argument("--skip-restore", action="store_true", help="Skip restore phase.")
    return p.parse_args()

def main():
    args = parse_args()
    logger.info("Starting tdarr_sync (dry_run=%s)", args.dry_run)
    try:
        process_sonarr_to_tdarr(dry_run=args.dry_run)
        if not args.skip_restore:
            move_tdarr_output_back(dry_run=args.dry_run)
            if not args.dry_run:
                cleanup_old_originals()
    except SystemExit:
        raise
    except Exception as e:
        report_error_and_exit("Unhandled error in main()", e)
    logger.info("Finished tdarr_sync run.")

if __name__ == "__main__":
    main()
#V1.1.1 - Update to handle Sonarr-tagged files, archive originals, and cleanup old archives.