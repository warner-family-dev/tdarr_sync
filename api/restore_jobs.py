import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .restore_service import RestoreService, RestoreOutcome, RestoreError, RestoreAuthError
from . import schemas


class RestoreJobConflictError(RestoreError):
    """Raised when a restore job is already in progress."""


logger = logging.getLogger("tdarr_sync.restore_jobs")


@dataclass
class RestoreJob:
    job_id: str
    request_id: str
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    status: str = "pending"  # pending | running | succeeded | failed
    result: Optional[schemas.RestoreResponse] = None
    error: Optional[str] = None
    selection_expr: Optional[str] = None
    structured: Optional[List[Dict[str, Optional[List[int]]]]] = None

    def to_status(self) -> schemas.RestoreJobStatus:
        created = int(self.created_at)
        started = int(self.started_at) if self.started_at else None
        finished = int(self.finished_at) if self.finished_at else None
        result_dict = self.result.model_dump() if self.result else None
        return schemas.RestoreJobStatus(
            job_id=self.job_id,
            request_id=self.request_id,
            status=self.status,
            created_at=created,
            started_at=started,
            finished_at=finished,
            result=result_dict,
            error=self.error,
        )


class RestoreJobManager:
    def __init__(self, restore_service: RestoreService):
        self._restore_service = restore_service
        self._jobs: Dict[str, RestoreJob] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        request_id: str,
        password: str,
        selection_expr: Optional[str],
        structured: Optional[List[Dict[str, Optional[List[int]]]]],
        *,
        build_response: Callable[[RestoreOutcome], schemas.RestoreResponse],
    ) -> RestoreJob:
        if password != self._restore_service.config.admin_password:
            raise RestoreAuthError("Invalid password.")

        with self._lock:
            if any(job.status in {"pending", "running"} for job in self._jobs.values()):
                raise RestoreJobConflictError("A restore is already running. Wait for it to complete.")

            job_id = uuid.uuid4().hex
            job = RestoreJob(
                job_id=job_id,
                request_id=request_id,
                created_at=time.time(),
                status="pending",
                selection_expr=selection_expr,
                structured=structured,
            )
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job, password, selection_expr, structured, build_response),
            daemon=True,
            name=f"restore-job-{job_id}",
        )
        thread.start()
        return job

    def _run_job(
        self,
        job: RestoreJob,
        password: str,
        selection_expr: Optional[str],
        structured: Optional[List[Dict[str, Optional[List[int]]]]],
        build_response: Callable[[RestoreOutcome], schemas.RestoreResponse],
    ):
        job.started_at = time.time()
        job.status = "running"
        logger.info("Restore job %s started (request_id=%s).", job.job_id, job.request_id)
        try:
            self._restore_service._current_request_id = job.request_id  # type: ignore[attr-defined]
            outcome = self._restore_service.restore(
                password=password,
                selection_expr=selection_expr,
                structured=structured,
            )
            response = build_response(outcome)
            job.result = response
            job.status = "succeeded"
            logger.info(
                "Restore job %s succeeded (request_id=%s) restored=%d.",
                job.job_id,
                job.request_id,
                response.summary.files_restored,
            )
        except RestoreError as exc:
            job.error = str(exc)
            job.status = "failed"
            logger.error("Restore job %s failed: %s", job.job_id, exc)
        except Exception as exc:  # pragma: no cover
            job.error = f"Unexpected error: {exc}"
            job.status = "failed"
            logger.exception("Restore job %s failed with unexpected error.", job.job_id)
        finally:
            job.finished_at = time.time()
            self._restore_service._current_request_id = None  # type: ignore[attr-defined]
            self._cleanup_old_jobs()

    def _cleanup_old_jobs(self, max_jobs: int = 20):
        with self._lock:
            if len(self._jobs) <= max_jobs:
                return
            sorted_jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            for job in sorted_jobs[max_jobs:]:
                self._jobs.pop(job.job_id, None)

    def get(self, job_id: str) -> schemas.RestoreJobStatus:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return job.to_status()

    def list_recent(self, limit: int = 10) -> List[schemas.RestoreJobStatus]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
            return [job.to_status() for job in jobs]
