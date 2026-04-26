from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ALLOWED_SOURCES = {"sonarr", "radarr"}
DEFAULT_RUNTIME_SETTINGS_FILE = Path("/data/runtime_settings.json")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def settings_path_from_env() -> Path:
    return Path(os.getenv("RUNTIME_SETTINGS_FILE", str(DEFAULT_RUNTIME_SETTINGS_FILE)))


def default_runtime_settings() -> Dict[str, Any]:
    return {
        "tdarr_server_url": "",
        "tdarr_api_key": "",
        "routes": [],
    }


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "default-flow"


def _normalize_input_subdir(raw_value: Any, flow_name: str) -> str:
    if raw_value is None or str(raw_value).strip() == "":
        return _slugify(flow_name)

    value = str(raw_value).strip()
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError("input_subdir must be a single safe folder name.")
    if not _SAFE_SEGMENT_RE.fullmatch(value):
        raise ValueError("input_subdir may only include letters, numbers, dot, underscore, and hyphen.")
    return value


def normalize_runtime_settings_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Settings payload must be an object.")

    tdarr_server_url = str(payload.get("tdarr_server_url", "")).strip()
    tdarr_api_key = str(payload.get("tdarr_api_key", "")).strip()

    routes_raw = payload.get("routes", [])
    if routes_raw is None:
        routes_raw = []
    if not isinstance(routes_raw, list):
        raise ValueError("routes must be a list.")

    normalized_routes: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for idx, route in enumerate(routes_raw):
        if not isinstance(route, dict):
            raise ValueError(f"Route #{idx + 1} must be an object.")

        source = str(route.get("source", "")).strip().lower()
        if source not in ALLOWED_SOURCES:
            raise ValueError(f"Route #{idx + 1} has invalid source '{source}'.")

        tag = str(route.get("tag", "")).strip()
        if not tag:
            raise ValueError(f"Route #{idx + 1} requires a tag.")

        flow_name = str(route.get("flow_name", "")).strip()
        if not flow_name:
            raise ValueError(f"Route #{idx + 1} requires a flow_name.")

        dedupe_key = (source, tag.lower())
        if dedupe_key in seen:
            raise ValueError(f"Duplicate route for source '{source}' and tag '{tag}'.")
        seen.add(dedupe_key)

        input_subdir = _normalize_input_subdir(route.get("input_subdir"), flow_name)
        normalized_routes.append(
            {
                "source": source,
                "tag": tag,
                "flow_name": flow_name,
                "input_subdir": input_subdir,
            }
        )

    return {
        "tdarr_server_url": tdarr_server_url,
        "tdarr_api_key": tdarr_api_key,
        "routes": normalized_routes,
    }


def load_runtime_settings(path: Path | None = None) -> Dict[str, Any]:
    settings_path = path or settings_path_from_env()
    if not settings_path.exists():
        return default_runtime_settings()

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return default_runtime_settings()

    if not isinstance(raw, dict):
        return default_runtime_settings()

    try:
        return normalize_runtime_settings_payload(raw)
    except ValueError:
        return default_runtime_settings()


def save_runtime_settings(payload: Dict[str, Any], path: Path | None = None) -> Dict[str, Any]:
    settings_path = path or settings_path_from_env()
    normalized = normalize_runtime_settings_payload(payload)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix=".runtime_settings_", suffix=".json", dir=str(settings_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, settings_path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)

    return normalized
