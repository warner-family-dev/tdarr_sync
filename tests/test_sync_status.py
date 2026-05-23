import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("API_AUTH_TOKEN", "tdarr-sync-test-api-token")
os.environ.setdefault("STATE_DB_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test-state.db"))
os.environ.setdefault("LOG_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test.log"))

try:
    import pydantic  # noqa: F401
except Exception:
    pydantic_stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **data):
            for key, value in data.items():
                if key == "progress" and isinstance(value, dict):
                    value = sys.modules["api.schemas"].SyncProgress(**value)
                elif key == "tdarr" and isinstance(value, dict):
                    value = sys.modules["api.schemas"].TdarrStatus(**value)
                elif key == "workers" and isinstance(value, list):
                    value = [sys.modules["api.schemas"].TdarrWorkerStatus(**item) if isinstance(item, dict) else item for item in value]
                elif key == "nodes" and isinstance(value, list):
                    value = [sys.modules["api.schemas"].TdarrNodeStatus(**item) if isinstance(item, dict) else item for item in value]
                setattr(self, key, value)

        def model_dump(self):
            return dict(self.__dict__)

    def _field(default=None, default_factory=None, **_kwargs):
        if default_factory is not None:
            return default_factory()
        return default

    pydantic_stub.BaseModel = _BaseModel
    pydantic_stub.Field = _field
    sys.modules["pydantic"] = pydantic_stub

try:
    import fastapi  # noqa: F401
