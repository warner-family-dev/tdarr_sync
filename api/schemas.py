from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SyncProgress(BaseModel):
    run_id: str
    state: str
    phase: str
    action: str = ""
    dry_run: bool = False
    source: Optional[str] = None
    title: Optional[str] = None
    path: Optional[str] = None
    destination: Optional[str] = None
    message: Optional[str] = None
    completed_items: int = 0
    total_items: Optional[int] = None
    skipped_items: int = 0
    failed_items: int = 0
    percent: Optional[float] = None
    eta_seconds: Optional[int] = None
    started_at: Optional[int] = None
    started_at_iso: Optional[str] = None
    phase_started_at: Optional[int] = None
    phase_started_at_iso: Optional[str] = None
    updated_at: Optional[int] = None
    updated_at_iso: Optional[str] = None
    finished_at: Optional[int] = None
    finished_at_iso: Optional[str] = None
    elapsed_seconds: Optional[int] = None
    error: Optional[str] = None


class TdarrWorkerStatus(BaseModel):
    id: str
    name: str = ""
    node: str = ""
    node_id: str = ""
    status: str = ""
    file: Optional[str] = None
    title: Optional[str] = None
    progress: Optional[float] = None
    eta_seconds: Optional[int] = None


class TdarrNodeStatus(BaseModel):
    id: str
    name: str
    address: str = ""
    paused: bool = False
    worker_limit: int = 0
    active_worker_count: int = 0
    workers: List[TdarrWorkerStatus] = Field(default_factory=list)


class TdarrStatus(BaseModel):
    configured: bool = False
    reachable: bool = False
    server_url: str = ""
    error: Optional[str] = None
    queue_count: Optional[int] = None
    error_count: Optional[int] = None
    job_error_count: Optional[int] = None
    show_job_error_count: bool = False
    active_worker_count: int = 0
    workers: List[TdarrWorkerStatus] = Field(default_factory=list)
    nodes: List[TdarrNodeStatus] = Field(default_factory=list)


class ProcessedFile(BaseModel):
    file_path: str = Field(...)
    processed_at: Optional[int] = Field(default=None, description="Epoch seconds")
    processed_at_iso: Optional[str] = Field(default=None, description="ISO8601 timestamp")




class ProcessedFileDeleteResponse(BaseModel):
    deleted: bool
    deleted_count: int
    file_path: str


class ProcessedFileDeleteRequest(BaseModel):
    file_paths: List[str] = Field(default_factory=list)


class ProcessedFileBulkDeleteResponse(BaseModel):
    requested_count: int
    deleted_count: int


class ProcessedDatabaseFile(BaseModel):
    file_path: str
    file_name: str
    processed_at: Optional[int] = None
    processed_at_iso: Optional[str] = None


class ProcessedDatabaseSeason(BaseModel):
    number: int
    name: str
    file_count: int
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None
    files: List[ProcessedDatabaseFile] = Field(default_factory=list)


class ProcessedDatabaseGroup(BaseModel):
    id: str
    type: Literal["tv", "movie", "folder"]
    title: str
    path: str
    file_count: int
    last_processed_at: Optional[int] = None
    last_processed_at_iso: Optional[str] = None
    seasons: List[ProcessedDatabaseSeason] = Field(default_factory=list)
    files: List[ProcessedDatabaseFile] = Field(default_factory=list)


class ProcessedDatabaseCatalog(BaseModel):
    total_files: int
    tv: List[ProcessedDatabaseGroup] = Field(default_factory=list)
    movies: List[ProcessedDatabaseGroup] = Field(default_factory=list)
    folders: List[ProcessedDatabaseGroup] = Field(default_factory=list)


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
    progress: Optional[SyncProgress] = None
    tdarr: Optional[TdarrStatus] = None


class SyncTriggerResponse(BaseModel):
    accepted: bool
    running: bool


class SyncSelectionPayload(BaseModel):
    series_id: int = Field(..., ge=0)
    seasons: Optional[List[int]] = None


class SyncRunRequest(BaseModel):
    dry_run: bool = False
    selections: Optional[List[SyncSelectionPayload]] = None


class TagFlowRoute(BaseModel):
    source: Literal["sonarr", "radarr"]
    tag: str = Field(..., min_length=1)
    flow_name: str = Field(..., min_length=1)
    input_subdir: Optional[str] = None


class RoutingSettingsUpdate(BaseModel):
    tdarr_server_url: str = ""
    tdarr_api_key: Optional[str] = None
    show_job_error_count: bool = False
    routes: List[TagFlowRoute] = Field(default_factory=list)


class RoutingSettingsResponse(BaseModel):
    tdarr_server_url: str = ""
    configured: bool = False
    show_job_error_count: bool = False
    routes: List[TagFlowRoute] = Field(default_factory=list)


class BuildVersion(BaseModel):
    git_version: str
    commit_date: str
    commit_sha: str
    source: Literal["env", "git", "unknown"]


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

_model_rebuild = getattr(RestoreJobStatus, "model_rebuild", None)
if callable(_model_rebuild):
    _model_rebuild()
else:  # Pydantic v1 fallback
    _update_forward_refs = getattr(RestoreJobStatus, "update_forward_refs", None)
    if callable(_update_forward_refs):
        _update_forward_refs()


def to_iso(timestamp: Optional[int], tz) -> Optional[str]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=tz).isoformat()
    except Exception:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
