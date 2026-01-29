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


class SyncSelectionPayload(BaseModel):
    series_id: int = Field(..., ge=0)
    seasons: Optional[List[int]] = None


class SyncRunRequest(BaseModel):
    dry_run: bool = False
    selections: Optional[List[SyncSelectionPayload]] = None


class RestoreSeasonEntry(BaseModel):
    number: int
    name: str
    processed: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    status: Literal["full", "partial", "none"]
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None


class RestoreSeriesEntry(BaseModel):
    index: int = Field(..., ge=1)
    series_id: int = Field(..., ge=0)
    title: str
    processed: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    status: Literal["full", "partial", "none"]
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None
    seasons: List[RestoreSeasonEntry] = Field(default_factory=list)


class RestoreSeriesList(BaseModel):
    series: List[RestoreSeriesEntry] = Field(default_factory=list)


class RestoreSelectionPayload(BaseModel):
    series_id: int
    seasons: Optional[List[int]] = None


class RestoreRequest(BaseModel):
    password: str = Field(..., min_length=1)
    selection: Optional[str] = Field(default=None)
    selections: Optional[List[RestoreSelectionPayload]] = None
    request_id: Optional[str] = Field(default=None, description="Client correlation id for logging")
    wait_for_completion: bool = Field(
        default=False, description="If true, wait for the restore to finish before responding."
    )


class RestoreSeriesResult(BaseModel):
    series_id: int
    title: str
    selected_seasons: Optional[List[int]] = None
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


class RestoreTriggerResponse(BaseModel):
    job_id: str
    request_id: str
    status: Literal["submitted", "pending", "running"] = "submitted"


class RestoreJobStatus(BaseModel):
    job_id: str
    request_id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    created_at: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    result: Optional["RestoreResponse"] = None
    error: Optional[str] = None


RestoreRunResponse = RestoreResponse | RestoreTriggerResponse

RestoreJobStatus.model_rebuild()


def to_iso(timestamp: Optional[int], tz) -> Optional[str]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=tz).isoformat()
    except Exception:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
