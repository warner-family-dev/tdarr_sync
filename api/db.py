import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)


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
