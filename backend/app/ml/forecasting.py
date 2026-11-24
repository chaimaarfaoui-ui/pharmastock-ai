"""Demand forecasting: baselines + statistical + ML models, compared by rolling-origin (expanding window)
validation. There is NO random train/test splitting: every fold trains strictly on data before its cutoff.
Scoring ignores censored (stocked-out) target days."""
import math
import warnings
from dataclasses import dataclass
from datetime import date
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

MODEL_VERSION = "1"
ALL_MODELS = ["seasonal_naive", "moving_average", "ets", "sarima", "random_forest", "lightgbm"]
FAST_MODELS = ["seasonal_naive", "moving_average", "ets", "random_forest"]
MIN_HISTORY_DAYS = 60      # below this: low-confidence moving-average fallback, no validation claims
TEST_H = 30
MIN_GAIN = 0.05   # challenger must improve validation WAPE by >=5% (relative) over the baseline
LAGS = (1, 2, 3, 7, 14, 21, 28)


# ------------------------------------------------------------------ simple models
def _seasonal_naive(y, dates, h, **_):
    n = len(y)
    out = []
    for k in range(h):
        vals = [y[n + k - 7 * j] for j in range(1, 5) if n + k - 7 * j >= 0 and n + k - 7 * j < n]
        out.append(np.mean(vals) if vals else np.mean(y[-28:]))
    return np.array(out)


def _moving_average(y, dates, h, **_):
    return np.full(h, float(np.mean(y[-28:])))


def _ets(y, dates, h, **_):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if len(y) >= 28:
            fit = ExponentialSmoothing(y[-180:] + 0.01, trend=None, seasonal="add", seasonal_periods=7,
                                       initialization_method="estimated").fit()
        else:
            fit = ExponentialSmoothing(y + 0.01, trend=None, seasonal=None, initialization_method="estimated").fit()
        return np.clip(fit.forecast(h) - 0.01, 0, None)


def _sarima(y, dates, h, **_):
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = SARIMAX(y[-150:], order=(1, 0, 1), seasonal_order=(1, 0, 1, 7), trend="c").fit(disp=False, maxiter=40)
        return np.clip(fit.forecast(h), 0, None)


# ------------------------------------------------------------------ ML models (recursive multi-step)
def _row(y, t, date_):
    lags = [y[t - l] for l in LAGS]
    doy = date_.dayofyear
    return lags + [np.mean(y[t - 7:t]), np.mean(y[t - 28:t]), date_.dayofweek, date_.month,
                   math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25)]


FEATURE_NAMES = [f"lag_{l}" for l in LAGS] + ["roll_mean_7", "roll_mean_28", "day_of_week", "month", "doy_sin", "doy_cos"]


def _fit_tree(kind, y, dates, mask):
    X, t_ = [], []
    for t in range(28, len(y)):
        if mask[t]:  # only train on targets that were not stocked out
            X.append(_row(y, t, dates[t])); t_.append(y[t])
    if len(X) < 30:
        return None
    if kind == "random_forest":
        mdl = RandomForestRegressor(n_estimators=100, min_samples_leaf=3, n_jobs=1, random_state=0)
    else:
        import lightgbm as lgb
        mdl = lgb.LGBMRegressor(n_estimators=150, learning_rate=0.05, num_leaves=15, min_child_samples=10,
                                subsample=0.9, colsample_bytree=0.9, verbose=-1, n_jobs=1, random_state=0)
    mdl.fit(np.array(X), np.array(t_))
    return mdl


def _tree_forecast(kind, y, dates, h, mask=None, return_model=False, **_):
    mask = np.ones(len(y), bool) if mask is None else mask
    mdl = _fit_tree(kind, y, dates, mask)
    if mdl is None:
        return (_seasonal_naive(y, dates, h), None) if return_model else _seasonal_naive(y, dates, h)
    hist = list(y)
    fdates = pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=h)
    preds = []
    for k in range(h):
        arr = np.array(hist)
        p = float(max(0.0, mdl.predict(np.array([_row(arr, len(arr), fdates[k])]))[0]))
        preds.append(p); hist.append(p)
    return (np.array(preds), mdl) if return_model else np.array(preds)


