import random
from datetime import date, timedelta
from tests.conftest import add_med, make_user, receive, register, login

API = "/api/v1"


def stock(client, h, med_id):
    return client.get(f"{API}/medicines/{med_id}", headers=h).json()


def test_fefo_takes_earliest_expiry_first(client, admin):
    m = add_med(client, admin)
    late = receive(client, admin, m["id"], "LATE", 300, 50)
    early = receive(client, admin, m["id"], "EARLY", 40, 30)
    mid = receive(client, admin, m["id"], "MID", 100, 30)
    r = client.post(f"{API}/sales", headers=admin, json={"medicine_id": m["id"], "quantity": 45})
    assert r.status_code == 201, r.text
    taken = {a["batch_number"]: a["quantity"] for a in r.json()["allocations"]}
    assert taken == {"EARLY": 30, "MID": 15}
    assert stock(client, admin, m["id"])["available_stock"] == 65


def test_expired_batches_never_issued(client, admin, ):
    m = add_med(client, admin)
    # an expired batch can't be received through the API, so create one by letting time pass in the DB
    receive(client, admin, m["id"], "OK", 100, 10)
    from app.core.db import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    from app.models import Batch
    old = Batch(pharmacy_id=1, medicine_id=m["id"], batch_number="OLD", expiration_date=date.today() - timedelta(days=1),
                quantity_received=500, quantity_remaining=500, unit_cost=1, received_date=date.today() - timedelta(days=200))
    db.add(old); db.commit()
    info = stock(client, admin, m["id"])
    assert info["total_stock"] == 510 and info["available_stock"] == 10   # expired stock is not available
    r = client.post(f"{API}/sales", headers=admin, json={"medicine_id": m["id"], "quantity": 11})
    assert r.status_code == 409 and r.json()["available"] == 10 and r.json()["code"] == "insufficient_stock"


def test_failed_sale_is_all_or_nothing(client, admin):
    m = add_med(client, admin)
    receive(client, admin, m["id"], "A", 100, 5)
    assert client.post(f"{API}/sales", headers=admin, json={"medicine_id": m["id"], "quantity": 6}).status_code == 409
    assert stock(client, admin, m["id"])["available_stock"] == 5
    assert client.get(f"{API}/inventory/movements?movement_type=sale", headers=admin).json()["total"] == 0


def test_cannot_receive_expired_batch(client, admin):
    m = add_med(client, admin)
    r = client.post(f"{API}/inventory/receipts", headers=admin, json={
        "medicine_id": m["id"], "batch_number": "X", "quantity": 5, "unit_cost": "1",
        "expiration_date": str(date.today() - timedelta(days=1))})
    assert r.status_code == 422 and r.json()["code"] == "expired_batch"


def test_adjustment_writeoff_and_returns(client, admin):
    m = add_med(client, admin)
    b = receive(client, admin, m["id"], "A", 100, 20)
    assert client.post(f"{API}/inventory/write-offs", headers=admin, json={"batch_id": b, "quantity": 5, "reason": "damaged"}).status_code == 201
    assert stock(client, admin, m["id"])["available_stock"] == 15
    assert client.post(f"{API}/inventory/adjustments", headers=admin, json={"batch_id": b, "new_quantity": 12, "reason": "count"}).json()["delta"] == -3
    assert client.post(f"{API}/inventory/returns/customer", headers=admin, json={"batch_id": b, "quantity": 2}).status_code == 201
    # cannot restock beyond what was received
    r = client.post(f"{API}/inventory/returns/customer", headers=admin, json={"batch_id": b, "quantity": 100})
    assert r.status_code == 409 and r.json()["code"] == "exceeds_received"
    assert client.post(f"{API}/inventory/write-offs", headers=admin, json={"batch_id": b, "quantity": 1000, "reason": "too many"}).status_code == 409
    assert client.post(f"{API}/inventory/write-offs", headers=admin, json={"batch_id": b, "quantity": 1, "reason": "x"}).status_code == 422


def test_employee_permissions(client, admin):
    emp = make_user(client, admin, "emp@example.com", "employee")
    m = add_med(client, admin)
    b = receive(client, emp, m["id"], "A", 100, 20)                       # may receive stock
    assert client.post(f"{API}/sales", headers=emp, json={"medicine_id": m["id"], "quantity": 1}).status_code == 201
    assert client.get(f"{API}/medicines", headers=emp).status_code == 200
    # but cannot change the catalog, write off, adjust, or buy
    assert client.post(f"{API}/medicines", headers=emp, json={"name": "X"}).status_code == 403
    assert client.post(f"{API}/inventory/write-offs", headers=emp, json={"batch_id": b, "quantity": 1, "reason": "nope!"}).status_code == 403
    assert client.post(f"{API}/inventory/adjustments", headers=emp, json={"batch_id": b, "new_quantity": 1, "reason": "nope!"}).status_code == 403
    assert client.post(f"{API}/purchase-orders", headers=emp, json={"supplier_id": 1, "items": []}).status_code in (403, 422)


