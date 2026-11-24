"""Forecasting views, shortage risk, expiration risk and reorder recommendations."""
from datetime import date, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import get_owned
from app.api.v1.jobs import submit_job
from app.core.db import get_db
from app.ml.demand import build_daily_series
from app.models import (Batch, ExpirationAlert, Forecast, Medicine, ModelEvaluation, Pharmacy, PurchaseOrder,
                        PurchaseOrderItem, ReorderRecommendation, ShortageAlert, User)
from app.schemas.planning import Approve, AlertStatus, CreatePOs, ForecastRun, SettingsIn, ShortageSim
from app.services import planning as pl
from app.services.audit import log_action
from app.services.settings import get_settings_row

router = APIRouter(tags=["planning"])
VIEW = require_permission("forecast:read")        # admin, manager
ACT = require_permission("purchasing:write")      # admin, manager


# ---------------------------------------------------------------- forecasting
@router.post("/forecasts/run", status_code=202)
def run_forecast(body: ForecastRun, bg: BackgroundTasks, u: User = Depends(ACT), db: Session = Depends(get_db)):
    for mid in body.medicine_ids or []:
        get_owned(db, Medicine, mid, u.pharmacy_id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="forecast.run", details=body.model_dump())
    return submit_job(bg, db, u, "forecast", body.model_dump())


@router.get("/forecasts/evaluations")
def evaluation_summary(u: User = Depends(VIEW), db: Session = Depends(get_db)):
    """Latest run per medicine: selected model vs the moving-average baseline, on identical validation days."""
    latest = db.scalars(select(ModelEvaluation).where(ModelEvaluation.pharmacy_id == u.pharmacy_id).order_by(ModelEvaluation.id.desc())).all()
    by_med: dict[int, list] = {}
    run_of: dict[int, str] = {}
    for e in latest:
        run_of.setdefault(e.medicine_id, e.run_id)
        if e.run_id == run_of[e.medicine_id]:
            by_med.setdefault(e.medicine_id, []).append(e)
    names = dict(db.execute(select(Medicine.id, Medicine.name).where(Medicine.pharmacy_id == u.pharmacy_id)).all())
    out = []
    for mid, evs in by_med.items():
        sel = next((e for e in evs if e.is_selected), None)
        base = next((e for e in evs if e.model_name == "moving_average"), None)
        out.append({"medicine_id": mid, "medicine": names.get(mid), "selected_model": sel.model_name if sel else None,
                    "selected_wape": sel.wape if sel else None, "baseline_wape": base.wape if base else None,
                    "confidence": ((sel.details or {}).get("confidence") if sel else None), "data_source": evs[0].data_source,
                    "n_censored_days": evs[0].n_censored_days, "n_history_days": evs[0].n_history_days,
                    "candidates": [{"model": e.model_name, "wape": e.wape, "mae": e.mae, "rmse": e.rmse, "n_folds": e.n_folds,
                                    "n_scored_days": e.n_scored_days} for e in sorted(evs, key=lambda x: x.wape if x.wape is not None else 9)]})
    return {"items": sorted(out, key=lambda x: x["medicine"] or "")}


