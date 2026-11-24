from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.core.db import get_db
from app.core.security import hash_password
from app.models import Role, User
from app.schemas.auth import UserCreate, UserOut
from app.api.v1.auth import revoke_all_for_user
from app.services.audit import log_action

router = APIRouter(prefix="/users", tags=["users"])


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role.name,
                   pharmacy_id=u.pharmacy_id, is_active=u.is_active)


@router.get("", response_model=list[UserOut])
def list_users(admin: User = Depends(require_permission("users:manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.pharmacy_id == admin.pharmacy_id).order_by(User.id))
    return [_out(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: User = Depends(require_permission("users:manage")),
                db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    role = db.scalar(select(Role).where(Role.name == body.role))
    user = User(pharmacy_id=admin.pharmacy_id, role_id=role.id, email=body.email.lower(),
                full_name=body.full_name, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    log_action(db, pharmacy_id=admin.pharmacy_id, user_id=admin.id, action="user.created",
               entity_type="user", entity_id=user.id, details={"role": body.role})
    db.commit()
    db.refresh(user)
    return _out(user)


@router.patch("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(user_id: int, admin: User = Depends(require_permission("users:manage")),
                    db: Session = Depends(get_db)):
    # Tenant scoping: a user from another pharmacy is indistinguishable from "not found".
    user = db.scalar(select(User).where(User.id == user_id, User.pharmacy_id == admin.pharmacy_id))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate yourself")
    user.is_active = False
    revoke_all_for_user(db, user.id)
    log_action(db, pharmacy_id=admin.pharmacy_id, user_id=admin.id, action="user.deactivated",
               entity_type="user", entity_id=user.id)
    db.commit()
    return _out(user)
