#!/usr/bin/env python3
"""
tdarr_sync.py

Workflow:
- Copy phase: copy Sonarr/Radarr tagged files into TDARR_INPUT_DIR (preserving relative paths).
  * NO renaming/moving of originals during copy.
- Restore phase: move transcoded files from TDARR_OUTPUT_DIR back into library paths.
  * If destination exists, rename it with BACKUP_SUFFIX and (optionally) move to MOVE_ORIGINAL_FILES_DEST.
  * When moved to archive, 'touch' its mtime to now so retention uses archive time (not content age).
- After restore, optionally sweep old archived originals based on DELETE_ORIGINAL_FILES settings.

New:
- Interactive picker (--interactive or INTERACTIVE=True in .env) with per-series processed status.
"""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv
from runtime_settings import load_runtime_settings, settings_path_from_env
from sync_progress import ProgressReporter, progress_path_from_env

# -------------------- ENV --------------------
load_dotenv()

try:
    SONARR_URL = os.environ["SONARR_URL"]
    SONARR_API_KEY = os.environ["SONARR_API_KEY"]
    SONARR_TAG_NAME = os.environ.get("SONARR_TAG_NAME", "")
    RADARR_URL = os.environ.get("RADARR_URL", "")
    RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
    RADARR_TAG_NAME = os.environ.get("RADARR_TAG_NAME", "")

    BASE_DIR = Path(os.environ["BASE_DIR"]).resolve()
    TDARR_INPUT_DIR = Path(os.environ["TDARR_INPUT_DIR"]).resolve()
    TDARR_OUTPUT_DIR = Path(os.environ["TDARR_OUTPUT_DIR"]).resolve()

    SONARR_BASE_PATH = Path(os.environ.get("SONARR_BASE_PATH", "/tv"))
    LOCAL_MOUNT_BASE_PATH = Path(os.environ.get("LOCAL_MOUNT_BASE_PATH", "/mnt/media-videos"))
    RADARR_BASE_PATH = Path(os.environ.get("RADARR_BASE_PATH", "/movies"))
    RADARR_LOCAL_MOUNT_BASE_PATH = Path(os.environ.get("RADARR_LOCAL_MOUNT_BASE_PATH", str(BASE_DIR)))

    RENAME_ORIGINAL_FILES = os.environ.get("RENAME_ORIGINAL_FILES", "True").lower() in ("true", "1", "yes")
    BACKUP_SUFFIX = os.environ.get("BACKUP_SUFFIX", ".orig")
    MOVE_ORIGINAL_FILES = os.environ.get("MOVE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    MOVE_ORIGINAL_FILES_DEST = Path(os.environ.get("MOVE_ORIGINAL_FILES_DEST", "/mnt/originals_archive"))
    DELETE_ORIGINAL_FILES = os.environ.get("DELETE_ORIGINAL_FILES", "False").lower() in ("true", "1", "yes")
    DELETE_ORIGINAL_FILES_DAYS = int(os.environ.get("DELETE_ORIGINAL_FILES_DAYS", "30"))

    # Interactive default via .env (new)
    ENV_INTERACTIVE = os.environ.get("INTERACTIVE", "False").lower() in ("true", "1", "yes")

    # Accept either TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN without requiring .env change
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    LOG_FILE = os.environ.get("LOG_FILE", "/var/log/sonarr_tdarr_sync/sonarr_tdarr_sync.log")
    LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))
    LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 3))

    STATE_DB_FILE = Path(os.environ.get("STATE_DB_FILE", "sonarr_tdarr_state.db")).resolve()
    RUNTIME_SETTINGS_FILE = settings_path_from_env().resolve()
    SYNC_PROGRESS_FILE = progress_path_from_env().resolve()
except KeyError as e:
    print(f"Missing required environment variable: {e}")
    raise SystemExit(1)

SOURCE_PREFIXES = {
    "sonarr": "__sonarr_input__",
    "radarr": "__radarr_input__",
}
# Temporary route-tag block list. Any matching routes are ignored for copy + restore handling.
TEMP_DISABLED_ROUTE_TAGS = {"remux"}
PROGRESS: Optional[ProgressReporter] = None


def _progress_begin(phase: str, *, total_items: Optional[int] = None, action: str = "planning") -> None:
    if PROGRESS:
        PROGRESS.begin_phase(phase, total_items=total_items, action=action)


def _progress_total(total_items: int, *, action: str = "processing", message: Optional[str] = None) -> None:
    if PROGRESS:
        PROGRESS.set_total(total_items, action=action, message=message)


def _progress_advance(
    *,
    action: str,
    source: Optional[str] = None,
    title: Optional[str] = None,
    path: Optional[Path] = None,
    destination: Optional[Path] = None,
    message: Optional[str] = None,
    skipped: bool = False,
    failed: bool = False,
) -> None:
    if PROGRESS:
        PROGRESS.advance(
            action=action,
            source=source,
            title=title,
            path=str(path) if path is not None else None,
            destination=str(destination) if destination is not None else None,
            message=message,
            skipped_delta=1 if skipped else 0,
            failed_delta=1 if failed else 0,
        )


