"""Planning maths on hand-built data with known answers."""
from datetime import date, datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.db import Base
from app.models import (Batch, Forecast, Medicine, Pharmacy, PurchaseOrder, PurchaseOrderItem, ReorderRecommendation,
                        ShortageAlert, ExpirationAlert, Supplier, SupplierProduct, Notification)
from app.services import planning as pl
from app.services.settings import get_settings_row

TODAY = date(2026, 6, 1)


def sim(batches, demand, arrivals=(), start=TODAY + timedelta(days=1)):
    return pl.simulate_fefo(batches, demand, list(arrivals), start)


def test_simulator_fefo_and_expiry_leftover():
    # batch 1 expires on day 3 (third simulated day), batch 2 much later
    d1, d2 = TODAY + timedelta(days=3), TODAY + timedelta(days=100)
    r = sim([(1, d1, 10), (2, d2, 50)], [4, 4, 4, 4])
    # days 1-3: demand 12 taken from batch 1 first (10) then batch 2 (2); batch 1 is empty -> no leftover
    assert r.expired == {} and r.closing[-1] == pytest.approx(60 - 16)
    # slower demand leaves batch 1 stock to expire after its last valid day
    r = sim([(1, d1, 10), (2, d2, 50)], [1, 1, 1, 1])
    assert r.expired[1] == pytest.approx(7)          # 3 used by day 3, 7 expire unused on day 4


def test_simulator_stockout_and_arrival():
    r = sim([(1, date(2030, 1, 1), 15)], [10, 10, 10], arrivals=[(TODAY + timedelta(days=3), 30)])
    assert r.first_stockout is None or r.first_stockout == 1
    assert r.unmet[1] == pytest.approx(5)            # day 2: only 5 left, 10 wanted
    assert r.closing[2] == pytest.approx(20)         # day 3: 30 arrive, 10 served
    assert sim([(1, date(2030, 1, 1), 100)], [10] * 5).first_stockout is None


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        p = Pharmacy(name="P"); s.add(p); s.flush()
        sup = Supplier(pharmacy_id=p.id, name="Sup", default_lead_time_days=7); s.add(sup); s.flush()
        s.info.update(pid=p.id, sid=sup.id)
        yield s


def make_med(db, name="Drug", stock=0, expiry_days=300, demand=10.0, band=0.0, moq=1, threshold=0, cost=2.0):
    pid, sid = db.info["pid"], db.info["sid"]
    m = Medicine(pharmacy_id=pid, name=name, preferred_supplier_id=sid, min_stock_threshold=threshold, purchase_price=cost)
    db.add(m); db.flush()
    db.add(SupplierProduct(pharmacy_id=pid, supplier_id=sid, medicine_id=m.id, unit_price=cost, min_order_quantity=moq))
    if stock:
        db.add(Batch(pharmacy_id=pid, medicine_id=m.id, batch_number="B1", expiration_date=TODAY + timedelta(days=expiry_days),
                     quantity_received=stock, quantity_remaining=stock, unit_cost=cost, received_date=TODAY - timedelta(days=30)))
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i in range(1, 91):
        db.add(Forecast(pharmacy_id=pid, medicine_id=m.id, run_id="t", model_name="test", target_date=TODAY + timedelta(days=i),
                        yhat=demand, lower=demand - band, upper=demand + band, generated_at=now))
    db.flush()
    return m


def level(db, med):
    cfg = get_settings_row(db, db.info["pid"])
    return pl.assess_shortage(db, db.info["pid"], med, cfg, TODAY)


def test_shortage_levels(db):
    assert level(db, make_med(db, "High", stock=50))["risk_level"] == "high"        # 70 expected over 7d > 50
    assert level(db, make_med(db, "Low", stock=500))["risk_level"] == "low"
    r = level(db, make_med(db, "Medium", stock=85, band=5))                          # covers point demand, not the stress case
    assert r["risk_level"] == "medium" and r["calculation"]["deterministic"]["safety_stock"] > 0
    assert "not a guarantee" in r["calculation"]["disclaimer"]


def test_shortage_calculation_is_transparent_and_separates_ml_input(db):
    r = level(db, make_med(db, "X", stock=50))
    c = r["calculation"]
    assert c["deterministic"]["usable_stock"] == 50 and c["deterministic"]["lead_time_days"] == 7
    assert c["deterministic"]["lead_time_source"] == "supplier_default"
    assert c["predicted_input"]["demand_source"] == "forecast:test"
    assert c["predicted_input"]["expected_demand_over_window"] == pytest.approx(70)


def test_open_purchase_order_reduces_risk(db):
    m = make_med(db, "Y", stock=50)
    po = PurchaseOrder(pharmacy_id=db.info["pid"], supplier_id=db.info["sid"], status="ordered",
                       ordered_at=datetime(2026, 5, 30, tzinfo=timezone.utc), expected_delivery_date=TODAY + timedelta(days=3))
    po.items.append(PurchaseOrderItem(medicine_id=m.id, quantity_ordered=200, unit_price=2)); db.add(po); db.flush()
    r = level(db, m)
    assert r["risk_level"] != "high"
    assert r["calculation"]["deterministic"]["open_orders"][0]["quantity"] == 200


