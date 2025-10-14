from datetime import datetime, timezone
from typing import List, Literal, Optional

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


class RestoreSeriesEntry(BaseModel):
    index: int = Field(..., ge=1)
    series_id: int = Field(..., ge=0)
    title: str
    processed: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    status: Literal["full", "partial", "none"]
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None


class RestoreSeriesList(BaseModel):
    series: List[RestoreSeriesEntry] = Field(default_factory=list)


class RestoreRequest(BaseModel):
    selection: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RestoreSeriesResult(BaseModel):
    series_id: int
    title: str
    restored: List[str] = Field(default_factory=list)
    archived_transcodes: List[str] = Field(default_factory=list)
    skipped_missing_db: List[str] = Field(default_factory=list)
    skipped_missing_archive: List[str] = Field(default_factory=list)
    skipped_outside_library: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class RestoreSummary(BaseModel):
    series_requested: int
    series_processed: int
    files_restored: int
    files_skipped_missing_db: int
    files_skipped_missing_archive: int


class RestoreResponse(BaseModel):
    summary: RestoreSummary
    results: List[RestoreSeriesResult] = Field(default_factory=list)
    messages: List[str] = Field(default_factory=list)


def to_iso(timestamp: Optional[int], tz) -> Optional[str]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=tz).isoformat()
    except Exception:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
