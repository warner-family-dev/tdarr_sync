from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from runtime_settings import load_runtime_settings


JOB_ERROR_CACHE_TTL_SECONDS = 60
_JOB_ERROR_COUNT_CACHE: Dict[str, Tuple[float, Optional[int]]] = {}


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


def _first_bool(item: Dict[str, Any], keys: set[str]) -> bool:
    for key, value in item.items():
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized not in keys:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    return False


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


def _records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if {"statusCode", "error", "message", "code"}.intersection(payload):
            return []
        return [item for item in payload.values() if isinstance(item, dict)]
    return []


def _status_values(item: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key, value in item.items():
        normalized = key.lower().replace("_", "").replace("-", "")
        if normalized not in {
            "healthcheck",
            "transcodedecisionmaker",
            "status",
            "state",
            "stage",
            "error",
            "reason",
        }:
            continue
        if value is not None:
            values.append(str(value).strip().lower())
    return [value for value in values if value]


def _has_error_status(item: Dict[str, Any]) -> bool:
    return any("error" in value or "fail" in value for value in _status_values(item))


def _has_queued_status(item: Dict[str, Any]) -> bool:
    return any("queued" in value or "queue" in value for value in _status_values(item))


def _file_queue_count(file_payload: Any) -> Optional[int]:
    records = _records_from_payload(file_payload)
    if not records:
        return None
    return sum(1 for item in records if _has_queued_status(item))


def _file_error_count(file_payload: Any) -> Optional[int]:
    records = _records_from_payload(file_payload)
    if not records:
        return None
    return sum(1 for item in records if _has_error_status(item))


def _job_error_count(jobs_payload: Any) -> Optional[int]:
    records = _records_from_payload(jobs_payload)
    if not records:
        return None
    return sum(1 for item in records if _has_error_status(item))


def _first_non_none(*values: Optional[int]) -> Optional[int]:
    for value in values:
        if value is not None:
            return value
    return None


def _node_items(payload: Any) -> List[Tuple[str, Dict[str, Any]]]:
    if not isinstance(payload, dict):
        return []

    container: Any = payload.get("nodes", payload)
    if isinstance(container, list):
        return [
            (_first_string(item, {"id", "nodeid", "_id"}) or str(index + 1), item)
            for index, item in enumerate(container)
            if isinstance(item, dict)
        ]
    if isinstance(container, dict):
        nodes = []
        for key, item in container.items():
            if not isinstance(item, dict):
                continue
            if not any(field in item for field in ("nodeName", "nodePaused", "workerLimits", "workers")):
                continue
            nodes.append((str(key), item))
        return nodes
    return []


def _active_status(status: str) -> bool:
    value = status.strip().lower()
    if not value:
        return False
    inactive = {"good", "idle", "ready", "online", "connected", "unknown", "available", "inactive"}
    if value in inactive:
        return False
    active_tokens = (
        "running",
        "transcod",
        "health",
        "process",
        "ffmpeg",
        "handbrake",
        "mkvpropedit",
        "copy",
        "scan",
        "work",
    )
    return any(token in value for token in active_tokens)


def _worker_has_active_work(worker: Dict[str, Any]) -> bool:
    if worker.get("file") or worker.get("title"):
        return True
    progress = worker.get("progress")
    if isinstance(progress, (int, float)) and progress < 100:
        return True
    return _active_status(str(worker.get("status") or ""))


def _worker_from_item(
    item: Dict[str, Any],
    *,
    worker_id: str,
    node_id: str,
    node_name: str,
) -> Optional[Dict[str, Any]]:
    status = _first_string(item, {"status", "state", "stage", "workerstage", "process", "activity"})
    file_path = (
        _first_string(
            item,
            {
                "file",
                "filepath",
                "currentfile",
                "currentfilepath",
                "sourcepath",
                "sourcefile",
                "inputfile",
                "originalfile",
                "workingfile",
            },
        )
        or None
    )
    title = _first_string(item, {"title", "filename", "filebasename", "basename"}) or None
    progress = _first_progress(item)
    eta_seconds = _first_eta(item)
    name = _first_string(item, {"name", "workername"})
    worker = {
        "id": _first_string(item, {"id", "workerid", "worker"}) or worker_id,
        "name": name,
        "node": node_name or node_id,
        "node_id": node_id,
        "status": status,
        "file": file_path,
        "title": title,
        "progress": progress,
        "eta_seconds": eta_seconds,
    }
    return worker if _worker_has_active_work(worker) else None


def _candidate_worker_items(value: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, dict):
                yield str(key), child
                yield from _candidate_worker_items(child)
            elif isinstance(child, list):
                yield from _candidate_worker_items(child)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, dict):
                yield str(index + 1), child
                yield from _candidate_worker_items(child)