@router.get("/forecasts/{medicine_id}")
def get_forecast(medicine_id: int, horizon: int = Query(30, ge=7, le=90), history_days: int = Query(90, ge=14, le=365),
                 u: User = Depends(VIEW), db: Session = Depends(get_db)):
    med = get_owned(db, Medicine, medicine_id, u.pharmacy_id)
    rows = list(db.scalars(select(Forecast).where(Forecast.pharmacy_id == u.pharmacy_id, Forecast.medicine_id == medicine_id)
                           .order_by(Forecast.target_date)))
    df = build_daily_series(db, u.pharmacy_id, medicine_id)
    hist = df.tail(history_days)
    ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.pharmacy_id == u.pharmacy_id, ModelEvaluation.medicine_id == medicine_id,
                                                 ModelEvaluation.is_selected.is_(True)).order_by(ModelEvaluation.id.desc()))
    cands = []
    if ev:
        cands = [{"model": e.model_name, "wape": e.wape, "mae": e.mae, "rmse": e.rmse, "is_selected": e.is_selected}
                 for e in db.scalars(select(ModelEvaluation).where(ModelEvaluation.run_id == ev.run_id, ModelEvaluation.medicine_id == medicine_id))]
    fc = rows[:horizon]
    tot = lambda n: round(sum(r.yhat for r in rows[:n]), 1) if len(rows) >= n else None
    return {"medicine": {"id": med.id, "name": med.name}, "data_source": db.get(Pharmacy, u.pharmacy_id).data_source,
            "history": [{"date": str(d.date()), "units": float(r.units), "censored": bool(r.censored)} for d, r in hist.iterrows()],
            "forecast": [{"date": str(r.target_date), "yhat": round(r.yhat, 2), "lower": round(r.lower, 2), "upper": round(r.upper, 2)} for r in fc],
            "totals": {"next_7_days": tot(7), "next_30_days": tot(30), "next_60_days": tot(60)},
            "model": ev.model_name if ev else None, "confidence": (ev.details or {}).get("confidence") if ev else None,
            "metrics": {"mae": ev.mae, "rmse": ev.rmse, "wape": ev.wape, "n_folds": ev.n_folds} if ev else None,
            "n_censored_days": int(df["censored"].sum()) if len(df) else 0,
            "backtest": (ev.details or {}).get("backtest") if ev else None,
            "explanation": (ev.details or {}).get("explanation") if ev else None,
            "notes": (ev.details or {}).get("notes") if ev else ["No forecast has been generated yet."],
            "candidates": cands,
            "uncertainty_note": "Forecasts are estimates, not a guarantee. The range is built from past validation errors; on held-out synthetic days it contained the true value on about 73-76% of days (target 80%), so treat it as slightly optimistic."}


# ---------------------------------------------------------------- shortage
def _med_names(db, pid):
    return dict(db.execute(select(Medicine.id, Medicine.name).where(Medicine.pharmacy_id == pid)).all())


@router.post("/shortage/evaluate")
def evaluate_shortage(u: User = Depends(ACT), db: Session = Depends(get_db)):
    return pl.evaluate_shortages(db, u.pharmacy_id)


@router.get("/shortage/alerts")
def shortage_alerts(status: str | None = "open", risk_level: str | None = None, limit: int = Query(100, ge=1, le=500),
                    u: User = Depends(VIEW), db: Session = Depends(get_db)):
    stmt = select(ShortageAlert).where(ShortageAlert.pharmacy_id == u.pharmacy_id)
    if status:
        stmt = stmt.where(ShortageAlert.status == status) if status != "active" else stmt.where(ShortageAlert.status.in_(("open", "reviewed")))
    if risk_level:
        stmt = stmt.where(ShortageAlert.risk_level == risk_level)
    names = _med_names(db, u.pharmacy_id)
    rows = db.scalars(stmt.order_by(ShortageAlert.risk_level.asc(), ShortageAlert.id.desc()).limit(limit))
    return {"items": [{"id": a.id, "medicine_id": a.medicine_id, "medicine": names.get(a.medicine_id), "risk_level": a.risk_level,
                       "status": a.status, "reasons": a.reasons, "calculation": a.calculation, "demand_source": a.demand_source,
                       "created_at": a.created_at} for a in rows]}


@router.patch("/shortage/alerts/{alert_id}")
def set_shortage_status(alert_id: int, body: AlertStatus, u: User = Depends(ACT), db: Session = Depends(get_db)):
    a = get_owned(db, ShortageAlert, alert_id, u.pharmacy_id)
    a.status = body.status
    if body.status == "resolved":
        a.resolved_by = u.id
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action=f"shortage.{body.status}", entity_type="shortage_alert", entity_id=a.id)
    db.commit()
    return {"id": a.id, "status": a.status}


