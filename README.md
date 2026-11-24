# PharmaStock AI

An intelligent inventory decision-support platform for pharmacies: batch-level stock with FEFO, stockout-aware demand forecasting, shortage and expiry risk, transparent reorder recommendations, supplier analytics, a BI dashboard, an inventory assistant, reports, validated CSV import and scenario simulation.

> **Demo data is synthetic.** Everything the app shows out of the box comes from a seeded generator, is labelled as synthetic in the UI and in every report, and says nothing about real-world accuracy. No real pharmacy data is included.

## What it solves
Pharmacies lose money to stockouts and to medicines that expire unsold, and typically reorder by gut feeling. PharmaStock AI tracks stock per batch, estimates demand while correctly handling out-of-stock days, shows *why* a medicine is at risk, and proposes order quantities with the formula visible. Humans approve everything; nothing is ordered automatically, and the assistant never gives medical advice.

## Features (all implemented and tested)
| Module | Highlights |
|---|---|
| Inventory | medicines, categories, batches, append-only movement ledger; receipts, sales/dispensing (FEFO), customer and supplier returns, write-offs, count adjustments; DB-enforced invariants |
| Data import | validated CSV import for medicines, stock receipts and sales history; check-then-import, all-or-nothing, row-level errors, chronological FEFO replay ([docs/IMPORTING_DATA.md](docs/IMPORTING_DATA.md)) |
| Forecasting | 7/30/60-day forecasts; baselines, ETS, SARIMA, random forest, LightGBM; rolling-origin validation; MAE/RMSE/WAPE; actual-vs-predicted; likely range; censored stockout days |
| Shortage risk | lead time + open orders + safety stock + variability -> low/medium/high with the calculation shown; what-if simulator |
| Expiration | batch-level FEFO waste projection, configurable 30/60/90-day windows, value at risk, slow movers |
| Reorder | reorder point / order-up-to / MOQ maths, 3 scenarios with cost, waste, holding and stockout estimates; approve/modify/reject -> draft PO |
| Suppliers and POs | status workflow, deliveries, measured lead time, on-time rate, fill rate, price variation, price comparison |
| Dashboard and analytics | KPIs and 10+ charts from real records, filters by period/category/supplier/status |
| Assistant | rules-based, tenant-scoped, refuses clinical questions, explains each answer |
| Reports and notifications | CSV/PDF for six report types (async jobs), in-app notification centre, alert history |
| Simulation and RL | Monte Carlo policy comparison; experimental Q-learning (not connected to purchasing) |
| Security | Argon2, rotating refresh tokens with reuse detection and logout, server-side RBAC, tenant isolation, rate limits, security headers, audit log |

Roles: **admin** (everything plus users), **manager/pharmacist** (inventory, purchasing, analytics, import), **employee** (receive, sell, returns, deliveries).

## Quick start

### Windows without Docker (recommended for a first run)
Needs Python 3.12 (not 3.13 or 3.14) and Node LTS. Keep the folder outside OneDrive.
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # once: venv, packages, database, npm install
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # starts the API and the web app, opens the browser
```
The scripts are provided but have **not been run on Windows by the author**; if one fails, the manual commands in "Manual steps" are the fallback.

### Docker
```bash
cp .env.example .env     # set POSTGRES_PASSWORD and SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(48))")
docker compose up --build
# app http://localhost:3000   API docs http://localhost:8000/docs
```

### Manual steps
```bash
cd backend && py -3.12 -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
echo DATABASE_URL=sqlite:///dev.db > .env && alembic upgrade head && uvicorn app.main:app --reload
cd frontend && copy .env.example .env.local && npm install && npm run dev
cd backend && pytest        # 81 tests
```
Then: register a pharmacy, **Settings -> Load synthetic demo data**, **Demand Forecasting -> Run forecasts**. To use your own data instead, see **Import Data**.

## Verification status (honest)
* **Verified:** 81 passing backend tests (SQLite): FEFO order, ledger-vs-stock property test, tenant isolation and RBAC on every module, token rotation and reuse detection, importer validation, planning maths. Mutation checks: deliberately breaking FEFO order, MOQ rounding, expiry-day logic, commit-on-error, import chronology and the synthetic-data guard each made tests fail. Migrations 0001-0004 apply with no drift. The frontend type-checks and builds (20 pages); a live server returned the expected security headers, rotated tokens, and accepted/rejected CSV uploads over real HTTP.
* **Not verified:** Docker/PostgreSQL runs; row-level locking under real concurrency (SQLite ignores `FOR UPDATE`); the Celery worker; the PowerShell scripts; browser click-through of the UI (no headless browser could be installed); real-world forecast accuracy.

## Results and limitations
* Forecast evaluation (synthetic, held-out, no leakage, four runs): ETS beat the moving-average baseline in every run (about 4-14% lower WAPE); random forest and LightGBM were competitive but not consistently better; per-medicine model selection never beat ETS alone. Run-to-run spread is as large as many between-model gaps. See `docs/MODEL_EVALUATION.md`.
* The forecast 'likely range' (nominal 80%) covered only 73-76% of held-out days, so it is somewhat optimistic. This is stated in the UI.
* RL (simulated): no demonstrated advantage over a cost-tuned classical policy. See `docs/RL_EXPERIMENT.md`.
* Shortage-classifier calibration and expiry-outcome evaluation need real labelled history and are not claimed.
* Single location: transfers between sites are not implemented. Reported values use cost basis.
* Security gaps and operational notes: `docs/ARCHITECTURE.md`.

## Future work
Default to ETS and revisit model selection on real data · calibrated shortage classifier · SHAP · httpOnly-cookie sessions · Content-Security-Policy verified in a browser · browser end-to-end tests · multi-location transfers · purge of expired token rows · LLM phrasing layer over the assistant tools · a fair RL study with fitted demand.

Layout and design: `docs/ARCHITECTURE.md` - API: `docs/openapi.json` (59 paths) or `/docs`.
