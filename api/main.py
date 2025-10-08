import logging
import os
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db, schemas
from .settings import settings
from .sync_runner import SyncAlreadyRunningError, SyncRunner


logger = logging.getLogger("tdarr_sync.api")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(console_handler)

if settings.api_log_file:
    file_handler = logging.FileHandler(settings.api_log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)


app = FastAPI(title="Tdarr Sync API", version="0.1.0")

allow_origins = ["*"] if settings.allow_all_cors else settings.cors_allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runner = SyncRunner(settings.sync_script_path, settings.sync_python_executable)


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


@app.get("/config")
def get_config():
    data = settings.sanitized()
    data["environment"] = {
        "hostname": os.getenv("HOSTNAME", ""),
        "tz": settings.tz,
    }
    return data


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
    return schemas.SyncStatus(
        running=status["running"],
        last_started_at=status["last_started_at"],
        last_started_at_iso=schemas.to_iso(status["last_started_at"], tz),
        last_finished_at=status["last_finished_at"],
        last_finished_at_iso=schemas.to_iso(status["last_finished_at"], tz),
        last_exit_code=status["last_exit_code"],
        last_error=status["last_error"],
    )


@app.post("/sync/run", response_model=schemas.SyncTriggerResponse)
def trigger_sync(dry_run: bool = False):
    try:
        runner.trigger(dry_run=dry_run)
        return schemas.SyncTriggerResponse(accepted=True, running=True)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
