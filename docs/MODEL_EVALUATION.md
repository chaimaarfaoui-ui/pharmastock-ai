# Forecast evaluation (synthetic data)

**All numbers below come from the seeded synthetic generator (`app/services/synthetic.py`), not from a real pharmacy.**
Reproduce: `cd backend && python -m app.ml.evaluate ../docs` (about 80 s). Raw output: `model_evaluation*.json`.

## Protocol (no temporal leakage)
* 20 medicines, 540 days of simulated sales, deliveries, stockouts and expiries.
* The last 30 days of each medicine are held out. Model selection (rolling-origin cross-validation, up to 4 expanding-window folds of 30 days) sees only earlier data.
* Every candidate and the selected model are refit on the earlier data, forecast the 30 held-out days, and are scored on the same **non-stocked-out** days (about 575 scored medicine-days per run).
* Metrics are pooled across medicines: WAPE = sum of absolute errors / sum of actual demand.
* Stockout days are *censored*: never scored as zero demand, imputed for training.

## Important: results depend on the run date
The generator aligns its weekly ordering with *today's date*, so the same seed produces a slightly different pharmacy on a different day. We therefore report four runs (2 seeds x 2 dates). The spread between runs is itself a finding: **differences of a few hundredths in WAPE between models are within the noise of the data-generating process.**

## Results: pooled held-out WAPE (lower is better)
| Model | Nov 6 seed 42 | Nov 6 seed 7 | Nov 21 seed 42 | Nov 21 seed 7 |
|---|---|---|---|---|
| ETS (weekly seasonal exponential smoothing) | **0.430** | 0.395 | **0.445** | 0.430 |
| Random forest (lag features) | 0.456 | 0.400 | 0.471 | **0.414** |
| LightGBM (lag features) | 0.502 | 0.406 | 0.495 | 0.428 |
| SARIMA(1,0,1)(1,0,1,7) | 0.446 | 0.430 | 0.467 | 0.457 |
| Moving average, 28 d (baseline) | 0.448 | 0.461 | 0.482 | 0.472 |
| Seasonal naive (baseline) | 0.487 | 0.494 | 0.525 | 0.513 |
| **Per-medicine selected model (what the app serves)** | 0.449 | 0.406 | 0.457 | 0.432 |

The Nov 6 selected scores include the 5% parsimony guard; before it, Nov 6 seed 42 selected = 0.451.

## What is consistent across all four runs
* **ETS beat the moving-average baseline every time**, by about 4%, 14%, 8% and 9% (relative WAPE). It is the most consistent single model.
* **Random forest and LightGBM are competitive but not consistently better than ETS.** On some runs they were worse than the moving average (LightGBM 0.502 vs 0.448); on others the random forest was the best model (0.414 vs ETS 0.430). With this much noise no tree model can be declared the winner.
* **Per-medicine model selection is not reliably better than always using ETS.** It beat the moving average in 3 of 4 runs but never beat ETS alone. Choosing among six models on a few noisy folds overfits. A guard was added (decided at 5% before testing): a challenger must beat the moving average by 5% in validation, or the baseline is kept. A sensible default is to use ETS and revisit selection on real data.
* Gains over the baseline are modest (single-digit to low-teens percent), and the error floor is high (WAPE about 0.4) because the simulated demand is very noisy.

## Interval coverage (measured Nov 21)
The 'likely range' shown with each forecast is the empirical 10th/90th percentile of validation errors (nominal 80%). On held-out days it contained the true value on **75.8% (seed 42) and 73.2% (seed 7)** of days. The range is therefore **somewhat too narrow**: 10-13% of days fell below it and 14% above. The UI and API now say so. A known cause is selection bias (the chosen model has the smallest validation errors, which makes its error history look better than its future). Not fixed: widening it by a factor chosen from this same holdout would be tuning on the test set.

## Stockout detection vs generator ground truth
Recall 100% on both seeds (every real stockout day was flagged as censored); precision 78% and 83% (false positives are days that sold exactly down to zero).

## What this does not show
* Nothing here measures accuracy on real pharmacy data.
* Not implemented: SHAP (tree models report impurity-based importance), XGBoost (LightGBM is used), holiday calendars, calibration of shortage risk and expiry-outcome evaluation (these need real labelled stockout and waste records).
