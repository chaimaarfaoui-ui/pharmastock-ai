"""Inventory assistant: a rules-based natural-language interface over the authenticated pharmacy's own data.

It is NOT a free-text language model. A question is matched to a supported intent; the answer is built only from
database queries and the same calculations the rest of the platform uses, so it cannot invent quantities, prices,
suppliers or predictions. It refuses clinical questions. (An LLM could later be added strictly as a phrasing layer
over these same tool functions.)"""
import re
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.ml.demand import build_daily_series
from app.models import Batch, Medicine, ReorderRecommendation, ShortageAlert
from app.services.supplier_perf import supplier_performance

CLINICAL = re.compile(r"\b(dose|dosing|dosage for|how (much|many) .* (should|can) i (take|give)|side effects?|interact(s|ion)?|treat(ment|ing)?|"
                      r"prescrib\w*|symptoms?|diagnos\w*|safe to (take|use)|can i take|pregnan\w*|contraindicat\w*|"
                      r"what (should|can) i (take|use)|which (medicine|drug|pill) (is|should)|cure|overdose|headache|infection|pain relief for)\b", re.I)
INVENTORY_CTX = re.compile(r"\b(stock|inventory|batch(es)?|supplier|expir\w*|reorder|order|purchase|demand|shortage|run out|value)\b", re.I)
REFUSAL = ("I can help with inventory questions about your own pharmacy's stock, batches, suppliers, demand and orders. "
           "I can't give medical advice, dosing, treatment, or clinical recommendations; please ask a pharmacist or physician for that.")
HELP = ("I can answer questions like: Which medicines are likely to run out soon? Which batches expire within 60 days? "
        "Which products have declining demand? Which suppliers have the longest delays? What should I reorder this week? "
        "Which medicines have the highest inventory value? How much <medicine> is in stock?")


def _table(columns, rows):
    return {"columns": columns, "rows": rows}


