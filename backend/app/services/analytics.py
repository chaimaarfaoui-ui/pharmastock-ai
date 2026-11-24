"""Dashboard metrics. Every number is computed from database rows; nothing is hard-coded or placeholder."""
from collections import defaultdict
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (Batch, Delivery, DeliveryItem, ExpirationAlert, InventoryMovement, Medicine, MedicineCategory,
                        ModelEvaluation, PurchaseOrder, PurchaseOrderItem, Sale, ShortageAlert)
from app.services.settings import get_settings_row
from app.services.supplier_perf import supplier_performance


def _filtered_medicines(db, pharmacy_id, category_id, supplier_id, medicine_id, status, today, windows):
    meds = list(db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id, Medicine.is_active.is_(True))))
    if category_id:
        meds = [m for m in meds if m.category_id == category_id]
    if supplier_id:
        sup_batches = {b for (b,) in db.execute(select(Batch.medicine_id).where(Batch.pharmacy_id == pharmacy_id, Batch.supplier_id == supplier_id))}
        meds = [m for m in meds if m.preferred_supplier_id == supplier_id or m.id in sup_batches]
    if medicine_id:
        meds = [m for m in meds if m.id == medicine_id]
    if status and status != "all":
        batches = db.scalars(select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.quantity_remaining > 0)).all()
        avail, expiring, expired = defaultdict(int), set(), set()
        for b in batches:
            d = (b.expiration_date - today).days
            if d >= 0:
                avail[b.medicine_id] += b.quantity_remaining
                if d <= windows[-1]:
                    expiring.add(b.medicine_id)
            else:
                expired.add(b.medicine_id)
        keep = {"low_stock": lambda m: avail[m.id] < m.min_stock_threshold, "out_of_stock": lambda m: avail[m.id] == 0,
                "expiring": lambda m: m.id in expiring, "expired": lambda m: m.id in expired}[status]
        meds = [m for m in meds if keep(m)]
    return meds


