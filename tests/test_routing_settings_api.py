from unittest.mock import patch

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


def test_accepts_tdarr_host_from_authenticated_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)

    response = TestClient(app).put(
        "/settings/routing",
        headers=_auth_headers(),
        json={
            "tdarr_server_url": "https://tdarr.example.test",
            "tdarr_api_key": "not-a-secret-test-value",
            "routes": [],
        },
    )

    assert response.status_code == 200
    assert (
        load_runtime_settings(settings_file)["tdarr_server_url"]
        == "https://tdarr.example.test"
    )


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


def test_get_routing_targets_returns_server_discovery(tmp_path, monkeypatch):
    settings_file = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(settings, "runtime_settings_file", settings_file)
    discovered = {
        "configured": True,
        "reachable": True,
        "error": None,
        "targets": [
            {
                "tdarr_library_id": "library-720",
                "tdarr_library_name": "720p",
                "tdarr_library_folder": "/media/input/720p",
                "tdarr_flow_id": "flow-720",
                "flow_name": "720p Cleaned",
                "input_subdir": "720p",
            }
        ],
    }

    with patch("api.main.fetch_tdarr_routing_targets", return_value=discovered):
        response = TestClient(app).get(
            "/settings/routing/targets", headers=_auth_headers()
        )

    assert response.status_code == 200
    assert response.json() == discovered


def test_routing_update_resolves_library_and_flow_from_tdarr(tmp_path, monkeypatch):
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
    target = {
        "tdarr_library_id": "library-720",
        "tdarr_library_name": "720p",
        "tdarr_library_folder": "/media/input/720p",
        "tdarr_flow_id": "flow-720",
        "flow_name": "720p Cleaned",
        "input_subdir": "720p",
    }

    with patch("api.main.TdarrClient.fetch_routing_targets", return_value=[target]):
        response = TestClient(app).put(
            "/settings/routing",
            headers=_auth_headers(),
            json={
                "tdarr_server_url": "http://tdarr.local:8266",
                "tdarr_api_key": "",
                "routes": [
                    {
                        "source": "sonarr",
                        "tag": "transcode",
                        "tdarr_library_id": "library-720",
                    }
                ],
            },
        )

    assert response.status_code == 200
    route = response.json()["routes"][0]
    assert route["tdarr_library_name"] == "720p"
    assert route["tdarr_flow_id"] == "flow-720"
    assert route["flow_name"] == "720p Cleaned"
    assert route["input_subdir"] == "720p"
    assert load_runtime_settings(settings_file)["routes"][0] == route


def test_routing_update_rejects_unavailable_library(tmp_path, monkeypatch):
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

    with patch("api.main.TdarrClient.fetch_routing_targets", return_value=[]):
        response = TestClient(app).put(
            "/settings/routing",
            headers=_auth_headers(),
            json={
                "tdarr_server_url": "http://tdarr.local:8266",
                "routes": [
                    {
                        "source": "sonarr",
                        "tag": "transcode",
                        "tdarr_library_id": "missing",
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert "unavailable" in response.json()["detail"]


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
