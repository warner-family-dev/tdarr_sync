from fastapi.testclient import TestClient

from api.main import app
from api.settings import settings
from runtime_settings import load_runtime_settings, save_runtime_settings


def _auth_headers():
    return {"Authorization": f"Bearer {settings.api_auth_token}"}


def test_get_routing_settings_does_not_return_api_key(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    save_runtime_settings(
        {
            "tdarr_server_url": "http://tdarr.local:8266",
            "tdarr_api_key": "not-a-secret-test-value",
            "routes": [],
        },
        settings_file,
    )
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).get("/settings/routing", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert "tdarr_api_key" not in response.json()
    assert "tapi_secret_value" not in response.text


def test_blank_routing_api_key_preserves_existing_secret(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    save_runtime_settings(
        {
            "tdarr_server_url": "http://tdarr.local:8266",
            "tdarr_api_key": "not-a-secret-test-value",
            "routes": [],
        },
        settings_file,
    )
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).put(
        "/settings/routing",
        headers=_auth_headers(),
        json={
            "tdarr_server_url": "http://tdarr-new.local:8266",
            "tdarr_api_key": "",
            "routes": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert "tdarr_api_key" not in response.json()
    stored = load_runtime_settings(settings_file)
    assert stored["tdarr_api_key"] == "not-a-secret-test-value"
    assert stored["tdarr_server_url"] == "http://tdarr-new.local:8266"