def dashboard(db: Session, pharmacy_id: int, *, date_from: date | None = None, date_to: date | None = None, category_id=None,
              supplier_id=None, medicine_id=None, status=None, today: date | None = None) -> dict:
    today = today or date.today()
    cfg = get_settings_row(db, pharmacy_id)
    windows = sorted(cfg.expiry_warning_days)
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=180))
    meds = _filtered_medicines(db, pharmacy_id, category_id, supplier_id, medicine_id, status, today, windows)
    ids = {m.id for m in meds}
    med_by = {m.id: m for m in meds}
    cats = dict(db.execute(select(MedicineCategory.id, MedicineCategory.name).where(MedicineCategory.pharmacy_id == pharmacy_id)).all())

    # ---- current stock snapshot (not period-filtered)
    batches = [b for b in db.scalars(select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.quantity_remaining > 0)) if b.medicine_id in ids]
    avail = defaultdict(int)
    val_ok = val_expired = 0.0
    exp_counts = {w: [0, 0.0] for w in windows}
    dist = {"expired": [0, 0.0]} | {f"<= {w} days": [0, 0.0] for w in windows} | {f"> {windows[-1]} days": [0, 0.0]}
    cat_value = defaultdict(float)
    for b in batches:
        v = b.quantity_remaining * float(b.unit_cost)
        d = (b.expiration_date - today).days
        if d < 0:
            val_expired += v; dist["expired"][0] += 1; dist["expired"][1] += v
        else:
            val_ok += v; avail[b.medicine_id] += b.quantity_remaining
            for w in windows:
                if d <= w:
                    exp_counts[w][0] += 1; exp_counts[w][1] += v
            key = next((f"<= {w} days" for w in windows if d <= w), f"> {windows[-1]} days")
            dist[key][0] += 1; dist[key][1] += v
        cat_value[cats.get(med_by[b.medicine_id].category_id, "Uncategorised")] += v
    low_stock = sum(1 for m in meds if avail[m.id] < m.min_stock_threshold)

    sh = db.scalars(select(ShortageAlert).where(ShortageAlert.pharmacy_id == pharmacy_id, ShortageAlert.status.in_(("open", "reviewed")))).all()
    sh_counts = {"high": 0, "medium": 0}
    for a in sh:
        if a.medicine_id in ids:
            sh_counts[a.risk_level] += 1
    waste = sum(a.at_risk_value for a in db.scalars(select(ExpirationAlert).where(
        ExpirationAlert.pharmacy_id == pharmacy_id, ExpirationAlert.status.in_(("open", "reviewed")),
        ExpirationAlert.alert_type.in_(("projected_waste", "expired")))) if a.medicine_id in ids)

    # ---- flows in period
    t0, t1 = pd.Timestamp(date_from), pd.Timestamp(date_to) + pd.Timedelta(days=1)
    sales = db.execute(select(Sale.medicine_id, Sale.sold_at, Sale.quantity).where(Sale.pharmacy_id == pharmacy_id)).all()
    sdf = pd.DataFrame([r for r in sales if r[0] in ids], columns=["mid", "ts", "q"])
    monthly_demand = []
    if len(sdf):
        sdf["ts"] = pd.to_datetime(sdf["ts"], utc=True).dt.tz_localize(None)
        sdf = sdf[(sdf.ts >= t0) & (sdf.ts < t1)]
        monthly_demand = [{"month": str(k), "units": int(v)} for k, v in sdf.groupby(sdf.ts.dt.to_period("M"))["q"].sum().items()]

    mv = db.execute(select(InventoryMovement.medicine_id, InventoryMovement.movement_type, InventoryMovement.quantity,
                           InventoryMovement.occurred_at, Batch.unit_cost).join(Batch, Batch.id == InventoryMovement.batch_id)
                    .where(InventoryMovement.pharmacy_id == pharmacy_id)).all()
    mdf = pd.DataFrame([r for r in mv if r[0] in ids], columns=["mid", "type", "qty", "ts", "cost"])
    movements_by_month, value_over_time, cogs = [], [], 0.0
    avg_inv = 0.0
    if len(mdf):
        mdf["ts"] = pd.to_datetime(mdf["ts"], utc=True).dt.tz_localize(None)
        mdf["cost"] = mdf["cost"].astype(float)
        mdf["value"] = mdf["qty"] * mdf["cost"]
        mdf["month"] = mdf.ts.dt.to_period("M")
        inwin = mdf[(mdf.ts >= t0) & (mdf.ts < t1)]
        g = inwin.groupby(["month", "type"])["qty"].apply(lambda s: int(s.abs().sum()))
        movements_by_month = [{"month": str(m), "type": t, "units": int(v)} for (m, t), v in g.items()]
        cogs = float((inwin[inwin.type.isin(["sale", "dispense"])]["value"].abs()).sum())
        monthly_end = mdf.groupby("month")["value"].sum().cumsum()
        months = pd.period_range(monthly_end.index.min(), pd.Period(date_to, "M"), freq="M")
        full = monthly_end.reindex(months).ffill().fillna(0.0)
        sel = full[(full.index >= pd.Period(date_from, "M"))]
        value_over_time = [{"month": str(m), "value": round(float(v), 2)} for m, v in sel.items()]
        avg_inv = float(sel.mean()) if len(sel) else 0.0
    period_days = max((date_to - date_from).days + 1, 1)
    turnover = {"value": round(cogs / avg_inv, 2) if avg_inv > 0 else None, "annualised": round(cogs / avg_inv * 365 / period_days, 2) if avg_inv > 0 else None,
                "cogs": round(cogs, 2), "avg_inventory_value": round(avg_inv, 2), "period_days": period_days}

    # purchasing: actual receipts (spend) and order trends
    recv = db.execute(select(Delivery.received_at, DeliveryItem.quantity, Batch.unit_cost, Batch.medicine_id).join(DeliveryItem, DeliveryItem.delivery_id == Delivery.id)
                      .join(Batch, Batch.id == DeliveryItem.batch_id).where(Delivery.pharmacy_id == pharmacy_id)).all()
    rdf = pd.DataFrame([r for r in recv if r[3] in ids], columns=["ts", "q", "c", "mid"])
    spend_by_month = []
    if len(rdf):
        rdf["ts"] = pd.to_datetime(rdf["ts"], utc=True).dt.tz_localize(None)
        rdf = rdf[(rdf.ts >= t0) & (rdf.ts < t1)]
        rdf["v"] = rdf["q"] * rdf["c"].astype(float)
        spend_by_month = [{"month": str(k), "spend": round(float(v), 2)} for k, v in rdf.groupby(rdf.ts.dt.to_period("M"))["v"].sum().items()]
    po_rows = db.execute(select(PurchaseOrder.ordered_at, PurchaseOrder.id, PurchaseOrderItem.medicine_id, PurchaseOrderItem.quantity_ordered, PurchaseOrderItem.unit_price)
                         .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
                         .where(PurchaseOrder.pharmacy_id == pharmacy_id, PurchaseOrder.ordered_at.is_not(None), PurchaseOrder.status != "canceled")).all()
    pdf = pd.DataFrame([r for r in po_rows if r[2] in ids], columns=["ts", "po", "mid", "q", "p"])
    purchasing_trend = []
    if len(pdf):
        pdf["ts"] = pd.to_datetime(pdf["ts"], utc=True).dt.tz_localize(None)
        pdf = pdf[(pdf.ts >= t0) & (pdf.ts < t1)]
        pdf["v"] = pdf["q"] * pdf["p"].astype(float)
        gp = pdf.groupby(pdf.ts.dt.to_period("M")).agg(value=("v", "sum"), orders=("po", "nunique"))
        purchasing_trend = [{"month": str(k), "order_value": round(float(r.value), 2), "orders": int(r.orders)} for k, r in gp.iterrows()]
    cur = pd.Period(today, "M")
    cur_spend = next((x["spend"] for x in spend_by_month if x["month"] == str(cur)), 0.0)

    # ---- actual vs forecast (validation window of the selected model per medicine; scored days only)
    evs = db.scalars(select(ModelEvaluation).where(ModelEvaluation.pharmacy_id == pharmacy_id, ModelEvaluation.is_selected.is_(True)).order_by(ModelEvaluation.id.desc())).all()
    seen, agg_a, agg_p = set(), defaultdict(float), defaultdict(float)
    for e in evs:
        if e.medicine_id in seen or e.medicine_id not in ids:
            continue
        seen.add(e.medicine_id)
        bt = (e.details or {}).get("backtest")
        if bt:
            for d, a, p in zip(bt["dates"], bt["actual"], bt["predicted"]):
                if a is not None:
                    agg_a[d] += a; agg_p[d] += p
    avf = [{"date": d, "actual": round(agg_a[d], 1), "forecast": round(agg_p[d], 1)} for d in sorted(agg_a)]

    sup_perf = supplier_performance(db, pharmacy_id, date_from, date_to)
    ot = [s["on_time_rate"] for s in sup_perf if s["on_time_rate"] is not None]
    return {
        "filters": {"date_from": str(date_from), "date_to": str(date_to), "category_id": category_id, "supplier_id": supplier_id,
                    "medicine_id": medicine_id, "status": status or "all", "note": "Stock snapshots use current data; demand, movements, purchasing and turnover use the selected period."},
        "kpis": {"total_inventory_value": round(val_ok + val_expired, 2), "usable_inventory_value": round(val_ok, 2), "expired_stock_value": round(val_expired, 2),
                 "active_medicines": len(meds), "low_stock_products": low_stock, "shortage_risk_high": sh_counts["high"], "shortage_risk_medium": sh_counts["medium"],
                 "expiring": {str(w): {"batches": c, "value": round(v, 2)} for w, (c, v) in exp_counts.items()},
                 "estimated_waste_value": round(waste, 2), "purchasing_cost_current_month": round(cur_spend, 2), "inventory_turnover": turnover,
                 "supplier_on_time_rate": round(sum(ot) / len(ot), 3) if ot else None},
        "series": {"monthly_demand": monthly_demand, "actual_vs_forecast": avf, "stock_movements": movements_by_month,
                   "inventory_value_over_time": value_over_time, "expiration_distribution": [{"bucket": k, "batches": v[0], "value": round(v[1], 2)} for k, v in dist.items()],
                   "category_value": [{"category": k, "value": round(v, 2)} for k, v in sorted(cat_value.items(), key=lambda x: -x[1])],
                   "supplier_performance": sup_perf, "purchasing_spend": spend_by_month, "purchasing_trend": purchasing_trend},
    }
