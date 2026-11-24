"""Background jobs: status is persisted in background_jobs so the UI can poll /jobs/{id}.

Default executor is FastAPI BackgroundTasks (works with no extra infrastructure). If USE_CELERY=true the
same handler runs inside a Celery worker (see app/worker.py). Handlers never receive request-scoped sessions.
"""
import traceback
import uuid
from datetime import datetime, timezone
from typing import Callable
from sqlalchemy.orm import Session, sessionmaker
from app.models import BackgroundJob

Handler = Callable[..., dict]
HANDLERS: dict[str, Handler] = {}


def register(job_type: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


def create_job(db: Session, *, pharmacy_id: int, user_id: int | None, job_type: str, params: dict | None) -> BackgroundJob:
    if job_type not in HANDLERS:
        raise ValueError(f"Unknown job type {job_type}")
    job = BackgroundJob(id=uuid.uuid4().hex, pharmacy_id=pharmacy_id, user_id=user_id, job_type=job_type,
                        params=params or {}, status="queued")
    db.add(job)
    db.flush()
    return job


def execute_job(bind, job_id: str) -> None:
    """Runs a queued job in its own session/transaction. Never raises: failures are stored on the job row."""
    Session_ = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with Session_() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status, job.progress = "running", 0.0
        db.commit()

        def progress(p: float) -> None:
            job.progress = max(0.0, min(1.0, p))
            db.commit()

        try:
            result = HANDLERS[job.job_type](db, pharmacy_id=job.pharmacy_id, user_id=job.user_id,
                                            params=job.params or {}, progress=progress)
            job.result, job.status, job.progress = result, "succeeded", 1.0
        except Exception as exc:  # noqa: BLE001 - job boundary
            db.rollback()
            job = db.get(BackgroundJob, job_id)
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
