from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("API_AUTH_TOKEN", "tdarr-sync-test-api-token")
os.environ.setdefault("SONARR_URL", "http://sonarr.test")
os.environ.setdefault("SONARR_API_KEY", "sonarr-test-key")
os.environ.setdefault("BASE_DIR", tempfile.gettempdir())
os.environ.setdefault("TDARR_INPUT_DIR", tempfile.gettempdir())
os.environ.setdefault("TDARR_OUTPUT_DIR", tempfile.gettempdir())
os.environ.setdefault(
    "STATE_DB_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test-state.db")
)
os.environ.setdefault(
    "LOG_FILE", str(Path(tempfile.gettempdir()) / "tdarr-sync-test.log")
)
os.environ.setdefault(
    "TDARR_ALLOWED_HOSTS", "tdarr.local,tdarr-new.local,192.168.4.55"
)