@router.post("/shortage/simulate")
def simulate_shortage(body: ShortageSim, u: User = Depends(VIEW), db: Session = Depends(get_db)):
    med = get_owned(db, Medicine, body.medicine_id, u.pharmacy_id)
    cfg = get_settings_row(db, u.pharmacy_id)
    today = date.today()
    base = pl.assess_shortage(db, u.pharmacy_id, med, cfg, today)
    scen = pl.assess_shortage(db, u.pharmacy_id, med, cfg, today, demand_multiplier=body.demand_multiplier,
                              lead_override=body.lead_time_days,
                              extra_order=(body.order_quantity, body.order_arrives_in_days) if body.order_quantity else None)
    pick = lambda r: {"risk_level": r["risk_level"], "reasons": r["reasons"], "projection": r["calculation"]["projection"],
                      "projected_min_stock": r["calculation"]["deterministic"]["projected_min_stock"],
                      "first_projected_stockout": r["calculation"]["deterministic"]["first_projected_stockout"],
                      "window_days": r["calculation"]["deterministic"]["window_days"]}
    return {"medicine": med.name, "baseline": pick(base), "scenario": pick(scen),
            "assumptions": body.model_dump(), "note": "What-if projection built from the same demand input and inventory arithmetic; it is not a prediction of what will happen."}


# ---------------------------------------------------------------- expiration
@router.post("/expiration/evaluate")
def evaluate_expiration(u: User = Depends(ACT), db: Session = Depends(get_db)):
    return pl.evaluate_expiry(db, u.pharmacy_id)


@router.get("/expiration/alerts")
def expiration_alerts(status: str | None = "open", alert_type: str | None = None, window_days: int | None = None,
                      limit: int = Query(200, ge=1, le=500), u: User = Depends(VIEW), db: Session = Depends(get_db)):
    stmt = select(ExpirationAlert, Batch.batch_number, Batch.expiration_date, Batch.unit_cost).join(Batch, Batch.id == ExpirationAlert.batch_id)\
        .where(ExpirationAlert.pharmacy_id == u.pharmacy_id)
    if status:
        stmt = stmt.where(ExpirationAlert.status == status) if status != "active" else stmt.where(ExpirationAlert.status.in_(("open", "reviewed")))
    if alert_type:
        stmt = stmt.where(ExpirationAlert.alert_type == alert_type)
    if window_days is not None:
        stmt = stmt.where(ExpirationAlert.window_days <= window_days)
    names = _med_names(db, u.pharmacy_id)
    rows = db.execute(stmt.order_by(ExpirationAlert.days_to_expiry).limit(limit)).all()
    return {"items": [{"id": a.id, "batch_id": a.batch_id, "batch_number": bn, "expiration_date": str(ed), "medicine_id": a.medicine_id,
                       "medicine": names.get(a.medicine_id), "alert_type": a.alert_type, "window_days": a.window_days,
                       "days_to_expiry": a.days_to_expiry, "quantity_remaining": a.quantity_remaining,
                       "projected_leftover": round(a.projected_leftover, 1), "at_risk_value": round(a.at_risk_value, 2),
                       "status": a.status, "calculation": a.calculation, "demand_source": a.demand_source} for a, bn, ed, uc in rows]}


@router.patch("/expiration/alerts/{alert_id}")
def set_expiration_status(alert_id: int, body: AlertStatus, u: User = Depends(ACT), db: Session = Depends(get_db)):
    a = get_owned(db, ExpirationAlert, alert_id, u.pharmacy_id)
    a.status = body.status
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action=f"expiration.{body.status}", entity_type="expiration_alert", entity_id=a.id)
    db.commit()
    return {"id": a.id, "status": a.status}


