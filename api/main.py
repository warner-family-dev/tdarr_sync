import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from logging.handlers import WatchedFileHandler
from starlette.responses import JSONResponse

from . import db, schemas
from .build_version import resolve_build_version
from .settings import settings
from .sync_runner import SyncAlreadyRunningError, SyncRunner
from .tdarr_client import fetch_tdarr_status
from sync_progress import read_progress_file
from runtime_settings import load_runtime_settings, save_runtime_settings
from .restore_service import (
    RestoreAuthError,
    RestoreConfigurationError,
    RestoreError,
    RestoreNotFoundError,
    RestoreSelectionError,
    RestoreService,
)
from .restore_jobs import RestoreJobManager, RestoreJobConflictError


class TZFormatter(logging.Formatter):
    converter = datetime.fromtimestamp

    def __init__(self, fmt: str, tz):
        super().__init__(fmt)
        self.tz = tz

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


logger = logging.getLogger("tdarr_sync.api")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = TZFormatter("%(asctime)s %(levelname)s [API] %(message)s", settings.zoneinfo)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if settings.log_file:
        file_handler = WatchedFileHandler(settings.log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


app = FastAPI(title="Tdarr Sync API", version="0.1.0")
API_AUTH_TOKEN = settings.require_api_auth_token()

allow_origins = ["*"] if settings.allow_all_cors else settings.cors_allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["http://localhost:3000"],
    allow_credentials=not settings.allow_all_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_bearer_auth(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token.strip(), API_AUTH_TOKEN):
        return JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)

runner = SyncRunner(settings.sync_script_path, settings.sync_python_executable, settings.sync_progress_file)

try:
    restore_service = RestoreService()
except RestoreConfigurationError as exc:  # pragma: no cover - configuration issue
    logger.error("Restore service disabled: %s", exc)
    restore_service = None
    restore_jobs = None
else:
    restore_jobs = RestoreJobManager(restore_service)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@app.on_event("startup")
def on_startup():
    logger.info("Tdarr Sync API started")
    logger.info("Database file: %s", settings.state_db_file)
    if not settings.state_db_file.exists():
        logger.warning("State DB not found yet; run will create %s", settings.state_db_file)


@app.get("/health")
def health():
    return {"status": "ok", "time": _now_iso()}


@app.get("/version", response_model=schemas.BuildVersion)
def get_version():
    return schemas.BuildVersion(**resolve_build_version())


@app.get("/config")
def get_config():
    data = settings.sanitized()
    data["environment"] = {
        "hostname": os.getenv("HOSTNAME", ""),
        "tz": settings.tz,
    }
    data["build"] = resolve_build_version()
    return data


@app.get("/settings/routing", response_model=schemas.RoutingSettings)
def get_routing_settings():
    data = load_runtime_settings(settings.runtime_settings_file)
    return schemas.RoutingSettings(**data)


