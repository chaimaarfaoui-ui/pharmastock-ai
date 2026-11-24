from collections import defaultdict
from datetime import date, datetime
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Batch, Delivery, DeliveryItem, Medicine, PurchaseOrder, PurchaseOrderItem, Supplier

MIN_DELIVERIES_FOR_ADVICE = 5


def _d(x) -> date:
    return x.date() if isinstance(x, datetime) else x


def supplier_performance(db: Session, pharmacy_id: int, date_from: date | None = None, date_to: date | None = None) -> list[dict]:
    sups = {s.id: s for s in db.scalars(select(Supplier).where(Supplier.pharmacy_id == pharmacy_id))}
    pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.pharmacy_id == pharmacy_id, PurchaseOrder.status != "draft",
                                                        PurchaseOrder.status != "canceled")))
    if date_from or date_to:
        pos = [p for p in pos if p.ordered_at and (not date_from or _d(p.ordered_at) >= date_from) and (not date_to or _d(p.ordered_at) <= date_to)]
    po_ids = [p.id for p in pos]
    dels = defaultdict(list)
    if po_ids:
        for d in db.scalars(select(Delivery).where(Delivery.purchase_order_id.in_(po_ids))):
            dels[d.purchase_order_id].append(d)
    spend = defaultdict(float)
    if po_ids:
        rows = db.execute(select(Delivery.purchase_order_id, DeliveryItem.quantity, Batch.unit_cost).join(DeliveryItem, DeliveryItem.delivery_id == Delivery.id)
                          .join(Batch, Batch.id == DeliveryItem.batch_id).where(Delivery.purchase_order_id.in_(po_ids))).all()
        by_po = {p.id: p for p in pos}
        for po_id, q, c in rows:
            spend[by_po[po_id].supplier_id] += q * float(c)
    prices = defaultdict(lambda: defaultdict(list))      # supplier -> medicine -> [unit prices]
    ordered_q, received_q = defaultdict(int), defaultdict(int)
    for p in pos:
        for it in p.items:
            prices[p.supplier_id][it.medicine_id].append(float(it.unit_price))
            ordered_q[p.supplier_id] += it.quantity_ordered; received_q[p.supplier_id] += it.quantity_received
    out = []
    for sid, s in sups.items():
        mine = [p for p in pos if p.supplier_id == sid]
        leads, delays, ontime, n_exp = [], [], 0, 0
        for p in mine:
            if not p.ordered_at or p.id not in dels:
                continue
            first = min(dels[p.id], key=lambda d: d.received_at)
            leads.append((_d(first.received_at) - _d(p.ordered_at)).days)
            if p.expected_delivery_date:
                n_exp += 1
                late = (_d(first.received_at) - p.expected_delivery_date).days
                delays.append(max(late, 0)); ontime += late <= 0
        n = len(leads)
        var = [(max(v) - min(v)) / np.mean(v) for v in prices[sid].values() if len(v) >= 2 and np.mean(v) > 0]
        rec = None
        if n >= MIN_DELIVERIES_FOR_ADVICE and n_exp:
            rate = ontime / n_exp
            if rate < 0.7:
                rec = (f"Delivered late on {100 * (1 - rate):.0f}% of {n_exp} orders (average delay when late "
                       f"{np.mean([d for d in delays if d > 0]):.1f} days). Add buffer to its quoted lead time or compare alternative suppliers.")
            else:
                rec = f"Reliable: {100 * rate:.0f}% of {n_exp} orders on time."
        elif n:
            rec = f"Only {n} completed deliveries; not enough data for a recommendation."
        out.append({"supplier_id": sid, "supplier": s.name, "orders": len(mine), "deliveries": n,
                    "avg_lead_time_days": round(float(np.mean(leads)), 1) if n else None,
                    "quoted_lead_time_days": s.default_lead_time_days,
                    "on_time_rate": round(ontime / n_exp, 3) if n_exp else None,
                    "delayed_orders": int(n_exp - ontime), "avg_delay_when_late_days": round(float(np.mean([d for d in delays if d > 0])), 1) if any(d > 0 for d in delays) else 0.0,
                    "fill_rate": round(received_q[sid] / ordered_q[sid], 3) if ordered_q[sid] else None,
                    "total_spend": round(spend[sid], 2), "avg_price_variation_pct": round(100 * float(np.mean(var)), 1) if var else None,
                    "recommendation": rec})
    return sorted(out, key=lambda x: x["supplier"])


def price_comparison(db: Session, pharmacy_id: int) -> list[dict]:
    rows = db.execute(select(PurchaseOrder.supplier_id, PurchaseOrderItem.medicine_id, PurchaseOrderItem.unit_price)
                      .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
                      .where(PurchaseOrder.pharmacy_id == pharmacy_id, PurchaseOrder.status.notin_(("draft", "canceled")))).all()
    agg = defaultdict(lambda: defaultdict(list))
    for sid, mid, price in rows:
        agg[mid][sid].append(float(price))
    names = dict(db.execute(select(Medicine.id, Medicine.name).where(Medicine.pharmacy_id == pharmacy_id)).all())
    sn = dict(db.execute(select(Supplier.id, Supplier.name).where(Supplier.pharmacy_id == pharmacy_id)).all())
    return [{"medicine_id": mid, "medicine": names.get(mid),
             "suppliers": [{"supplier": sn.get(sid), "avg_unit_price": round(float(np.mean(v)), 4), "orders": len(v)} for sid, v in by.items()]}
            for mid, by in agg.items() if len(by) >= 2]
