import pytest
from tests.conftest import login, make_user, register

API = "/api/v1"
FAST = ["moving_average", "ets"]


def run_job(client, h, path, body):
    r = client.post(f"{API}{path}", headers=h, json=body)
    assert r.status_code == 202, r.text
    j = client.get(f"{API}/jobs/{r.json()['job_id']}", headers=h).json()
    assert j["status"] == "succeeded", j
    return j


@pytest.fixture()
def seeded(client, admin):
    run_job(client, admin, "/demo/seed", {"days": 200, "n_medicines": 6, "seed": 3})
    return admin


def test_demo_seed_is_labeled_synthetic_and_only_into_empty_pharmacy(client, seeded):
    assert client.get(f"{API}/settings", headers=seeded).json()["data_source"] == "synthetic"
    assert client.get(f"{API}/medicines?limit=50", headers=seeded).json()["total"] == 6
    assert client.post(f"{API}/demo/seed", headers=seeded, json={}).status_code == 409


def test_forecast_job_end_to_end(client, seeded):
    j = run_job(client, seeded, "/forecasts/run", {"models": FAST, "horizon": 30})
    assert j["result"]["medicines"] == 6 and j["progress"] == 1.0
    assert "shortage" in j["result"] and "reorder" in j["result"]
    med = client.get(f"{API}/medicines", headers=seeded).json()["items"][0]
    f = client.get(f"{API}/forecasts/{med['id']}?horizon=30", headers=seeded).json()
    assert f["data_source"] == "synthetic" and len(f["forecast"]) == 30 and f["model"] in FAST
    assert all(p["lower"] <= p["yhat"] <= p["upper"] + 1e-9 for p in f["forecast"])
    assert f["totals"]["next_30_days"] > 0 and "not a guarantee" in f["uncertainty_note"]
    assert f["metrics"]["n_folds"] >= 1 and f["backtest"]["actual"]
    ev = client.get(f"{API}/forecasts/evaluations", headers=seeded).json()["items"]
    assert len(ev) == 6 and all(e["candidates"] for e in ev)


def test_censored_days_are_reported_not_treated_as_zero_demand(client, seeded):
    run_job(client, seeded, "/forecasts/run", {"models": FAST, "refresh_alerts": False})
    total_cens = 0
    for m in client.get(f"{API}/medicines", headers=seeded).json()["items"]:
        f = client.get(f"{API}/forecasts/{m['id']}", headers=seeded).json()
        flagged = [h for h in f["history"] if h["censored"]]
        total_cens += len(flagged)
        assert f["n_censored_days"] >= len(flagged)
    assert total_cens > 0     # synthetic data contains stockouts and the pipeline sees them


def test_alerts_and_notifications_flow(client, seeded):
    run_job(client, seeded, "/forecasts/run", {"models": FAST})
    sh = client.get(f"{API}/shortage/alerts?status=active", headers=seeded).json()["items"]
    for a in sh:
        assert a["risk_level"] in ("medium", "high") and a["reasons"]
        assert "deterministic" in a["calculation"] and "predicted_input" in a["calculation"]
    if sh:
        assert client.patch(f"{API}/shortage/alerts/{sh[0]['id']}", headers=seeded, json={"status": "reviewed"}).json()["status"] == "reviewed"
        assert client.patch(f"{API}/shortage/alerts/{sh[0]['id']}", headers=seeded, json={"status": "bogus"}).status_code == 422
    n = client.get(f"{API}/notifications", headers=seeded).json()
    assert n["unread"] == len(n["items"]) or n["unread"] > 0 or n["items"] == []
    if n["items"]:
        nid = n["items"][0]["id"]
        assert client.patch(f"{API}/notifications/{nid}", headers=seeded, json={"status": "resolved"}).json()["status"] == "resolved"
    summ = client.get(f"{API}/expiration/summary", headers=seeded).json()
    assert {b["bucket"] for b in summ["buckets"]} >= {"expired", "<= 30 days", "> 90 days"}


