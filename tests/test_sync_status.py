import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("STATE_DB_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test-state.db"))
os.environ.setdefault("LOG_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test.log"))

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

    def _body(*args, **kwargs):
        return kwargs.get("default")

    def _query(*args, **kwargs):
        return kwargs.get("default")

    fastapi_stub.Body = _body
    fastapi_stub.FastAPI = _FastAPI
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Query = _query
    middleware_stub = types.ModuleType("fastapi.middleware")
    cors_stub = types.ModuleType("fastapi.middleware.cors")
    cors_stub.CORSMiddleware = object
    sys.modules["fastapi"] = fastapi_stub
    sys.modules["fastapi.middleware"] = middleware_stub
    sys.modules["fastapi.middleware.cors"] = cors_stub

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
                "active_worker_count": 0,
                "workers": [],
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
            self.assertFalse(payload.tdarr["configured"])

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
                "active_worker_count": 0,
                "workers": [],
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
            self.assertEqual(payload.progress["run_id"], "abc")
            self.assertEqual(payload.progress["percent"], 50.0)
            self.assertFalse(payload.tdarr["reachable"])


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


if __name__ == "__main__":
    unittest.main()
