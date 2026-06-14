"""FastAPI application entrypoint for Amazon Edge-Return.

Creates the ASGI app, configures CORS so the Next.js dev client at
``http://localhost:3000`` can send credentialed requests (session cookies),
and exposes a health route used for readiness checks.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import logging

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.matches import router as matches_router
from app.api.notifications import router as notifications_router
from app.api.resale import router as resale_router
from app.api.returns import router as returns_router
from app.api.shop import router as shop_router
from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import dispose_engine, get_sessionmaker
from app.services.expiry_sweep import start_expiry_sweep, stop_expiry_sweep

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown.

    On startup, opt-in starts the background expiry sweep (Requirements 3.4,
    3.5, 9.4) when enabled in settings; starting is guarded so a failure to
    launch never prevents the app from coming up. On shutdown the sweep is
    stopped and the engine pool released.
    """
    sweep_handle = None
    try:
        sweep_handle = start_expiry_sweep(get_sessionmaker())
    except Exception:  # noqa: BLE001 - never block startup on the sweep
        logger.exception("Failed to start expiry sweep; continuing without it.")
    try:
        yield
    finally:
        await stop_expiry_sweep(sweep_handle)
        await dispose_engine()


def create_app() -> FastAPI:
    """Application factory: build and configure the FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title="Amazon Edge-Return API",
        description=(
            "Decentralized logistics, real-time return intercept, and "
            "peer-to-peer resale backend."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS: allow the Next.js dev origin with credentials so signed session
    # cookies (Requirement 1.4) are accepted on cross-origin requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Map domain errors to the consistent envelope from the REST API Contract:
    # ``{"error": {"code", "message"}}``. Each DomainError subclass carries the
    # code and HTTP status (e.g. AuthError -> 401 NO_SESSION,
    # NotEligibleError -> 422 RETURN_NOT_PERMITTED for Requirement 3.7).
    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=getattr(exc, "http_status", 400),
            content={
                "error": {
                    "code": getattr(exc, "code", "DOMAIN_ERROR"),
                    "message": str(exc),
                }
            },
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Return service health status."""
        return {"status": "ok"}

    # Serve uploaded product photos as static files at ``/uploads`` (the upload
    # endpoint in the shop router writes here and stores an absolute URL on the
    # product). The directory is created on import so the mount never fails.
    uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    app.include_router(auth_router)
    app.include_router(returns_router)
    app.include_router(matches_router)
    app.include_router(resale_router)
    app.include_router(shop_router)
    app.include_router(notifications_router)
    app.include_router(admin_router)

    return app


app = create_app()
