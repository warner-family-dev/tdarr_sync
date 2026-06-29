import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


Category = str


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


def _fetch_processed_rows(db_path: Path) -> List[Dict]:
    if not db_path.exists():
        return []

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
            return []
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
    rows = _fetch_processed_rows(db_path)
    return {row["file_path"]: row["processed_at"] for row in rows}


def fetch_processed_catalog(db_path: Path) -> Dict:
    rows = _fetch_processed_rows(db_path)
    catalog = _empty_catalog()
    if not rows:
        return catalog

    bases = _catalog_bases()
    tv_groups: Dict[Tuple[str, str], Dict] = {}
    movie_groups: Dict[str, Dict] = {}
    folder_groups: Dict[str, Dict] = {}

    for row in rows:
        file_path = str(row.get("file_path") or "")
        if not file_path:
            continue
        metadata = _record_metadata(file_path, bases)
        processed_at = row.get("processed_at")
        if metadata["category"] == "movies":
            group = movie_groups.setdefault(
                metadata["group_path"],
                _new_group(metadata["group_id"], "movie", metadata["group_title"], metadata["group_path"]),
            )
            _touch_group(group, processed_at)
            continue

        if metadata["category"] == "tv":
            group = tv_groups.setdefault(
                (metadata["group_path"], metadata["group_title"]),
                {
                    **_new_group(metadata["group_id"], "tv", metadata["group_title"], metadata["group_path"]),
                    "seasons": {},
                },
            )
            season_number = metadata["season_number"]
            season = group["seasons"].setdefault(
                season_number,
                {
                    "number": season_number,
                    "name": metadata["season_name"],
                    "file_count": 0,
                    "last_processed_at": None,
                    "files": [],
                },
            )
            _touch_group(group, processed_at)
            _touch_group(season, processed_at)
            continue

        group = folder_groups.setdefault(
            metadata["group_path"],
            _new_group(metadata["group_id"], "folder", metadata["group_title"], metadata["group_path"]),
        )
        _touch_group(group, processed_at)

    tv_items = []
    for group in tv_groups.values():
        seasons = list(group.pop("seasons").values())
        seasons.sort(key=lambda item: (item["number"] < 0, item["number"], item["name"].lower()))
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


def fetch_processed_records(
    db_path: Path,
    category: Category,
    group_id: str,
    season_number: Optional[int] = None,
) -> List[Dict]:
    if category not in {"tv", "movies", "folders"}:
        return []

    bases = _catalog_bases()
    records = []
    for row in _fetch_processed_rows(db_path):
        file_path = str(row.get("file_path") or "")
        if not file_path:
            continue
        metadata = _record_metadata(file_path, bases)
        if metadata["category"] != category or metadata["group_id"] != group_id:
            continue
        if season_number is not None and metadata["season_number"] != season_number:
            continue
        records.append(
            {
                "file_path": file_path,
                "file_name": Path(file_path).name,
                "processed_at": row.get("processed_at"),
            }
        )

    records.sort(key=lambda item: item["file_name"].lower())
    return records


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
                # Placeholder count is generated internally; all file paths remain bound parameters.
                cursor.execute(
                    f"DELETE FROM processed_files WHERE file_path IN ({placeholders})",  # nosec B608
                    chunk,
                )
            except sqlite3.OperationalError:
                continue
            if cursor.rowcount and cursor.rowcount > 0:
                deleted += cursor.rowcount
        conn.commit()
    return deleted


def _empty_catalog() -> Dict:
    return {"total_files": 0, "tv": [], "movies": [], "folders": []}


def _catalog_bases() -> Dict[str, str]:
    sonarr_base = os.getenv("LOCAL_MOUNT_BASE_PATH", os.getenv("BASE_DIR", "/media/library"))
    radarr_base = os.getenv("RADARR_LOCAL_MOUNT_BASE_PATH", os.getenv("BASE_DIR", "/media/radarr_library"))
    return {
        "sonarr": _normalize_path_string(sonarr_base),
        "radarr": _normalize_path_string(radarr_base),
    }


