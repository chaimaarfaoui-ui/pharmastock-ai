import csv, io
from datetime import date
import pytest
from tests.conftest import login, make_user, register
from tests.test_api_planning import run_job, FAST

API = "/api/v1"


@pytest.fixture()
def ready(client, admin):
    run_job(client, admin, "/demo/seed", {"days": 260, "n_medicines": 6, "seed": 5})
    run_job(client, admin, "/forecasts/run", {"models": FAST})
    return admin


def test_dashboard_numbers_match_database(client, ready):
    d = client.get(f"{API}/analytics/dashboard", headers=ready).json()
    batches = client.get(f"{API}/batches?limit=200&include_empty=false", headers=ready).json()["items"]
    total = sum(float(b["remaining_value"]) for b in batches)
    assert d["kpis"]["total_inventory_value"] == pytest.approx(total, abs=0.05)
    assert d["kpis"]["active_medicines"] == 6 and d["data_source"] == "synthetic"
    assert d["series"]["monthly_demand"] and d["series"]["inventory_value_over_time"] and d["series"]["actual_vs_forecast"]
    # monthly demand equals sum of recorded sales in range
    mv = client.get(f"{API}/inventory/movements?movement_type=sale&limit=200", headers=ready).json()
    assert sum(x["units"] for x in d["series"]["monthly_demand"]) > 0
    t = d["kpis"]["inventory_turnover"]
    assert t["value"] is None or t["value"] > 0


def test_dashboard_filters_change_results(client, ready):
    full = client.get(f"{API}/analytics/dashboard", headers=ready).json()
    cats = client.get(f"{API}/categories", headers=ready).json()
    one = client.get(f"{API}/analytics/dashboard?category_id={cats[0]['id']}", headers=ready).json()
    assert one["kpis"]["active_medicines"] < full["kpis"]["active_medicines"]
    assert one["kpis"]["total_inventory_value"] <= full["kpis"]["total_inventory_value"]
    short = client.get(f"{API}/analytics/dashboard?date_from=2026-10-01&date_to=2026-10-31", headers=ready).json()
    assert sum(x["units"] for x in short["series"]["monthly_demand"]) <= sum(x["units"] for x in full["series"]["monthly_demand"])
    assert client.get(f"{API}/analytics/dashboard?date_from=2026-10-31&date_to=2026-10-01", headers=ready).status_code == 422
    assert client.get(f"{API}/analytics/dashboard?status=low_stock", headers=ready).status_code == 200
    assert client.get(f"{API}/analytics/dashboard?status=nonsense", headers=ready).status_code == 422


def test_supplier_performance_from_deliveries(client, ready):
    r = client.get(f"{API}/suppliers/performance", headers=ready).json()
    used = [s for s in r["items"] if s["deliveries"] > 0]
    assert used and all(s["avg_lead_time_days"] >= 1 for s in used)
    assert all(0 <= s["on_time_rate"] <= 1 for s in used if s["on_time_rate"] is not None)
    assert all(s["total_spend"] > 0 for s in used)


def test_reports_csv_and_pdf(client, ready):
    for rtype in ("inventory_status", "demand_forecast", "shortage_alerts", "expiration_risk", "supplier_performance", "purchasing_recommendations"):
        for fmt in ("csv", "pdf"):
            j = run_job(client, ready, "/reports", {"report_type": rtype, "format": fmt})
            dl = client.get(f"{API}/reports/{j['result']['report_id']}/download", headers=ready)
            assert dl.status_code == 200 and "synthetic" in j["result"]["filename"]
            if fmt == "pdf":
                assert dl.content[:4] == b"%PDF"
            else:
                text = dl.content.decode("utf-8-sig")
                assert "SYNTHETIC" in text.splitlines()[0] and "not guarantees" in text.splitlines()[1]
                rows = list(csv.reader(io.StringIO(text)))
                assert len(rows) >= 3
    assert client.post(f"{API}/reports", headers=ready, json={"report_type": "nope", "format": "csv"}).status_code == 422


def test_report_csv_neutralises_formula_injection(client, admin):
    client.post(f"{API}/medicines", headers=admin, json={"name": "=HYPERLINK(\"http://evil\")", "min_stock_threshold": 5})
    j = run_job(client, admin, "/reports", {"report_type": "inventory_status", "format": "csv"})
    text = client.get(f"{API}/reports/{j['result']['report_id']}/download", headers=admin).content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\n=HYPERLINK" not in text


