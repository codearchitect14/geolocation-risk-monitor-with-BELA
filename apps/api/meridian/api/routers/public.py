"""Unauthenticated endpoints for the marketing site: newsletter double opt-in and aggregate coverage figures."""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr

from meridian.api import db
from meridian.api.auth import client_ip
from meridian.api.errors import ProblemError
from meridian.api.security import ratelimit, tokens
from meridian.api.services import mailer
from meridian.api.settings import get_api_settings

router = APIRouter(tags=["public"])
STATS_TTL = 300.0
_stats_cache: tuple[float, dict[str, Any]] | None = None


class SubscribeBody(BaseModel):
    email: EmailStr


class ConfirmBody(BaseModel):
    token: str


@router.post(
    "/newsletter/subscribe", summary="Subscribe to the newsletter (confirmation email follows)", status_code=202
)
def subscribe(body: SubscribeBody, request: Request) -> dict[str, str]:
    ratelimit.check(
        f"newsletter:{client_ip(request) or 'unknown'}", 5, 3600, detail="Too many requests. Try again later."
    )
    email = body.email.lower()
    raw = secrets.token_urlsafe(32)
    with db.system_connection() as conn:
        row = conn.execute(
            "SELECT confirmed_at FROM newsletter_subscribers WHERE lower(email) = %s", (email,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO newsletter_subscribers (email, token_hash) VALUES (%s, %s)",
                (email, tokens.sha256_hex(raw)),
            )
        elif row[0] is None:
            conn.execute(
                "UPDATE newsletter_subscribers SET token_hash = %s WHERE lower(email) = %s",
                (tokens.sha256_hex(raw), email),
            )
        conn.commit()
    if row is None or row[0] is None:  # an already confirmed address gets no second message and no different answer
        link = f"{get_api_settings().public_url}/newsletter/confirm?token={raw}"
        mailer.get_mailer().send(
            email,
            "Confirm your subscription",
            f"Confirm that you want to receive the newsletter by opening this link:\n{link}\n"
            "If you did not ask for this, ignore this message and nothing will be sent.",
        )
    return {"status": "If the address is valid, a confirmation message has been sent."}


@router.post("/newsletter/confirm", summary="Confirm a newsletter subscription")
def confirm(body: ConfirmBody) -> dict[str, str]:
    with db.system_connection() as conn:
        row = conn.execute(
            "UPDATE newsletter_subscribers SET confirmed_at = coalesce(confirmed_at, now()) WHERE token_hash = %s RETURNING id",
            (tokens.sha256_hex(body.token),),
        ).fetchone()
        conn.commit()
    if row is None:
        raise ProblemError(404, "This confirmation link is not valid.", code="invalid-token")
    return {"status": "Subscription confirmed."}


@router.get("/public/stats", summary="Aggregate coverage figures shown on the marketing site")
def public_stats() -> dict[str, Any]:
    """Counts only. No tenant data, asset data or event text leaves this endpoint."""
    global _stats_cache
    now = time.monotonic()
    if _stats_cache and now - _stats_cache[0] < STATS_TTL:
        return _stats_cache[1]
    with db.system_connection() as conn:
        places = conn.execute("SELECT count(*) FROM places").fetchone()
        incidents = conn.execute(
            "SELECT count(*) FROM events WHERE last_seen_at >= now() - interval '30 days'"
        ).fetchone()
        sources = conn.execute(
            """SELECT source_kind, count(*) FROM event_sources
                WHERE coalesce(published_at, created_at) >= now() - interval '30 days' GROUP BY 1 ORDER BY 1"""
        ).fetchall()
        gazetteer = conn.execute("SELECT count(*) FILTER (WHERE qid IS NOT NULL), count(*) FROM places").fetchone()
    result = {
        "places_indexed": places[0] if places else 0,
        "places_with_wikidata": gazetteer[0] if gazetteer else 0,
        "incidents_30d": incidents[0] if incidents else 0,
        "event_sources_30d": {kind: n for kind, n in sources},
    }
    _stats_cache = (now, result)
    return result
