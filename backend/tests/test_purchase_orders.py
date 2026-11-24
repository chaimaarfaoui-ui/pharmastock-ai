from datetime import date, timedelta
from tests.conftest import add_med, make_user, register, login

API = "/api/v1"


def setup(client, admin):
    sup = client.post(f"{API}/suppliers", headers=admin, json={"name": "MedSupply", "default_lead_time_days": 3}).json()
    m1, m2 = add_med(client, admin, "Drug A"), add_med(client, admin, "Drug B")
    po = client.post(f"{API}/purchase-orders", headers=admin, json={
        "supplier_id": sup["id"], "items": [
            {"medicine_id": m1["id"], "quantity_ordered": 100, "unit_price": "2.50"},
            {"medicine_id": m2["id"], "quantity_ordered": 50, "unit_price": "4.00"}]})
    assert po.status_code == 201, po.text
    return sup, m1, m2, po.json()


def line(item, qty, number="L1", days=200):
    return {"po_item_id": item["id"], "batch_number": number, "quantity": qty,
            "expiration_date": str(date.today() + timedelta(days=days))}


def test_full_lifecycle_and_stock_effect(client, admin):
    _, m1, m2, po = setup(client, admin)
    assert po["status"] == "draft" and po["total_value"] == "450.00"
    # cannot receive before it is ordered
    assert client.post(f"{API}/purchase-orders/{po['id']}/receive", headers=admin, json={"lines": [line(po["items"][0], 10)]}).status_code == 409
    assert client.post(f"{API}/purchase-orders/{po['id']}/order", headers=admin).status_code == 409   # must approve first
    assert client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=admin).json()["status"] == "approved"
    o = client.post(f"{API}/purchase-orders/{po['id']}/order", headers=admin).json()
    assert o["status"] == "ordered" and o["ordered_at"]

    emp = make_user(client, admin, "emp@example.com", "employee")     # employees can receive deliveries
    r = client.post(f"{API}/purchase-orders/{po['id']}/receive", headers=emp, json={"lines": [line(po["items"][0], 60, "A1")]})
    assert r.status_code == 200 and r.json()["status"] == "partially_received"
    assert client.get(f"{API}/medicines/{m1['id']}", headers=admin).json()["available_stock"] == 60
    r = client.post(f"{API}/purchase-orders/{po['id']}/receive", headers=emp, json={"lines": [
        line(po["items"][0], 40, "A2"), line(po["items"][1], 50, "B1")]})
    assert r.json()["status"] == "completed"
    assert client.get(f"{API}/medicines/{m1['id']}", headers=admin).json()["available_stock"] == 100
    assert client.post(f"{API}/purchase-orders/{po['id']}/cancel", headers=admin).status_code == 409


def test_over_receipt_rejected_and_atomic(client, admin):
    _, m1, m2, po = setup(client, admin)
    client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=admin)
    client.post(f"{API}/purchase-orders/{po['id']}/order", headers=admin)
    r = client.post(f"{API}/purchase-orders/{po['id']}/receive", headers=admin, json={"lines": [
        line(po["items"][1], 10, "B1"), line(po["items"][0], 101, "A1")]})
    assert r.status_code == 409
    # the valid first line must not have been applied
    assert client.get(f"{API}/medicines/{m2['id']}", headers=admin).json()["total_stock"] == 0
    assert client.get(f"{API}/purchase-orders/{po['id']}", headers=admin).json()["status"] == "ordered"


def test_employee_cannot_approve_or_create(client, admin):
    _, _, _, po = setup(client, admin)
    emp = make_user(client, admin, "emp@example.com", "employee")
    assert client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=emp).status_code == 403
    assert client.post(f"{API}/purchase-orders/{po['id']}/cancel", headers=emp).status_code == 403


def test_po_tenant_isolation_and_validation(client, admin):
    sup, m1, _, po = setup(client, admin)
    register(client, "Pharma B", "b@example.com")
    hb = login(client, "b@example.com")
    assert client.get(f"{API}/purchase-orders/{po['id']}", headers=hb).status_code == 404
    assert client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=hb).status_code == 404
    assert client.post(f"{API}/purchase-orders", headers=hb, json={"supplier_id": sup["id"], "items": [
        {"medicine_id": m1["id"], "quantity_ordered": 1, "unit_price": "1"}]}).status_code == 422
    dup = client.post(f"{API}/purchase-orders", headers=admin, json={"supplier_id": sup["id"], "items": [
        {"medicine_id": m1["id"], "quantity_ordered": 1, "unit_price": "1"},
        {"medicine_id": m1["id"], "quantity_ordered": 2, "unit_price": "1"}]})
    assert dup.status_code == 422
    assert client.post(f"{API}/purchase-orders", headers=admin, json={"supplier_id": sup["id"], "items": [
        {"medicine_id": m1["id"], "quantity_ordered": 0, "unit_price": "1"}]}).status_code == 422
