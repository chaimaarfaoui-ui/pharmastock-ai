from sqlalchemy.orm import Session
from app.models.audit import AuditLog


def log_action(db: Session, *, pharmacy_id: int, user_id: int | None, action: str,
               entity_type: str | None = None, entity_id: int | None = None, details: dict | None = None) -> None:
    """Adds an audit row to the caller's transaction (commits with the business operation)."""
    db.add(AuditLog(pharmacy_id=pharmacy_id, user_id=user_id, action=action,
                    entity_type=entity_type, entity_id=entity_id, details=details))
