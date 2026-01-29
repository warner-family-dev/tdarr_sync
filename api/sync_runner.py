import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Sequence


class SyncAlreadyRunningError(RuntimeError):
    pass


class SyncRunner:
    def __init__(self, script_path: Path, python_executable: str, env: Optional[dict] = None):
        self._script_path = script_path
        self._python_executable = python_executable
        self._env = env or os.environ.copy()
        self._lock = threading.Lock()
        self._running = False
        self._last_started_at: Optional[float] = None
        self._last_finished_at: Optional[float] = None
        self._last_exit_code: Optional[int] = None
        self._last_error: Optional[str] = None

    def trigger(self, dry_run: bool = False, selection: Optional[Sequence[dict]] = None) -> None:
        with self._lock:
            if self._running:
                raise SyncAlreadyRunningError("Sync is already in progress")
            self._running = True
            self._last_started_at = time.time()
            self._last_error = None

        thread = threading.Thread(target=self._run, args=(dry_run, selection), daemon=True)
        thread.start()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "last_started_at": int(self._last_started_at) if self._last_started_at else None,
                "last_finished_at": int(self._last_finished_at) if self._last_finished_at else None,
                "last_exit_code": self._last_exit_code,
                "last_error": self._last_error,
            }

    def _run(self, dry_run: bool, selection: Optional[Sequence[dict]]) -> None:
        cmd = [self._python_executable, str(self._script_path)]
        if dry_run:
            cmd.append("--dry-run")

        env = self._env.copy()
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
            self._last_exit_code = exit_code
        except FileNotFoundError as exc:
            self._last_error = f"Script not found: {exc}"
            self._last_exit_code = -1
        except Exception as exc:  # pragma: no cover
            self._last_error = str(exc)
            self._last_exit_code = -1
        finally:
            with self._lock:
                self._running = False
                self._last_finished_at = time.time()
