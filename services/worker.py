import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from logging.handlers import WatchedFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class _TZFormatter(logging.Formatter):
    def __init__(self, fmt: str, tz):
        super().__init__(fmt)
        self._tz = tz

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self._tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def _current_zone() -> ZoneInfo:
    tz_name = os.getenv("TZ", "UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


SYNC_DRY_RUN = os.getenv("SYNC_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
SYNC_SCRIPT_PATH = Path(os.getenv("SYNC_SCRIPT_PATH", "/app/tdarr_sync.py"))
SYNC_PYTHON_EXECUTABLE = os.getenv("SYNC_PYTHON_EXECUTABLE", sys.executable or "python")

LOG_FILE = os.getenv("LOG_FILE")


logger = logging.getLogger("tdarr_sync.worker")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = _TZFormatter("%(asctime)s %(levelname)s [WORKER] %(message)s", _current_zone())
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(formatter)
    logger.addHandler(_console_handler)

    if LOG_FILE:
        log_path = Path(LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_path.touch(exist_ok=True)
        except PermissionError:
            pass
        _file_handler = WatchedFileHandler(log_path)
        _file_handler.setFormatter(formatter)
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Tdarr Sync once.")
    parser.add_argument("--dry-run", action="store_true", help="Run Tdarr Sync in dry-run mode.")
    return parser.parse_args()


def main():
    args = _parse_args()
    dry_run = bool(args.dry_run or SYNC_DRY_RUN)

    logger.info("Tdarr Sync worker booting (manual run only)")
    exit_code = run_sync(dry_run)
    if exit_code != 0:
        logger.error("Sync failed with exit code %s", exit_code)
        raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Worker stopped via keyboard interrupt")