def test_reorder_review_flow_never_auto_orders(client, seeded):
    run_job(client, seeded, "/forecasts/run", {"models": FAST})
    po_before = client.get(f"{API}/purchase-orders", headers=seeded).json()["total"]
    # The demo generator aligns its weekly ordering with today's date, so open orders in flight vary by day.
    # Cancel every open order first so the scenario is deterministic: no stock and nothing arriving.
    for po in client.get(f"{API}/purchase-orders?status=ordered&limit=200", headers=seeded).json()["items"]:
        assert client.post(f"{API}/purchase-orders/{po['id']}/cancel", headers=seeded).status_code == 200
    assert client.get(f"{API}/purchase-orders?status=partially_received", headers=seeded).json()["total"] == 0
    # Force a genuine low-stock situation for one medicine: write off all its stock.
    med = next(m for m in client.get(f"{API}/medicines", headers=seeded).json()["items"] if m["name"].startswith("Paracetamol"))
    for b in client.get(f"{API}/batches?medicine_id={med['id']}&limit=200", headers=seeded).json()["items"]:
        assert client.post(f"{API}/inventory/write-offs", headers=seeded, json={"batch_id": b["id"], "quantity": b["quantity_remaining"], "reason": "test write-off"}).status_code == 201
    client.post(f"{API}/reorder/generate", headers=seeded)
    recs = [r for r in client.get(f"{API}/reorder/recommendations", headers=seeded).json()["items"] if r["medicine_id"] == med["id"]]
    assert recs, "a medicine with no stock and ongoing demand must get a recommendation"
    r = recs[0]
    assert r["explanation"]["formulas"] and len(r["scenarios"]) == 3 and r["explanation"]["expected_position"]
    # generating recommendations created no purchase orders
    assert client.get(f"{API}/purchase-orders", headers=seeded).json()["total"] == po_before
    ap = client.post(f"{API}/reorder/recommendations/{r['id']}/approve", headers=seeded, json={"final_qty": r["recommended_qty"] + 5})
    assert ap.json()["final_qty"] == r["recommended_qty"] + 5
    assert client.post(f"{API}/reorder/recommendations/{r['id']}/approve", headers=seeded, json={}).status_code == 409   # already decided
    out = client.post(f"{API}/reorder/create-purchase-orders", headers=seeded, json={})
    assert out.status_code == 201, out.text
    po = client.get(f"{API}/purchase-orders/{out.json()['purchase_order_ids'][0]}", headers=seeded).json()
    assert po["status"] == "draft"          # still needs explicit PO approval
    assert any(i["quantity_ordered"] == r["recommended_qty"] + 5 for i in po["items"])
    assert client.get(f"{API}/reorder/recommendations?status=po_created", headers=seeded).json()["items"][0]["purchase_order_id"] == po["id"]


def test_shortage_simulator(client, seeded):
    run_job(client, seeded, "/forecasts/run", {"models": FAST})
    m = client.get(f"{API}/medicines", headers=seeded).json()["items"][0]
    base = client.post(f"{API}/shortage/simulate", headers=seeded, json={"medicine_id": m["id"]}).json()
    surge = client.post(f"{API}/shortage/simulate", headers=seeded, json={"medicine_id": m["id"], "demand_multiplier": 3.0}).json()
    assert surge["scenario"]["projected_min_stock"] <= base["scenario"]["projected_min_stock"]
    big = client.post(f"{API}/shortage/simulate", headers=seeded, json={
        "medicine_id": m["id"], "demand_multiplier": 3.0, "order_quantity": 100000, "order_arrives_in_days": 1}).json()
    assert big["scenario"]["projected_min_stock"] >= surge["scenario"]["projected_min_stock"]


def test_settings_validation_and_effect(client, admin):
    assert client.put(f"{API}/settings", headers=admin, json={"expiry_warning_days": [14, 45, 120]}).json()["expiry_warning_days"] == [14, 45, 120]
    assert client.put(f"{API}/settings", headers=admin, json={"service_level": 1.5}).status_code == 422
    emp = make_user(client, admin, "emp@example.com", "employee")
    assert client.put(f"{API}/settings", headers=emp, json={"service_level": 0.9}).status_code == 403


def test_permissions_and_tenancy(client, seeded):
    emp = make_user(client, seeded, "emp@example.com", "employee")
    assert client.post(f"{API}/forecasts/run", headers=emp, json={}).status_code == 403
    assert client.get(f"{API}/shortage/alerts", headers=emp).status_code == 403
    assert client.post(f"{API}/reorder/generate", headers=emp).status_code == 403
    assert client.post(f"{API}/demo/seed", headers=emp, json={}).status_code == 403
    mid = client.get(f"{API}/medicines", headers=seeded).json()["items"][0]["id"]
    register(client, "Other", "b@example.com")
    hb = login(client, "b@example.com")
    assert client.get(f"{API}/forecasts/{mid}", headers=hb).status_code == 404
    assert client.post(f"{API}/forecasts/run", headers=hb, json={"medicine_ids": [mid]}).status_code == 404
    assert client.post(f"{API}/shortage/simulate", headers=hb, json={"medicine_id": mid}).status_code == 404
    # job status is tenant-scoped too
    jid = client.post(f"{API}/forecasts/run", headers=seeded, json={"models": FAST, "refresh_alerts": False}).json()["job_id"]
    assert client.get(f"{API}/jobs/{jid}", headers=hb).status_code == 404
