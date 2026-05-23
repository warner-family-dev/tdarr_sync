import sqlite3

from fastapi.testclient import TestClient

from api.main import app
from api.settings import settings


def _auth_headers():
    return {"Authorization": f"Bearer {settings.api_auth_token}"}


def test_delete_processed_file_marker_removes_matching_row(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    file_path = "/media/library/Example/episode.mkv"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE processed_files (file_path TEXT PRIMARY KEY, processed_at INTEGER)")
        conn.execute("INSERT INTO processed_files (file_path, processed_at) VALUES (?, ?)", (file_path, 1234))
        conn.commit()

    monkeypatch.setattr(settings, "state_db_file", db_path)
    client = TestClient(app)

    response = client.delete("/processed-files", params={"file_path": file_path}, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "deleted_count": 1, "file_path": file_path}
    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
    assert remaining == 0


def test_delete_processed_file_marker_reports_missing_row(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE processed_files (file_path TEXT PRIMARY KEY, processed_at INTEGER)")
        conn.commit()

    monkeypatch.setattr(settings, "state_db_file", db_path)
    client = TestClient(app)

    response = client.delete("/processed-files", params={"file_path": "/missing.mkv"}, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": False, "deleted_count": 0, "file_path": "/missing.mkv"}
