#!/usr/bin/env python3
import sqlite3
from pathlib import Path
import time
import os

DB_FILE = Path(os.environ.get("STATE_DB_FILE", "sonarr_tdarr_state.db"))

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            file_path TEXT PRIMARY KEY,
            processed_at INTEGER
        )
    """)
    conn.commit()
    return conn

if __name__ == "__main__":
    conn = init_db()
    print(f"DB initialized at {DB_FILE}")
    conn.close()
