from statistics import NormalDist
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import PharmacySettings


def get_settings_row(db: Session, pharmacy_id: int) -> PharmacySettings:
    row = db.scalar(select(PharmacySettings).where(PharmacySettings.pharmacy_id == pharmacy_id))
    if row is None:
        row = PharmacySettings(pharmacy_id=pharmacy_id, service_level=0.95, default_lead_time_days=7,
                               review_period_days=7, expiry_warning_days=[30, 60, 90],
                               holding_cost_rate=0.20, forecast_horizon_days=60)
        db.add(row)
        db.flush()
    return row


def z_value(service_level: float) -> float:
    """Normal quantile for the configured cycle service level (e.g. 0.95 -> 1.645)."""
    return NormalDist().inv_cdf(min(max(service_level, 0.5), 0.9995))
