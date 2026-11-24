import uuid
from datetime import date, datetime, timezone
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.ml.demand import build_daily_series
from app.ml.forecasting import ALL_MODELS, MODEL_VERSION, forecast_series
from app.models import Forecast, Medicine, ModelEvaluation, Pharmacy
from app.services.settings import get_settings_row


def run_forecasts(db: Session, pharmacy_id: int, *, medicine_ids: list[int] | None = None, models: list[str] | None = None,
                  horizon: int | None = None, today: date | None = None, progress=None) -> dict:
    cfg = get_settings_row(db, pharmacy_id)
    horizon = horizon or cfg.forecast_horizon_days
    source = db.get(Pharmacy, pharmacy_id).data_source
    stmt = select(Medicine).where(Medicine.pharmacy_id == pharmacy_id, Medicine.is_active.is_(True))
    if medicine_ids:
        stmt = stmt.where(Medicine.id.in_(medicine_ids))
    meds = list(db.scalars(stmt.order_by(Medicine.id)))
    run_id = uuid.uuid4().hex[:12]
    summary = []
    for i, med in enumerate(meds):
        df = build_daily_series(db, pharmacy_id, med.id, today)
        res = forecast_series(df, models=models or ALL_MODELS, horizon=horizon)
        for ev in res["evaluations"]:
            sel = ev["model"] == res["selected"]
            db.add(ModelEvaluation(pharmacy_id=pharmacy_id, medicine_id=med.id, run_id=run_id, model_name=ev["model"],
                                   model_version=MODEL_VERSION, mae=ev["mae"], rmse=ev["rmse"], wape=ev["wape"],
                                   n_folds=ev["n_folds"], n_scored_days=ev["n_scored_days"], n_history_days=res["n_history_days"],
                                   n_censored_days=res["n_censored_days"], is_selected=sel, data_source=source,
                                   details={"explanation": res.get("explanation"), "backtest": res.get("backtest"),
                                            "residual_sigma": res.get("residual_sigma"), "notes": res["notes"],
                                            "confidence": res["confidence"]} if sel else None))
        if not res["evaluations"] and res["selected"] != "none":   # fallback path: record that no validation happened
            db.add(ModelEvaluation(pharmacy_id=pharmacy_id, medicine_id=med.id, run_id=run_id, model_name=res["selected"],
                                   model_version=MODEL_VERSION, n_folds=0, n_history_days=res["n_history_days"],
                                   n_censored_days=res["n_censored_days"], is_selected=True, data_source=source,
                                   details={"explanation": res.get("explanation"), "notes": res["notes"], "confidence": res["confidence"]}))
        db.execute(delete(Forecast).where(Forecast.pharmacy_id == pharmacy_id, Forecast.medicine_id == med.id))
        now = datetime.now(timezone.utc)
        for d, y, lo, hi in zip(res.get("dates", []), res.get("yhat", []), res.get("lower", []), res.get("upper", [])):
            db.add(Forecast(pharmacy_id=pharmacy_id, medicine_id=med.id, run_id=run_id, model_name=res["selected"],
                            target_date=date.fromisoformat(d), yhat=float(y), lower=float(lo), upper=float(hi), generated_at=now))
        summary.append({"medicine_id": med.id, "name": med.name, "selected_model": res["selected"],
                        "confidence": res["confidence"], "n_censored_days": res["n_censored_days"], "notes": res["notes"]})
        db.commit()
        if progress:
            progress((i + 1) / max(len(meds), 1))
    return {"run_id": run_id, "medicines": len(meds), "results": summary}