def ask(db: Session, pharmacy_id: int, question: str, today: date | None = None) -> dict:
    today = today or date.today()
    q = question.strip()
    names = {m.id: m for m in db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id))}
    if CLINICAL.search(q) and not INVENTORY_CTX.search(q):
        return {"intent": "refused_clinical", "answer": REFUSAL, "table": None, "how_calculated": None, "refused": True}
    low = q.lower()

    if re.search(r"run out|stock ?out|shortage|running low|out of stock|going to run", low):
        rows = db.scalars(select(ShortageAlert).where(ShortageAlert.pharmacy_id == pharmacy_id, ShortageAlert.status.in_(("open", "reviewed"))).order_by(ShortageAlert.risk_level.asc())).all()
        if not rows:
            return {"intent": "shortage", "answer": "There are no open shortage alerts. Run 'Evaluate shortage risk' to refresh them if your data changed.", "table": None,
                    "how_calculated": "Reads current shortage alerts; none are open.", "refused": False}
        t = _table(["Medicine", "Risk", "Usable stock", "Days of cover", "Lead time (d)", "Why"],
                   [[names[a.medicine_id].name, a.risk_level, a.calculation["deterministic"]["usable_stock"], a.calculation["deterministic"]["days_of_cover"],
                     a.calculation["deterministic"]["lead_time_days"], a.reasons[0] if a.reasons else ""] for a in rows])
        return {"intent": "shortage", "answer": f"{len(rows)} medicines currently carry a shortage risk (estimates, not certainties).", "table": t,
                "how_calculated": "Usable stock, open orders and a demand forecast are projected day by day over the supplier lead time; see each alert for the full calculation.", "refused": False}

    if "expir" in low:
        m = re.search(r"(\d+)\s*(day|days|d)\b", low) or re.search(r"within\s*(\d+)", low)
        days = int(m.group(1)) if m else 60
        bs = db.execute(select(Batch, Medicine.name).join(Medicine, Medicine.id == Batch.medicine_id).where(
            Batch.pharmacy_id == pharmacy_id, Batch.quantity_remaining > 0, Batch.expiration_date <= today + timedelta(days=days)).order_by(Batch.expiration_date)).all()
        t = _table(["Medicine", "Batch", "Expires", "Days left", "Qty", "Value"],
                   [[n, b.batch_number, str(b.expiration_date), (b.expiration_date - today).days, b.quantity_remaining, round(b.quantity_remaining * float(b.unit_cost), 2)] for b, n in bs])
        return {"intent": "expiring", "answer": f"{len(bs)} batches with stock on hand expire within {days} days (negative days left means already expired).", "table": t,
                "how_calculated": "Batches with remaining quantity whose expiration date is on or before today plus the window.", "refused": False}

    if re.search(r"declin|decreas|dropp?ing|falling|going down|lower demand", low):
        rows = []
        for mid, med in names.items():
            df = build_daily_series(db, pharmacy_id, mid, today)
            if len(df) < 70:
                continue
            ok = df[~df.censored]["units"]
            last, prev = ok[-28:].mean(), ok[-56:-28].mean()
            if prev and prev > 0.5 and (last - prev) / prev <= -0.15:
                rows.append([med.name, round(prev, 2), round(last, 2), round(100 * (last - prev) / prev, 1)])
        rows.sort(key=lambda r: r[3])
        return {"intent": "declining_demand", "answer": f"{len(rows)} products show demand at least 15% lower in the last 28 days than in the 28 days before.",
                "table": _table(["Medicine", "Prior 28d avg/day", "Last 28d avg/day", "Change %"], rows),
                "how_calculated": "Average daily units sold over two consecutive 28-day windows, excluding days when the product was out of stock.", "refused": False}

    if re.search(r"supplier", low) and re.search(r"delay|late|slow|longest|reliab|on.?time", low):
        perf = [p for p in supplier_performance(db, pharmacy_id) if p["deliveries"]]
        perf.sort(key=lambda p: -(p["avg_delay_when_late_days"] or 0) * (1 - (p["on_time_rate"] or 1)))
        t = _table(["Supplier", "Deliveries", "Avg lead time (d)", "On-time rate", "Delayed orders", "Avg delay when late (d)"],
                   [[p["supplier"], p["deliveries"], p["avg_lead_time_days"], p["on_time_rate"], p["delayed_orders"], p["avg_delay_when_late_days"]] for p in perf])
        return {"intent": "supplier_delays", "answer": "Suppliers ranked by delivery delays." if perf else "No completed deliveries are recorded yet.", "table": t,
                "how_calculated": "Actual delivery dates compared with each order's expected delivery date.", "refused": False}

    if re.search(r"reorder|order this week|what should i (buy|order)|purchase", low):
        recs = db.scalars(select(ReorderRecommendation).where(ReorderRecommendation.pharmacy_id == pharmacy_id, ReorderRecommendation.status == "pending")).all()
        t = _table(["Medicine", "Suggested qty", "Est. cost", "Trigger", "Position", "Reorder point formula"],
                   [[names[r.medicine_id].name, r.recommended_qty, round(r.recommended_qty * (r.unit_price or 0), 2), r.explanation["trigger"],
                     r.explanation["inputs"]["inventory_position"], r.explanation["formulas"]["reorder_point"]] for r in recs])
        return {"intent": "reorder", "answer": (f"{len(recs)} pending reorder recommendations. Nothing is ordered until you approve it." if recs else
                "No pending recommendations. Use 'Generate recommendations' on the Reorder page to refresh them."), "table": t,
                "how_calculated": "Inventory position compared with the reorder point (lead-time demand + safety stock); see the Reorder page for scenarios.", "refused": False}

    if re.search(r"(highest|most|largest|top|biggest).*(value|worth|expensive)|inventory value", low):
        rows = db.execute(select(Medicine.name, func.sum(Batch.quantity_remaining), func.sum(Batch.quantity_remaining * Batch.unit_cost)).join(Batch, Batch.medicine_id == Medicine.id)
                          .where(Batch.pharmacy_id == pharmacy_id, Batch.quantity_remaining > 0).group_by(Medicine.id, Medicine.name)
                          .order_by(func.sum(Batch.quantity_remaining * Batch.unit_cost).desc()).limit(10)).all()
        return {"intent": "inventory_value", "answer": "Top medicines by value of stock on hand (cost basis).",
                "table": _table(["Medicine", "Units", "Value"], [[n, int(u), round(float(v), 2)] for n, u, v in rows]),
                "how_calculated": "Sum of remaining quantity x batch unit cost.", "refused": False}

    if re.search(r"low stock|below (the )?(min|threshold)", low):
        use = []
        for mid, med in names.items():
            a = db.scalar(select(func.coalesce(func.sum(Batch.quantity_remaining), 0)).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == mid, Batch.expiration_date >= today))
            if a < med.min_stock_threshold:
                use.append([med.name, int(a), med.min_stock_threshold])
        return {"intent": "low_stock", "answer": f"{len(use)} medicines are below their minimum stock threshold.", "table": _table(["Medicine", "Usable stock", "Minimum"], use),
                "how_calculated": "Non-expired remaining quantity compared with each medicine's minimum threshold.", "refused": False}

    hit = [m for m in names.values() if m.name.lower().split()[0] in low or (m.active_ingredient and m.active_ingredient.lower() in low)]
    if hit and re.search(r"stock|have|how (many|much)|inventory|on hand", low):
        rows = []
        for m in hit:
            for b in db.scalars(select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == m.id, Batch.quantity_remaining > 0).order_by(Batch.expiration_date)):
                rows.append([m.name, b.batch_number, str(b.expiration_date), b.quantity_remaining, "expired" if b.expiration_date < today else "usable"])
        usable = sum(r[3] for r in rows if r[4] == "usable")
        return {"intent": "stock_lookup", "answer": f"{', '.join(m.name for m in hit)}: {usable} usable units across {len([r for r in rows if r[4]=='usable'])} batches.",
                "table": _table(["Medicine", "Batch", "Expires", "Qty", "State"], rows), "how_calculated": "Remaining quantity per batch; expired batches are not usable.", "refused": False}

    return {"intent": "unsupported", "answer": HELP, "table": None, "how_calculated": None, "refused": False}
