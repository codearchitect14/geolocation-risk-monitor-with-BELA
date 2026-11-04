"""Health, contact form, and server-sent event streams."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from meridian import notify
from meridian.api import db
from meridian.api.auth import Principal, client_ip, require
from meridian.api.errors import ProblemError
from meridian.api.security import ratelimit
from meridian.api.services.uploads import clean_text
from meridian.api.settings import get_api_settings

router = APIRouter(tags=["system"])
_open_streams: dict[str, int] = {}
_stream_lock = threading.Lock()


@router.get("/health", summary="Liveness")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness: the database answers")
def ready() -> dict[str, str]:
    try:
        with db.system_connection() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        raise ProblemError(503, "The database is not reachable.", code="not-ready") from exc
    return {"status": "ready"}


class DemoRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    company: str | None = Field(default=None, max_length=150)
    role: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=2000)
    consent: bool = Field(default=False, description="Agreement to be contacted about this request")
    website: str | None = Field(default=None, max_length=200, description="Leave empty")


@router.post("/contact/demo-request", summary="Request a demo", status_code=202)
def demo_request(body: DemoRequest, request: Request) -> dict[str, str]:
    ratelimit.check(f"demo:{client_ip(request) or 'unknown'}", 5, 3600, detail="Too many requests. Try again later.")
    if body.website:  # hidden field that people leave empty; accept silently so bots learn nothing
        return {"status": "Thank you. We will be in touch."}
    if not body.consent:
        raise ProblemError(422, "Consent to be contacted is required.", code="consent-required")
    with db.system_connection() as conn:
        conn.execute(
            """INSERT INTO demo_requests (name, email, company, role, industry, message, consent_at)
               VALUES (%s, %s, %s, %s, %s, %s, now())""",
            (
                clean_text(body.name, 100),
                body.email.lower(),
                clean_text(body.company or "", 150) or None,
                clean_text(body.role or "", 100) or None,
                clean_text(body.industry or "", 100) or None,
                clean_text(body.message or "", 2000) or None,
            ),
        )
        conn.commit()
    return {"status": "Thank you. We will be in touch."}


async def _stream(request: Request, channel: str, tenant_key: str) -> AsyncIterator[str]:
    limit = get_api_settings().sse_connections_per_tenant
    with _stream_lock:
        if _open_streams.get(tenant_key, 0) >= limit:
            raise ProblemError(429, "Too many open streams for this tenant.", code="too-many-streams")
        _open_streams[tenant_key] = _open_streams.get(tenant_key, 0) + 1
    subscription = notify.Subscription(channel)
    try:
        yield "retry: 5000\n: connected\n\n"
        idle = 0
        while not await request.is_disconnected():
            message = await asyncio.to_thread(subscription.get, 1.0)
            if message is not None:
                idle = 0
                yield f"event: update\ndata: {message}\n\n"
            else:
                idle += 1
                if idle >= 15:
                    idle = 0
                    yield ": keep-alive\n\n"
    finally:
        subscription.close()
        with _stream_lock:
            _open_streams[tenant_key] = max(0, _open_streams.get(tenant_key, 1) - 1)


def _sse(request: Request, principal: Principal, prefix: str) -> StreamingResponse:
    if principal.tenant_id is None:
        raise ProblemError(403, "Streams are scoped to a tenant.", code="forbidden")
    ratelimit.check(f"stream:{principal.tenant_id}", 60, 60, detail="Too many stream connections.")
    return StreamingResponse(
        _stream(request, f"{prefix}:{principal.tenant_id}", principal.tenant_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/stream/alerts", summary="Server-sent events: alert changes for this tenant")
def stream_alerts(request: Request, principal: Principal = Depends(require("view"))) -> StreamingResponse:
    return _sse(request, principal, "alerts")


@router.get("/stream/events", summary="Server-sent events: event updates that affect this tenant")
def stream_events(request: Request, principal: Principal = Depends(require("view"))) -> StreamingResponse:
    return _sse(request, principal, "events")


_ = Any