def _progress_current(
    *,
    action: str,
    source: Optional[str] = None,
    title: Optional[str] = None,
    path: Optional[Path] = None,
    destination: Optional[Path] = None,
    message: Optional[str] = None,
) -> None:
    if PROGRESS:
        PROGRESS.action = action
        PROGRESS.emit(
            source=source,
            title=title,
            path=str(path) if path is not None else None,
            destination=str(destination) if destination is not None else None,
            message=message,
        )

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
def _fmt_ts(epoch: Optional[int]) -> str:
    if not epoch:
        return "-"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")

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

def _arr_get(base_url: str, api_key: str, endpoint: str, params: Optional[Dict] = None) -> requests.Response:
    query = dict(params or {})
    query["apikey"] = api_key
    url = base_url.rstrip("/") + "/api/v3" + endpoint
    response = requests.get(url, params=query, timeout=20)
    response.raise_for_status()
    return response


def sonarr_get(endpoint: str, params: Optional[Dict] = None) -> requests.Response:
    return _arr_get(SONARR_URL, SONARR_API_KEY, endpoint, params)


def radarr_get(endpoint: str, params: Optional[Dict] = None) -> requests.Response:
    if not RADARR_URL or not RADARR_API_KEY:
        raise RuntimeError("Radarr is not configured.")
    return _arr_get(RADARR_URL, RADARR_API_KEY, endpoint, params)


def _translate_path(arr_path: str, arr_base_path: Path, local_mount_path: Path) -> Path:
    """Map an ARR path rooted at arr_base_path to local_mount_path."""
    candidate = Path(arr_path)
    try:
        if candidate.is_absolute() and candidate.parts[: len(arr_base_path.parts)] == arr_base_path.parts:
            relative = candidate.relative_to(arr_base_path)
            return local_mount_path.joinpath(relative)
        return candidate
    except Exception as exc:
        logger.warning("Path translation failed for '%s': %s", arr_path, exc)
        return candidate


def translate_sonarr_path(sonarr_path: str) -> Path:
    return _translate_path(sonarr_path, SONARR_BASE_PATH, LOCAL_MOUNT_BASE_PATH)


def translate_radarr_path(radarr_path: str) -> Path:
    return _translate_path(radarr_path, RADARR_BASE_PATH, RADARR_LOCAL_MOUNT_BASE_PATH)


def get_episode_files_for_series(series_id: int) -> List[Dict]:
    try:
        return sonarr_get("/episodefile", params={"seriesId": series_id}).json()
    except Exception as e:
        report_error_and_exit(f"Failed fetching episode files for series {series_id}", e)


def get_tag_lookup(source: str) -> Dict[str, int]:
    getter = sonarr_get if source == "sonarr" else radarr_get
    label_to_id: Dict[str, int] = {}
    try:
        tags = getter("/tag").json()
    except Exception as exc:
        report_error_and_exit(f"Failed to load tags from {source.capitalize()}", exc)
    for tag in tags:
        label = str(tag.get("label", "")).strip()
        if not label:
            continue
        try:
            label_to_id[label.lower()] = int(tag.get("id"))
        except (TypeError, ValueError):
            continue
    return label_to_id


def _find_route_for_item(
    item_tag_ids: List[int], routes: List[Dict[str, str]], tag_lookup: Dict[str, int]
) -> Optional[Dict[str, str]]:
    for route in routes:
        route_tag_id = tag_lookup.get(route["tag"].lower())
        if route_tag_id is None:
            continue
        if route_tag_id in item_tag_ids:
            return route
    return None


def _normalize_tag_ids(raw_tags: object) -> List[int]:
    normalized: List[int] = []
    if not isinstance(raw_tags, list):
        return normalized
    for value in raw_tags:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def _route_tag(route: Dict[str, object]) -> str:
    return str(route.get("tag", "")).strip().lower()