@app.put("/settings/routing", response_model=schemas.RoutingSettings)
def update_routing_settings(payload: schemas.RoutingSettings):
    body = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    try:
        saved = save_runtime_settings(body, settings.runtime_settings_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Updated routing settings (%d routes)", len(saved.get("routes", [])))
    return schemas.RoutingSettings(**saved)


@app.get("/processed-files", response_model=List[schemas.ProcessedFile])
def list_processed_files(limit: int = Query(default=50, le=500, gt=0), offset: int = Query(default=0, ge=0)):
    rows = db.fetch_processed_files(settings.state_db_file, limit=limit, offset=offset)
    tz = settings.zoneinfo
    response = []
    for row in rows:
        response.append(
            schemas.ProcessedFile(
                file_path=row["file_path"],
                processed_at=row["processed_at"],
                processed_at_iso=schemas.to_iso(row["processed_at"], tz),
            )
        )
    return response


@app.get("/processed-files/catalog", response_model=schemas.ProcessedDatabaseCatalog)
def processed_files_catalog():
    catalog = db.fetch_processed_catalog(settings.state_db_file)
    tz = settings.zoneinfo

    def enrich_file(file_item: dict) -> dict:
        return {
            **file_item,
            "processed_at_iso": schemas.to_iso(file_item.get("processed_at"), tz),
        }

    def enrich_group(group: dict) -> dict:
        seasons = []
        for season in group.get("seasons", []):
            seasons.append(
                {
                    **season,
                    "last_processed_at_iso": schemas.to_iso(season.get("last_processed_at"), tz),
                    "files": [enrich_file(item) for item in season.get("files", [])],
                }
            )
        return {
            **group,
            "last_processed_at_iso": schemas.to_iso(group.get("last_processed_at"), tz),
            "seasons": seasons,
            "files": [enrich_file(item) for item in group.get("files", [])],
        }

    return schemas.ProcessedDatabaseCatalog(
        total_files=catalog["total_files"],
        tv=[enrich_group(item) for item in catalog["tv"]],
        movies=[enrich_group(item) for item in catalog["movies"]],
        folders=[enrich_group(item) for item in catalog["folders"]],
    )


@app.get("/processed-files/records", response_model=List[schemas.ProcessedDatabaseFile])
def processed_file_records(
    category: str = Query(..., pattern="^(tv|movies|folders)$"),
    group_id: str = Query(..., min_length=1),
    season_number: int | None = Query(default=None),
):
    rows = db.fetch_processed_records(
        settings.state_db_file,
        category=category,
        group_id=group_id,
        season_number=season_number,
    )
    tz = settings.zoneinfo
    return [
        schemas.ProcessedDatabaseFile(
            file_path=row["file_path"],
            file_name=row["file_name"],
            processed_at=row["processed_at"],
            processed_at_iso=schemas.to_iso(row["processed_at"], tz),
        )
        for row in rows
    ]


@app.post("/processed-files/delete", response_model=schemas.ProcessedFileBulkDeleteResponse)
def delete_processed_file_markers(payload: schemas.ProcessedFileDeleteRequest):
    paths = [path for path in payload.file_paths if path]
    if not paths:
        raise HTTPException(status_code=400, detail="At least one database record must be selected.")

    deleted_count = db.delete_processed_entries(settings.state_db_file, paths)
    logger.info("Deleted %d processed marker(s) from %d requested path(s).", deleted_count, len(paths))
    return schemas.ProcessedFileBulkDeleteResponse(requested_count=len(paths), deleted_count=deleted_count)


@app.delete("/processed-files", response_model=schemas.ProcessedFileDeleteResponse)
def delete_processed_file_marker(file_path: str = Query(..., min_length=1)):
    deleted_count = db.delete_processed_entries(settings.state_db_file, [file_path])
    logger.info("Deleted processed marker for %s (deleted=%d)", file_path, deleted_count)
    return schemas.ProcessedFileDeleteResponse(
        deleted=deleted_count > 0,
        deleted_count=deleted_count,
        file_path=file_path,
    )


@app.get("/metrics/summary", response_model=schemas.ProcessedSummary)
def metrics_summary():
    summary = db.fetch_summary(settings.state_db_file)
    stats = db.database_file_stats(settings.state_db_file)
    tz = settings.zoneinfo
    return schemas.ProcessedSummary(
        total_processed=summary["total"],
        last_processed_at=summary["last_processed_at"],
        last_processed_at_iso=schemas.to_iso(summary["last_processed_at"], tz),
        earliest_processed_at=summary["earliest_processed_at"],
        earliest_processed_at_iso=schemas.to_iso(summary["earliest_processed_at"], tz),
        database_size_bytes=stats["size_bytes"],
        database_last_modified=stats["last_modified"],
        database_last_modified_iso=schemas.to_iso(stats["last_modified"], tz),
    )


@app.get("/sync/status", response_model=schemas.SyncStatus)
def sync_status():
    status = runner.status()
    tz = settings.zoneinfo
    progress = read_progress_file(settings.sync_progress_file)
    if progress:
        for key in ("started_at", "phase_started_at", "updated_at", "finished_at"):
            progress[f"{key}_iso"] = schemas.to_iso(progress.get(key), tz)
    return schemas.SyncStatus(
        running=status["running"],
        last_started_at=status["last_started_at"],
        last_started_at_iso=schemas.to_iso(status["last_started_at"], tz),
        last_finished_at=status["last_finished_at"],
        last_finished_at_iso=schemas.to_iso(status["last_finished_at"], tz),
        last_exit_code=status["last_exit_code"],
        last_error=status["last_error"],
        progress=progress,
        tdarr=fetch_tdarr_status(settings.runtime_settings_file),
    )


@app.post("/sync/run", response_model=schemas.SyncTriggerResponse)
def trigger_sync(dry_run: bool = False, payload: schemas.SyncRunRequest | None = Body(default=None)):
    request = payload or schemas.SyncRunRequest()
    structured = None
    if request.selections:
        structured = []
        for item in request.selections:
            seasons = None
            if item.seasons is not None:
                seasons = [int(season) for season in item.seasons if isinstance(season, int)]
            structured.append({"series_id": int(item.series_id), "seasons": seasons})

    effective_dry_run = bool(dry_run or request.dry_run)
    try:
        runner.trigger(dry_run=effective_dry_run, selection=structured)
        return schemas.SyncTriggerResponse(accepted=True, running=True)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/restore/series", response_model=schemas.RestoreSeriesList)
def list_restore_series():
    if restore_service is None:
        raise HTTPException(status_code=503, detail="Restore service is not configured.")

    try:
        entries = restore_service.series_catalog()
    except RestoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return schemas.RestoreSeriesList(
        series=[
            schemas.RestoreSeriesEntry(
                index=item.index,
                series_id=item.series_id,
                title=item.title,
                processed=item.processed,
                total=item.total,
                status=item.status,
                last_processed_at=item.last_processed_at,
                last_processed_at_iso=item.last_processed_at_iso,
                seasons=[
                    schemas.RestoreSeasonEntry(
                        number=season.number,
                        name=season.name,
                        processed=season.processed,
                        total=season.total,
                        status=season.status,
                        last_processed_at=season.last_processed_at,
                        last_processed_at_iso=season.last_processed_at_iso,
                    )
                    for season in item.seasons
                ],
            )
            for item in entries
        ]
    )


def _outcome_to_response(outcome) -> schemas.RestoreResponse:
    summary = schemas.RestoreSummary(
        series_requested=outcome.series_requested,
        series_processed=outcome.series_processed,
        files_restored=outcome.files_restored,
        files_skipped_missing_db=outcome.files_skipped_missing_db,
        files_skipped_missing_archive=outcome.files_skipped_missing_archive,
    )
    results = [
        schemas.RestoreSeriesResult(
            series_id=result.series_id,
            title=result.title,
            selected_seasons=result.selected_seasons,
            restored=result.restored,
            archived_transcodes=result.archived_transcodes,
            skipped_missing_db=result.skipped_missing_db,
            skipped_missing_archive=result.skipped_missing_archive,
            skipped_outside_library=result.skipped_outside_library,
            errors=result.errors,
        )
        for result in outcome.results
    ]
    return schemas.RestoreResponse(summary=summary, results=results, messages=outcome.messages)


@app.post("/restore/run", response_model=schemas.RestoreRunResponse)
def run_restore(payload: schemas.RestoreRequest):
    if restore_service is None:
        raise HTTPException(status_code=503, detail="Restore service is not configured.")

    status = runner.status()
    if status.get("running"):
        raise HTTPException(status_code=409, detail="Sync is currently running; wait for it to finish.")

    request_id = payload.request_id or str(uuid.uuid4())
    logger.info(
        "Restore request received (request_id=%s): selection=%s structured=%s",
        request_id,
        payload.selection,
        len(payload.selections or []),
    )

    structured = None
    if payload.selections:
        structured = [{"series_id": item.series_id, "seasons": item.seasons} for item in payload.selections]

    wait_for_completion = bool(payload.wait_for_completion)

    def execute_restore():
        try:
            restore_service._current_request_id = request_id  # type: ignore[attr-defined]
            outcome = restore_service.restore(
                password=payload.password,
                selection_expr=payload.selection,
                structured=structured,
            )
            return outcome
        finally:
            restore_service._current_request_id = None  # type: ignore[attr-defined]

    if wait_for_completion:
        try:
            outcome = execute_restore()
        except RestoreAuthError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RestoreSelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RestoreNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RestoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            logger.exception("Restore run failed with unexpected error")
            raise HTTPException(status_code=500, detail="Restore failed due to an unexpected error.") from exc
        return _outcome_to_response(outcome)

    if restore_jobs is None:
        raise HTTPException(status_code=503, detail="Restore service is not configured.")

    try:
        job = restore_jobs.submit(
            request_id=request_id,
            password=payload.password,
            selection_expr=payload.selection,
            structured=structured,
            build_response=_outcome_to_response,
        )
    except RestoreJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RestoreAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RestoreSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RestoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RestoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Restore job submitted (request_id=%s, job_id=%s)", request_id, job.job_id)
    return schemas.RestoreTriggerResponse(job_id=job.job_id, request_id=job.request_id, status="submitted")


@app.get("/restore/jobs/{job_id}", response_model=schemas.RestoreJobStatus)
def get_restore_job(job_id: str):
    if restore_jobs is None:
        raise HTTPException(status_code=503, detail="Restore service is not configured.")
    try:
        status = restore_jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Restore job not found.") from None
    return status