def test_overdue_order_is_not_trusted(db):
    m = make_med(db, "Z", stock=50)
    po = PurchaseOrder(pharmacy_id=db.info["pid"], supplier_id=db.info["sid"], status="ordered",
                       ordered_at=datetime(2026, 5, 1, tzinfo=timezone.utc), expected_delivery_date=TODAY - timedelta(days=5))
    po.items.append(PurchaseOrderItem(medicine_id=m.id, quantity_ordered=200, unit_price=2)); db.add(po); db.flush()
    r = level(db, m)
    assert r["calculation"]["deterministic"]["open_orders"][0]["overdue"] is True
    assert any("past its expected date" in x for x in r["reasons"])


def test_expired_stock_is_not_usable_for_shortage(db):
    m = make_med(db, "Old", stock=500, expiry_days=-1)       # all stock already expired
    assert level(db, m)["risk_level"] == "high"
    assert level(db, m)["calculation"]["deterministic"]["usable_stock"] == 0


def test_no_history_is_not_treated_as_zero_demand_alert(db):
    pid, sid = db.info["pid"], db.info["sid"]
    m = Medicine(pharmacy_id=pid, name="New", preferred_supplier_id=sid, min_stock_threshold=0); db.add(m); db.flush()
    r = level(db, m)
    assert r["calculation"]["predicted_input"]["demand_source"] == "no_history" and r["risk_level"] == "low"
    assert "unknown" in " ".join(r["reasons"]).lower()


def test_evaluate_shortages_upserts_and_notifies_once(db):
    make_med(db, "A", stock=50); make_med(db, "B", stock=900)
    c1 = pl.evaluate_shortages(db, db.info["pid"], TODAY)
    assert c1["high"] == 1 and c1["low"] == 1 and c1["new_alerts"] == 1
    pl.evaluate_shortages(db, db.info["pid"], TODAY)                       # idempotent
    assert len(list(db.scalars(select(ShortageAlert).where(ShortageAlert.status == "open")))) == 1
    assert len(list(db.scalars(select(Notification)))) == 1


def test_reorder_quantity_math_with_moq(db):
    m = make_med(db, "R", stock=25, demand=10.0, band=0.0, moq=24)
    out = pl.build_recommendations(db, db.info["pid"], TODAY)
    assert out["recommendations_created"] == 1
    rec = db.scalar(select(ReorderRecommendation))
    # sigma=0: S = 10*(7+7)=140; position=25 -> need 115 -> ceil(115/24)*24 = 120
    assert rec.recommended_qty == 120 and rec.status == "pending"
    inp = rec.explanation["inputs"]
    assert inp["inventory_position"] == 25 and inp["lead_time_days"] == 7 and inp["min_order_quantity"] == 24
    assert "ceil" in rec.explanation["formulas"]["quantity"]
    assert [s["label"].split()[0] for s in rec.scenarios] == ["Lean", "Recommended", "Buffered"]
    assert rec.scenarios[2]["quantity"] > rec.scenarios[1]["quantity"] > rec.scenarios[0]["quantity"] - 1
    assert "Nothing is ordered" in rec.explanation["disclaimer"]


def test_reorder_not_suggested_when_well_stocked_and_counts_open_orders(db):
    make_med(db, "Full", stock=1000)
    m2 = make_med(db, "Covered", stock=25)
    po = PurchaseOrder(pharmacy_id=db.info["pid"], supplier_id=db.info["sid"], status="approved")
    po.items.append(PurchaseOrderItem(medicine_id=m2.id, quantity_ordered=500, unit_price=2)); db.add(po); db.flush()
    assert pl.build_recommendations(db, db.info["pid"], TODAY)["recommendations_created"] == 0


def test_reorder_regeneration_supersedes_pending(db):
    make_med(db, "R", stock=25)
    pl.build_recommendations(db, db.info["pid"], TODAY); pl.build_recommendations(db, db.info["pid"], TODAY)
    statuses = sorted(r.status for r in db.scalars(select(ReorderRecommendation)))
    assert statuses == ["pending", "superseded"]


def test_expiry_projected_waste_and_value(db):
    make_med(db, "Slow", stock=100, expiry_days=20, demand=2.0, cost=3.0)   # uses 40 of 100 before expiry
    pl.evaluate_expiry(db, db.info["pid"], TODAY)
    a = db.scalar(select(ExpirationAlert))
    assert a.alert_type == "projected_waste" and a.window_days == 30
    assert a.projected_leftover == pytest.approx(60, abs=1) and a.at_risk_value == pytest.approx(180, abs=3)
    assert "never be redistributed" in a.calculation["disclaimer"] or "never redistributed" in a.calculation["disclaimer"]


def test_expiry_fast_mover_no_waste_and_expired_stock_alert(db):
    make_med(db, "Fast", stock=100, expiry_days=20, demand=20.0)           # all consumed before expiry
    make_med(db, "Dead", stock=40, expiry_days=-3, demand=1.0)
    pl.evaluate_expiry(db, db.info["pid"], TODAY)
    types = {(a.alert_type) for a in db.scalars(select(ExpirationAlert))}
    assert "expired" in types and "projected_waste" not in types
    assert "approaching" in types                                              # within first warning window, informational


def test_configurable_warning_windows(db):
    cfg = get_settings_row(db, db.info["pid"]); cfg.expiry_warning_days = [10, 20]
    make_med(db, "W", stock=100, expiry_days=15, demand=0.5)
    pl.evaluate_expiry(db, db.info["pid"], TODAY)
    assert db.scalar(select(ExpirationAlert)).window_days == 20
