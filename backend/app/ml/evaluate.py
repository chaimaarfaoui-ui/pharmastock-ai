"""Reproducible forecasting experiment on SYNTHETIC data. Run: python -m app.ml.evaluate ../docs

Protocol per medicine (no leakage):
  1. Hold out the last 30 days. Model selection (rolling-origin CV) sees only data before the holdout.
  2. The selected model is refit on that earlier data and forecasts the 30 held-out days.
  3. All models, and the baselines, are scored on the same held-out, non-censored days (pooled WAPE / MAE).
Also reports how well stockout (censored) days are detected versus the generator's ground truth."""
import json
import sys
import warnings
from collections import Counter
from datetime import date
from pathlib import Path
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

warnings.filterwarnings("ignore")
import app.models  # noqa: E402,F401
from app.core.db import Base  # noqa: E402
from app.ml.demand import build_daily_series, impute_censored  # noqa: E402
from app.ml.forecasting import ALL_MODELS, MODEL_FNS, forecast_series, metrics  # noqa: E402
from app.models import Pharmacy  # noqa: E402
from app.services.synthetic import generate_demo_pharmacy  # noqa: E402

H = 30


def main(outdir: str = "../docs", seed: int = 42, days: int = 540, n_med: int = 20) -> dict:
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    today = date.today()
    pooled = {m: ([], []) for m in ALL_MODELS} | {"selected": ([], [])}
    selected_count, per_med, cens_tp, cens_fp, cens_truth = Counter(), [], 0, 0, 0
    cover_hits, cover_n, below, above = 0, 0, 0, 0
    with Session(eng) as db:
        p = Pharmacy(name="eval"); db.add(p); db.flush()
        info = generate_demo_pharmacy(db, p.id, seed=seed, days=days, n_medicines=n_med, today=today); db.commit()
        for mid, truth in info["truth_stockout_days"].items():
            df = build_daily_series(db, p.id, mid, today)
            flagged = {str(d.date()) for d in df.index[df.censored]}; t = {str(d) for d in truth}
            cens_tp += len(flagged & t); cens_fp += len(flagged - t); cens_truth += len(t)
            train, test = df.iloc[:-H], df.iloc[-H:]
            keep = ~test["censored"].values
            if keep.sum() < 10:
                continue
            y_train = impute_censored(train["units"].values, train["censored"].values, train.index)
            res = forecast_series(train, models=ALL_MODELS, horizon=H)
            if res["selected"] == "none":
                continue
            actual = test["units"].values[keep]
            sel_pred = np.array(res["yhat"])[keep]
            lo, hi = np.array(res["lower"])[keep], np.array(res["upper"])[keep]
            cover_hits += int(((actual >= lo) & (actual <= hi)).sum()); cover_n += len(actual)
            below += int((actual < lo).sum()); above += int((actual > hi).sum())
            pooled["selected"][0].append(actual); pooled["selected"][1].append(sel_pred)
            selected_count[res["selected"]] += 1
            row = {"medicine_id": mid, "selected": res["selected"], "confidence": res["confidence"], "n_censored_days": res["n_censored_days"],
                   "holdout_wape_selected": metrics(actual, sel_pred)["wape"]}
            for m in ALL_MODELS:
                try:
                    pr = np.asarray(MODEL_FNS[m](y_train, train.index, H, mask=~train["censored"].values), float)[keep]
                except Exception:  # noqa: BLE001
                    continue
                pooled[m][0].append(actual); pooled[m][1].append(pr)
            per_med.append(row)
    summary = {}
    for k, (a, pr) in pooled.items():
        if a:
            a, pr = np.concatenate(a), np.concatenate(pr)
            summary[k] = metrics(a, pr) | {"n_scored_days": int(len(a))}
    interval = {"nominal": 0.80, "empirical_coverage": cover_hits / max(cover_n, 1), "n_scored_days": cover_n,
                "share_below_lower": below / max(cover_n, 1), "share_above_upper": above / max(cover_n, 1)}
    out = {"interval_coverage": interval, "data": "SYNTHETIC (seeded generator), not real pharmacy data", "seed": seed, "history_days": days, "medicines": n_med, "holdout_days": H,
           "pooled_holdout_metrics": summary, "selected_model_counts": dict(selected_count), "per_medicine": per_med,
           "stockout_detection": {"true_stockout_days": cens_truth, "detected": cens_tp, "recall": cens_tp / max(cens_truth, 1),
                                  "false_positive_days": cens_fp, "precision": cens_tp / max(cens_tp + cens_fp, 1)}}
    Path(outdir).mkdir(parents=True, exist_ok=True)
    Path(outdir, "model_evaluation.json").write_text(json.dumps(out, indent=2, default=float))
    return out


if __name__ == "__main__":
    r = main(*(sys.argv[1:2] or ["../docs"]))
    for k, v in sorted(r["pooled_holdout_metrics"].items(), key=lambda x: x[1]["wape"]):
        print(f"{k:16s} WAPE {v['wape']:.3f}  MAE {v['mae']:.2f}  RMSE {v['rmse']:.2f}  (n={v['n_scored_days']})")
    print("80% interval coverage on held-out days:", {k: round(v, 3) if isinstance(v, float) else v for k, v in r["interval_coverage"].items()})
    print("selected counts:", r["selected_model_counts"]); print("stockout detection:", r["stockout_detection"])
