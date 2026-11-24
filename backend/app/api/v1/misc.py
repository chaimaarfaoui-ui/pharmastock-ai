"""Notifications and demo-data loading."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import get_owned
from app.api.v1.jobs import submit_job
from app.core.db import get_db
from app.models import Medicine, Notification, User
from app.services.audit import log_action

router = APIRouter(tags=["notifications"])
READ = require_permission("inventory:read")


class NotifStatus(BaseModel):
    status: str = Field(pattern="^(read|resolved|unread)$")


@router.get("/notifications")
def list_notifications(status: str | None = None, limit: int = Query(50, ge=1, le=200), u: User = Depends(READ), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.pharmacy_id == u.pharmacy_id)
    if status:
        stmt = stmt.where(Notification.status == status)
    unread = db.scalar(select(func.count()).where(Notification.pharmacy_id == u.pharmacy_id, Notification.status == "unread"))
    rows = db.scalars(stmt.order_by(Notification.id.desc()).limit(limit))
    return {"unread": unread, "items": [{"id": n.id, "type": n.type, "severity": n.severity, "title": n.title, "body": n.body,
                                         "entity_type": n.entity_type, "entity_id": n.entity_id, "status": n.status,
                                         "created_at": n.created_at} for n in rows]}


@router.patch("/notifications/{nid}")
def set_notification(nid: int, body: NotifStatus, u: User = Depends(READ), db: Session = Depends(get_db)):
    n = get_owned(db, Notification, nid, u.pharmacy_id)
    n.status = body.status
    db.commit()
    return {"id": n.id, "status": n.status}


@router.post("/notifications/read-all")
def read_all(u: User = Depends(READ), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.pharmacy_id == u.pharmacy_id, Notification.status == "unread")).all()
    for n in rows:
        n.status = "read"
    db.commit()
    return {"updated": len(rows)}


class DemoIn(BaseModel):
    seed: int = 42
    days: int = Field(default=540, ge=120, le=900)
    n_medicines: int = Field(default=20, ge=3, le=24)


@router.post("/demo/seed", status_code=202)
def seed_demo(body: DemoIn, bg: BackgroundTasks, u: User = Depends(require_permission("settings:manage")), db: Session = Depends(get_db)):
    """Loads SYNTHETIC demonstration data into an empty pharmacy and labels the pharmacy as synthetic."""
    if db.scalar(select(func.count()).select_from(Medicine).where(Medicine.pharmacy_id == u.pharmacy_id)):
        raise HTTPException(409, "Demo data can only be loaded into a pharmacy with no medicines")
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="demo.seed_requested", details=body.model_dump())
    return submit_job(bg, db, u, "seed_demo", body.model_dump())