def test_tenant_isolation_across_inventory(client, admin):
    m = add_med(client, admin)
    b = receive(client, admin, m["id"], "A", 100, 20)
    register(client, "Pharma B", "b@example.com")
    hb = login(client, "b@example.com")
    assert client.get(f"{API}/medicines", headers=hb).json()["total"] == 0
    assert client.get(f"{API}/medicines/{m['id']}", headers=hb).status_code == 404
    assert client.patch(f"{API}/medicines/{m['id']}", headers=hb, json={"name": "hacked"}).status_code == 404
    assert client.get(f"{API}/batches", headers=hb).json()["total"] == 0
    assert client.post(f"{API}/sales", headers=hb, json={"medicine_id": m["id"], "quantity": 1}).status_code == 404
    assert client.post(f"{API}/inventory/write-offs", headers=hb, json={"batch_id": b, "quantity": 1, "reason": "attack"}).status_code == 404
    # cannot reference another tenant's supplier/category when creating a medicine
    sup = client.post(f"{API}/suppliers", headers=admin, json={"name": "S"}).json()
    r = client.post(f"{API}/medicines", headers=hb, json={"name": "Y", "preferred_supplier_id": sup["id"]})
    assert r.status_code == 422
    assert stock(client, admin, m["id"])["available_stock"] == 20


def test_search_low_stock_and_pagination(client, admin):
    a = add_med(client, admin, "Amoxicillin 500mg", active_ingredient="amoxicillin")
    add_med(client, admin, "Ibuprofen 200mg")
    receive(client, admin, a["id"], "A", 100, 500)
    assert client.get(f"{API}/medicines?q=amox", headers=admin).json()["total"] == 1
    low = client.get(f"{API}/medicines?low_stock=true", headers=admin).json()
    assert [x["name"] for x in low["items"]] == ["Ibuprofen 200mg"] and low["items"][0]["below_threshold"] is True
    page = client.get(f"{API}/medicines?limit=1&offset=1", headers=admin).json()
    assert page["total"] == 2 and len(page["items"]) == 1


def test_ledger_always_matches_batch_quantities(client, admin):
    """Property test: after any random mix of operations, sum(ledger) == quantity_remaining for every batch."""
    rng = random.Random(7)
    m = add_med(client, admin)
    batches = [receive(client, admin, m["id"], f"B{i}", rng.randint(20, 400), rng.randint(30, 200)) for i in range(5)]
    for _ in range(150):
        op = rng.choice(["sale", "write", "adjust", "ret", "sup"])
        b = rng.choice(batches)
        q = rng.randint(1, 40)
        if op == "sale":
            client.post(f"{API}/sales", headers=admin, json={"medicine_id": m["id"], "quantity": q})
        elif op == "write":
            client.post(f"{API}/inventory/write-offs", headers=admin, json={"batch_id": b, "quantity": q, "reason": "test"})
        elif op == "adjust":
            client.post(f"{API}/inventory/adjustments", headers=admin, json={"batch_id": b, "new_quantity": rng.randint(0, 150), "reason": "count"})
        elif op == "ret":
            client.post(f"{API}/inventory/returns/customer", headers=admin, json={"batch_id": b, "quantity": q})
        else:
            client.post(f"{API}/inventory/returns/supplier", headers=admin, json={"batch_id": b, "quantity": q, "reason": "test"})
    total_moves = client.get(f"{API}/inventory/movements?limit=1", headers=admin).json()["total"]
    assert total_moves > 60, "random ops should mostly succeed, otherwise this test proves nothing"
    kinds = {m["movement_type"] for m in client.get(f"{API}/inventory/movements?limit=200", headers=admin).json()["items"]}
    assert {"sale", "write_off", "adjustment"} <= kinds
    per_batch = {}
    off = 0
    while True:
        page = client.get(f"{API}/inventory/movements?limit=200&offset={off}", headers=admin).json()
        for mvt in page["items"]:
            per_batch[mvt["batch_id"]] = per_batch.get(mvt["batch_id"], 0) + mvt["quantity"]
        off += 200
        if off >= page["total"]:
            break
    live = {b["id"]: b for b in client.get(f"{API}/batches?include_empty=true&limit=200", headers=admin).json()["items"]}
    for bid, remaining in ((i, live[i]["quantity_remaining"]) for i in live):
        assert per_batch.get(bid, 0) == remaining
        assert 0 <= remaining <= live[bid]["quantity_received"]


def test_supplier_product_terms_drive_reorder_moq(client, admin):
    sup = client.post(f"{API}/suppliers", headers=admin, json={"name": "S1", "default_lead_time_days": 4}).json()
    m = add_med(client, admin, preferred_supplier_id=sup["id"])
    assert client.put(f"{API}/supplier-products", headers=admin, json={"supplier_id": sup["id"], "medicine_id": m["id"], "unit_price": 1.5, "min_order_quantity": 50}).status_code == 200
    assert client.put(f"{API}/supplier-products", headers=admin, json={"supplier_id": sup["id"], "medicine_id": m["id"], "unit_price": 1.6, "min_order_quantity": 60}).status_code == 200
    items = client.get(f"{API}/supplier-products?medicine_id={m['id']}", headers=admin).json()["items"]
    assert len(items) == 1 and items[0]["min_order_quantity"] == 60          # upsert, not duplicate
    emp = make_user(client, admin, "emp@example.com", "employee")
    assert client.put(f"{API}/supplier-products", headers=emp, json={"supplier_id": sup["id"], "medicine_id": m["id"], "unit_price": 1}).status_code == 403
    register(client, "Other", "b@example.com")
    hb = login(client, "b@example.com")
    assert client.put(f"{API}/supplier-products", headers=hb, json={"supplier_id": sup["id"], "medicine_id": m["id"], "unit_price": 1}).status_code == 422
