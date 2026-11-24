from pydantic import BaseModel, Field


class ForecastRun(BaseModel):
    medicine_ids: list[int] | None = None
    models: list[str] | None = None
    horizon: int | None = Field(default=None, ge=7, le=90)
    refresh_alerts: bool = True


class AlertStatus(BaseModel):
    status: str = Field(pattern="^(reviewed|resolved)$")


class ShortageSim(BaseModel):
    medicine_id: int
    demand_multiplier: float = Field(default=1.0, ge=0.1, le=5)
    lead_time_days: int | None = Field(default=None, ge=1, le=180)
    order_quantity: int = Field(default=0, ge=0, le=10_000_000)
    order_arrives_in_days: int = Field(default=7, ge=1, le=180)


class Approve(BaseModel):
    final_qty: int | None = Field(default=None, ge=1, le=10_000_000)


class CreatePOs(BaseModel):
    recommendation_ids: list[int] | None = None


class SettingsIn(BaseModel):
    service_level: float | None = Field(default=None, ge=0.5, le=0.999)
    default_lead_time_days: int | None = Field(default=None, ge=1, le=180)
    review_period_days: int | None = Field(default=None, ge=1, le=90)
    expiry_warning_days: list[int] | None = Field(default=None, min_length=1, max_length=5)
    holding_cost_rate: float | None = Field(default=None, ge=0, le=2)
    forecast_horizon_days: int | None = Field(default=None, ge=7, le=90)
