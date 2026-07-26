from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SyncProgress(BaseModel):
    run_id: str
    state: str
    phase: str
    action: str = ""
    dry_run: bool = False
    source: str | None = None
    title: str | None = None
    path: str | None = None
    destination: str | None = None
    message: str | None = None
    completed_items: int = 0
    total_items: int | None = None
    skipped_items: int = 0
    failed_items: int = 0
    percent: float | None = None
    eta_seconds: int | None = None
    started_at: int | None = None
    started_at_iso: str | None = None
    phase_started_at: int | None = None
    phase_started_at_iso: str | None = None
    updated_at: int | None = None
    updated_at_iso: str | None = None
    finished_at: int | None = None
    finished_at_iso: str | None = None
    elapsed_seconds: int | None = None
    error: str | None = None


class TdarrWorkerStatus(BaseModel):
    id: str
    name: str = ""
    node: str = ""
    node_id: str = ""
    status: str = ""
    file: str | None = None
    title: str | None = None
    progress: float | None = None
    eta_seconds: int | None = None


class TdarrNodeStatus(BaseModel):
    id: str
    name: str
    address: str = ""
    paused: bool = False
    worker_limit: int = 0
    active_worker_count: int = 0
    workers: list[TdarrWorkerStatus] = Field(default_factory=list)


class TdarrStatus(BaseModel):
    configured: bool = False
    reachable: bool = False
    server_url: str = ""
    error: str | None = None
    queue_count: int | None = None
    error_count: int | None = None
    job_error_count: int | None = None
    show_job_error_count: bool = False
    active_worker_count: int = 0
    workers: list[TdarrWorkerStatus] = Field(default_factory=list)
    nodes: list[TdarrNodeStatus] = Field(default_factory=list)


class ProcessedFile(BaseModel):
    file_path: str = Field(...)
    processed_at: int | None = Field(default=None, description="Epoch seconds")
    processed_at_iso: str | None = Field(default=None, description="ISO8601 timestamp")


class ProcessedFileDeleteResponse(BaseModel):
    deleted: bool
    deleted_count: int
    file_path: str


class ProcessedFileDeleteRequest(BaseModel):
    file_paths: list[str] = Field(default_factory=list)


class ProcessedFileBulkDeleteResponse(BaseModel):
    requested_count: int
    deleted_count: int


class ProcessedDatabaseFile(BaseModel):
    file_path: str
    file_name: str
    processed_at: int | None = None
    processed_at_iso: str | None = None


class ProcessedDatabaseSeason(BaseModel):
    number: int
    name: str
    file_count: int
    last_processed_at: int | None = None
    last_processed_at_iso: str | None = None
    files: list[ProcessedDatabaseFile] = Field(default_factory=list)


class ProcessedDatabaseGroup(BaseModel):
    id: str
    type: Literal["tv", "movie", "folder"]
    title: str
    path: str
    file_count: int
    last_processed_at: int | None = None
    last_processed_at_iso: str | None = None
    seasons: list[ProcessedDatabaseSeason] = Field(default_factory=list)
    files: list[ProcessedDatabaseFile] = Field(default_factory=list)


class ProcessedDatabaseCatalog(BaseModel):
    total_files: int
    tv: list[ProcessedDatabaseGroup] = Field(default_factory=list)
    movies: list[ProcessedDatabaseGroup] = Field(default_factory=list)
    folders: list[ProcessedDatabaseGroup] = Field(default_factory=list)


class ProcessedSummary(BaseModel):
    total_processed: int
    last_processed_at: int | None = None
    last_processed_at_iso: str | None = None
    earliest_processed_at: int | None = None
    earliest_processed_at_iso: str | None = None
    database_size_bytes: int | None = None
    database_last_modified: int | None = None
    database_last_modified_iso: str | None = None


class SyncStatus(BaseModel):
    running: bool
    last_started_at: int | None = None
    last_started_at_iso: str | None = None
    last_finished_at: int | None = None
    last_finished_at_iso: str | None = None
    last_exit_code: int | None = None
    last_error: str | None = None
    progress: SyncProgress | None = None
    tdarr: TdarrStatus | None = None