def _partition_routes_by_disabled_tag(
    routes: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    enabled: List[Dict[str, str]] = []
    disabled: List[Dict[str, str]] = []
    for route in routes:
        if _route_tag(route) in TEMP_DISABLED_ROUTE_TAGS:
            disabled.append(route)
        else:
            enabled.append(route)
    return enabled, disabled


def _log_disabled_routes(disabled_routes: List[Dict[str, str]], *, scope: str) -> None:
    if not disabled_routes:
        return
    tags = sorted({_route_tag(route) for route in disabled_routes if _route_tag(route)})
    logger.warning(
        "Temporarily disabled %d %s route(s) for blocked tag(s): %s",
        len(disabled_routes),
        scope,
        ", ".join(tags),
    )


def _disabled_route_input_subdirs(runtime_settings: Dict[str, object]) -> Set[str]:
    disabled_subdirs: Set[str] = set()
    configured_routes = runtime_settings.get("routes", [])
    if not isinstance(configured_routes, list):
        return disabled_subdirs

    for route in configured_routes:
        if not isinstance(route, dict):
            continue
        if _route_tag(route) not in TEMP_DISABLED_ROUTE_TAGS:
            continue
        input_subdir = str(route.get("input_subdir", "")).strip()
        if input_subdir:
            disabled_subdirs.add(input_subdir)
    return disabled_subdirs


def _route_input_root(route: Dict[str, str], source: str) -> Path:
    parts = [TDARR_INPUT_DIR]
    input_subdir = route.get("input_subdir", "").strip()
    if input_subdir:
        parts.append(Path(input_subdir))
    parts.append(Path(SOURCE_PREFIXES[source]))
    dest = Path(parts[0])
    for segment in parts[1:]:
        dest = dest.joinpath(segment)
    return dest

def build_relative_path(full_path: Path, base_dir: Path) -> Path:
    try:
        return full_path.resolve().relative_to(base_dir.resolve())
    except Exception as e:
        report_error_and_exit(f"Failed to relativize '{full_path}' to '{base_dir}'", e)

def _format_copy_status(copied_bytes: int, total_bytes: int, mb_per_second: Optional[float]) -> str:
    total_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else 0
    copied_mb = copied_bytes / (1024 * 1024)
    if mb_per_second is None:
        return f"Copying {copied_mb:.1f} / {total_mb:.1f} MB"
    return f"Copying {copied_mb:.1f} / {total_mb:.1f} MB at {mb_per_second:.1f} MB/s"


def safe_copy_to_tdarr(
    src: Path,
    dest_root: Path,
    base_dir: Path,
    dry_run=False,
    progress_callback: Optional[Callable[[int, int, float], None]] = None,
) -> Path:
    rel = build_relative_path(src, base_dir)
    dest = dest_root.joinpath(rel)
    if dry_run:
        logger.info("[COPY DRY] %s -> %s", src, dest)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("COPY: %s -> %s", src, dest)
    total_bytes = src.stat().st_size
    copied_bytes = 0
    started_at = time.monotonic()
    last_emit = started_at
    chunk_size = 8 * 1024 * 1024

    with src.open("rb") as source_handle, dest.open("wb") as dest_handle:
        while True:
            chunk = source_handle.read(chunk_size)
            if not chunk:
                break
            dest_handle.write(chunk)
            copied_bytes += len(chunk)
            now = time.monotonic()
            if progress_callback and (now - last_emit >= 1 or copied_bytes >= total_bytes):
                elapsed = max(now - started_at, 0.001)
                mb_per_second = (copied_bytes / (1024 * 1024)) / elapsed
                progress_callback(copied_bytes, total_bytes, mb_per_second)
                last_emit = now

    shutil.copystat(str(src), str(dest))
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


def load_structured_selection_from_env() -> Optional[Dict[int, Optional[Set[int]]]]:
    raw = os.environ.get("TDARR_SYNC_SELECTION")
    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid TDARR_SYNC_SELECTION payload: %s", exc)
        return None

    if not isinstance(payload, list):
        logger.error("TDARR_SYNC_SELECTION must be a list of selections; ignoring value.")
        return None

    structured: Dict[int, Optional[Set[int]]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        series_raw = item.get("series_id")
        if series_raw is None:
            continue
        try:
            series_id = int(series_raw)
        except (TypeError, ValueError):
            continue

        seasons_raw = item.get("seasons")
        if seasons_raw is None:
            structured[series_id] = None
            continue

        if not isinstance(seasons_raw, list):
            continue

        normalized: Set[int] = set()
        for season in seasons_raw:
            try:
                normalized.add(int(season))
            except (TypeError, ValueError):
                continue

        if not normalized:
            # Skip entries that do not include any valid seasons
            continue

        structured[series_id] = normalized

    if not structured:
        logger.warning("TDARR_SYNC_SELECTION did not contain any valid series entries.")
        return None

    logger.info(
        "Structured selection received via environment: %s",
        {series_id: (sorted(seasons) if seasons is not None else None) for series_id, seasons in structured.items()},
    )
    return structured


def load_effective_routes() -> Tuple[Dict[str, object], List[Dict[str, str]], bool]:
    runtime_settings = load_runtime_settings(RUNTIME_SETTINGS_FILE)
    configured_routes = runtime_settings.get("routes", [])
    if isinstance(configured_routes, list) and configured_routes:
        routes: List[Dict[str, str]] = []
        for route in configured_routes:
            if isinstance(route, dict):
                routes.append(route)
        enabled_routes, disabled_routes = _partition_routes_by_disabled_tag(routes)
        _log_disabled_routes(disabled_routes, scope="UI")
        logger.info(
            "Loaded %d active route rule(s) from %s%s",
            len(enabled_routes),
            RUNTIME_SETTINGS_FILE,
            f" ({len(disabled_routes)} temporarily disabled)" if disabled_routes else "",
        )
        return runtime_settings, enabled_routes, False

    # Legacy fallback keeps existing behaviour if UI rules have not been configured yet.
    fallback_routes: List[Dict[str, str]] = []
    if SONARR_TAG_NAME:
        fallback_routes.append(
            {
                "source": "sonarr",
                "tag": SONARR_TAG_NAME,
                "flow_name": "legacy-sonarr",
                "input_subdir": "",
            }
        )
    if RADARR_URL and RADARR_API_KEY and RADARR_TAG_NAME:
        fallback_routes.append(
            {
                "source": "radarr",
                "tag": RADARR_TAG_NAME,
                "flow_name": "legacy-radarr",
                "input_subdir": "",
            }
        )
    enabled_fallback, disabled_fallback = _partition_routes_by_disabled_tag(fallback_routes)
    _log_disabled_routes(disabled_fallback, scope="legacy")
    if enabled_fallback:
        logger.info(
            "No UI routes configured in %s; using %d legacy env-based route(s).",
            RUNTIME_SETTINGS_FILE,
            len(enabled_fallback),
        )
    elif disabled_fallback:
        logger.warning("No active legacy routes after temporary tag suppression.")
    else:
        logger.warning("No routes configured in runtime settings or environment.")
    return runtime_settings, enabled_fallback, True


def _group_routes_by_source(routes: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    grouped: Dict[str, List[Dict[str, str]]] = {"sonarr": [], "radarr": []}
    for route in routes:
        source = str(route.get("source", "")).lower()
        if source not in grouped:
            continue
        grouped[source].append(route)
    return grouped


def episode_season_number(episode: dict) -> int:
    raw = episode.get("seasonNumber")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0

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
    epoch = str(int(time.time()))
    candidate = original.with_name(f"{base}.{epoch}{BACKUP_SUFFIX}")
    counter = 1
    while candidate.exists():
        candidate = original.with_name(f"{base}.{epoch}.{counter}{BACKUP_SUFFIX}")
        counter += 1
    return candidate

def archive_original_before_restore(file_path: Path, library_base: Path) -> Optional[Path]:
    """
    If RENAME_ORIGINAL_FILES and destination exists, rename it with BACKUP_SUFFIX.
    If MOVE_ORIGINAL_FILES, move that backup into MOVE_ORIGINAL_FILES_DEST preserving path under library_base.
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
            rel = backup_on_site.resolve().relative_to(library_base.resolve())
            dest = MOVE_ORIGINAL_FILES_DEST.joinpath(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            logger.info("ARCHIVE: move to archive %s -> %s", backup_on_site, dest)
            shutil.move(str(backup_on_site), str(dest))
            archived_path = dest
        except Exception as e:
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
    _progress_begin("sweep_archives", action="scanning")
    if not DELETE_ORIGINAL_FILES:
        _progress_total(0, action="skipped", message="Archive deletion is disabled.")
        return
    if not MOVE_ORIGINAL_FILES_DEST.exists() or not MOVE_ORIGINAL_FILES_DEST.is_dir():
        logger.warning("SWEEP: archive dir %s missing; skipping sweep.", MOVE_ORIGINAL_FILES_DEST)
        _progress_total(0, action="skipped", message="Archive directory is missing.")
        return

    now = time.time()
    cutoff = now - (DELETE_ORIGINAL_FILES_DAYS * 86400) if DELETE_ORIGINAL_FILES_DAYS > 0 else 0

    sweep_files: List[Path] = []
    for root, _, files in os.walk(MOVE_ORIGINAL_FILES_DEST):
        for fname in files:
            if fname.endswith(BACKUP_SUFFIX):
                sweep_files.append(Path(root) / fname)

    _progress_total(len(sweep_files), action="sweeping", message=f"Sweeping {len(sweep_files)} archived original(s).")
    deleted = 0
    scanned = 0
    for fpath in sweep_files:
        scanned += 1
        try:
            mtime = fpath.stat().st_mtime
            if DELETE_ORIGINAL_FILES_DAYS == 0 or mtime < cutoff:
                logger.info("SWEEP: deleting archived original: %s", fpath)
                fpath.unlink(missing_ok=True)
                deleted += 1
                _progress_advance(action="deleted", path=fpath)
            else:
                _progress_advance(action="kept", path=fpath, skipped=True)
        except Exception as e:
            logger.warning("SWEEP: failed to handle %s: %s", fpath, e)
            _progress_advance(action="failed", path=fpath, message=str(e), failed=True)
    logger.info("SWEEP: scanned=%d, deleted=%d", scanned, deleted)

# -------------------- Phases --------------------
def _copy_sonarr_items(
    conn: sqlite3.Connection,
    routes: List[Dict[str, str]],
    *,
    dry_run: bool,
    selection: Optional[Dict[int, Optional[Set[int]]]],
    legacy_mode: bool,
) -> None:
    _progress_begin("copy_sonarr", action="loading_routes")
    if not routes:
        logger.info("No Sonarr routes configured; skipping Sonarr copy.")
        _progress_total(0, action="skipped", message="No Sonarr routes configured.")
        return

    tag_lookup = get_tag_lookup("sonarr")
    unknown_tags = sorted({route["tag"] for route in routes if route["tag"].lower() not in tag_lookup})
    if unknown_tags:
        logger.warning("Sonarr routes contain unknown tag(s): %s", ", ".join(unknown_tags))

    try:
        series_list = sonarr_get("/series").json()
    except Exception as exc:
        report_error_and_exit("Failed to get series from Sonarr", exc)

    if selection is not None:
        selected_ids = set(selection.keys())
        before = len(series_list)
        series_list = [series for series in series_list if series.get("id") in selected_ids]
        logger.info("Structured selection: %d -> %d Sonarr series", before, len(series_list))

    if not series_list:
        logger.info("No Sonarr series found to process.")
        _progress_total(0, action="skipped", message="No Sonarr series found to process.")
        return

    work_items: List[Dict[str, object]] = []
    for series in series_list:
        try:
            series_id = int(series.get("id"))
        except (TypeError, ValueError):
            logger.warning("Skipping Sonarr series with invalid id: %s", series)
            continue

        season_filter = None
        if selection is not None and series_id in selection:
            season_filter = selection.get(series_id)

        item_tag_ids = _normalize_tag_ids(series.get("tags"))
        route = _find_route_for_item(item_tag_ids, routes, tag_lookup)
        if route is None:
            continue

        if legacy_mode:
            destination_root = TDARR_INPUT_DIR
        else:
            destination_root = _route_input_root(route, "sonarr")

        logger.info(
            "SONARR: %s (id=%s) -> flow='%s' tag='%s' dest='%s'",
            series.get("title"),
            series_id,
            route.get("flow_name", ""),
            route.get("tag", ""),
            destination_root,
        )
        for episode_file in get_episode_files_for_series(series_id):
            path = episode_file.get("path") or episode_file.get("relativePath")
            if not path:
                logger.warning("Skipping Sonarr episode file with no path: %s", episode_file)
                continue
            if season_filter is not None:
                season_number = episode_season_number(episode_file)
                if season_number not in season_filter:
                    continue

            work_items.append(
                {
                    "title": str(series.get("title") or f"Series {series_id}"),
                    "src": translate_sonarr_path(path),
                    "destination_root": destination_root,
                }
            )

    _progress_total(len(work_items), action="copying", message=f"Copying {len(work_items)} Sonarr file(s).")

    for item in work_items:
        title = str(item["title"])
        src = item["src"]
        destination_root = item["destination_root"]
        if not isinstance(src, Path) or not isinstance(destination_root, Path):
            continue
        try:
            planned_dest = destination_root.joinpath(src.resolve().relative_to(BASE_DIR.resolve()))
        except (OSError, RuntimeError, ValueError):
            planned_dest = None

        if not src.exists():
            logger.warning("Missing Sonarr source file, skipping: %s", src)
            _progress_advance(
                action="skipped_missing_source",
                source="sonarr",
                title=title,
                path=src,
                destination=planned_dest,
                skipped=True,
            )
            continue

        src_resolved = str(src.resolve())
        if is_processed(conn, src_resolved):
            logger.info("SKIP (already processed): %s", src)
            _progress_advance(
                action="skipped_already_processed",
                source="sonarr",
                title=title,
                path=src,
                destination=planned_dest,
                skipped=True,
            )
            continue

        try:
            total_bytes = src.stat().st_size
            _progress_current(
                action="copying",
                source="sonarr",
                title=title,
                path=src,
                destination=planned_dest,
                message=_format_copy_status(0, total_bytes, None),
            )

            def report_copy_progress(copied_bytes: int, total: int, mb_per_second: float) -> None:
                _progress_current(
                    action="copying",
                    source="sonarr",
                    title=title,
                    path=src,
                    destination=planned_dest,
                    message=_format_copy_status(copied_bytes, total, mb_per_second),
                )

            dest = safe_copy_to_tdarr(
                src=src,
                dest_root=destination_root,
                base_dir=BASE_DIR,
                dry_run=dry_run,
                progress_callback=report_copy_progress,
            )
            if not dry_run:
                mark_processed(conn, src_resolved)
            _progress_advance(action="copied", source="sonarr", title=title, path=src, destination=dest, message="Copy complete")
        except Exception as exc:
            _progress_advance(
                action="failed",
                source="sonarr",
                title=title,
                path=src,
                destination=planned_dest,
                message=str(exc),
                failed=True,
            )
            report_error_and_exit(f"Copy failed {src} -> {destination_root}", exc)


def _extract_radarr_movie_file_path(movie: Dict) -> Optional[str]:
    movie_file = movie.get("movieFile")
    if isinstance(movie_file, dict):
        path = movie_file.get("path")
        if path:
            return str(path)

    movie_id_raw = movie.get("id")
    if movie_id_raw is None:
        return None
    try:
        movie_id = int(movie_id_raw)
    except (TypeError, ValueError):
        return None

    try:
        movie_files = radarr_get("/moviefile", params={"movieId": movie_id}).json()
    except Exception as exc:
        logger.warning("Failed fetching Radarr movie file for movie id=%s: %s", movie_id, exc)
        return None

    if isinstance(movie_files, list):
        for item in movie_files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if path:
                return str(path)
    return None


def _copy_radarr_items(
    conn: sqlite3.Connection,
    routes: List[Dict[str, str]],
    *,
    dry_run: bool,
    legacy_mode: bool,
) -> None:
    _progress_begin("copy_radarr", action="loading_routes")
    if not routes:
        logger.info("No Radarr routes configured; skipping Radarr copy.")
        _progress_total(0, action="skipped", message="No Radarr routes configured.")
        return
    if not RADARR_URL or not RADARR_API_KEY:
        logger.warning("Radarr routes exist but RADARR_URL/RADARR_API_KEY are not configured; skipping Radarr copy.")
        _progress_total(0, action="skipped", message="Radarr is not configured.")
        return

    tag_lookup = get_tag_lookup("radarr")
    unknown_tags = sorted({route["tag"] for route in routes if route["tag"].lower() not in tag_lookup})
    if unknown_tags:
        logger.warning("Radarr routes contain unknown tag(s): %s", ", ".join(unknown_tags))

    try:
        movies = radarr_get("/movie").json()
    except Exception as exc:
        report_error_and_exit("Failed to get movies from Radarr", exc)

    if not movies:
        logger.info("No Radarr movies found to process.")
        _progress_total(0, action="skipped", message="No Radarr movies found to process.")
        return

    work_items: List[Dict[str, object]] = []
    for movie in movies:
        item_tag_ids = _normalize_tag_ids(movie.get("tags"))
        route = _find_route_for_item(item_tag_ids, routes, tag_lookup)
        if route is None:
            continue

        path = _extract_radarr_movie_file_path(movie)
        if not path:
            logger.warning("Skipping Radarr movie with no file path: %s", movie.get("title"))
            continue

        src = translate_radarr_path(path)
        if legacy_mode:
            destination_root = TDARR_INPUT_DIR.joinpath(SOURCE_PREFIXES["radarr"])
        else:
            destination_root = _route_input_root(route, "radarr")

        logger.info(
            "RADARR: %s -> flow='%s' tag='%s' dest='%s'",
            movie.get("title"),
            route.get("flow_name", ""),
            route.get("tag", ""),
            destination_root,
        )
        work_items.append(
            {
                "title": str(movie.get("title") or "Radarr movie"),
                "src": src,
                "destination_root": destination_root,
            }
        )

    _progress_total(len(work_items), action="copying", message=f"Copying {len(work_items)} Radarr file(s).")

    for item in work_items:
        title = str(item["title"])
        src = item["src"]
        destination_root = item["destination_root"]
        if not isinstance(src, Path) or not isinstance(destination_root, Path):
            continue
        try:
            planned_dest = destination_root.joinpath(src.resolve().relative_to(RADARR_LOCAL_MOUNT_BASE_PATH.resolve()))
        except (OSError, RuntimeError, ValueError):
            planned_dest = None

        if not src.exists():
            logger.warning("Missing Radarr source file, skipping: %s", src)
            _progress_advance(
                action="skipped_missing_source",
                source="radarr",
                title=title,
                path=src,
                destination=planned_dest,
                skipped=True,
            )
            continue

        src_resolved = str(src.resolve())
        if is_processed(conn, src_resolved):
            logger.info("SKIP (already processed): %s", src)
            _progress_advance(
                action="skipped_already_processed",
                source="radarr",
                title=title,
                path=src,
                destination=planned_dest,
                skipped=True,
            )
            continue

        try:
            total_bytes = src.stat().st_size
            _progress_current(
                action="copying",
                source="radarr",
                title=title,
                path=src,
                destination=planned_dest,
                message=_format_copy_status(0, total_bytes, None),
            )

            def report_copy_progress(copied_bytes: int, total: int, mb_per_second: float) -> None:
                _progress_current(
                    action="copying",
                    source="radarr",
                    title=title,
                    path=src,
                    destination=planned_dest,
                    message=_format_copy_status(copied_bytes, total, mb_per_second),
                )

            dest = safe_copy_to_tdarr(
                src=src,
                dest_root=destination_root,
                base_dir=RADARR_LOCAL_MOUNT_BASE_PATH,
                dry_run=dry_run,
                progress_callback=report_copy_progress,
            )
            if not dry_run:
                mark_processed(conn, src_resolved)
            _progress_advance(action="copied", source="radarr", title=title, path=src, destination=dest, message="Copy complete")
        except Exception as exc:
            _progress_advance(
                action="failed",
                source="radarr",
                title=title,
                path=src,
                destination=planned_dest,
                message=str(exc),
                failed=True,
            )
            report_error_and_exit(f"Copy failed {src} -> {destination_root}", exc)


def process_media_to_tdarr(dry_run=False, selection: Optional[Dict[int, Optional[Set[int]]]] = None):
    _progress_begin("copy_sonarr", action="loading_routes")
    _, routes, legacy_mode = load_effective_routes()
    if not routes:
        logger.info("No route rules resolved. Nothing to copy into Tdarr input.")
        _progress_total(0, action="skipped", message="No route rules resolved.")
        return

    grouped_routes = _group_routes_by_source(routes)
    conn = init_db()
    try:
        _copy_sonarr_items(conn, grouped_routes["sonarr"], dry_run=dry_run, selection=selection, legacy_mode=legacy_mode)
        _copy_radarr_items(conn, grouped_routes["radarr"], dry_run=dry_run, legacy_mode=legacy_mode)
    finally:
        conn.close()


def _resolve_restore_destination(rel_path: Path, routes: List[Dict[str, str]]) -> Tuple[Path, Path]:
    prefix_to_source = {prefix: source for source, prefix in SOURCE_PREFIXES.items()}
    flow_subdirs = {str(route.get("input_subdir", "")).strip() for route in routes if route.get("input_subdir")}
    parts = rel_path.parts

    if len(parts) >= 2 and parts[0] in flow_subdirs and parts[1] in prefix_to_source:
        source = prefix_to_source[parts[1]]
        relative_to_library = Path(*parts[2:]) if len(parts) > 2 else Path()
    elif len(parts) >= 1 and parts[0] in prefix_to_source:
        source = prefix_to_source[parts[0]]
        relative_to_library = Path(*parts[1:]) if len(parts) > 1 else Path()
    else:
        source = "sonarr"
        relative_to_library = rel_path

    library_base = BASE_DIR if source == "sonarr" else RADARR_LOCAL_MOUNT_BASE_PATH
    return library_base, relative_to_library


def move_tdarr_output_back(dry_run=False):
    _progress_begin("restore_outputs", action="scanning")
    if not TDARR_OUTPUT_DIR.exists():
        logger.info("Tdarr output dir does not exist: %s", TDARR_OUTPUT_DIR)
        _progress_total(0, action="skipped", message="Tdarr output directory does not exist.")
        return

    runtime_settings, routes, _ = load_effective_routes()
    disabled_input_subdirs = _disabled_route_input_subdirs(runtime_settings)
    if disabled_input_subdirs:
        logger.info(
            "RESTORE: skipping disabled-tag subdir(s): %s",
            ", ".join(sorted(disabled_input_subdirs)),
        )
    logger.info("RESTORE: scanning %s", TDARR_OUTPUT_DIR)
    output_files = [path for path in TDARR_OUTPUT_DIR.rglob("*") if not path.is_dir()]
    _progress_total(len(output_files), action="restoring", message=f"Restoring {len(output_files)} output file(s).")
    for out_path in output_files:
        try:
            rel = out_path.relative_to(TDARR_OUTPUT_DIR)
        except ValueError:
            logger.warning("RESTORE: unexpected file outside output dir: %s", out_path)
            _progress_advance(action="skipped_outside_output", path=out_path, skipped=True)
            continue
        if rel.parts and rel.parts[0] in disabled_input_subdirs:
            logger.info("RESTORE: skip output under disabled-tag subdir %s: %s", rel.parts[0], out_path)
            _progress_advance(action="skipped_disabled_route", path=out_path, skipped=True)
            continue

        library_base, relative_to_library = _resolve_restore_destination(rel, routes)
        if str(relative_to_library) in {"", "."}:
            logger.warning("RESTORE: skipped malformed output path %s", out_path)
            _progress_advance(action="skipped_malformed_path", path=out_path, skipped=True)
            continue
        dest = library_base.joinpath(relative_to_library)
        if dry_run:
            logger.info("[RESTORE DRY] %s -> %s", out_path, dest)
            _progress_advance(action="dry_run_restore", path=out_path, destination=dest)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)

        # If destination exists, archive original NOW (rename + optional move + touch)
        if dest.exists():
            archive_original_before_restore(dest, library_base)

        logger.info("RESTORE: move transcoded %s -> %s", out_path, dest)
        try:
            shutil.move(str(out_path), str(dest))
            _progress_advance(action="restored", path=out_path, destination=dest)
        except Exception as e:
            _progress_advance(action="failed", path=out_path, destination=dest, message=str(e), failed=True)
            report_error_and_exit(f"Failed to move restored file {out_path} -> {dest}", e)

# -------------------- Interactive Picker --------------------
def _load_processed_cache() -> Dict[str, int]:
    """Return {abs_path: processed_at} from SQLite."""
    cache: Dict[str, int] = {}
    if not STATE_DB_FILE.exists():
        return cache
    conn = sqlite3.connect(STATE_DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute("SELECT file_path, processed_at FROM processed_files")
        for p, ts in cur.fetchall():
            cache[p] = ts or 0
    finally:
        conn.close()
    return cache

def _series_status(series: Dict, processed_cache: Dict[str, int]) -> Tuple[int, int, Optional[int]]:
    """Return (processed_count, total, last_ts) for a series."""
    series_id = series.get("id")
    eps = get_episode_files_for_series(series_id)
    total = 0
    processed = 0
    last_ts: Optional[int] = None
    for ef in eps:
        path = ef.get("path") or ef.get("relativePath")
        if not path:
            continue
        src = translate_sonarr_path(path)
        if not src.exists():
            continue
        total += 1
        key = str(src.resolve())
        ts = processed_cache.get(key)
        if ts is not None:
            processed += 1
            if (last_ts or 0) < ts:
                last_ts = ts
    return processed, total, last_ts

def _status_rank(processed: int, total: int) -> int:
    """0 = unprocessed, 1 = partial, 2 = full"""
    if processed <= 0:
        return 0
    if processed < total:
        return 1
    return 2

def _print_series_menu(series_list: List[Dict], processed_cache: Dict[str, int], filter_term: Optional[str] = None):
    print("\nLegend: ✓ fully processed   ◐ partially processed   ○ not processed")
    # apply filter (case-insensitive substring match on title)
    if filter_term:
        fl = [s for s in series_list if filter_term in (s.get("title", "").lower())]
    else:
        fl = list(series_list)

    # compute status for current filtered list
    decorated = []
    for s in fl:
        p, t, last = _series_status(s, processed_cache)
        decorated.append((s, p, t, last, _status_rank(p, t)))

    # sort: unprocessed first (rank asc), then title
    decorated.sort(key=lambda x: (x[4], (x[0].get("title") or "").lower()))

    print("\nAvailable series:")
    for idx, (s, p, t, last, rank) in enumerate(decorated, start=1):
        title = s.get("title") or f"<id {s.get('id')}>"
        status_str: str
        if rank == 2:
            status_str = f"✓ FULLY PROCESSED on {_fmt_ts(last)}"
        elif rank == 1:
            status_str = f"◐ {p}/{t} processed (last on {_fmt_ts(last)})"
        else:
            status_str = "○ not processed"
        print(f"  [{idx:>2}] {title} (id={s.get('id')}) — {t} eps  {status_str}")
    print()

    # Return the same decorated list so caller can map indexes back to IDs
    return decorated

def _parse_selection(expr: str, max_index: int) -> List[int]:
    """Parse '1,3,5-7' or 'all' → list of 1-based indexes."""
    expr = (expr or "").strip().lower()
    if expr in ("all", "a", "*"):
        return list(range(1, max_index + 1))
    selection: List[int] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                start = int(a)
                end = int(b)
                if start <= end:
                    for i in range(start, end + 1):
                        if 1 <= i <= max_index:
                            selection.append(i)
            continue
        if part.isdigit():
            i = int(part)
            if 1 <= i <= max_index:
                selection.append(i)
    # de-dup and keep order
    seen = set()
    result = []
    for i in selection:
        if i not in seen:
            seen.add(i)
            result.append(i)
    return result

def interactive_select_series() -> List[int]:
    """Fetch series list, show status-aware menu, prompt user, and return selected series IDs."""
    import sys as _sys
    if not _sys.stdin.isatty():
        print("--interactive requested but no TTY is attached; aborting.")
        raise SystemExit(2)

    try:
        series_all = sonarr_get("/series").json()
    except Exception as exc:
        report_error_and_exit("Failed to get series from Sonarr", exc)

    _, routes, _ = load_effective_routes()
    sonarr_routes = _group_routes_by_source(routes).get("sonarr", [])
    if sonarr_routes:
        tag_lookup = get_tag_lookup("sonarr")
        filtered = []
        for series in series_all:
            tags = _normalize_tag_ids(series.get("tags"))
            if _find_route_for_item(tags, sonarr_routes, tag_lookup) is not None:
                filtered.append(series)
        series_all = filtered

    if not series_all:
        print("No series found to process.")
        return []

    processed_cache = _load_processed_cache()
    filter_term: Optional[str] = None

    while True:
        decorated = _print_series_menu(series_all, processed_cache, filter_term)
        prompt = "Select (e.g., 1,3,5-7 | 'all' | /filter text | r/s to refresh | q to quit): "
        ans = input(prompt).strip()

        if not ans:
            print("No selection made. Try again or 'q' to quit.\n")
            continue

        low = ans.lower()
        if low in ("q", "quit", "exit"):
            print("Aborted by user.")
            raise SystemExit(0)

        if low in ("r", "s"):
            # refresh DB cache and recompute status
            processed_cache = _load_processed_cache()
            print("Refreshed processed status.\n")
            continue

        if ans.startswith("/"):
            term = ans[1:].strip().lower()
            if not term:
                print("Empty filter.\n")
                continue
            filter_term = term
            continue

        sel_idx = _parse_selection(ans, len(decorated))
        if not sel_idx:
            print("Invalid selection. Try again.\n")
            continue

        selected_ids = [decorated[i - 1][0].get("id") for i in sel_idx]
        names = ", ".join((decorated[i - 1][0].get("title") or str(decorated[i - 1][0].get("id"))) for i in sel_idx)
        confirm = input(f"Proceed with: {names}? (y/N): ").strip().lower()
        if confirm == "y":
            return selected_ids
        print("Cancelled. Starting over...\n")

# -------------------- CLI --------------------
def parse_args():
    p = argparse.ArgumentParser(description="Sync tagged media to Tdarr and restore outputs.")
    p.add_argument("--dry-run", action="store_true", help="Log intended actions without writing.")
    p.add_argument("--skip-restore", action="store_true", help="Skip restore phase.")
    p.add_argument("--interactive", action="store_true", help="Prompt to select which series to process before copying.")
    return p.parse_args()

def main():
    global PROGRESS
    args = parse_args()
    run_id = os.environ.get("TDARR_SYNC_RUN_ID") or uuid.uuid4().hex
    PROGRESS = ProgressReporter(SYNC_PROGRESS_FILE, run_id, dry_run=args.dry_run)
    PROGRESS.begin_phase("starting", action="starting")
    # CLI flag enables interactive; otherwise fall back to .env default
    use_interactive = args.interactive or ENV_INTERACTIVE
    if use_interactive and not sys.stdin.isatty():
        logger.warning("Interactive mode requested but no TTY detected; continuing without prompts.")
        use_interactive = False

    logger.info("Starting tdarr_sync (dry_run=%s, interactive=%s)", args.dry_run, use_interactive)
    try:
        selection = load_structured_selection_from_env()
        if selection is None and use_interactive:
            selected_ids = interactive_select_series()
            if selected_ids:
                selection = {series_id: None for series_id in selected_ids}

        process_media_to_tdarr(dry_run=args.dry_run, selection=selection)
        if not args.skip_restore:
            move_tdarr_output_back(dry_run=args.dry_run)
            if not args.dry_run:
                cleanup_old_originals()
    except SystemExit:
        if PROGRESS:
            PROGRESS.finish("failed", error="Sync exited before completion.")
        raise
    except Exception as e:
        if PROGRESS:
            PROGRESS.finish("failed", error=str(e))
        report_error_and_exit("Unhandled error in main()", e)
    if PROGRESS:
        PROGRESS.finish("succeeded", message="Finished tdarr_sync run.")
    logger.info("Finished tdarr_sync run.")

if __name__ == "__main__":
    main()
