from fastapi.testclient import TestClient

from api.main import app
from api.settings import settings


def test_health_does_not_require_auth():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_endpoint_rejects_missing_auth():
    client = TestClient(app)

    response = client.get("/config")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_protected_endpoint_rejects_bad_bearer_token():
    client = TestClient(app)

    response = client.get("/config", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_protected_endpoint_accepts_configured_bearer_token():
    client = TestClient(app)

    response = client.get("/config", headers={"Authorization": f"Bearer {settings.api_auth_token}"})

    assert response.status_code == 200
    assert response.json()["api_auth_configured"] is True
