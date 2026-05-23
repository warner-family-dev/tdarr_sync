import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)


def _chunked(iterable: Iterable[str], size: int) -> Iterator[List[str]]:
    chunk: List[str] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def fetch_processed_files(db_path: Path, limit: int = 50, offset: int = 0) -> List[Dict]:
    if not db_path.exists():
        return []

    with closing(_connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT file_path, processed_at
                FROM processed_files
                ORDER BY processed_at DESC, file_path ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        except sqlite3.OperationalError:
            return []
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_summary(db_path: Path) -> Dict[str, Optional[int]]:
    if not db_path.exists():
        return {"total": 0, "last_processed_at": None, "earliest_processed_at": None}

    with closing(_connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    MAX(processed_at) AS last_processed_at,
                    MIN(processed_at) AS earliest_processed_at
                FROM processed_files
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return {"total": 0, "last_processed_at": None, "earliest_processed_at": None}

    return {
        "total": row["total"],
        "last_processed_at": row["last_processed_at"],
        "earliest_processed_at": row["earliest_processed_at"],
    }


def database_file_stats(db_path: Path) -> Dict[str, Optional[int]]:
    if not db_path.exists():
        return {"exists": False, "size_bytes": None, "last_modified": None}

    stat = db_path.stat()
    return {
        "exists": True,
        "size_bytes": stat.st_size,
        "last_modified": int(stat.st_mtime),
    }


def fetch_all_processed(db_path: Path) -> Dict[str, Optional[int]]:
    if not db_path.exists():
        return {}

    with closing(_connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT file_path, processed_at
                FROM processed_files
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

    return {row["file_path"]: row["processed_at"] for row in rows}


def fetch_processed_catalog(db_path: Path) -> Dict:
    rows = fetch_processed_files(db_path, limit=100000, offset=0)
    catalog = _empty_catalog()
    if not rows:
        return catalog

    sonarr_base = _env_path("LOCAL_MOUNT_BASE_PATH", os.getenv("BASE_DIR", "/media/library"))
    radarr_base = _env_path("RADARR_LOCAL_MOUNT_BASE_PATH", os.getenv("BASE_DIR", "/media/radarr_library"))
    tv_groups: Dict[Tuple[str, str], Dict] = {}
    movie_groups: Dict[str, Dict] = {}
    folder_groups: Dict[str, Dict] = {}

    for row in rows:
        file_path = str(row.get("file_path") or "")
        if not file_path:
            continue
        processed_at = row.get("processed_at")
        file_entry = {
            "file_path": file_path,
            "file_name": Path(file_path).name,
            "processed_at": processed_at,
        }
        source = _classify_path(file_path, sonarr_base, radarr_base)
        if source == "movie":
            key, title = _movie_group_key(file_path, radarr_base)
            group = movie_groups.setdefault(
                key,
                {
                    "id": f"movie:{key}",
                    "type": "movie",
                    "title": title,
                    "path": key,
                    "file_count": 0,
                    "last_processed_at": None,
                    "files": [],
                },
            )
            _append_file(group, file_entry)
            continue

        if source == "tv":
            show_key, show_title, season_number, season_name = _tv_group_key(file_path, sonarr_base)
            group = tv_groups.setdefault(
                (show_key, show_title),
                {
                    "id": f"tv:{show_key}",
                    "type": "tv",
                    "title": show_title,
                    "path": show_key,
                    "file_count": 0,
                    "last_processed_at": None,
                    "seasons": {},
                },
            )
            season = group["seasons"].setdefault(
                season_number,
                {
                    "number": season_number,
                    "name": season_name,
                    "file_count": 0,
                    "last_processed_at": None,
                    "files": [],
                },
            )
            _append_file(group, file_entry)
            _append_file(season, file_entry)
            continue

        key, title = _folder_group_key(file_path)
        group = folder_groups.setdefault(
            key,
            {
                "id": f"folder:{key}",
                "type": "folder",
                "title": title,
                "path": key,
                "file_count": 0,
                "last_processed_at": None,
                "files": [],
            },
        )
        _append_file(group, file_entry)

    tv_items = []
    for group in tv_groups.values():
        seasons = list(group.pop("seasons").values())
        seasons.sort(key=lambda item: (item["number"] < 0, item["number"], item["name"].lower()))
        for season in seasons:
            season["files"].sort(key=lambda item: item["file_name"].lower())
        group["seasons"] = seasons
        tv_items.append(group)

    movies = list(movie_groups.values())
    folders = list(folder_groups.values())
    for collection in (tv_items, movies, folders):
        collection.sort(key=lambda item: item["title"].lower())

    catalog["total_files"] = len(rows)
    catalog["tv"] = tv_items
    catalog["movies"] = movies
    catalog["folders"] = folders
    return catalog


def delete_processed_entries(db_path: Path, file_paths: Iterable[str], chunk_size: int = 200) -> int:
    paths = [path for path in file_paths if path]
    if not paths or not db_path.exists():
        return 0

    deleted = 0
    with closing(_connect(db_path)) as conn:
        cursor = conn.cursor()
        for chunk in _chunked(paths, chunk_size):
            placeholders = ",".join("?" for _ in chunk)
            try:
                cursor.execute(f"DELETE FROM processed_files WHERE file_path IN ({placeholders})", chunk)
            except sqlite3.OperationalError:
                continue
            if cursor.rowcount and cursor.rowcount > 0:
                deleted += cursor.rowcount
        conn.commit()
    return deleted


def _empty_catalog() -> Dict:
    return {"total_files": 0, "tv": [], "movies": [], "folders": []}


def _env_path(name: str, fallback: str) -> Path:
    return Path(os.getenv(name, fallback)).resolve()


def _classify_path(file_path: str, sonarr_base: Path, radarr_base: Path) -> str:
    path = Path(file_path)
    if _is_relative_to(path, radarr_base) and not _is_relative_to(path, sonarr_base):
        return "movie"
    if _is_relative_to(path, sonarr_base) and not _is_relative_to(path, radarr_base):
        return "tv"

    lowered = file_path.lower()
    if any(token in lowered for token in ("/radarr", "/movie", "/movies")):
        return "movie"
    if any(token in lowered for token in ("/sonarr", "/tv", "/series", "/season ")):
        return "tv"
    if re.search(r"\bs\d{1,2}e\d{1,3}\b", lowered):
        return "tv"
    return "folder"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(base)
        return True
    except ValueError:
        return False


def _relative_parts(path: Path, base: Path) -> List[str]:
    try:
        return list(path.resolve(strict=False).relative_to(base).parts)
    except ValueError:
        return list(path.parts)


def _tv_group_key(file_path: str, base: Path) -> Tuple[str, str, int, str]:
    path = Path(file_path)
    parts = _relative_parts(path, base)
    if len(parts) < 2:
        return (str(path.parent), path.parent.name or "Unknown series", -1, "Unknown season")

    directory_parts = parts[:-1]
    season_index = _find_season_index(directory_parts)
    if season_index is None:
        season_number = _season_from_filename(path.name)
        show_parts = directory_parts[:-1] if len(directory_parts) > 1 else directory_parts
    else:
        season_number = _season_from_name(directory_parts[season_index])
        show_parts = directory_parts[:season_index]

    if not show_parts and len(directory_parts) > 0:
        show_parts = [directory_parts[0]]

    show_title = show_parts[-1] if show_parts else path.parent.name or "Unknown series"
    show_key = str(base.joinpath(*show_parts)) if show_parts else str(path.parent)
    return (show_key, show_title, season_number, _season_label(season_number))


def _movie_group_key(file_path: str, base: Path) -> Tuple[str, str]:
    path = Path(file_path)
    parts = _relative_parts(path, base)
    if len(parts) >= 2:
        title = parts[-2]
        key = str(base.joinpath(*parts[:-1]))
        return (key, title)
    return (str(path), path.stem or path.name)


def _folder_group_key(file_path: str) -> Tuple[str, str]:
    parent = Path(file_path).parent
    return (str(parent), parent.name or str(parent))


def _find_season_index(parts: List[str]) -> Optional[int]:
    for index, part in enumerate(parts):
        if _season_from_name(part) >= 0:
            return index
    return None


def _season_from_name(name: str) -> int:
    match = re.search(r"\bseason\s*(\d+)\b", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return -1


def _season_from_filename(name: str) -> int:
    match = re.search(r"\bs(\d{1,2})e\d{1,3}\b", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return -1


def _season_label(number: int) -> str:
    if number == 0:
        return "Specials"
    if number < 0:
        return "Unknown season"
    return f"Season {number:02d}"


def _append_file(target: Dict, file_entry: Dict) -> None:
    target["file_count"] += 1
    target.setdefault("files", []).append(file_entry)
    processed_at = file_entry.get("processed_at")
    if isinstance(processed_at, int) and (target.get("last_processed_at") or 0) < processed_at:
        target["last_processed_at"] = processed_at
