from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ProcessedFile(BaseModel):
    file_path: str = Field(...)
    processed_at: Optional[int] = Field(default=None, description="Epoch seconds")
    processed_at_iso: Optional[str] = Field(default=None, description="ISO8601 timestamp")


class ProcessedSummary(BaseModel):
    total_processed: int
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None
    earliest_processed_at: Optional[int] = None
    earliest_processed_at_iso: Optional[str] = None
    database_size_bytes: Optional[int] = None
    database_last_modified: Optional[int] = None
    database_last_modified_iso: Optional[str] = None


class SyncStatus(BaseModel):
    running: bool
    last_started_at: Optional[int] = None
    last_started_at_iso: Optional[str] = None
    last_finished_at: Optional[int] = None
    last_finished_at_iso: Optional[str] = None
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None


class SyncTriggerResponse(BaseModel):
    accepted: bool
    running: bool


def to_iso(timestamp: Optional[int], tz) -> Optional[str]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=tz).isoformat()
    except Exception:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
