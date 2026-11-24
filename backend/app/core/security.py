import uuid
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from app.core.config import get_settings

_ph = PasswordHasher()
ALGO = "HS256"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _token(sub: str, kind: str, delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": sub, "type": kind, "iat": now, "exp": now + delta},
                      get_settings().secret_key, algorithm=ALGO)


def create_access_token(user_id: int) -> str:
    return _token(str(user_id), "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at). The jti is stored server-side so the token can be rotated and revoked."""
    jti = uuid.uuid4().hex
    delta = timedelta(days=get_settings().refresh_token_days)
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(user_id), "type": "refresh", "jti": jti, "iat": now, "exp": now + delta},
                       get_settings().secret_key, algorithm=ALGO)
    return token, jti, now + delta


def decode_payload(token: str, expected_type: str) -> dict | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    return data if data.get("type") == expected_type else None


def decode_token(token: str, expected_type: str) -> int | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    if data.get("type") != expected_type:
        return None
    return int(data["sub"])
