from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("API_AUTH_TOKEN", "tdarr-sync-test-api-token")
os.environ.setdefault("STATE_DB_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test-state.db"))
os.environ.setdefault("LOG_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test.log"))
