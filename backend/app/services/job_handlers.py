from datetime import date
from app.models import Medicine
from app.services import planning
from app.services.forecast_runner import run_forecasts
from app.services.jobs import register
from sqlalchemy import func, select


@register("forecast")
def forecast_job(db, *, pharmacy_id, user_id, params, progress):
    res = run_forecasts(db, pharmacy_id, medicine_ids=params.get("medicine_ids"), models=params.get("models"),
                        horizon=params.get("horizon"), progress=lambda p: progress(p * 0.8))
    if params.get("refresh_alerts", True):
        res["shortage"] = planning.evaluate_shortages(db, pharmacy_id)
        progress(0.9)
        res["expiry"] = planning.evaluate_expiry(db, pharmacy_id)
        res["reorder"] = planning.build_recommendations(db, pharmacy_id)
    return res


@register("seed_demo")
def seed_demo_job(db, *, pharmacy_id, user_id, params, progress):
    from app.services.synthetic import generate_demo_pharmacy
    if db.scalar(select(func.count()).select_from(Medicine).where(Medicine.pharmacy_id == pharmacy_id)):
        raise ValueError("Demo data can only be loaded into a pharmacy with no medicines")
    info = generate_demo_pharmacy(db, pharmacy_id, seed=params.get("seed", 42), days=params.get("days", 540),
                                  n_medicines=params.get("n_medicines", 20))
    db.commit()
    progress(0.5)
    info.pop("truth_stockout_days", None)
    return info


@register("report")
def report_job(db, *, pharmacy_id, user_id, params, progress):
    from app.services.reports import generate_report
    r = generate_report(db, pharmacy_id, user_id, params["report_type"], params["format"])
    return {"report_id": r.id, "filename": r.filename}
