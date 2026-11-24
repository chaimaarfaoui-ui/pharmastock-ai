"""Dashboard analytics, supplier performance, reports, assistant, simulations."""
from datetime import date
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import get_owned
from app.api.v1.jobs import submit_job
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.ml.simulation import SimParams, compare_policies
from app.models import GeneratedReport, Medicine, User
from app.services import analytics, assistant, planning as pl
from app.services.audit import log_action
from app.services.reports import REPORT_TYPES
from app.services.settings import get_settings_row
from app.services.supplier_perf import price_comparison, supplier_performance

router = APIRouter(tags=["insights"])
ANALYTICS = require_permission("analytics:read")      # admin, manager
READ = require_permission("inventory:read")


@router.get("/analytics/dashboard")
def dashboard(date_from: date | None = None, date_to: date | None = None, category_id: int | None = None, supplier_id: int | None = None,
              medicine_id: int | None = None, status: str | None = Query(None, pattern="^(all|low_stock|out_of_stock|expiring|expired)$"),
              u: User = Depends(ANALYTICS), db: Session = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    out = analytics.dashboard(db, u.pharmacy_id, date_from=date_from, date_to=date_to, category_id=category_id, supplier_id=supplier_id,
                              medicine_id=medicine_id, status=status)
    from app.models import Pharmacy
    out["data_source"] = db.get(Pharmacy, u.pharmacy_id).data_source
    return out


@router.get("/suppliers/performance")
def suppliers_performance(date_from: date | None = None, date_to: date | None = None, u: User = Depends(ANALYTICS), db: Session = Depends(get_db)):
    return {"items": supplier_performance(db, u.pharmacy_id, date_from, date_to), "price_comparison": price_comparison(db, u.pharmacy_id)}


# ---- reports (generated asynchronously, then downloaded)
class ReportIn(BaseModel):
    report_type: str
    format: str = Field(pattern="^(csv|pdf)$")


@router.post("/reports", status_code=202)
def create_report(body: ReportIn, bg: BackgroundTasks, u: User = Depends(ANALYTICS), db: Session = Depends(get_db)):
    if body.report_type not in REPORT_TYPES:
        raise HTTPException(422, f"report_type must be one of {', '.join(REPORT_TYPES)}")
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="report.requested", details=body.model_dump())
    return submit_job(bg, db, u, "report", {"report_type": body.report_type, "format": body.format})


@router.get("/reports")
def list_reports(u: User = Depends(ANALYTICS), db: Session = Depends(get_db)):
    rows = db.scalars(select(GeneratedReport).where(GeneratedReport.pharmacy_id == u.pharmacy_id).order_by(GeneratedReport.id.desc()).limit(50))
    return {"types": list(REPORT_TYPES), "items": [{"id": r.id, "report_type": r.report_type, "format": r.fmt, "filename": r.filename,
                                                    "created_at": r.created_at, "size_bytes": len(r.content)} for r in rows]}


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, u: User = Depends(ANALYTICS), db: Session = Depends(get_db)):
    r = get_owned(db, GeneratedReport, report_id, u.pharmacy_id)
    media = "application/pdf" if r.fmt == "pdf" else "text/csv; charset=utf-8"
    return Response(r.content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{r.filename}"', "X-Content-Type-Options": "nosniff"})


# ---- assistant
class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/assistant/ask")
@limiter.limit("30/minute")
def ask_assistant(request: Request, body: AskIn, u: User = Depends(READ), db: Session = Depends(get_db)):
    return assistant.ask(db, u.pharmacy_id, body.question)


# ---- scenario simulation
class PolicySim(BaseModel):
    medicine_id: int | None = None
    mean_daily: float | None = Field(default=None, ge=0, le=100_000)
    sigma_daily: float | None = Field(default=None, ge=0, le=100_000)
    demand_multiplier: float = Field(default=1.0, ge=0.1, le=5)
    lead_time_days: float | None = Field(default=None, ge=1, le=180)
    lead_time_sd: float = Field(default=1.0, ge=0, le=60)
    lead_time_multiplier: float = Field(default=1.0, ge=0.25, le=4)
    shelf_life_days: int = Field(default=365, ge=7, le=3650)
    service_level: float = Field(default=0.95, ge=0.5, le=0.999)
    budget_per_30_days: float | None = Field(default=None, ge=0)
    runs: int = Field(default=60, ge=10, le=300)
    horizon_days: int = Field(default=180, ge=30, le=730)
    seed: int = 123


@router.post("/simulations/policies")
def simulate_policies(body: PolicySim, u: User = Depends(require_permission("forecast:read")), db: Session = Depends(get_db)):
    cfg = get_settings_row(db, u.pharmacy_id)
    mean, sigma, cost, lead = body.mean_daily, body.sigma_daily, 1.0, body.lead_time_days
    source = "user-specified"
    if body.medicine_id:
        med = get_owned(db, Medicine, body.medicine_id, u.pharmacy_id)
        prof = pl.demand_profile(db, u.pharmacy_id, med.id, date.today(), 30)
        mean = mean if mean is not None else sum(prof.daily) / 30
        sigma = sigma if sigma is not None else prof.sigma_daily
        cost, source = float(med.purchase_price) or 1.0, f"medicine demand ({prof.source})"
        if lead is None:
            lead = pl.lead_time_for(db, u.pharmacy_id, med, cfg)[0]
    if mean is None or sigma is None:
        raise HTTPException(422, "Provide medicine_id or both mean_daily and sigma_daily")
    p = SimParams(mean_daily=mean * body.demand_multiplier, sigma_daily=sigma * body.demand_multiplier,
                  lead_mean=(lead or cfg.default_lead_time_days) * body.lead_time_multiplier, lead_sd=body.lead_time_sd,
                  shelf_days=body.shelf_life_days, unit_cost=cost, holding_rate=cfg.holding_cost_rate, service_level=body.service_level,
                  review_days=cfg.review_period_days, budget_per_30d=body.budget_per_30_days, horizon_days=body.horizon_days)
    res = compare_policies(p, runs=body.runs, seed=body.seed)
    return {"inputs": {"mean_daily": p.mean_daily, "sigma_daily": p.sigma_daily, "lead_time_days": p.lead_mean, "unit_cost": p.unit_cost, "demand_source": source,
                       "holding_rate": p.holding_rate, "stockout_penalty_per_unit_multiple_of_cost": p.stockout_penalty_mult},
            "policies": res, "runs": body.runs, "seed": body.seed,
            "note": "Monte Carlo what-if under the stated assumptions (all policies see identical random demand and lead times). It is not a forecast. "
                    "Cost = holding + expiry waste + lost-sale penalty; purchase spend is reported separately."}
