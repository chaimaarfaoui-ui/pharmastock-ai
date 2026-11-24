from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_owned(db: Session, model, obj_id: int, pharmacy_id: int):
    """Fetch a tenant-owned row or 404. Cross-tenant ids look identical to missing ones."""
    obj = db.scalar(select(model).where(model.id == obj_id, model.pharmacy_id == pharmacy_id))
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def check_fk_owned(db: Session, model, obj_id: int | None, pharmacy_id: int, label: str):
    """Reject references to rows belonging to another pharmacy (or nonexistent)."""
    if obj_id is None:
        return
    ok = db.scalar(select(model.id).where(model.id == obj_id, model.pharmacy_id == pharmacy_id))
    if ok is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown {label}")
