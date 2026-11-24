# Architecture

```
frontend/  Next.js 14 · React · TypeScript · Tailwind · shadcn-style components · Recharts
backend/   FastAPI · Pydantic · SQLAlchemy 2 · Alembic
  app/api/v1/      routers (auth, users, catalog, inventory, purchase_orders, planning, insights, imports, jobs, misc)
  app/services/    business logic: movements (FEFO ledger), planning (shortage/expiry/reorder), analytics,
                   supplier_perf, assistant, reports, synthetic, jobs
  app/ml/          demand series (stockout-aware), forecasting + validation, simulation, rl, evaluate
  alembic/         migrations 0001–0004
docs/      this file, MODEL_EVALUATION.md, RL_EXPERIMENT.md, openapi.json (56 paths), experiment JSON
```

## Principles
1. **Deterministic maths is separate from ML.** ML supplies only the demand input. FEFO simulation, safety stock, reorder point and order-up-to are plain formulas; every alert/recommendation stores its inputs (`calculation` / `explanation`) and labels which part was predicted.
2. **Append-only stock ledger.** Only `services/movements.py` changes batch quantities, in the caller's transaction, with row locks and DB CHECK constraints (`0 ≤ remaining ≤ received`). A randomized test proves ledger sum = batch quantity after 150 mixed operations.
3. **Tenant isolation everywhere.** Every tenant table has `pharmacy_id`; each query filters on it; cross-tenant ids return 404 (no existence leak); foreign keys in request bodies are ownership-checked. Tested per module.
4. **Humans decide.** Recommendations → approve → *draft* PO → approve → ordered, all audited. No automatic ordering. Expired stock is never allocated; only written off.
5. **Uncertainty is explicit.** Risk levels, intervals and projections are labelled estimates; unvalidated forecasts are flagged low-confidence.

## Stockout-aware demand
A day is censored when closing non-expired stock is zero (rebuilt by replaying the ledger per batch). Censored days are not scored as zero demand and are imputed for training. Products with < 60 usable days get a flagged moving-average fallback; no sales history yields no forecast (demand unknown, not zero).

## Async jobs
`background_jobs` stores status/progress/result; `GET /jobs/{id}` is tenant-scoped. Default executor is FastAPI BackgroundTasks; `USE_CELERY=true` runs the same handlers in a Celery worker (`app/worker.py`, compose service `worker`). **The Celery path is provided but not exercised by the automated tests.**

## Security
Argon2 hashing; short-lived access JWTs (15 min); **rotating refresh tokens**: each refresh token works once, only its random id is stored server-side, presenting an already-used token revokes the whole family and is audited, logout and user deactivation revoke sessions; server-side RBAC (`admin`, `manager`, `employee`); login and assistant rate limiting; Pydantic validation everywhere; parameterised SQL; CSV formula-injection neutralisation on export; **validated, size-limited, all-or-nothing CSV import** (see `docs/IMPORTING_DATA.md`); security headers on the API (`nosniff`, `X-Frame-Options: DENY`, `no-store`, `default-src 'none'`) and on the web app (`nosniff`, `DENY`, `Referrer-Policy`, `Permissions-Policy`); secrets only from the environment (compose refuses to start without them); audit log for sensitive operations.
Known gaps: access and refresh tokens are kept in `sessionStorage` (httpOnly cookies would be stronger and need coordinated backend and frontend changes); no Content-Security-Policy on the web app (Next.js needs inline scripts and this could not be verified in a real browser here); rate limits are per process (use Redis storage behind several workers); expired refresh-token rows are not purged; backups are an operational responsibility (`pg_dump` on a schedule plus tested restores).

## Assistant
Rules-based intent router over the user's own data (not an LLM). It cannot invent figures, refuses clinical questions, and every answer states how it was calculated. An LLM could later be added strictly as a phrasing layer over the same tool functions.

## Data
`pharmacies.data_source` is `real` or `synthetic`; synthetic pharmacies show a banner, label every report and evaluation row. Real data requires authorisation and anonymisation by the operator before import; no public pharmacy-sales dataset is assumed.