MODEL_FNS = {
    "seasonal_naive": _seasonal_naive, "moving_average": _moving_average, "ets": _ets, "sarima": _sarima,
    "random_forest": lambda y, d, h, mask=None, **k: _tree_forecast("random_forest", y, d, h, mask=mask),
    "lightgbm": lambda y, d, h, mask=None, **k: _tree_forecast("lightgbm", y, d, h, mask=mask),
}


# ------------------------------------------------------------------ evaluation
def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    if len(actual) == 0:
        return {"mae": None, "rmse": None, "wape": None}
    err = actual - pred
    denom = float(np.sum(np.abs(actual)))
    return {"mae": float(np.mean(np.abs(err))), "rmse": float(math.sqrt(np.mean(err ** 2))),
            "wape": float(np.sum(np.abs(err)) / denom) if denom > 0 else None}


@dataclass
class Backtest:
    actual: np.ndarray        # scored days only (uncensored)
    pred: np.ndarray
    last_dates: list          # last fold, all days (for plotting)
    last_actual: list         # None where censored
    last_pred: list
    n_folds: int


def backtest(name, y, units, censored, dates, folds=4) -> Backtest | None:
    n = len(y)
    k = min(folds, (n - MIN_HISTORY_DAYS) // TEST_H)
    if k < 1:
        return None
    fn = MODEL_FNS[name]
    act, prd = [], []
    last = None
    for f in range(k):
        cut = n - TEST_H * (k - f)
        try:
            p = np.asarray(fn(y[:cut], dates[:cut], TEST_H, mask=~censored[:cut]), float)
        except Exception:  # noqa: BLE001 - a failing candidate is excluded, not fatal
            return None
        a, c = units[cut:cut + TEST_H], censored[cut:cut + TEST_H]
        act.append(a[~c]); prd.append(p[~c])
        last = (dates[cut:cut + TEST_H], a, c, p)
    d, a, c, p = last
    return Backtest(np.concatenate(act), np.concatenate(prd), [str(x.date()) for x in d],
                    [None if ci else float(ai) for ai, ci in zip(a, c)], [float(x) for x in p], k)


def _explain(y, dates, model_name, mdl=None) -> dict:
    s = pd.Series(y, index=dates)
    recent = s[-56:]
    prof = recent.groupby(recent.index.dayofweek).mean()
    base = float(recent.mean()) or 1e-9
    last28, prev28 = float(s[-28:].mean()), float(s[-56:-28].mean()) if len(s) >= 56 else None
    out = {"weekday_profile": {str(int(d)): round(float(v / base), 3) for d, v in prof.items()},
           "level_last_28d": round(last28, 3),
           "change_vs_prior_28d_pct": round(100 * (last28 - prev28) / prev28, 1) if prev28 else None}
    if mdl is not None and hasattr(mdl, "feature_importances_"):
        imp = sorted(zip(FEATURE_NAMES, mdl.feature_importances_), key=lambda x: -x[1])[:6]
        tot = float(sum(v for _, v in imp)) or 1.0
        out["feature_importance"] = {k: round(float(v) / tot, 3) for k, v in imp}
    out["note"] = "Weekday pattern and recent level drive statistical models; tree models report impurity-based feature importance (SHAP not implemented)."
    return out


def forecast_series(df: pd.DataFrame, *, models=None, horizon: int = 60, folds: int = 4) -> dict:
    """df from ml.demand.build_daily_series. Returns evaluations, selected model, and horizon forecast with 80% interval."""
    from app.ml.demand import impute_censored
    models = models or ALL_MODELS
    dates = df.index
    units = df["units"].values
    censored = df["censored"].values
    n = len(df)
    n_cens = int(censored.sum())
    y = impute_censored(units, censored, dates)
    result = {"n_history_days": n, "n_censored_days": n_cens, "evaluations": [], "notes": []}
    fdates = pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=horizon) if n else None

    if n == 0 or units.sum() == 0:
        result.update(selected="none", confidence="none", dates=[], yhat=[], lower=[], upper=[])
        result["notes"].append("No sales history: no forecast produced. Demand is not assumed to be zero; it is unknown.")
        return result
    if n - n_cens < MIN_HISTORY_DAYS:
        yhat = _moving_average(y, dates, horizon)
        sd = float(np.std(units[~censored][-56:])) if (~censored).sum() > 3 else float(np.std(units))
        result.update(selected="moving_average", confidence="low", dates=[str(d.date()) for d in fdates],
                      yhat=yhat.tolist(), lower=np.clip(yhat - 1.28 * sd, 0, None).tolist(), upper=(yhat + 1.28 * sd).tolist(),
                      explanation=_explain(y, dates, "moving_average"))
        result["notes"].append(f"Only {n - n_cens} usable days of history (< {MIN_HISTORY_DAYS}); using a moving average, not validated.")
        return result

    scored = []
    for name in models:
        bt = backtest(name, y, units, censored, dates, folds)
        if bt is None:
            result["notes"].append(f"{name}: skipped (insufficient history for validation or fit failed)")
            continue
        m = metrics(bt.actual, bt.pred)
        scored.append((name, m, bt))
        result["evaluations"].append({"model": name, **m, "n_folds": bt.n_folds, "n_scored_days": int(len(bt.actual))})
    if not scored:
        yhat = _moving_average(y, dates, horizon)
        result.update(selected="moving_average", confidence="low", dates=[str(d.date()) for d in fdates],
                      yhat=yhat.tolist(), lower=yhat.tolist(), upper=yhat.tolist())
        return result

    def key(t):  # lower WAPE wins; MAE breaks ties / handles undefined WAPE
        w = t[1]["wape"]
        return (w if w is not None else 9e9, t[1]["mae"] or 9e9)
    best = min(scored, key=key)
    base = next((t for t in scored if t[0] == "moving_average"), None)
    # Parsimony guard: model selection on a few noisy folds overfits, so a challenger must beat the
    # moving-average baseline by at least MIN_GAIN in validation WAPE or the baseline is kept.
    if base is not None and best[0] != "moving_average" and best[1]["wape"] is not None and base[1]["wape"] is not None \
            and best[1]["wape"] > base[1]["wape"] * (1 - MIN_GAIN):
        result["notes"].append(f"{best[0]} did not beat the moving-average baseline by at least {int(MIN_GAIN * 100)}% in validation; baseline kept.")
        best = base
    name, m, bt = best
    mdl = None
    if name in ("random_forest", "lightgbm"):
        yhat, mdl = _tree_forecast(name, y, dates, horizon, mask=~censored, return_model=True)
    else:
        yhat = np.asarray(MODEL_FNS[name](y, dates, horizon), float)
    resid = bt.actual - bt.pred
    q_lo, q_hi = (np.quantile(resid, 0.10), np.quantile(resid, 0.90)) if len(resid) >= 20 else (-1.28 * resid.std(), 1.28 * resid.std())
    result.update(selected=name, confidence="validated", dates=[str(d.date()) for d in fdates], yhat=yhat.tolist(),
                  lower=np.clip(yhat + q_lo, 0, None).tolist(), upper=np.clip(yhat + q_hi, 0, None).tolist(),
                  residual_sigma=float(resid.std()), explanation=_explain(y, dates, name, mdl),
                  backtest={"dates": bt.last_dates, "actual": bt.last_actual, "predicted": bt.last_pred})
    result["notes"].append("Range = empirical 10th/90th percentile of validation errors (nominal 80%). Measured coverage on held-out synthetic days was about 73-76%, so it is somewhat optimistic.")
    return result
