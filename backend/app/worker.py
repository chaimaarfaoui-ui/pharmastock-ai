"""Optional Celery worker. Enable with USE_CELERY=true and run: celery -A app.worker.celery_app worker
Uses the exact same job handlers as the in-process BackgroundTasks executor."""
from celery import Celery
from app.core.config import get_settings
from app.core.db import engine
import app.services.job_handlers  # noqa: F401  (registers handlers)
from app.services.jobs import execute_job

celery_app = Celery("pharmastock", broker=get_settings().redis_url, backend=get_settings().redis_url)


@celery_app.task(name="run_job")
def run_job(job_id: str) -> None:
    execute_job(engine, job_id)
