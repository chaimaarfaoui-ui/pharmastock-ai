from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.security import (create_access_token, create_refresh_token, decode_payload, hash_password,
                               verify_password)
from app.models import Pharmacy, RefreshToken, Role, User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterPharmacy, TokenPair, UserOut
from app.services.audit import log_action
from app.services.bootstrap import ensure_roles

router = APIRouter(prefix="/auth", tags=["auth"])

# Constant-time-ish: verify against a dummy hash when the user doesn't exist.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _issue(db: Session, user: User) -> TokenPair:
    refresh, jti, exp = create_refresh_token(user.id)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=exp))
    return TokenPair(access_token=create_access_token(user.id), refresh_token=refresh)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def revoke_all_for_user(db: Session, user_id: int) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))).all()
    for r in rows:
        r.revoked_at = now
    return len(rows)


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role.name,
                   pharmacy_id=u.pharmacy_id, is_active=u.is_active)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterPharmacy, db: Session = Depends(get_db)):
    """Self-service signup: creates a new pharmacy (tenant) and its first admin."""
    ensure_roles(db)
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    admin_role = db.scalar(select(Role).where(Role.name == "admin"))
    pharmacy = Pharmacy(name=body.pharmacy_name)
    db.add(pharmacy)
    db.flush()
    user = User(pharmacy_id=pharmacy.id, role_id=admin_role.id, email=body.email.lower(),
                full_name=body.full_name, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    log_action(db, pharmacy_id=pharmacy.id, user_id=user.id, action="pharmacy.registered",
               entity_type="pharmacy", entity_id=pharmacy.id)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/login", response_model=TokenPair)
@limiter.limit(get_settings().login_rate_limit)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    log_action(db, pharmacy_id=user.pharmacy_id, user_id=user.id, action="auth.login")
    pair = _issue(db, user)
    db.commit()
    return pair


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """Rotating refresh: a token works once. Presenting an already-used token revokes the whole family (likely theft)."""
    bad = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    payload = decode_payload(body.refresh_token, "refresh")
    if not payload or "jti" not in payload:
        raise bad
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    if row is None:
        raise bad
    user = db.get(User, row.user_id)
    if row.revoked_at is not None:
        if user:
            revoke_all_for_user(db, user.id)
            log_action(db, pharmacy_id=user.pharmacy_id, user_id=user.id, action="auth.refresh_reuse_detected")
        db.commit()
        raise bad
    if _aware(row.expires_at) < datetime.now(timezone.utc) or not user or not user.is_active:
        raise bad
    row.revoked_at = datetime.now(timezone.utc)
    pair = _issue(db, user)
    db.commit()
    return pair


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    """Revokes the presented refresh token. Always 204 so the endpoint reveals nothing about token validity."""
    payload = decode_payload(body.refresh_token, "refresh")
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload["jti"])) if payload and "jti" in payload else None
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        user = db.get(User, row.user_id)
        if user:
            log_action(db, pharmacy_id=user.pharmacy_id, user_id=user.id, action="auth.logout")
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
