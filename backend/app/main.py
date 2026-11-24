from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
from app.api.v1 import auth, catalog, imports, insights, inventory, jobs, misc, planning, purchase_orders, users
from app.services.movements import InsufficientStock, InventoryError
from app.core.config import get_settings
from app.core.ratelimit import limiter

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router, prefix="/api/v1")
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):     # the interactive docs at /docs need their own scripts, so only lock down the API
        h.setdefault("Cache-Control", "no-store")
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


for r in (users.router, catalog.router, inventory.router, purchase_orders.router, jobs.router, planning.router, misc.router, insights.router, imports.router):
    app.include_router(r, prefix="/api/v1")


@app.exception_handler(InventoryError)
def inventory_error_handler(_: Request, exc: InventoryError):
    status_code = 404 if exc.code == "not_found" else 409 if isinstance(exc, InsufficientStock) or exc.code in ("exceeds_received", "no_change") else 422
    body = {"detail": exc.message, "code": exc.code}
    if isinstance(exc, InsufficientStock):
        body.update(requested=exc.requested, available=exc.available)
    return JSONResponse(status_code=status_code, content=body)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
