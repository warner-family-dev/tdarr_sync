from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BUILD_METADATA_FILE = "build-metadata.json"


def _clean_metadata_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    return "" if cleaned.lower() == "unknown" else cleaned


def _normalize_deployed_version(value: str) -> str:
    version = _clean_metadata_value(value)
    version = version.removeprefix("refs/heads/")
    version = version.removeprefix("dev/")
    return version


def _read_build_metadata(repo_root: Path) -> dict[str, str]:
    metadata_path = repo_root / BUILD_METADATA_FILE
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: cleaned
        for key in (
            "image_tag",
            "image_published_date",
            "git_version",
            "commit_date",
            "commit_sha",
        )
        if (cleaned := _clean_metadata_value(payload.get(key)))
    }


def _read_ref_sha(git_dir: Path, ref: str) -> str:
    ref_path = git_dir / ref
    if ref_path.exists():
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""

    packed_refs = git_dir / "packed-refs"
    if not packed_refs.exists():
        return ""

    try:
        lines = packed_refs.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return ""

    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith(("#", "^")):
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
        lines = [
            line.strip()
            for line in log_head.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError):
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
    except (OSError, UnicodeError):
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
        "git_version": _normalize_deployed_version(branch_name) or "unknown",
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
            "git_version": _normalize_deployed_version(
                _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            ),
            "commit_date": _run_git(["show", "-s", "--format=%cs", "HEAD"]),
            "commit_sha": _run_git(["rev-parse", "--short", "HEAD"]),
            "source": "git",
        }
    except (OSError, subprocess.SubprocessError):
        return None


def _build_version_payload(
    *,
    image_tag: str = "",
    image_published_date: str = "",
    git_version: str = "",
    commit_date: str = "",
    commit_sha: str = "",
    source: str,
) -> dict:
    display_version = _normalize_deployed_version(git_version) or image_tag or "unknown"
    display_date = commit_date or image_published_date or "unknown"
    return {
        "image_tag": image_tag or "unknown",
        "image_published_date": image_published_date or "unknown",
        "git_version": display_version,
        "commit_date": display_date,
        "commit_sha": commit_sha,
        "source": source,
    }


def resolve_build_version(repo_root: Path | None = None) -> dict:
    current_repo_root = repo_root or Path(__file__).resolve().parents[1]
    metadata = _read_build_metadata(current_repo_root)
    git_data = _resolve_build_version_from_git_command(
        current_repo_root
    ) or _resolve_build_version_from_git_files(current_repo_root)

    git_version = metadata.get("git_version", "")
    commit_date = metadata.get("commit_date", "")
    commit_sha = metadata.get("commit_sha", "")
    if git_data:
        git_version = git_version or git_data["git_version"]
        commit_date = commit_date or git_data["commit_date"]
        commit_sha = commit_sha or git_data["commit_sha"]

    if metadata:
        return _build_version_payload(
            image_tag=metadata.get("image_tag", ""),
            image_published_date=metadata.get("image_published_date", ""),
            git_version=git_version,
            commit_date=commit_date,
            commit_sha=commit_sha,
            source="image",
        )

    if git_data:
        return _build_version_payload(
            git_version=git_version,
            commit_date=commit_date,
            commit_sha=commit_sha,
            source="git",
        )

    return _build_version_payload(source="unknown")


__all__ = ["_resolve_build_version_from_git_files", "resolve_build_version"]
