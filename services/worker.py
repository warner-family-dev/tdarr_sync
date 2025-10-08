import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "1800"))
SYNC_DRY_RUN = _bool_env("SYNC_DRY_RUN", False)
SYNC_ON_START = _bool_env("SYNC_ON_START", True)
SYNC_ERROR_BACKOFF_SECONDS = int(os.getenv("SYNC_ERROR_BACKOFF_SECONDS", "300"))
SYNC_SCRIPT_PATH = Path(os.getenv("SYNC_SCRIPT_PATH", "/app/tdarr_sync.py"))
SYNC_PYTHON_EXECUTABLE = os.getenv("SYNC_PYTHON_EXECUTABLE", sys.executable or "python")

LOG_FILE = os.getenv("LOG_FILE")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))


logger = logging.getLogger("tdarr_sync.worker")
logger.setLevel(logging.INFO)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_console_handler)

if LOG_FILE:
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_file_handler)


def run_sync(dry_run: bool = False) -> int:
    if not SYNC_SCRIPT_PATH.exists():
        logger.error("Sync script not found at %s", SYNC_SCRIPT_PATH)
        return 1

    cmd = [SYNC_PYTHON_EXECUTABLE, str(SYNC_SCRIPT_PATH)]
    if dry_run:
        cmd.append("--dry-run")

    logger.info("Starting Tdarr sync (%s)", "dry run" if dry_run else "live")
    process = subprocess.run(cmd, check=False)
    logger.info("Sync finished with code %s", process.returncode)
    return process.returncode


def _sleep(seconds: int):
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        logger.warning("Sleep interrupted: %s", exc)


def main():
    logger.info("Tdarr Sync worker booting")
    logger.info("Interval: %s seconds | Dry run: %s | On start: %s", SYNC_INTERVAL_SECONDS, SYNC_DRY_RUN, SYNC_ON_START)

    if SYNC_ON_START:
        exit_code = run_sync(SYNC_DRY_RUN)
        if exit_code != 0:
            logger.error("Initial sync failed; backing off for %s seconds", SYNC_ERROR_BACKOFF_SECONDS)
            _sleep(SYNC_ERROR_BACKOFF_SECONDS)

    if SYNC_INTERVAL_SECONDS <= 0:
        logger.info("SYNC_INTERVAL_SECONDS <= 0; exiting after initial run")
        return

    while True:
        logger.info("Sleeping for %s seconds before next sync", SYNC_INTERVAL_SECONDS)
        _sleep(SYNC_INTERVAL_SECONDS)
        exit_code = run_sync(SYNC_DRY_RUN)
        if exit_code != 0:
            logger.error("Sync failed; backing off for %s seconds", SYNC_ERROR_BACKOFF_SECONDS)
            _sleep(SYNC_ERROR_BACKOFF_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Worker stopped via keyboard interrupt")
