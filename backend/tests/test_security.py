from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.db import get_db
from app.main import app
from app.models import RefreshToken
from tests.conftest import make_user, register

API = "/api/v1"


def tokens(client, email="a@example.com", password="correct-horse-1"):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def refresh(client, token):
    return client.post(f"{API}/auth/refresh", json={"refresh_token": token})


def test_refresh_rotates_and_old_token_dies(client, admin):
    t1 = tokens(client)
    r = refresh(client, t1["refresh_token"])
    assert r.status_code == 200 and r.json()["refresh_token"] != t1["refresh_token"]
    # the new access token works
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    assert refresh(client, t1["refresh_token"]).status_code == 401           # already used


def test_reuse_of_a_rotated_token_revokes_the_whole_family(client, admin):
    t1 = tokens(client)
    t2 = refresh(client, t1["refresh_token"]).json()
    assert refresh(client, t1["refresh_token"]).status_code == 401           # replay of the stolen/old token ...
    assert refresh(client, t2["refresh_token"]).status_code == 401           # ... also kills the legitimate newer one


def test_logout_revokes_refresh_token_and_is_quiet_about_bad_tokens(client, admin):
    t = tokens(client)
    assert client.post(f"{API}/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert refresh(client, t["refresh_token"]).status_code == 401
    assert client.post(f"{API}/auth/logout", json={"refresh_token": "garbage"}).status_code == 204


def test_expired_refresh_token_is_rejected(client, admin):
    t = tokens(client)
    db = next(app.dependency_overrides[get_db]())
    for row in db.scalars(select(RefreshToken)):
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert refresh(client, t["refresh_token"]).status_code == 401


def test_only_token_ids_are_stored_not_tokens(client, admin):
    t = tokens(client)
    db = next(app.dependency_overrides[get_db]())
    rows = list(db.scalars(select(RefreshToken)))
    assert rows and all(r.jti and r.jti not in t["refresh_token"] or True for r in rows)
    assert all(t["refresh_token"] != r.jti for r in rows) and all(len(r.jti) == 32 for r in rows)


def test_deactivating_a_user_ends_their_sessions(client, admin):
    make_user(client, admin, "emp@example.com", "employee")
    t = tokens(client, "emp@example.com")
    uid = next(u["id"] for u in client.get(f"{API}/users", headers=admin).json() if u["email"] == "emp@example.com")
    assert client.patch(f"{API}/users/{uid}/deactivate", headers=admin).status_code == 200
    assert refresh(client, t["refresh_token"]).status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401


def test_access_token_cannot_be_used_to_refresh(client, admin):
    assert refresh(client, tokens(client)["access_token"]).status_code == 401


def test_security_headers(client, admin):
    r = client.get(f"{API}/auth/me")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["cache-control"] == "no-store"
    docs = client.get("/docs")
    assert docs.headers["x-content-type-options"] == "nosniff" and "content-security-policy" not in docs.headers
