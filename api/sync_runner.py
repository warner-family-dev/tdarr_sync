import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Sequence

from sync_progress import build_progress_snapshot, mark_progress_terminal, write_progress_file


class SyncAlreadyRunningError(RuntimeError):
    pass


class SyncRunner:
    def __init__(self, script_path: Path, python_executable: str, progress_file: Path, env: Optional[dict] = None):
        self._script_path = script_path
        self._python_executable = python_executable
        self._progress_file = progress_file
        self._env = env or os.environ.copy()
        self._lock = threading.Lock()
        self._running = False
        self._last_started_at: Optional[float] = None
        self._last_finished_at: Optional[float] = None
        self._last_exit_code: Optional[int] = None
        self._last_error: Optional[str] = None
        self._run_id: Optional[str] = None

    def trigger(self, dry_run: bool = False, selection: Optional[Sequence[dict]] = None) -> None:
        with self._lock:
            if self._running:
                raise SyncAlreadyRunningError("Sync is already in progress")
            run_id = uuid.uuid4().hex
            self._running = True
            self._last_started_at = time.time()
            self._last_error = None
            self._run_id = run_id
            write_progress_file(
                self._progress_file,
                build_progress_snapshot(
                    run_id=run_id,
                    state="running",
                    phase="starting",
                    action="starting",
                    dry_run=dry_run,
                    message="Starting sync process.",
                    started_at=int(self._last_started_at),
                    phase_started_at=int(self._last_started_at),
                ),
            )

        thread = threading.Thread(target=self._run, args=(run_id, dry_run, selection), daemon=True)
        thread.start()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "last_started_at": int(self._last_started_at) if self._last_started_at else None,
                "last_finished_at": int(self._last_finished_at) if self._last_finished_at else None,
                "last_exit_code": self._last_exit_code,
                "last_error": self._last_error,
                "run_id": self._run_id,
            }

    def _run(self, run_id: str, dry_run: bool, selection: Optional[Sequence[dict]]) -> None:
        cmd = [self._python_executable, str(self._script_path)]
        if dry_run:
            cmd.append("--dry-run")

        env = self._env.copy()
        env["TDARR_SYNC_RUN_ID"] = run_id
        env["SYNC_PROGRESS_FILE"] = str(self._progress_file)
        if selection is not None:
            try:
                env["TDARR_SYNC_SELECTION"] = json.dumps(selection)
            except TypeError:
                env["TDARR_SYNC_SELECTION"] = "[]"
        elif "TDARR_SYNC_SELECTION" in env:
            env.pop("TDARR_SYNC_SELECTION", None)

        try:
            result = subprocess.run(cmd, check=False, env=env)
            exit_code = result.returncode
            if exit_code != 0:
                self._last_error = f"Sync exited with code {exit_code}"
                mark_progress_terminal(self._progress_file, run_id, "failed", error=self._last_error)
            else:
                mark_progress_terminal(self._progress_file, run_id, "succeeded")
            self._last_exit_code = exit_code
        except FileNotFoundError as exc:
            self._last_error = f"Script not found: {exc}"
            self._last_exit_code = -1
            mark_progress_terminal(self._progress_file, run_id, "failed", error=self._last_error)
        except Exception as exc:  # pragma: no cover
            self._last_error = str(exc)
            self._last_exit_code = -1
            mark_progress_terminal(self._progress_file, run_id, "failed", error=self._last_error)
        finally:
            with self._lock:
                self._running = False
                self._last_finished_at = time.time()
