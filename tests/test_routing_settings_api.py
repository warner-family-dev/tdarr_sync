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


def test_rejects_unlisted_tdarr_host(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).put(
        "/settings/routing",
        headers=_auth_headers(),
        json={
            "tdarr_server_url": "http://metadata.internal/latest",
            "tdarr_api_key": "not-a-secret-test-value",
            "routes": [],
        },
    )

    assert response.status_code == 400
    assert "TDARR_ALLOWED_HOSTS" in response.json()["detail"]
    assert not settings_file.exists()


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


def test_web_auth_settings_round_trip_preserves_routing(tmp_path, monkeypatch):
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
    client = TestClient(app)

    response = client.put(
        "/settings/web-auth",
        headers=_auth_headers(),
        json={
            "enabled": True,
            "trust_proxy_headers": True,
            "trusted_networks": ["192.168.4.55/24"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "trust_proxy_headers": True,
        "trusted_networks": ["192.168.4.0/24"],
    }
    stored = load_runtime_settings(settings_file)
    assert stored["tdarr_api_key"] == "not-a-secret-test-value"
    assert stored["tdarr_server_url"] == "http://tdarr.local:8266"


def test_web_auth_settings_reject_unsafe_enablement(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).put(
        "/settings/web-auth",
        headers=_auth_headers(),
        json={"enabled": True, "trust_proxy_headers": True, "trusted_networks": []},
    )

    assert response.status_code == 400
    assert "at least one trusted CIDR" in response.json()["detail"]
    assert not settings_file.exists()


def test_routing_update_preserves_web_auth_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    save_runtime_settings(
        {
            "web_auth_bypass_enabled": True,
            "web_auth_trust_proxy_headers": True,
            "web_auth_trusted_networks": ["192.168.4.0/24"],
            "routes": [],
        },
        settings_file,
    )
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).put(
        "/settings/routing",
        headers=_auth_headers(),
        json={"tdarr_server_url": "", "tdarr_api_key": "", "routes": []},
    )

    assert response.status_code == 200
    stored = load_runtime_settings(settings_file)
    assert stored["web_auth_bypass_enabled"] is True
    assert stored["web_auth_trusted_networks"] == ["192.168.4.0/24"]