class SyncTriggerResponse(BaseModel):
    accepted: bool
    running: bool


class SyncSelectionPayload(BaseModel):
    series_id: int = Field(..., ge=0)
    seasons: list[int] | None = None


class SyncRunRequest(BaseModel):
    dry_run: bool = False
    selections: list[SyncSelectionPayload] | None = None


class TagFlowRoute(BaseModel):
    source: Literal["sonarr", "radarr"]
    tag: str = Field(..., min_length=1)
    flow_name: str = Field(..., min_length=1)
    input_subdir: str | None = None


class RoutingSettingsUpdate(BaseModel):
    tdarr_server_url: str = ""
    tdarr_api_key: str | None = None
    show_job_error_count: bool = False
    routes: list[TagFlowRoute] = Field(default_factory=list)


class RoutingSettingsResponse(BaseModel):
    tdarr_server_url: str = ""
    configured: bool = False
    show_job_error_count: bool = False
    routes: list[TagFlowRoute] = Field(default_factory=list)


class BuildVersion(BaseModel):
    image_tag: str
    image_published_date: str
    git_version: str
    commit_date: str
    commit_sha: str
    source: Literal["image", "env", "git", "unknown"]


class RestoreSeasonEntry(BaseModel):
    number: int
    name: str
    processed: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    status: Literal["full", "partial", "none"]
    last_processed_at: int | None = None
    last_processed_at_iso: str | None = None


class RestoreSeriesEntry(BaseModel):
    index: int = Field(..., ge=1)
    series_id: int = Field(..., ge=0)
    title: str
    processed: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    status: Literal["full", "partial", "none"]
    last_processed_at: int | None = None
    last_processed_at_iso: str | None = None
    seasons: list[RestoreSeasonEntry] = Field(default_factory=list)


class RestoreSeriesList(BaseModel):
    series: list[RestoreSeriesEntry] = Field(default_factory=list)


class RestoreSelectionPayload(BaseModel):
    series_id: int
    seasons: list[int] | None = None


class RestoreRequest(BaseModel):
    password: str = Field(..., min_length=1)
    selection: str | None = Field(default=None)
    selections: list[RestoreSelectionPayload] | None = None
    request_id: str | None = Field(
        default=None, description="Client correlation id for logging"
    )
    wait_for_completion: bool = Field(
        default=False,
        description="If true, wait for the restore to finish before responding.",
    )


class RestoreSeriesResult(BaseModel):
    series_id: int
    title: str
    selected_seasons: list[int] | None = None
    restored: list[str] = Field(default_factory=list)
    archived_transcodes: list[str] = Field(default_factory=list)
    skipped_missing_db: list[str] = Field(default_factory=list)
    skipped_missing_archive: list[str] = Field(default_factory=list)
    skipped_outside_library: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RestoreSummary(BaseModel):
    series_requested: int
    series_processed: int
    files_restored: int
    files_skipped_missing_db: int
    files_skipped_missing_archive: int


class RestoreResponse(BaseModel):
    summary: RestoreSummary
    results: list[RestoreSeriesResult] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class RestoreTriggerResponse(BaseModel):
    job_id: str
    request_id: str
    status: Literal["submitted", "pending", "running"] = "submitted"


class RestoreJobStatus(BaseModel):
    job_id: str
    request_id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    created_at: int
    started_at: int | None = None
    finished_at: int | None = None
    result: Optional["RestoreResponse"] = None
    error: str | None = None


RestoreRunResponse = RestoreResponse | RestoreTriggerResponse

_model_rebuild = getattr(RestoreJobStatus, "model_rebuild", None)
if callable(_model_rebuild):
    _model_rebuild()
else:  # Pydantic v1 fallback
    _update_forward_refs = getattr(RestoreJobStatus, "update_forward_refs", None)
    if callable(_update_forward_refs):
        _update_forward_refs()


def to_iso(timestamp: int | None, tz) -> str | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=tz).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
