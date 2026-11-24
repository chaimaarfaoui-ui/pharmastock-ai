from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.permissions import ROLE_PERMISSIONS
from app.models import Role


def ensure_roles(db: Session) -> None:
    existing = set(db.scalars(select(Role.name)))
    for name in ROLE_PERMISSIONS:
        if name not in existing:
            db.add(Role(name=name))
    db.commit()
