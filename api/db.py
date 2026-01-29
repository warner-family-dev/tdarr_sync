import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional


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
