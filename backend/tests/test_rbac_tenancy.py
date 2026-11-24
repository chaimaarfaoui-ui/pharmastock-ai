from tests.conftest import register, login


def _make_user(client, h, email, role):
    return client.post("/api/v1/users", headers=h, json={
        "full_name": "Test " + role, "email": email, "password": "correct-horse-1", "role": role})


def test_admin_can_create_users_employee_cannot(client):
    register(client)
    admin = login(client, "a@example.com")
    assert _make_user(client, admin, "emp@example.com", "employee").status_code == 201
    emp = login(client, "emp@example.com")
    assert client.get("/api/v1/users", headers=emp).status_code == 403
    assert _make_user(client, emp, "x@example.com", "employee").status_code == 403


def test_manager_cannot_manage_users(client):
    register(client)
    admin = login(client, "a@example.com")
    _make_user(client, admin, "mgr@example.com", "manager")
    mgr = login(client, "mgr@example.com")
    assert client.get("/api/v1/users", headers=mgr).status_code == 403


def test_tenant_isolation_users(client):
    register(client, "Pharma A", "a@example.com")
    register(client, "Pharma B", "b@example.com")
    ha, hb = login(client, "a@example.com"), login(client, "b@example.com")
    emp = _make_user(client, hb, "bemp@example.com", "employee").json()

    # A only sees its own users
    emails = {u["email"] for u in client.get("/api/v1/users", headers=ha).json()}
    assert emails == {"a@example.com"}
    # A cannot deactivate B's user (404, not 403, so existence is not leaked)
    assert client.patch(f"/api/v1/users/{emp['id']}/deactivate", headers=ha).status_code == 404


def test_deactivated_user_loses_access(client):
    register(client)
    admin = login(client, "a@example.com")
    emp = _make_user(client, admin, "emp@example.com", "employee").json()
    emp_h = login(client, "emp@example.com")
    assert client.patch(f"/api/v1/users/{emp['id']}/deactivate", headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=emp_h).status_code == 401


def test_admin_cannot_deactivate_self(client):
    u = register(client)
    admin = login(client, "a@example.com")
    assert client.patch(f"/api/v1/users/{u['id']}/deactivate", headers=admin).status_code == 400