def _normalize_path_string(path: str) -> str:
    value = str(path).replace("\\", "/").rstrip("/")
    return value or "/"


def _is_under_base(file_path: str, base: str) -> bool:
    normalized = _normalize_path_string(file_path)
    return normalized == base or normalized.startswith(f"{base}/")


def _parts_relative_to(file_path: str, base: str) -> List[str]:
    normalized = _normalize_path_string(file_path)
    if _is_under_base(normalized, base):
        relative = normalized[len(base) :].lstrip("/")
        return [part for part in relative.split("/") if part]
    return [part for part in normalized.split("/") if part]


def _record_metadata(file_path: str, bases: Dict[str, str]) -> Dict:
    source = _classify_path(file_path, bases["sonarr"], bases["radarr"])
    if source == "movies":
        group_path, group_title = _movie_group_key(file_path, bases["radarr"])
        return {
            "category": "movies",
            "group_id": f"movie:{group_path}",
            "group_path": group_path,
            "group_title": group_title,
            "season_number": None,
            "season_name": None,
        }
    if source == "tv":
        group_path, group_title, season_number, season_name = _tv_group_key(file_path, bases["sonarr"])
        return {
            "category": "tv",
            "group_id": f"tv:{group_path}",
            "group_path": group_path,
            "group_title": group_title,
            "season_number": season_number,
            "season_name": season_name,
        }

    group_path, group_title = _folder_group_key(file_path)
    return {
        "category": "folders",
        "group_id": f"folder:{group_path}",
        "group_path": group_path,
        "group_title": group_title,
        "season_number": None,
        "season_name": None,
    }


def _classify_path(file_path: str, sonarr_base: str, radarr_base: str) -> str:
    in_radarr = _is_under_base(file_path, radarr_base)
    in_sonarr = _is_under_base(file_path, sonarr_base)
    if in_radarr and not in_sonarr:
        return "movies"
    if in_sonarr and not in_radarr:
        return "tv"

    lowered = file_path.lower().replace("\\", "/")
    if any(token in lowered for token in ("/radarr", "/movie", "/movies")):
        return "movies"
    if any(token in lowered for token in ("/sonarr", "/tv", "/series", "/season ")):
        return "tv"
    if re.search(r"\bs\d{1,2}e\d{1,3}\b", lowered):
        return "tv"
    return "folders"


def _tv_group_key(file_path: str, base: str) -> Tuple[str, str, int, str]:
    parts = _parts_relative_to(file_path, base)
    path = Path(file_path)
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
    show_key = _normalize_path_string("/".join([base, *show_parts])) if show_parts else str(path.parent)
    return (show_key, show_title, season_number, _season_label(season_number))


def _movie_group_key(file_path: str, base: str) -> Tuple[str, str]:
    parts = _parts_relative_to(file_path, base)
    path = Path(file_path)
    if len(parts) >= 2:
        title = parts[-2]
        key = _normalize_path_string("/".join([base, *parts[:-1]]))
        return (key, title)
    return (str(path), path.stem or path.name)


def _folder_group_key(file_path: str) -> Tuple[str, str]:
    parent = Path(file_path).parent
    return (str(parent), parent.name or str(parent))


def _new_group(group_id: str, group_type: str, title: str, path: str) -> Dict:
    return {
        "id": group_id,
        "type": group_type,
        "title": title,
        "path": path,
        "file_count": 0,
        "last_processed_at": None,
        "seasons": [],
        "files": [],
    }


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


def _touch_group(target: Dict, processed_at: Optional[int]) -> None:
    target["file_count"] += 1
    if isinstance(processed_at, int) and (target.get("last_processed_at") or 0) < processed_at:
        target["last_processed_at"] = processed_at