def _workers_for_node(node_id: str, node: Dict[str, Any]) -> List[Dict[str, Any]]:
    node_name = _first_string(node, {"nodename", "name"}) or node_id
    workers_payload = node.get("workers")
    if not workers_payload:
        return []

    workers: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for worker_id, item in _candidate_worker_items(workers_payload):
        worker = _worker_from_item(item, worker_id=worker_id, node_id=node_id, node_name=node_name)
        if not worker:
            continue
        fingerprint = "|".join(
            [
                str(worker.get("id") or ""),
                str(worker.get("node_id") or ""),
                str(worker.get("file") or ""),
                str(worker.get("title") or ""),
                str(worker.get("status") or ""),
            ]
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        workers.append(worker)
    return workers


def _worker_limit(node: Dict[str, Any]) -> int:
    limits = node.get("workerLimits")
    if not isinstance(limits, dict):
        return 0
    total = 0
    for key, value in limits.items():
        if "transcode" not in str(key).lower():
            continue
        try:
            total += max(0, int(value))
        except (TypeError, ValueError):
            continue
    return total


def _extract_nodes(nodes_payload: Any) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for fallback_id, node in _node_items(nodes_payload):
        node_id = _first_string(node, {"id", "nodeid", "_id"}) or fallback_id
        name = _first_string(node, {"nodename", "name"}) or node_id
        workers = _workers_for_node(node_id, node)
        nodes.append(
            {
                "id": node_id,
                "name": name,
                "address": _first_string(node, {"remoteaddress", "address", "host"}),
                "paused": _first_bool(node, {"nodepaused", "paused"}),
                "worker_limit": _worker_limit(node),
                "active_worker_count": len(workers),
                "workers": workers,
            }
        )
    return nodes


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

    def _fetch_collection(self, collection: str) -> Any:
        return self._request_json(
            "POST",
            "/api/v2/cruddb",
            json={"data": {"collection": collection, "mode": "getAll"}},
        )

    def _fetch_job_error_count(self) -> Optional[int]:
        now = time.monotonic()
        cached = _JOB_ERROR_COUNT_CACHE.get(self.server_url)
        if cached and now - cached[0] < JOB_ERROR_CACHE_TTL_SECONDS:
            return cached[1]

        try:
            jobs_payload = self._fetch_collection("JobsJSONDB")
        except Exception:
            return None

        count = _job_error_count(jobs_payload)
        if count is not None:
            _JOB_ERROR_COUNT_CACHE[self.server_url] = (now, count)
        return count

    def fetch_status(self) -> Dict[str, Any]:
        status_payload: Any = {}
        nodes_payload: Any = {}
        stats_payload: Any = {}
        file_payload: Any = {}

        try:
            status_payload = self._request_json("GET", "/api/v2/status")
        except Exception as exc:
            raise RuntimeError(f"Tdarr status request failed: {exc}") from exc

        try:
            nodes_payload = self._request_json("GET", "/api/v2/get-nodes")
        except Exception as exc:
            nodes_payload = {"_tdarr_sync_warning": f"nodes: {exc}"}

        try:
            stats_payload = self._fetch_collection("StatisticsJSONDB")
        except Exception:
            stats_payload = {}

        try:
            file_payload = self._fetch_collection("FileJSONDB")
        except Exception:
            file_payload = {}

        inferred_queue_count = _file_queue_count(file_payload)
        inferred_error_count = _file_error_count(file_payload)
        job_error_count = self._fetch_job_error_count()
        nodes = _extract_nodes(nodes_payload)
        workers = [worker for node in nodes for worker in node["workers"]]
        return {
            "configured": True,
            "reachable": True,
            "server_url": self.server_url,
            "error": nodes_payload.get("_tdarr_sync_warning") if isinstance(nodes_payload, dict) else None,
            "queue_count": _first_non_none(
                inferred_queue_count,
                _first_number(
                    [status_payload, stats_payload],
                    {"queue", "queued", "queuecount", "queuedcount", "transcodequeue", "transcodequeuecount", "dbqueue"},
                ),
            ),
            "error_count": _first_non_none(
                inferred_error_count,
                _first_number(
                    [status_payload, stats_payload],
                    {"error", "errors", "errorcount", "errored", "failed", "failedcount"},
                ),
            ),
            "job_error_count": job_error_count,
            "active_worker_count": len(workers),
            "workers": workers,
            "nodes": nodes,
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
            "job_error_count": None,
            "active_worker_count": 0,
            "workers": [],
            "nodes": [],
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
            "job_error_count": None,
            "active_worker_count": 0,
            "workers": [],
            "nodes": [],
        }