except Exception:
    fastapi_stub = types.ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            pass

        def middleware(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def on_event(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def put(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def delete(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    def _body(*args, **kwargs):
        return kwargs.get("default")

    def _query(*args, **kwargs):
        return kwargs.get("default")

    fastapi_stub.Body = _body
    fastapi_stub.FastAPI = _FastAPI
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Query = _query
    fastapi_stub.Request = object
    middleware_stub = types.ModuleType("fastapi.middleware")
    cors_stub = types.ModuleType("fastapi.middleware.cors")
    cors_stub.CORSMiddleware = object
    sys.modules["fastapi"] = fastapi_stub
    sys.modules["fastapi.middleware"] = middleware_stub
    sys.modules["fastapi.middleware.cors"] = cors_stub
    starlette_stub = types.ModuleType("starlette")
    responses_stub = types.ModuleType("starlette.responses")

    class _JSONResponse:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    responses_stub.JSONResponse = _JSONResponse
    sys.modules["starlette"] = starlette_stub
    sys.modules["starlette.responses"] = responses_stub

from api.main import sync_status  # noqa: E402
from api.tdarr_client import TdarrClient  # noqa: E402


class SyncStatusApiTests(unittest.TestCase):
    def test_sync_status_works_without_progress_file(self):
        with patch("api.main.runner.status") as mock_status, patch("api.main.read_progress_file", return_value=None), patch(
            "api.main.fetch_tdarr_status",
            return_value={
                "configured": False,
                "reachable": False,
                "server_url": "",
                "error": "Tdarr server URL is not configured.",
                "queue_count": None,
                "error_count": None,
                "job_error_count": None,
                "show_job_error_count": False,
                "active_worker_count": 0,
                "workers": [],
                "nodes": [],
            },
        ):
            mock_status.return_value = {
                "running": False,
                "last_started_at": None,
                "last_finished_at": None,
                "last_exit_code": None,
                "last_error": None,
            }
            payload = sync_status()
            self.assertFalse(payload.running)
            self.assertIsNone(payload.progress)
            self.assertFalse(payload.tdarr.configured)

    def test_sync_status_includes_progress(self):
        progress = {
            "run_id": "abc",
            "state": "running",
            "phase": "copy_sonarr",
            "action": "copied",
            "completed_items": 3,
            "total_items": 6,
            "skipped_items": 1,
            "failed_items": 0,
            "percent": 50.0,
            "eta_seconds": 30,
            "started_at": 100,
            "phase_started_at": 100,
            "updated_at": 120,
            "elapsed_seconds": 20,
        }
        with patch("api.main.runner.status") as mock_status, patch("api.main.read_progress_file", return_value=progress), patch(
            "api.main.fetch_tdarr_status",
            return_value={
                "configured": True,
                "reachable": False,
                "server_url": "http://tdarr:8266",
                "error": "connection failed",
                "queue_count": None,
                "error_count": None,
                "job_error_count": None,
                "show_job_error_count": False,
                "active_worker_count": 0,
                "workers": [],
                "nodes": [],
            },
        ):
            mock_status.return_value = {
                "running": True,
                "last_started_at": 100,
                "last_finished_at": None,
                "last_exit_code": None,
                "last_error": None,
            }
            payload = sync_status()
            self.assertTrue(payload.running)
            self.assertEqual(payload.progress.run_id, "abc")
            self.assertEqual(payload.progress.percent, 50.0)
            self.assertFalse(payload.tdarr.reachable)


class TdarrClientTests(unittest.TestCase):
    def test_stats_request_uses_get_all_and_stats_failure_is_nonfatal(self):
        client = TdarrClient("http://tdarr.example", "tapi_test")
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == "/api/v2/status":
                return {"status": "good"}
            if path == "/api/v2/get-nodes":
                return {"nodes": []}
            if path == "/api/v2/cruddb":
                raise RuntimeError("bad request")
            raise AssertionError(path)

        with patch.object(client, "_request_json", side_effect=fake_request):
            payload = client.fetch_status()

        crud_call = [call for call in calls if call[1] == "/api/v2/cruddb"][0]
        self.assertEqual(crud_call[2]["json"]["data"]["mode"], "getAll")
        self.assertTrue(payload["reachable"])
        self.assertIsNone(payload["error"])
        self.assertEqual(payload["active_worker_count"], 0)

    def test_tdarr_health_status_is_not_reported_as_worker(self):
        client = TdarrClient("http://tdarr.example", "tapi_test")

        def fake_request(method, path, **kwargs):
            if path == "/api/v2/status":
                return {"status": "good"}
            if path == "/api/v2/get-nodes":
                return {
                    "node-1": {
                        "_id": "node-1",
                        "nodeName": "Server-Node",
                        "nodePaused": False,
                        "workerLimits": {"transcodegpu": 3},
                        "workers": {},
                    }
                }
            if path == "/api/v2/cruddb":
                return {}
            raise AssertionError(path)

        with patch.object(client, "_request_json", side_effect=fake_request):
            payload = client.fetch_status()

        self.assertEqual(payload["active_worker_count"], 0)
        self.assertEqual(payload["workers"], [])
        self.assertEqual(payload["nodes"][0]["name"], "Server-Node")
        self.assertEqual(payload["nodes"][0]["workers"], [])

    def test_tdarr_workers_are_grouped_under_nodes(self):
        client = TdarrClient("http://tdarr.example", "tapi_test")

        def fake_request(method, path, **kwargs):
            if path == "/api/v2/status":
                return {"status": "good"}
            if path == "/api/v2/get-nodes":
                return {
                    "node-1": {
                        "_id": "node-1",
                        "nodeName": "Windows-Node",
                        "remoteAddress": "192.0.2.10",
                        "nodePaused": False,
                        "workerLimits": {"transcodecpu": 0, "transcodegpu": 6, "healthcheckgpu": 2},
                        "workers": {
                            "male-mutt": {
                                "status": "Running transcode",
                                "currentFile": "/media/input/show.mkv",
                                "percentage": 0.5,
                                "etaSeconds": 90,
                            }
                        },
                    }
                }
            if path == "/api/v2/cruddb":
                return {}
            raise AssertionError(path)

        with patch.object(client, "_request_json", side_effect=fake_request):
            payload = client.fetch_status()

        self.assertEqual(payload["active_worker_count"], 1)
        self.assertEqual(payload["nodes"][0]["name"], "Windows-Node")
        self.assertEqual(payload["nodes"][0]["worker_limit"], 6)
        self.assertEqual(payload["nodes"][0]["workers"][0]["id"], "male-mutt")
        self.assertEqual(payload["nodes"][0]["workers"][0]["node"], "Windows-Node")
        self.assertEqual(payload["nodes"][0]["workers"][0]["progress"], 50.0)

    def test_tdarr_counts_queue_and_errors_from_file_and_job_tables(self):
        client = TdarrClient("http://tdarr.example", "tapi_test")

        def fake_request(method, path, **kwargs):
            if path == "/api/v2/status":
                return {"status": "good"}
            if path == "/api/v2/get-nodes":
                return {"nodes": []}
            if path == "/api/v2/cruddb":
                collection = kwargs["json"]["data"]["collection"]
                if collection == "StatisticsJSONDB":
                    return [{"DBQueue": 0}]
                if collection == "FileJSONDB":
                    return [
                        {"file": "/media/queued.mkv", "HealthCheck": "Queued", "TranscodeDecisionMaker": "Queued"},
                        {"file": "/media/current-error.mkv", "TranscodeDecisionMaker": "Transcode error"},
                        {"file": "/media/complete.mkv", "HealthCheck": "Success"},
                    ]
                if collection == "JobsJSONDB":
                    return [
                        {"file": "/media/old-success.mkv", "status": "Transcode success"},
                        {"file": "/media/old-error.mkv", "status": "Transcode error"},
                        {"file": "/media/old-health-error.mkv", "status": "Error"},
                    ]
            raise AssertionError(path)

        with patch.object(client, "_request_json", side_effect=fake_request):
            payload = client.fetch_status(include_job_error_count=True)

        self.assertEqual(payload["queue_count"], 1)
        self.assertEqual(payload["error_count"], 1)
        self.assertEqual(payload["job_error_count"], 2)
        self.assertTrue(payload["show_job_error_count"])

    def test_tdarr_job_error_count_is_skipped_by_default(self):
        client = TdarrClient("http://tdarr.example", "tapi_test")
        requested_collections = []

        def fake_request(method, path, **kwargs):
            if path == "/api/v2/status":
                return {"status": "good"}
            if path == "/api/v2/get-nodes":
                return {"nodes": []}
            if path == "/api/v2/cruddb":
                collection = kwargs["json"]["data"]["collection"]
                requested_collections.append(collection)
                if collection == "StatisticsJSONDB":
                    return [{"DBQueue": 0}]
                if collection == "FileJSONDB":
                    return []
                if collection == "JobsJSONDB":
                    raise AssertionError("JobsJSONDB should not be queried by default")
            raise AssertionError(path)

        with patch.object(client, "_request_json", side_effect=fake_request):
            payload = client.fetch_status()

        self.assertIsNone(payload["job_error_count"])
        self.assertFalse(payload["show_job_error_count"])
        self.assertNotIn("JobsJSONDB", requested_collections)


if __name__ == "__main__":
    unittest.main()
