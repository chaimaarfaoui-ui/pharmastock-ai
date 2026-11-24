from tests.conftest import register, login


def test_register_login_me(client):
    u = register(client)
    assert u["role"] == "admin"
    h = login(client, "a@example.com")
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["email"] == "a@example.com"


def test_duplicate_email_rejected(client):
    register(client)
    r = client.post("/api/v1/auth/register", json={
        "pharmacy_name": "Other Pharmacy", "full_name": "Someone", "email": "a@example.com", "password": "correct-horse-1"})
    assert r.status_code == 409


def test_wrong_password_and_unknown_user_same_error(client):
    register(client)
    r1 = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "nope"})
    r2 = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={
        "pharmacy_name": "X", "full_name": "Someone", "email": "w@example.com", "password": "short"})
    assert r.status_code == 422


def test_protected_route_needs_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_token_cannot_be_used_as_access(client):
    register(client)
    r = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}).json()
    h = {"Authorization": f"Bearer {r['refresh_token']}"}
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r["refresh_token"]}).status_code == 200
