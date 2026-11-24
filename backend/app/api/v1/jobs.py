from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.models import BackgroundJob, User
from app.services import job_handlers  # noqa: F401 (register handlers)
from app.services.jobs import create_job, execute_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def submit_job(bg: BackgroundTasks, db: Session, user: User, job_type: str, params: dict | None = None) -> dict:
    job = create_job(db, pharmacy_id=user.pharmacy_id, user_id=user.id, job_type=job_type, params=params)
    db.commit()
    if get_settings().use_celery:
        from app.worker import run_job
        run_job.delay(job.id)
    else:
        bg.add_task(execute_job, db.get_bind(), job.id)
    return {"job_id": job.id, "status": "queued"}


@router.get("/{job_id}")
def job_status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.pharmacy_id == user.pharmacy_id))
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job_id": job.id, "type": job.job_type, "status": job.status, "progress": job.progress,
            "result": job.result, "error": job.error, "created_at": job.created_at, "finished_at": job.finished_at}
