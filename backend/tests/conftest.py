import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LOGIN_RATE_LIMIT"] = "1000/minute"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (register tables)
from app.core.db import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client, name="Pharma A", email="a@example.com", password="correct-horse-1"):
    r = client.post("/api/v1/auth/register", json={
        "pharmacy_name": name, "full_name": "Admin " + name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email, password="correct-horse-1"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_user(client, admin_h, email, role):
    r = client.post("/api/v1/users", headers=admin_h, json={
        "full_name": "Test " + role, "email": email, "password": "correct-horse-1", "role": role})
    assert r.status_code == 201, r.text
    return login(client, email)


@pytest.fixture()
def admin(client):
    register(client)
    return login(client, "a@example.com")


def add_med(client, h, name="Paracetamol 500mg", **kw):
    r = client.post("/api/v1/medicines", headers=h, json={"name": name, "min_stock_threshold": 10, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def receive(client, h, med_id, number, days_to_expiry, qty, cost="1.00"):
    from datetime import date, timedelta
    r = client.post("/api/v1/inventory/receipts", headers=h, json={
        "medicine_id": med_id, "batch_number": number, "quantity": qty, "unit_cost": cost,
        "expiration_date": str(date.today() + timedelta(days=days_to_expiry))})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]