@router.get("/expiration/summary")
def expiration_summary(u: User = Depends(VIEW), db: Session = Depends(get_db)):
    cfg = get_settings_row(db, u.pharmacy_id)
    today = date.today()
    batches = db.scalars(select(Batch).where(Batch.pharmacy_id == u.pharmacy_id, Batch.quantity_remaining > 0)).all()
    edges = sorted(cfg.expiry_warning_days)
    buckets = {"expired": [0, 0.0]} | {f"<= {e} days": [0, 0.0] for e in edges} | {f"> {edges[-1]} days": [0, 0.0]}
    for b in batches:
        d = (b.expiration_date - today).days
        key = "expired" if d < 0 else next((f"<= {e} days" for e in edges if d <= e), f"> {edges[-1]} days")
        buckets[key][0] += 1; buckets[key][1] += b.quantity_remaining * float(b.unit_cost)
    waste = db.scalar(select(func.coalesce(func.sum(ExpirationAlert.at_risk_value), 0.0)).where(
        ExpirationAlert.pharmacy_id == u.pharmacy_id, ExpirationAlert.status.in_(("open", "reviewed")),
        ExpirationAlert.alert_type.in_(("projected_waste", "expired"))))
    return {"buckets": [{"bucket": k, "batches": v[0], "value": round(v[1], 2)} for k, v in buckets.items()],
            "estimated_waste_value": round(float(waste), 2), "warning_days": edges}


@router.get("/expiration/slow-moving")
def slow_moving(cover_days_threshold: int = Query(180, ge=30, le=1000), u: User = Depends(VIEW), db: Session = Depends(get_db)):
    cfg = get_settings_row(db, u.pharmacy_id)
    today, out = date.today(), []
    for med in db.scalars(select(Medicine).where(Medicine.pharmacy_id == u.pharmacy_id, Medicine.is_active.is_(True))):
        avail = db.scalar(select(func.coalesce(func.sum(Batch.quantity_remaining), 0)).where(
            Batch.pharmacy_id == u.pharmacy_id, Batch.medicine_id == med.id, Batch.expiration_date >= today))
        if not avail:
            continue
        prof = pl.demand_profile(db, u.pharmacy_id, med.id, today, 30)
        rate = sum(prof.daily) / 30
        if not prof.has_history:
            continue
        cover = avail / rate if rate > 0 else 10_000
        if cover > cover_days_threshold:
            out.append({"medicine_id": med.id, "medicine": med.name, "usable_stock": int(avail), "mean_daily_demand": round(rate, 3),
                        "days_of_cover": round(cover, 0) if rate > 0 else None, "demand_source": prof.source})
    return {"items": sorted(out, key=lambda x: -(x["days_of_cover"] or 10_000)), "threshold_days": cover_days_threshold}


# ---------------------------------------------------------------- reorder
@router.post("/reorder/generate")
def generate_recommendations(u: User = Depends(ACT), db: Session = Depends(get_db)):
    r = pl.build_recommendations(db, u.pharmacy_id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="reorder.generated", details={"count": r["recommendations_created"]})
    db.commit()
    return r


def _rec_out(r, names, sup_names):
    return {"id": r.id, "medicine_id": r.medicine_id, "medicine": names.get(r.medicine_id), "supplier_id": r.supplier_id,
            "supplier": sup_names.get(r.supplier_id), "status": r.status, "recommended_qty": r.recommended_qty, "final_qty": r.final_qty,
            "unit_price": r.unit_price, "estimated_cost": round((r.final_qty or r.recommended_qty) * (r.unit_price or 0), 2),
            "demand_source": r.demand_source, "explanation": r.explanation, "scenarios": r.scenarios, "created_at": r.created_at,
            "purchase_order_id": r.purchase_order_id}


@router.get("/reorder/recommendations")
def list_recommendations(status: str | None = "pending", u: User = Depends(VIEW), db: Session = Depends(get_db)):
    from app.models import Supplier
    stmt = select(ReorderRecommendation).where(ReorderRecommendation.pharmacy_id == u.pharmacy_id)
    if status:
        stmt = stmt.where(ReorderRecommendation.status == status)
    sup = dict(db.execute(select(Supplier.id, Supplier.name).where(Supplier.pharmacy_id == u.pharmacy_id)).all())
    names = _med_names(db, u.pharmacy_id)
    return {"items": [_rec_out(r, names, sup) for r in db.scalars(stmt.order_by(ReorderRecommendation.id.desc()))]}


