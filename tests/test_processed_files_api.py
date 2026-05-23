import sqlite3

from fastapi.testclient import TestClient

from api.main import app
from api.settings import settings


def _auth_headers():
    return {"Authorization": f"Bearer {settings.api_auth_token}"}


def _create_processed_db(db_path, rows=None):
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE processed_files (file_path TEXT PRIMARY KEY, processed_at INTEGER)")
        for file_path, processed_at in rows or []:
            conn.execute("INSERT INTO processed_files (file_path, processed_at) VALUES (?, ?)", (file_path, processed_at))
        conn.commit()


def test_delete_processed_file_marker_removes_matching_row(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    file_path = "/media/library/Example/episode.mkv"
    _create_processed_db(db_path, [(file_path, 1234)])

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
    _create_processed_db(db_path)

    monkeypatch.setattr(settings, "state_db_file", db_path)
    client = TestClient(app)

    response = client.delete("/processed-files", params={"file_path": "/missing.mkv"}, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": False, "deleted_count": 0, "file_path": "/missing.mkv"}


def test_processed_files_catalog_groups_tv_and_movies(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    tv_file = "/media/library/Example Show/Season 01/Example.Show.S01E01.mkv"
    movie_file = "/media/radarr_library/Example Movie (2024)/Example Movie.mkv"
    _create_processed_db(db_path, [(tv_file, 1234), (movie_file, 2345)])

    monkeypatch.setattr(settings, "state_db_file", db_path)
    monkeypatch.setenv("LOCAL_MOUNT_BASE_PATH", "/media/library")
    monkeypatch.setenv("RADARR_LOCAL_MOUNT_BASE_PATH", "/media/radarr_library")
    client = TestClient(app)

    response = client.get("/processed-files/catalog", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 2
    assert payload["tv"][0]["title"] == "Example Show"
    assert payload["tv"][0]["seasons"][0]["name"] == "Season 01"
    assert payload["tv"][0]["seasons"][0]["files"][0]["file_path"] == tv_file
    assert payload["movies"][0]["title"] == "Example Movie (2024)"
    assert payload["movies"][0]["files"][0]["file_path"] == movie_file


def test_bulk_delete_processed_file_markers_removes_selected_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    first = "/media/library/Example Show/Season 01/Example.Show.S01E01.mkv"
    second = "/media/library/Example Show/Season 01/Example.Show.S01E02.mkv"
    third = "/media/library/Other Show/Season 01/Other.Show.S01E01.mkv"
    _create_processed_db(db_path, [(first, 1234), (second, 2345), (third, 3456)])

    monkeypatch.setattr(settings, "state_db_file", db_path)
    client = TestClient(app)

    response = client.post(
        "/processed-files/delete",
        json={"file_paths": [first, second]},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"requested_count": 2, "deleted_count": 2}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT file_path FROM processed_files ORDER BY file_path").fetchall()
    assert [row[0] for row in rows] == [third]
