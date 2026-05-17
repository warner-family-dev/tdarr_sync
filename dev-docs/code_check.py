#!/usr/bin/env python3
"""Run local Ruff and Pytest checks and log output with timestamps."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "tdarr_sync_build.log"
ENV_FILE = ROOT_DIR / ".env"


def load_env_tz() -> str:
    if not ENV_FILE.exists():
        return "UTC"
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("TZ="):
            return stripped.split("=", 1)[1].strip() or "UTC"
    return "UTC"


def get_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def timestamp(tz: ZoneInfo) -> str:
    return datetime.now(tz=tz).strftime("%Y-%m-%d %H:%M:%S")


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_log(line: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def log_command_header(command: str, tz: ZoneInfo) -> None:
    append_log(f"{timestamp(tz)} [BUILD] Running: {command}")


def log_stream(stream: str, tz: ZoneInfo) -> None:
    for raw_line in stream.splitlines():
        if raw_line.strip():
            append_log(f"{timestamp(tz)} [BUILD] {raw_line}")


def run_command(label: str, command: list[str], tz: ZoneInfo) -> int:
    log_command_header(" ".join(command), tz)
    print(f"Running {label}...", flush=True)
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    prefix = str(ROOT_DIR)
    if existing_path:
        env["PYTHONPATH"] = f"{prefix}{os.pathsep}{existing_path}"
    else:
        env["PYTHONPATH"] = prefix
    append_log(f"{timestamp(tz)} [BUILD] CWD={ROOT_DIR}")
    append_log(f"{timestamp(tz)} [BUILD] PYTHONPATH={env.get('PYTHONPATH', '')}")
    result = subprocess.run(command, cwd=ROOT_DIR, text=True, capture_output=True, env=env)
    if result.stdout:
        log_stream(result.stdout, tz)
    if result.stderr:
        log_stream(result.stderr, tz)
    if result.returncode == 0:
        print(f"PASS: {label}", flush=True)
    else:
        print(f"FAIL: {label} (exit code {result.returncode})", flush=True)
    return result.returncode


def main() -> int:
    tz_name = load_env_tz()
    tz = get_zone(tz_name)
    ensure_log_dir()
    append_log(
        f"{timestamp(tz)} [BUILD] Starting build check\n"
        f"{timestamp(tz)} [BUILD] =====================\n"
        f"{timestamp(tz)} [BUILD]  ____          _       ____ _               _    \n"
        f"{timestamp(tz)} [BUILD] / ___|___   __| | ___/ ___| |__   ___  ___| | __\n"
        f"{timestamp(tz)} [BUILD] | |   / _ \\ / _` |/ _ \\___ \\ '_ \\ / _ \\/ __| |/ /\n"
        f"{timestamp(tz)} [BUILD] | |__| (_) | (_| |  __/___) | | | |  __/ (__|   < \n"
        f"{timestamp(tz)} [BUILD]  \\____\\___/ \\__,_|\\___|____/|_| |_|\\___|\\___|_|\\_\\\n"
        f"{timestamp(tz)} [BUILD] ====================="
    )
    append_log(f"{timestamp(tz)} [BUILD] Local checks started (TZ={tz_name})")

    checks = [
        ("Ruff", ["pipx", "run", "ruff", "check", "."]),
        (
            "Pytest",
            [
                "pipx",
                "run",
                "--no-cache",
                "--pip-args",
                "-r requirements/base.txt",
                "pytest",
                "-q",
            ],
        ),
    ]

    exit_code = 0
    for label, command in checks:
        result = run_command(label, command, tz)
        if result != 0:
            exit_code = result
            append_log(f"{timestamp(tz)} [BUILD] Command failed with exit code {result}")

    status = "succeeded" if exit_code == 0 else "failed"
    append_log(f"{timestamp(tz)} [BUILD] Local checks {status}")
    append_log(f"{timestamp(tz)} [BUILD] Code check complete")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
