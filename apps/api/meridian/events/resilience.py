"""Retries, dependency health, rule based fallbacks, and the dead letter queue for news articles.

The model server and the entity linker are optional at run time. When either is down the news path keeps working with weaker
methods and says so: events built that way carry `reduced_confidence`. An article that cannot be processed at all is parked in
`dead_letters` and retried with growing delays; after the last attempt it is abandoned and stays visible to operators.
Article text is never written to the queue. The retry caller supplies the text again (`text_for`).
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
import psycopg

from meridian.events.classify import Classification

T = TypeVar("T")

BACKOFF_SECONDS = (60, 300, 1800, 7200, 43200)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
HEALTH_TTL_SECONDS = 20.0
RULES_VERSION = "headline_rules_v1"


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base: float = 0.4,
    cap: float = 6.0,
    retry_on: tuple[type[BaseException], ...] = (httpx.TransportError, httpx.TimeoutException),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying transient failures with exponential backoff and full jitter. The last error is raised."""
    for attempt in range(attempts):
        try:
            return fn()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(random.uniform(0, min(cap, base * 2**attempt)))  # noqa: S311 - jitter, not security
    raise AssertionError("unreachable")


class DependencyHealth:
    """Cached health of the model server and the entity linker, so a long outage costs one probe per interval."""

    def __init__(self, nel: Any | None, llm: Any | None, clock: Callable[[], float] = time.monotonic) -> None:
        self._probes = {"nel": nel, "llm": llm}
        self._clock = clock
        self._seen: dict[str, tuple[float, bool]] = {}

    def up(self, name: str) -> bool:
        target = self._probes.get(name)
        if target is None:
            return False
        now = self._clock()
        cached = self._seen.get(name)
        if cached is not None and now - cached[0] < HEALTH_TTL_SECONDS:
            return cached[1]
        ok = bool(target.healthy())
        self._seen[name] = (now, ok)
        return ok

    def mark_down(self, name: str) -> None:
        """A call failed after the last probe: stop trying until the next probe interval."""
        self._seen[name] = (self._clock(), False)


# Headline keywords for the model-free fallback. First match wins; severity is capped because a headline alone is weak evidence.
_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("natural_hazard", "earthquake", "earthquake", ("earthquake", "quake", "terremoto", "erdbeben", "séisme", "seisme")),
    ("natural_hazard", "flood", "flood", ("flood", "inundación", "inundacion", "überschwemmung", "inondation")),
    ("natural_hazard", "wildfire", "wildfire", ("wildfire", "bushfire", "incendio forestal", "waldbrand")),
    ("natural_hazard", "storm", "storm", ("hurricane", "typhoon", "cyclone", "tornado", "huracán", "sturm")),
    ("industrial_accident", "explosion", "explosion", ("explosion", "blast", "explosión", "explosión")),
    ("industrial_accident", "spill", "spill", ("chemical spill", "oil spill", "derrame")),
    ("industrial_accident", "fire", "fire", ("factory fire", "warehouse fire", "plant fire", "refinery fire", "incendio")),
    ("transport_disruption", "port_closure", "port closure", ("port closed", "port closure", "port strike")),
    ("transport_disruption", "airport_closure", "airport closure", ("airport closed", "airport closure", "flights cancelled")),
    ("transport_disruption", "rail_closure", "rail closure", ("derail", "rail line closed", "train service suspended")),
    ("labor_action", "strike", "strike", ("strike", "walkout", "huelga", "streik", "grève")),
    ("civil_unrest", "protest", "protest", ("protesters", "demonstrators", "blockade", "riot", "manifestación")),
    ("infrastructure_outage", "power_outage", "power outage", ("power outage", "blackout", "apagón", "stromausfall")),
    ("infrastructure_outage", "telecom_outage", "telecom outage", ("network outage", "internet outage", "telecom outage")),
    ("health_outbreak", "outbreak", "outbreak", ("outbreak", "epidemic", "brote")),
)  # fmt: skip
_PERSON = re.compile(
    r"\b\d{1,2}[- ]year[- ]old\b|,\s*\d{2},|\b(?:man|woman|boy|girl|teen|teenager|suspect|victim|mayor|singer|actor)\b",
    re.I,
)


