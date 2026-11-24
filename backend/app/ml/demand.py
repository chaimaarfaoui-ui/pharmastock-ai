"""Builds a stockout-aware daily demand series from sales and the movement ledger.

A day is CENSORED when closing available (non-expired) stock was zero: customers may have wanted more than was
sold, so recorded sales understate demand. Censored days are never scored as "zero demand" and are imputed for
model inputs. Days before the first stock receipt are excluded entirely (nothing was observable).
"""
from datetime import date
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Batch, InventoryMovement, Sale


def build_daily_series(db: Session, pharmacy_id: int, medicine_id: int, today: date | None = None) -> pd.DataFrame:
    today = pd.Timestamp(today or date.today())
    mv = db.execute(select(InventoryMovement.batch_id, InventoryMovement.quantity, InventoryMovement.occurred_at)
                    .where(InventoryMovement.pharmacy_id == pharmacy_id, InventoryMovement.medicine_id == medicine_id)).all()
    if not mv:
        return pd.DataFrame(columns=["units", "available_close", "censored"], index=pd.DatetimeIndex([], name="day"))
    m = pd.DataFrame(mv, columns=["batch_id", "qty", "ts"])
    m["day"] = pd.to_datetime(m["ts"], utc=True).dt.tz_localize(None).dt.normalize()
    idx = pd.date_range(m["day"].min(), today.normalize(), freq="D", name="day")
    cum = m.groupby(["day", "batch_id"])["qty"].sum().unstack(fill_value=0).reindex(idx, fill_value=0).cumsum()
    exp = pd.Series({b: pd.Timestamp(e) for b, e in db.execute(
        select(Batch.id, Batch.expiration_date).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == medicine_id))})
    expiry = exp.reindex(cum.columns).values.astype("datetime64[ns]")
    usable = idx.values[:, None] <= expiry[None, :]
    available = (cum.values * usable).sum(axis=1)
    sales = db.execute(select(Sale.sold_at, Sale.quantity).where(Sale.pharmacy_id == pharmacy_id, Sale.medicine_id == medicine_id)).all()
    if sales:
        s = pd.DataFrame(sales, columns=["ts", "q"])
        s["day"] = pd.to_datetime(s["ts"], utc=True).dt.tz_localize(None).dt.normalize()
        units = s.groupby("day")["q"].sum().reindex(idx, fill_value=0)
    else:
        units = pd.Series(0, index=idx)
    return pd.DataFrame({"units": units.astype(float).values, "available_close": available.astype(float),
                         "censored": available <= 0}, index=idx)


def impute_censored(units: np.ndarray, censored: np.ndarray, dates: pd.DatetimeIndex) -> np.ndarray:
    """Fill censored days with the median of recent uncensored same-weekday days (never lower than observed sales)."""
    y = units.astype(float).copy()
    dow = dates.dayofweek.values
    for i in np.where(censored)[0]:
        lo = max(0, i - 56)
        window = [j for j in range(lo, i) if not censored[j] and dow[j] == dow[i]]
        if not window:
            window = [j for j in range(lo, i) if not censored[j]]
        fill = float(np.median(units[window])) if window else float(units[i])
        y[i] = max(units[i], fill)
    return y
