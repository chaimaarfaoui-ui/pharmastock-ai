from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Notification


def notify(db: Session, *, pharmacy_id: int, type_: str, severity: str, title: str, body: str | None = None,
           entity_type: str | None = None, entity_id: int | None = None) -> Notification | None:
    """Create an in-app notification unless an unresolved identical one already exists (dedupe)."""
    dup = db.scalar(select(Notification.id).where(
        Notification.pharmacy_id == pharmacy_id, Notification.type == type_, Notification.entity_type == entity_type,
        Notification.entity_id == entity_id, Notification.title == title, Notification.status != "resolved"))
    if dup:
        return None
    n = Notification(pharmacy_id=pharmacy_id, type=type_, severity=severity, title=title, body=body,
                     entity_type=entity_type, entity_id=entity_id)
    db.add(n)
    return n