_FIRE = re.compile(r"\b(fire|blaze|inferno)\b", re.I)
_FACILITY = re.compile(r"\b(plant|factory|refinery|warehouse|terminal|mill|depot|facility|port|mine)\b", re.I)


def rule_classify(title: str) -> Classification | None:
    """A conservative label from the headline alone. None when it is not clearly a disruption or may name a private person."""
    lowered = title.lower()
    if _PERSON.search(title):
        return None
    if _FIRE.search(title) and _FACILITY.search(title) and not re.search(r"open fire|cease-?fire", lowered):
        return Classification(
            "industrial_accident",
            "fire",
            2,
            False,
            "headline mentions a fire at a facility; model unavailable",
            RULES_VERSION,
        )
    for event_type, subtype, label, words in _RULES:
        if any(w in lowered for w in words):
            return Classification(
                event_type, subtype, 2, False, f"headline mentions {label}; model unavailable", RULES_VERSION
            )
    return None


# -- dead letter queue ----------------------------------------------------------------------------------------------
@dataclass
class DeadLetter:
    id: int
    kind: str
    ref: str
    payload: dict[str, Any]
    attempts: int


def enqueue(
    conn: psycopg.Connection[Any], kind: str, ref: str, payload: dict[str, Any], error: str, now: dt.datetime
) -> None:
    """Park a failed item. A repeat of the same item keeps one row and counts another failure."""
    conn.execute(
        """INSERT INTO dead_letters (kind, ref, payload, last_error, attempts, next_attempt_at)
           VALUES (%s, %s, %s::jsonb, %s, 1, %s)
           ON CONFLICT (kind, ref) DO UPDATE
              SET last_error = EXCLUDED.last_error, updated_at = now(),
                  attempts = dead_letters.attempts + 1,
                  status = CASE WHEN dead_letters.attempts + 1 >= %s THEN 'abandoned' ELSE 'queued' END,
                  next_attempt_at = %s + make_interval(secs => %s)
              WHERE dead_letters.status = 'queued'""",
        (
            kind,
            ref,
            json.dumps(payload),
            error[:500],
            now + dt.timedelta(seconds=BACKOFF_SECONDS[0]),
            MAX_ATTEMPTS,
            now,
            float(BACKOFF_SECONDS[0]),
        ),
    )


def fail(conn: psycopg.Connection[Any], letter: DeadLetter, error: str, now: dt.datetime) -> str:
    attempts = letter.attempts + 1
    if attempts >= MAX_ATTEMPTS:
        status, delay = "abandoned", 0
    else:
        status, delay = "queued", BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
    conn.execute(
        """UPDATE dead_letters SET attempts = %s, status = %s, last_error = %s, updated_at = now(),
                  next_attempt_at = %s + make_interval(secs => %s) WHERE id = %s""",
        (attempts, status, error[:500], now, float(delay), letter.id),
    )
    return status


def due(conn: psycopg.Connection[Any], kind: str, now: dt.datetime, limit: int = 100) -> list[DeadLetter]:
    rows = conn.execute(
        """SELECT id, kind, ref, payload, attempts FROM dead_letters
            WHERE kind = %s AND status = 'queued' AND next_attempt_at <= %s ORDER BY next_attempt_at LIMIT %s""",
        (kind, now, limit),
    ).fetchall()
    return [DeadLetter(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def resolve_letter(conn: psycopg.Connection[Any], letter: DeadLetter) -> None:
    conn.execute("UPDATE dead_letters SET status = 'done', updated_at = now() WHERE id = %s", (letter.id,))


def queue_depth(conn: psycopg.Connection[Any]) -> dict[str, int]:
    rows = conn.execute("SELECT status, count(*) FROM dead_letters GROUP BY status").fetchall()
    return {str(s): int(n) for s, n in rows}
