from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _read_ref_sha(git_dir: Path, ref: str) -> str:
    ref_path = git_dir / ref
    if ref_path.exists():
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    packed_refs = git_dir / "packed-refs"
    if not packed_refs.exists():
        return ""

    try:
        lines = packed_refs.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#") or entry.startswith("^"):
            continue
        try:
            sha, name = entry.split(" ", 1)
        except ValueError:
            continue
        if name.strip() == ref:
            return sha.strip()
    return ""


def _read_commit_date_from_git_log(git_dir: Path) -> str:
    log_head = git_dir / "logs" / "HEAD"
    if not log_head.exists():
        return ""

    try:
        lines = [line.strip() for line in log_head.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return ""

    if not lines:
        return ""

    last_entry = lines[-1]
    metadata = last_entry.split("\t", 1)[0].strip()
    parts = metadata.split()
    if len(parts) < 2:
        return ""

    timestamp_raw = parts[-2]
    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return ""

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def _resolve_build_version_from_git_files(repo_root: Path) -> dict | None:
    git_dir = repo_root / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return None

    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None

    if not head:
        return None

    branch_name = "detached"
    full_sha = ""
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        if not ref:
            return None
        if ref.startswith("refs/heads/"):
            branch_name = ref[len("refs/heads/") :]
        elif ref.startswith("refs/"):
            branch_name = ref[len("refs/") :]
        else:
            branch_name = ref
        full_sha = _read_ref_sha(git_dir, ref)
    else:
        full_sha = head

    commit_date = _read_commit_date_from_git_log(git_dir)
    if not branch_name and not commit_date and not full_sha:
        return None

    return {
        "git_version": branch_name or "unknown",
        "commit_date": commit_date or "unknown",
        "commit_sha": full_sha[:7],
        "source": "git",
    }


def _resolve_build_version_from_git_command(repo_root: Path) -> dict | None:
    def _run_git(args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    try:
        return {
            "git_version": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
            "commit_date": _run_git(["show", "-s", "--format=%cs", "HEAD"]),
            "commit_sha": _run_git(["rev-parse", "--short", "HEAD"]),
            "source": "git",
        }
    except Exception:
        return None


def resolve_build_version(repo_root: Path | None = None) -> dict:
    env_version = os.getenv("APP_GIT_VERSION", "").strip()
    env_date = os.getenv("APP_GIT_COMMIT_DATE", "").strip()
    env_sha = os.getenv("APP_GIT_COMMIT_SHA", "").strip()
    if env_version and env_date:
        return {
            "git_version": env_version,
            "commit_date": env_date,
            "commit_sha": env_sha,
            "source": "env",
        }

    current_repo_root = repo_root or Path(__file__).resolve().parents[1]
    git_data = _resolve_build_version_from_git_command(current_repo_root) or _resolve_build_version_from_git_files(
        current_repo_root
    )
    if git_data:
        return {
            "git_version": env_version or git_data["git_version"] or "unknown",
            "commit_date": env_date or git_data["commit_date"] or "unknown",
            "commit_sha": env_sha or git_data["commit_sha"],
            "source": "env" if (env_version or env_date or env_sha) else git_data["source"],
        }

    return {
        "git_version": env_version or "unknown",
        "commit_date": env_date or "unknown",
        "commit_sha": env_sha or "",
        "source": "unknown",
    }


__all__ = ["resolve_build_version", "_resolve_build_version_from_git_files"]
