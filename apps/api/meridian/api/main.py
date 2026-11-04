"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from meridian.api import errors
from meridian.api.middleware import SecurityMiddleware, configure_logging
from meridian.api.routers import (
    admin,
    alerts,
    analytics,
    assets,
    auth,
    events,
    platform,
    public,
    reports,
    revenue,
    staged,
    system,
    zones,
)
from meridian.api.security import ratelimit
from meridian.api.settings import get_api_settings

DESCRIPTION = (
    "Signals are situational awareness derived from public news and public data feeds. They are not official warnings. "
    "Verify with local authorities and follow their guidance."
)


def create_app() -> FastAPI:
    settings = get_api_settings()
    configure_logging()
    ratelimit.configure(settings.valkey_url)
    app = FastAPI(
        title="Meridian Signal API",
        version="1.0.0",
        description=DESCRIPTION,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )
    app.add_middleware(SecurityMiddleware)
    errors.install(app)
    v1 = APIRouter(prefix="/api/v1")
    for module in (auth, staged, assets, zones, events, alerts, reports, admin, platform, revenue, analytics, public, system):
        v1.include_router(module.router)
    app.include_router(v1)
    return app
