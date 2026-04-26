from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from runtime_settings import load_runtime_settings


def _walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_number(payload: Any, keys: set[str]) -> Optional[int]:
    for item in _walk_dicts(payload):
        for key, value in item.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized in keys:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    return None


def _first_string(item: Dict[str, Any], keys: set[str]) -> str:
    for key, value in item.items():
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized in keys and value is not None:
            return str(value)
    return ""


def _first_progress(item: Dict[str, Any]) -> Optional[float]:
    for key, value in item.items():
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized not in {"progress", "percent", "percentage", "percentcomplete", "transcodepercent"}:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number <= 1:
            number *= 100
        return max(0.0, min(100.0, round(number, 1)))
    return None


def _first_eta(item: Dict[str, Any]) -> Optional[int]:
    for key, value in item.items():
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized not in {"eta", "etaseconds", "remainingseconds", "timeleftseconds"}:
            continue
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    return None


def _looks_like_worker(item: Dict[str, Any]) -> bool:
    keys = {key.lower().replace("_", "").replace("-", "") for key in item}
    worker_keys = {"worker", "workerid", "workername", "nodeid", "nodename", "currentfile", "file", "status"}
    progress_keys = {"progress", "percent", "percentage", "transcodepercent"}
    return bool(keys & worker_keys) and bool(keys & (progress_keys | {"currentfile", "file", "status"}))


def _extract_workers(*payloads: Any) -> List[Dict[str, Any]]:
    workers: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        for item in _walk_dicts(payload):
            if not _looks_like_worker(item):
                continue
            worker_id = _first_string(item, {"id", "workerid", "worker"}) or str(len(workers) + 1)
            name = _first_string(item, {"name", "workername"})
            node = _first_string(item, {"node", "nodeid", "nodename"})
            status = _first_string(item, {"status", "state", "stage", "workerstage"})
            file_path = _first_string(item, {"file", "filepath", "currentfile", "currentfilepath", "sourcepath"}) or None
            title = _first_string(item, {"title", "filename", "filebasename"}) or None
            progress = _first_progress(item)
            eta_seconds = _first_eta(item)

            fingerprint = "|".join([worker_id, name, node, file_path or "", title or ""])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if not any([status, file_path, title, progress is not None]):
                continue
            workers.append(
                {
                    "id": worker_id,
                    "name": name,
                    "node": node,
                    "status": status,
                    "file": file_path,
                    "title": title,
                    "progress": progress,
                    "eta_seconds": eta_seconds,
                }
            )
    return workers[:20]


class TdarrClient:
    def __init__(self, server_url: str, api_key: str = "", timeout: int = 4):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"x-api-key": api_key} if api_key else {}

    def _request_json(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.server_url}{path}"
        response = requests.request(method, url, headers=self.headers, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def fetch_status(self) -> Dict[str, Any]:
        errors: List[str] = []
        status_payload: Any = {}
        nodes_payload: Any = {}
        stats_payload: Any = {}

        try:
            status_payload = self._request_json("GET", "/api/v2/status")
        except Exception as exc:
            raise RuntimeError(f"Tdarr status request failed: {exc}") from exc

        try:
            nodes_payload = self._request_json("GET", "/api/v2/get-nodes")
        except Exception as exc:
            errors.append(f"nodes: {exc}")

        try:
            stats_payload = self._request_json(
                "POST",
                "/api/v2/cruddb",
                json={"data": {"collection": "StatisticsJSONDB", "mode": "get"}},
            )
        except Exception as exc:
            errors.append(f"stats: {exc}")

        workers = _extract_workers(status_payload, nodes_payload)
        return {
            "configured": True,
            "reachable": True,
            "server_url": self.server_url,
            "error": "; ".join(errors) if errors else None,
            "queue_count": _first_number(
                [status_payload, stats_payload],
                {"queue", "queued", "queuecount", "queuedcount", "transcodequeue", "transcodequeuecount"},
            ),
            "error_count": _first_number(
                [status_payload, stats_payload],
                {"error", "errors", "errorcount", "errored", "failed", "failedcount"},
            ),
            "active_worker_count": len(workers),
            "workers": workers,
        }


def fetch_tdarr_status(runtime_settings_file: Path) -> Dict[str, Any]:
    settings = load_runtime_settings(runtime_settings_file)
    server_url = str(settings.get("tdarr_server_url", "")).strip()
    api_key = str(settings.get("tdarr_api_key", "")).strip()

    if not server_url:
        return {
            "configured": False,
            "reachable": False,
            "server_url": "",
            "error": "Tdarr server URL is not configured.",
            "queue_count": None,
            "error_count": None,
            "active_worker_count": 0,
            "workers": [],
        }

    try:
        return TdarrClient(server_url, api_key).fetch_status()
    except Exception as exc:
        return {
            "configured": True,
            "reachable": False,
            "server_url": server_url,
            "error": str(exc),
            "queue_count": None,
            "error_count": None,
            "active_worker_count": 0,
            "workers": [],
        }
