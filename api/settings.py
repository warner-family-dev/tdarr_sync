import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    tz: str = field(default_factory=lambda: os.getenv("TZ", "UTC"))
    state_db_file: Path = field(default_factory=lambda: Path(os.getenv("STATE_DB_FILE", "/data/sonarr_tdarr_state.db")))
    log_file: Optional[Path] = field(default=None)
    sync_script_path: Path = field(default_factory=lambda: Path(os.getenv("SYNC_SCRIPT_PATH", "/app/tdarr_sync.py")))
    sync_python_executable: str = field(default_factory=lambda: os.getenv("SYNC_PYTHON_EXECUTABLE", sys.executable or "python"))
    cors_allow_origins: List[str] = field(default_factory=list)
    allow_all_cors: bool = field(default_factory=lambda: _bool_env("API_CORS_ALLOW_ALL", True))

    def __post_init__(self):
        log_env = os.getenv("LOG_FILE", "/logs/tdarr_sync.log")
        if log_env:
            self.log_file = Path(log_env)
        else:
            self.log_file = None

        cors_env = os.getenv("API_CORS_ALLOW_ORIGINS", "")
        if cors_env:
            self.cors_allow_origins = [item.strip() for item in cors_env.split(",") if item.strip()]

        self.state_db_file.parent.mkdir(parents=True, exist_ok=True)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.cors_allow_origins and not self.allow_all_cors:
            # Fall back to localhost if custom list not provided and allow_all_cors is false
            self.cors_allow_origins = ["http://localhost:3000"]

    @property
    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def sanitized(self) -> dict:
        return {
            "tz": self.tz,
            "state_db_file": str(self.state_db_file),
            "log_file": str(self.log_file) if self.log_file else None,
            "sync_script_path": str(self.sync_script_path),
            "cors_allow_all": self.allow_all_cors,
            "cors_allow_origins": self.cors_allow_origins,
            "sonarr": {
                "url": os.getenv("SONARR_URL", ""),
                "tag_name": os.getenv("SONARR_TAG_NAME", ""),
                "api_key_configured": bool(os.getenv("SONARR_API_KEY")),
            },
            "tdarr": {
                "base_dir": os.getenv("BASE_DIR", ""),
                "input_dir": os.getenv("TDARR_INPUT_DIR", ""),
                "output_dir": os.getenv("TDARR_OUTPUT_DIR", ""),
                "archive_dir": os.getenv("MOVE_ORIGINAL_FILES_DEST", ""),
            },
            "telegram_enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        }


settings = Settings()
