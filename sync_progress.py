from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
ETA_MIN_COMPLETED = 3
ETA_MIN_ELAPSED_SECONDS = 10


def progress_path_from_env(default: str = "/data/sync_progress.json") -> Path:
    return Path(os.getenv("SYNC_PROGRESS_FILE", default))


def _now() -> int:
    return int(time.time())


def calculate_eta_seconds(
    completed_items: int,
    total_items: Optional[int],
    phase_started_at: Optional[int],
    *,
    now: Optional[int] = None,
) -> Optional[int]:
    if not total_items or total_items <= 0:
        return None
    if completed_items >= total_items:
        return 0
    if completed_items < ETA_MIN_COMPLETED:
        return None
    if not phase_started_at:
        return None

    current = now if now is not None else _now()
    elapsed = max(0, current - int(phase_started_at))
    if elapsed < ETA_MIN_ELAPSED_SECONDS:
        return None

    rate = completed_items / elapsed if elapsed > 0 else 0
    if rate <= 0:
        return None
    remaining = max(0, total_items - completed_items)
    return int(round(remaining / rate))


def calculate_percent(completed_items: int, total_items: Optional[int]) -> Optional[float]:
    if not total_items or total_items <= 0:
        return None
    bounded = min(max(completed_items, 0), total_items)
    return round((bounded / total_items) * 100, 1)


def build_progress_snapshot(
    *,
    run_id: str,
    state: str,
    phase: str,
    action: str = "",
    dry_run: bool = False,
    source: Optional[str] = None,
    title: Optional[str] = None,
    path: Optional[str] = None,
    destination: Optional[str] = None,
    message: Optional[str] = None,
    completed_items: int = 0,
    total_items: Optional[int] = None,
    skipped_items: int = 0,
    failed_items: int = 0,
    started_at: Optional[int] = None,
    phase_started_at: Optional[int] = None,
    updated_at: Optional[int] = None,
    finished_at: Optional[int] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    current = updated_at if updated_at is not None else _now()
    start = started_at if started_at is not None else current
    phase_start = phase_started_at if phase_started_at is not None else current

    snapshot: Dict[str, Any] = {
        "run_id": run_id,
        "state": state,
        "phase": phase,
        "action": action,
        "dry_run": dry_run,
        "source": source,
        "title": title,
        "path": path,
        "destination": destination,
        "message": message,
        "completed_items": int(completed_items),
        "total_items": total_items,
        "skipped_items": int(skipped_items),
        "failed_items": int(failed_items),
        "percent": calculate_percent(int(completed_items), total_items),
        "eta_seconds": calculate_eta_seconds(int(completed_items), total_items, phase_start, now=current),
        "started_at": int(start),
        "phase_started_at": int(phase_start),
        "updated_at": int(current),
        "finished_at": finished_at,
        "elapsed_seconds": max(0, int(current) - int(start)),
        "error": error,
    }
    return snapshot


def write_progress_file(path: Path, snapshot: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".sync_progress_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def read_progress_file(path: Path, *, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    if not raw.get("run_id") or not raw.get("state") or not raw.get("phase"):
        return None
    if max_age_seconds is not None:
        updated_at = raw.get("updated_at")
        try:
            age = _now() - int(updated_at)
        except Exception:
            return None
        if age > max_age_seconds:
            return None
    return raw


class ProgressReporter:
    def __init__(self, path: Path, run_id: str, *, dry_run: bool = False):
        self.path = path
        self.run_id = run_id
        self.dry_run = dry_run
        self.started_at = _now()
        self.phase_started_at = self.started_at
        self.phase = "starting"
        self.action = "starting"
        self.completed_items = 0
        self.total_items: Optional[int] = None
        self.skipped_items = 0
        self.failed_items = 0

    def begin_phase(self, phase: str, *, total_items: Optional[int] = None, action: str = "planning") -> None:
        self.phase = phase
        self.action = action
        self.phase_started_at = _now()
        self.completed_items = 0
        self.total_items = total_items
        self.skipped_items = 0
        self.failed_items = 0
        self.emit()

    def set_total(self, total_items: int, *, action: str = "processing", message: Optional[str] = None) -> None:
        self.total_items = total_items
        self.action = action
        self.emit(message=message)

    def advance(
        self,
        *,
        action: str,
        source: Optional[str] = None,
        title: Optional[str] = None,
        path: Optional[str] = None,
        destination: Optional[str] = None,
        message: Optional[str] = None,
        completed_delta: int = 1,
        skipped_delta: int = 0,
        failed_delta: int = 0,
    ) -> None:
        self.action = action
        self.completed_items += completed_delta
        self.skipped_items += skipped_delta
        self.failed_items += failed_delta
        self.emit(source=source, title=title, path=path, destination=destination, message=message)

    def emit(
        self,
        *,
        state: str = "running",
        source: Optional[str] = None,
        title: Optional[str] = None,
        path: Optional[str] = None,
        destination: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        finished_at: Optional[int] = None,
    ) -> None:
        snapshot = build_progress_snapshot(
            run_id=self.run_id,
            state=state,
            phase=self.phase,
            action=self.action,
            dry_run=self.dry_run,
            source=source,
            title=title,
            path=path,
            destination=destination,
            message=message,
            completed_items=self.completed_items,
            total_items=self.total_items,
            skipped_items=self.skipped_items,
            failed_items=self.failed_items,
            started_at=self.started_at,
            phase_started_at=self.phase_started_at,
            finished_at=finished_at,
            error=error,
        )
        write_progress_file(self.path, snapshot)

    def finish(self, state: str = "succeeded", *, message: Optional[str] = None, error: Optional[str] = None) -> None:
        finished_at = _now()
        self.emit(state=state, message=message, error=error, finished_at=finished_at)


def mark_progress_terminal(path: Path, run_id: str, state: str, *, error: Optional[str] = None) -> None:
    current = read_progress_file(path)
    if current and current.get("run_id") == run_id and current.get("state") in TERMINAL_STATES:
        return

    now = _now()
    if current and current.get("run_id") == run_id:
        current.update(
            {
                "state": state,
                "updated_at": now,
                "finished_at": now,
                "elapsed_seconds": max(0, now - int(current.get("started_at") or now)),
                "eta_seconds": 0 if state == "succeeded" else None,
                "error": error,
            }
        )
        if state == "succeeded" and current.get("total_items"):
            current["completed_items"] = current.get("total_items")
            current["percent"] = 100.0
        write_progress_file(path, current)
        return

    write_progress_file(
        path,
        build_progress_snapshot(
            run_id=run_id,
            state=state,
            phase="complete" if state == "succeeded" else "failed",
            action=state,
            started_at=now,
            phase_started_at=now,
            updated_at=now,
            finished_at=now,
            error=error,
        ),
    )
