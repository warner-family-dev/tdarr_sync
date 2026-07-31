from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from ipaddress import ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ALLOWED_SOURCES = {"sonarr", "radarr"}
MAX_WEB_AUTH_TRUSTED_NETWORKS = 32
DEFAULT_RUNTIME_SETTINGS_FILE = Path("/data/runtime_settings.json")
DEFAULT_TDARR_ALLOWED_HOSTS = (
    "tdarr",
    "localhost",
    "127.0.0.1",
    "::1",
)
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
logger = logging.getLogger(__name__)


def settings_path_from_env() -> Path:
    return Path(os.getenv("RUNTIME_SETTINGS_FILE", str(DEFAULT_RUNTIME_SETTINGS_FILE)))


def default_runtime_settings() -> dict[str, Any]:
    return {
        "tdarr_server_url": "",
        "tdarr_api_key": "",
        "show_job_error_count": False,
        "web_auth_bypass_enabled": False,
        "web_auth_trust_proxy_headers": False,
        "web_auth_trusted_networks": [],
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
        raise ValueError(
            "input_subdir may only include letters, numbers, dot, underscore, and hyphen."
        )
    return value


def _normalize_web_auth_trusted_networks(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise TypeError("web_auth_trusted_networks must be a list.")
    if len(raw_value) > MAX_WEB_AUTH_TRUSTED_NETWORKS:
        raise ValueError(
            f"web_auth_trusted_networks may contain at most {MAX_WEB_AUTH_TRUSTED_NETWORKS} entries."
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_network in raw_value:
        value = str(raw_network).strip()
        if not value or "%" in value:
            raise ValueError("Trusted networks must be valid IPv4 or IPv6 CIDRs.")
        try:
            network = ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid trusted network CIDR: {value}") from exc
        canonical = network.with_prefixlen
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return normalized


def _tdarr_allowed_hosts() -> set[str]:
    raw = os.getenv("TDARR_ALLOWED_HOSTS")
    if raw is None:
        return set(DEFAULT_TDARR_ALLOWED_HOSTS)
    return {
        item.strip().casefold().rstrip(".")
        for item in raw.split(",")
        if item.strip()
    }


def _normalize_tdarr_server_url(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    if any(character.isspace() for character in value):
        raise ValueError("tdarr_server_url must not contain whitespace.")

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("tdarr_server_url is not a valid URL.") from exc

    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("tdarr_server_url must use http or https.")
    if not parsed.netloc or not hostname:
        raise ValueError("tdarr_server_url must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("tdarr_server_url must not include credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("tdarr_server_url must not include a query or fragment.")

    normalized_host = hostname.casefold().rstrip(".")
    candidates = {normalized_host}
    if port is not None:
        if ":" in normalized_host:
            candidates.add(f"[{normalized_host}]:{port}")
        else:
            candidates.add(f"{normalized_host}:{port}")

    allowed_hosts = _tdarr_allowed_hosts()
    if not candidates.intersection(allowed_hosts):
        raise ValueError(
            f"Tdarr host '{normalized_host}' is not in TDARR_ALLOWED_HOSTS."
        )

    return value.rstrip("/")


def normalize_runtime_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("Settings payload must be an object.")

    tdarr_server_url = _normalize_tdarr_server_url(
        payload.get("tdarr_server_url", "")
    )
    tdarr_api_key = str(payload.get("tdarr_api_key", "")).strip()
    show_job_error_count = bool(payload.get("show_job_error_count", False))
    web_auth_bypass_enabled = bool(
        payload.get("web_auth_bypass_enabled", False)
    )
    web_auth_trust_proxy_headers = bool(
        payload.get("web_auth_trust_proxy_headers", False)
    )
    web_auth_trusted_networks = _normalize_web_auth_trusted_networks(
        payload.get("web_auth_trusted_networks", [])
    )
    if web_auth_bypass_enabled and not web_auth_trust_proxy_headers:
        raise ValueError(
            "Trusted-network login bypass requires trusted proxy headers."
        )
    if web_auth_bypass_enabled and not web_auth_trusted_networks:
        raise ValueError(
            "Trusted-network login bypass requires at least one trusted CIDR."
        )

    routes_raw = payload.get("routes", [])
    if routes_raw is None:
        routes_raw = []
    if not isinstance(routes_raw, list):
        raise TypeError("routes must be a list.")

    normalized_routes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for idx, route in enumerate(routes_raw):
        if not isinstance(route, dict):
            raise TypeError(f"Route #{idx + 1} must be an object.")

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
        "show_job_error_count": show_job_error_count,
        "web_auth_bypass_enabled": web_auth_bypass_enabled,
        "web_auth_trust_proxy_headers": web_auth_trust_proxy_headers,
        "web_auth_trusted_networks": web_auth_trusted_networks,
        "routes": normalized_routes,
    }


def load_runtime_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or settings_path_from_env()
    if not settings_path.exists():
        return default_runtime_settings()

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Unable to read runtime settings from %s: %s", settings_path, exc
        )
        return default_runtime_settings()

    if not isinstance(raw, dict):
        logger.warning(
            "Runtime settings in %s are not a JSON object; using defaults.",
            settings_path,
        )
        return default_runtime_settings()

    try:
        return normalize_runtime_settings_payload(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Runtime settings in %s are invalid: %s", settings_path, exc)
        return default_runtime_settings()


def save_runtime_settings(
    payload: dict[str, Any], path: Path | None = None
) -> dict[str, Any]:
    settings_path = path or settings_path_from_env()
    normalized = normalize_runtime_settings_payload(payload)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=".runtime_settings_", suffix=".json", dir=str(settings_path.parent)
    )
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
