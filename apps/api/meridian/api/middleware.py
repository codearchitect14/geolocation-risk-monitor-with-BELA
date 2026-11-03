"""Request IDs, security headers, body size limits, per-IP rate limits, and structured access logs (no bodies, no query strings)."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from meridian.api.security import ratelimit
from meridian.api.settings import get_api_settings

log = logging.getLogger("meridian.access")
DOCS_PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


def _problem(
    status: int, title: str, detail: str, request_id: str, headers: dict[str, str] | None = None
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    body = json.dumps(
        {"type": "about:blank", "title": title, "status": status, "detail": detail, "request_id": request_id}
    ).encode()
    raw = [(b"content-type", b"application/problem+json"), (b"content-length", str(len(body)).encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return status, raw, body


class SecurityMiddleware:
    """One ASGI layer so that rejected requests still get request IDs and security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_api_settings()
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        path = scope["path"]
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                out = list(message.get("headers", []))
                present = {k.lower() for k, _ in out}
                # A route that sets its own value for a header (for example Cache-Control on analytics) keeps it.
                out += [(k, v) for k, v in self.security_headers(path, settings.production) if k not in present]
                out.append((b"x-request-id", request_id.encode()))
                message["headers"] = out
            await send(message)

        async def reject(status: int, title: str, detail: str, extra: dict[str, str] | None = None) -> None:
            code, raw, body = _problem(status, title, detail, request_id, extra)
            await send_wrapper({"type": "http.response.start", "status": code, "headers": raw})
            await send_wrapper({"type": "http.response.body", "body": body})

        limit = settings.max_upload_bytes + 65536 if path.endswith("/uploads") else settings.max_body_bytes
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await reject(413, "Payload too large", "The request body is larger than the allowed size.")
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if settings.trust_proxy and headers.get("x-forwarded-for"):
            ip = headers["x-forwarded-for"].split(",")[0].strip()
        if path.startswith("/api") and path not in DOCS_PATHS:
            try:
                ratelimit.check(f"ip:{ip}", settings.rate_ip_per_minute, 60)
            except Exception as exc:  # noqa: BLE001 - ProblemError carries the headers
                extra = getattr(exc, "headers", {})
                await reject(429, "Too many requests", "Too many requests from this address.", extra)
                return

        received = {"bytes": 0}

        async def limited_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                received["bytes"] += len(message.get("body", b""))
                if received["bytes"] > limit:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _TooLarge:
            await reject(413, "Payload too large", "The request body is larger than the allowed size.")
        finally:
            route = scope.get("route")
            log.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": getattr(route, "path", None) or _template(path),
                        "status": status_holder["status"],
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
            )

    @staticmethod
    def security_headers(path: str, production: bool) -> list[tuple[bytes, bytes]]:
        docs = path in DOCS_PATHS
        csp = (
            "default-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
            if docs
            else "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        headers = {
            "content-security-policy": csp,
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "permissions-policy": "geolocation=(), camera=(), microphone=(), payment=(), usb=()",
            "cross-origin-opener-policy": "same-origin",
            "cross-origin-resource-policy": "same-origin",
            "cache-control": "no-store",
        }
        if production:
            headers["strict-transport-security"] = "max-age=63072000; includeSubDomains"
        return [(k.encode(), v.encode()) for k, v in headers.items()]


_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\d+")


def _template(path: str) -> str:
    """The path with identifiers replaced, so logs never carry object ids or query values."""
    return _ID.sub("{id}", path)


class _TooLarge(Exception):
    pass


def configure_logging() -> None:
    logging.getLogger("meridian.access").setLevel(logging.INFO)
    _ = Any
