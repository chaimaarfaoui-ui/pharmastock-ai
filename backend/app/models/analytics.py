from datetime import date, datetime
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, JSON,
                        LargeBinary, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.models.mixins import TenantMixin, TimestampMixin, utcnow


class PharmacySettings(Base, TimestampMixin):
    """Per-pharmacy thresholds. Every value that influences an alert or recommendation lives here."""
    __tablename__ = "pharmacy_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    pharmacy_id: Mapped[int] = mapped_column(ForeignKey("pharmacies.id", ondelete="CASCADE"), unique=True, nullable=False)
    service_level: Mapped[float] = mapped_column(Float, default=0.95, nullable=False)
    default_lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    review_period_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    expiry_warning_days: Mapped[list] = mapped_column(JSON, default=lambda: [30, 60, 90], nullable=False)
    holding_cost_rate: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)  # annual, user-configurable assumption
    forecast_horizon_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class SupplierProduct(Base, TenantMixin, TimestampMixin):
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("supplier_id", "medicine_id", name="uq_supplier_product"),
                      CheckConstraint("min_order_quantity >= 1", name="ck_sp_moq"))
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_order_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)


class Forecast(Base, TenantMixin):
    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecast_med_date", "pharmacy_id", "medicine_id", "target_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    yhat: Mapped[float] = mapped_column(Float, nullable=False)
    lower: Mapped[float] = mapped_column(Float, nullable=False)
    upper: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModelEvaluation(Base, TenantMixin):
    """One row per (run, medicine, candidate model). Backtest metrics come from rolling-origin validation."""
    __tablename__ = "model_evaluations"
    __table_args__ = (Index("ix_modeleval_med_run", "pharmacy_id", "medicine_id", "run_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    wape: Mapped[float | None] = mapped_column(Float)
    n_folds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_scored_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_history_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_censored_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_source: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)   # backtest arrays, feature importance, notes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ShortageAlert(Base, TenantMixin, TimestampMixin):
    __tablename__ = "shortage_alerts"
    __table_args__ = (Index("ix_shortage_status", "pharmacy_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)          # medium | high
    status: Mapped[str] = mapped_column(String(15), default="open", nullable=False)  # open|reviewed|resolved|superseded
    demand_source: Mapped[str] = mapped_column(String(60), nullable=False)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False)
    calculation: Mapped[dict] = mapped_column(JSON, nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ExpirationAlert(Base, TenantMixin, TimestampMixin):
    __tablename__ = "expiration_alerts"
    __table_args__ = (Index("ix_expiry_status", "pharmacy_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)   # expired | projected_waste | approaching
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    days_to_expiry: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    projected_leftover: Mapped[float] = mapped_column(Float, nullable=False)
    at_risk_value: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="open", nullable=False)
    demand_source: Mapped[str] = mapped_column(String(60), nullable=False)
    calculation: Mapped[dict] = mapped_column(JSON, nullable=False)


class ReorderRecommendation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "reorder_recommendations"
    __table_args__ = (Index("ix_reorder_status", "pharmacy_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)  # pending|approved|rejected|ordered|superseded
    recommended_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    final_qty: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[float | None] = mapped_column(Float)
    demand_source: Mapped[str] = mapped_column(String(60), nullable=False)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False)
    scenarios: Mapped[list] = mapped_column(JSON, nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))


class Notification(Base, TenantMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_status", "pharmacy_id", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="unread", nullable=False)  # unread|read|resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BackgroundJob(Base, TenantMixin):
    __tablename__ = "background_jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="queued", nullable=False)  # queued|running|succeeded|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeneratedReport(Base, TenantMixin):
    __tablename__ = "generated_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    fmt: Mapped[str] = mapped_column(String(5), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