def _decide(db, u, rec_id, new_status, final_qty=None):
    r = get_owned(db, ReorderRecommendation, rec_id, u.pharmacy_id)
    if r.status != "pending":
        raise HTTPException(409, f"Recommendation is '{r.status}', not pending")
    r.status, r.decided_by, r.decided_at = new_status, u.id, func.now()
    if new_status == "approved":
        r.final_qty = final_qty or r.recommended_qty
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action=f"reorder.{new_status}", entity_type="reorder_recommendation",
               entity_id=r.id, details={"recommended": r.recommended_qty, "final": r.final_qty})
    db.commit()
    return r


@router.post("/reorder/recommendations/{rec_id}/approve")
def approve_recommendation(rec_id: int, body: Approve, u: User = Depends(ACT), db: Session = Depends(get_db)):
    r = _decide(db, u, rec_id, "approved", body.final_qty)
    return {"id": r.id, "status": r.status, "final_qty": r.final_qty}


@router.post("/reorder/recommendations/{rec_id}/reject")
def reject_recommendation(rec_id: int, u: User = Depends(ACT), db: Session = Depends(get_db)):
    r = _decide(db, u, rec_id, "rejected")
    return {"id": r.id, "status": r.status}


@router.post("/reorder/create-purchase-orders", status_code=201)
def create_pos_from_recommendations(body: CreatePOs, u: User = Depends(ACT), db: Session = Depends(get_db)):
    """Turns APPROVED recommendations into DRAFT purchase orders (one per supplier). Drafts still need PO approval."""
    stmt = select(ReorderRecommendation).where(ReorderRecommendation.pharmacy_id == u.pharmacy_id, ReorderRecommendation.status == "approved")
    if body.recommendation_ids:
        stmt = stmt.where(ReorderRecommendation.id.in_(body.recommendation_ids))
    recs = list(db.scalars(stmt))
    if not recs:
        raise HTTPException(409, "No approved recommendations to convert")
    if any(r.supplier_id is None for r in recs):
        raise HTTPException(422, "A recommendation has no supplier; set a preferred supplier for the medicine first")
    by_sup: dict[int, list] = {}
    for r in recs:
        by_sup.setdefault(r.supplier_id, []).append(r)
    ids = []
    for sid, group in by_sup.items():
        po = PurchaseOrder(pharmacy_id=u.pharmacy_id, supplier_id=sid, status="draft", created_by=u.id, notes="Created from approved reorder recommendations")
        for r in group:
            po.items.append(PurchaseOrderItem(medicine_id=r.medicine_id, quantity_ordered=r.final_qty or r.recommended_qty, unit_price=r.unit_price or 0))
        db.add(po); db.flush()
        for r in group:
            r.status, r.purchase_order_id = "po_created", po.id
        ids.append(po.id)
        log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="po.created_from_recommendations", entity_type="purchase_order", entity_id=po.id)
    db.commit()
    return {"purchase_order_ids": ids, "note": "Draft purchase orders created. They must still be approved and placed by a user."}


# ---------------------------------------------------------------- settings
def _settings_out(db, pid):
    s = get_settings_row(db, pid)
    return {"service_level": s.service_level, "default_lead_time_days": s.default_lead_time_days, "review_period_days": s.review_period_days,
            "expiry_warning_days": s.expiry_warning_days, "holding_cost_rate": s.holding_cost_rate,
            "forecast_horizon_days": s.forecast_horizon_days, "data_source": db.get(Pharmacy, pid).data_source}


@router.get("/settings")
def get_pharmacy_settings(u: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    out = _settings_out(db, u.pharmacy_id); db.commit(); return out


@router.put("/settings")
def update_pharmacy_settings(body: SettingsIn, u: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    s = get_settings_row(db, u.pharmacy_id)
    ch = body.model_dump(exclude_unset=True, exclude_none=True)
    if "expiry_warning_days" in ch:
        if any(d < 1 or d > 365 for d in ch["expiry_warning_days"]):
            raise HTTPException(422, "Warning days must be between 1 and 365")
        ch["expiry_warning_days"] = sorted(set(ch["expiry_warning_days"]))
    for k, v in ch.items():
        setattr(s, k, v)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="settings.updated", details=ch)
    db.commit()
    return _settings_out(db, u.pharmacy_id)