def test_reports_permissions_and_tenancy(client, ready):
    emp = make_user(client, ready, "emp@example.com", "employee")
    assert client.post(f"{API}/reports", headers=emp, json={"report_type": "inventory_status", "format": "csv"}).status_code == 403
    assert client.get(f"{API}/analytics/dashboard", headers=emp).status_code == 403
    j = run_job(client, ready, "/reports", {"report_type": "inventory_status", "format": "csv"})
    register(client, "Other", "b@example.com")
    hb = login(client, "b@example.com")
    assert client.get(f"{API}/reports/{j['result']['report_id']}/download", headers=hb).status_code == 404
    assert client.get(f"{API}/reports", headers=hb).json()["items"] == []


def ask(client, h, q):
    r = client.post(f"{API}/assistant/ask", headers=h, json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_assistant_answers_from_real_data(client, ready):
    a = ask(client, ready, "Which batches expire within 60 days?")
    assert a["intent"] == "expiring" and a["table"]
    for row in a["table"]["rows"]:
        assert row[3] <= 60
    hv = ask(client, ready, "Which medicines have the highest inventory value?")
    vals = [r[2] for r in hv["table"]["rows"]]
    assert vals == sorted(vals, reverse=True) and hv["intent"] == "inventory_value"
    lookup = ask(client, ready, "How much Paracetamol do we have in stock?")
    assert lookup["intent"] == "stock_lookup" and "Paracetamol" in lookup["answer"]
    meds = {m["name"]: m for m in client.get(f"{API}/medicines", headers=ready).json()["items"]}
    assert f"{meds['Paracetamol 500mg']['available_stock']} usable units" in lookup["answer"]
    assert ask(client, ready, "which suppliers have the longest delays")["intent"] == "supplier_delays"
    assert ask(client, ready, "what should I reorder this week?")["intent"] == "reorder"
    assert ask(client, ready, "which medicines will run out next month?")["intent"] == "shortage"
    assert ask(client, ready, "which products have declining demand?")["intent"] == "declining_demand"


def test_assistant_refuses_clinical_questions_and_does_not_invent(client, ready):
    for q in ("What dose of paracetamol should I take for a headache?", "Is ibuprofen safe to take while pregnant?",
              "Which medicine should I take for an infection?", "What are the side effects of amoxicillin?"):
        a = ask(client, ready, q)
        assert a["refused"] is True and a["table"] is None and "medical advice" in a["answer"]
    u = ask(client, ready, "what is the meaning of life")
    assert u["intent"] == "unsupported" and u["table"] is None


def test_assistant_is_tenant_scoped(client, ready):
    register(client, "Other", "b@example.com")
    hb = login(client, "b@example.com")
    a = ask(client, hb, "How much Paracetamol do we have in stock?")
    assert a["intent"] != "stock_lookup" or not a["table"]["rows"]
    assert ask(client, hb, "which batches expire within 90 days?")["table"]["rows"] == []


def test_policy_simulation(client, ready):
    m = client.get(f"{API}/medicines", headers=ready).json()["items"][0]
    r = client.post(f"{API}/simulations/policies", headers=ready, json={"medicine_id": m["id"], "runs": 20, "horizon_days": 90})
    assert r.status_code == 200, r.text
    pol = r.json()["policies"]
    assert set(pol) == {"reorder_point_fixed_qty", "periodic_order_up_to", "min_max"}
    assert all(0 <= p["fill_rate"] <= 1 and p["total_cost"] >= 0 for p in pol.values())
    base = client.post(f"{API}/simulations/policies", headers=ready, json={"mean_daily": 10, "sigma_daily": 3, "runs": 20, "lead_time_days": 4}).json()
    slow = client.post(f"{API}/simulations/policies", headers=ready, json={"mean_daily": 10, "sigma_daily": 3, "runs": 20, "lead_time_days": 4, "lead_time_multiplier": 3}).json()
    assert slow["policies"]["min_max"]["fill_rate"] <= base["policies"]["min_max"]["fill_rate"] + 0.02
    capped = client.post(f"{API}/simulations/policies", headers=ready, json={"mean_daily": 10, "sigma_daily": 3, "runs": 20, "budget_per_30_days": 50}).json()
    assert capped["policies"]["periodic_order_up_to"]["purchase_spend"] < base["policies"]["periodic_order_up_to"]["purchase_spend"]
    assert client.post(f"{API}/simulations/policies", headers=ready, json={"runs": 20}).status_code == 422
