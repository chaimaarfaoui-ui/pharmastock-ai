import csv
import io
from datetime import date, datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (Batch, ExpirationAlert, Forecast, GeneratedReport, Medicine, MedicineCategory, ModelEvaluation, Pharmacy,
                        ReorderRecommendation, ShortageAlert)
from app.services.supplier_perf import supplier_performance

REPORT_TYPES = ("inventory_status", "demand_forecast", "shortage_alerts", "expiration_risk", "supplier_performance", "purchasing_recommendations")
DISCLAIMER = "Forecasts, risk levels and recommendations are estimates to support human decisions, not guarantees. No orders are placed automatically."


def _data(db: Session, pid: int, rtype: str):
    today = date.today()
    names = dict(db.execute(select(Medicine.id, Medicine.name).where(Medicine.pharmacy_id == pid)).all())
    if rtype == "inventory_status":
        cats = dict(db.execute(select(MedicineCategory.id, MedicineCategory.name).where(MedicineCategory.pharmacy_id == pid)).all())
        rows = []
        for m in db.scalars(select(Medicine).where(Medicine.pharmacy_id == pid, Medicine.is_active.is_(True)).order_by(Medicine.name)):
            bs = db.scalars(select(Batch).where(Batch.pharmacy_id == pid, Batch.medicine_id == m.id, Batch.quantity_remaining > 0)).all()
            usable = sum(b.quantity_remaining for b in bs if b.expiration_date >= today)
            exp = sum(b.quantity_remaining for b in bs if b.expiration_date < today)
            value = sum(b.quantity_remaining * float(b.unit_cost) for b in bs)
            rows.append([m.name, cats.get(m.category_id, ""), usable, exp, m.min_stock_threshold, "BELOW MIN" if usable < m.min_stock_threshold else "ok", round(value, 2)])
        return "Inventory status", ["Medicine", "Category", "Usable units", "Expired units", "Minimum", "Status", "Stock value"], rows
    if rtype == "demand_forecast":
        rows = []
        for mid, n in sorted(names.items(), key=lambda x: x[1]):
            fc = list(db.scalars(select(Forecast).where(Forecast.pharmacy_id == pid, Forecast.medicine_id == mid).order_by(Forecast.target_date)))
            if not fc:
                continue
            ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.pharmacy_id == pid, ModelEvaluation.medicine_id == mid, ModelEvaluation.is_selected.is_(True)).order_by(ModelEvaluation.id.desc()))
            s = lambda k: round(sum(r.yhat for r in fc[:k]), 1) if len(fc) >= k else ""
            rows.append([n, s(7), s(30), s(60), fc[0].model_name, round(ev.wape, 3) if ev and ev.wape is not None else "n/a (not validated)"])
        return "Demand forecast", ["Medicine", "Next 7d units", "Next 30d units", "Next 60d units", "Model", "Validation WAPE"], rows
    if rtype == "shortage_alerts":
        al = db.scalars(select(ShortageAlert).where(ShortageAlert.pharmacy_id == pid, ShortageAlert.status.in_(("open", "reviewed"))).order_by(ShortageAlert.risk_level))
        return "Shortage alerts", ["Medicine", "Risk", "Status", "Usable stock", "Days of cover", "Reason"], [
            [names.get(a.medicine_id), a.risk_level, a.status, a.calculation["deterministic"]["usable_stock"], a.calculation["deterministic"]["days_of_cover"], " ".join(a.reasons)] for a in al]
    if rtype == "expiration_risk":
        q = db.execute(select(ExpirationAlert, Batch.batch_number, Batch.expiration_date).join(Batch, Batch.id == ExpirationAlert.batch_id)
                       .where(ExpirationAlert.pharmacy_id == pid, ExpirationAlert.status.in_(("open", "reviewed"))).order_by(ExpirationAlert.days_to_expiry)).all()
        return "Expiration risk", ["Medicine", "Batch", "Expires", "Days left", "Qty", "Projected leftover", "Value at risk", "Type"], [
            [names.get(a.medicine_id), bn, str(ed), a.days_to_expiry, a.quantity_remaining, round(a.projected_leftover, 1), round(a.at_risk_value, 2), a.alert_type] for a, bn, ed in q]
    if rtype == "supplier_performance":
        return "Supplier performance", ["Supplier", "Deliveries", "Avg lead time (d)", "Quoted (d)", "On-time rate", "Delayed orders", "Fill rate", "Spend", "Note"], [
            [p["supplier"], p["deliveries"], p["avg_lead_time_days"], p["quoted_lead_time_days"], p["on_time_rate"], p["delayed_orders"], p["fill_rate"], p["total_spend"], p["recommendation"] or ""]
            for p in supplier_performance(db, pid)]
    if rtype == "purchasing_recommendations":
        rs = db.scalars(select(ReorderRecommendation).where(ReorderRecommendation.pharmacy_id == pid, ReorderRecommendation.status.in_(("pending", "approved", "po_created"))).order_by(ReorderRecommendation.id.desc()))
        return "Purchasing recommendations", ["Medicine", "Status", "Recommended qty", "Final qty", "Est. cost", "Trigger", "Quantity formula"], [
            [names.get(r.medicine_id), r.status, r.recommended_qty, r.final_qty or "", round((r.final_qty or r.recommended_qty) * (r.unit_price or 0), 2), r.explanation["trigger"], r.explanation["formulas"]["quantity"]] for r in rs]
    raise ValueError("Unknown report type")


def _safe(v):
    """Neutralise spreadsheet formula injection in user-controlled text."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s); return True
    except ValueError:
        return False


def generate_report(db: Session, pharmacy_id: int, user_id: int | None, rtype: str, fmt: str) -> GeneratedReport:
    if rtype not in REPORT_TYPES or fmt not in ("csv", "pdf"):
        raise ValueError("Unsupported report type or format")
    pharm = db.get(Pharmacy, pharmacy_id)
    title, cols, rows = _data(db, pharmacy_id, rtype)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = f"{pharm.name} | {title} | generated {stamp} | data source: {pharm.data_source.upper()}" + (" (SYNTHETIC DEMO DATA)" if pharm.data_source == "synthetic" else "")
    fname = f"{rtype}{'-synthetic' if pharm.data_source == 'synthetic' else ''}-{date.today()}.{fmt}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"# {meta}"]); w.writerow([f"# {DISCLAIMER}"]); w.writerow(cols)
        for r in rows:
            w.writerow([_safe(c) for c in r])
        content = buf.getvalue().encode("utf-8-sig")
    else:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        ss = getSampleStyleSheet()
        cell = ss["BodyText"].clone("c"); cell.fontSize = 7; cell.leading = 9
        out = io.BytesIO()
        doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title=title)
        esc = lambda x: ("" if x is None else str(x)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        data = [[Paragraph(f"<b>{esc(c)}</b>", cell) for c in cols]] + [[Paragraph(esc(c), cell) for c in r] for r in rows[:500]]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9efe9")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        extra = [Paragraph(f"<i>Showing the first 500 of {len(rows)} rows. Use CSV for the full list.</i>", cell)] if len(rows) > 500 else []
        if not rows:
            extra = [Paragraph("No records.", cell)]
        doc.build([Paragraph(esc(title), ss["Title"]), Paragraph(esc(meta), cell), Spacer(1, 8), t, Spacer(1, 8), *extra, Paragraph(esc(DISCLAIMER), cell)])
        content = out.getvalue()
    rep = GeneratedReport(pharmacy_id=pharmacy_id, user_id=user_id, report_type=rtype, fmt=fmt, filename=fname, content=content)
    db.add(rep); db.flush()
    return rep
