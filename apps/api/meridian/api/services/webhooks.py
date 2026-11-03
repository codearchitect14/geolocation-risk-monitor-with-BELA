"""Webhook delivery: HMAC signatures, retries with backoff, and SSRF protection (HTTPS only, public addresses only).

The signature header is `t=<unix time>,v1=<hex>` where v1 is HMAC-SHA256 of `<t>.<body>` with the signing secret. During a
secret rotation the previous secret also signs for a grace period, so receivers can switch without losing deliveries.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

import httpx
import psycopg

from meridian.api.security import crypto
from meridian.api.security.ssrf import Resolver, UnsafeUrl, validate_url

BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
ROTATION_GRACE = dt.timedelta(days=7)
TIMEOUT_SECONDS = 5.0


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(secrets_in_use: list[str], timestamp: int, body: bytes) -> str:
    return f"t={timestamp}," + ",".join(f"v1={sign(s, timestamp, body)}" for s in secrets_in_use)


def verify_signature(
    secret: str, header: str, body: bytes, tolerance_seconds: int = 300, now: float | None = None
) -> bool:
    """Receiver side check, used by the tests and documented for customers."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - timestamp) > tolerance_seconds:
        return False
    candidates = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    expected = sign(secret, timestamp, body)
    return any(hmac.compare_digest(expected, c) for c in candidates)


def _secrets_for(row: dict[str, Any]) -> list[str]:
    current = [crypto.decrypt(row["secret_encrypted"])]
    rotated = row["secret_rotated_at"]
    if row["previous_secret_encrypted"] and rotated and dt.datetime.now(dt.UTC) - rotated < ROTATION_GRACE:
        current.append(crypto.decrypt(row["previous_secret_encrypted"]))
    return current


def deliver_one(
    conn: psycopg.Connection[Any],
    delivery_id: str,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Attempt one delivery. Returns delivered, retry, or abandoned."""
    conn.row_factory = psycopg.rows.dict_row
    try:
        row = conn.execute(
            """SELECT d.id, d.payload, d.attempts, w.url, w.secret_encrypted, w.previous_secret_encrypted, w.secret_rotated_at, w.enabled
                 FROM webhook_deliveries d JOIN webhooks w ON w.id = d.webhook_id WHERE d.id = %s FOR UPDATE OF d""",
            (delivery_id,),
        ).fetchone()
    finally:
        conn.row_factory = psycopg.rows.tuple_row
    if row is None:
        return "abandoned"
    attempts = row["attempts"] + 1
    status_code: int | None = None
    error: str | None = None
    ok = False
    if not row["enabled"]:
        attempts = MAX_ATTEMPTS  # a disabled webhook is not retried
        error = "webhook disabled"
    else:
        body = json.dumps(row["payload"], separators=(",", ":")).encode()
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MeridianSignal-Webhook/1",
            "X-Meridian-Signature": signature_header(_secrets_for(row), timestamp, body),
            "X-Meridian-Delivery": str(row["id"]),
        }
        try:
            host, port, addresses = validate_url(row["url"], resolver)
            owns_client = client is None
            http = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
            try:
                if owns_client:  # connect to the validated address, so a second DNS answer cannot redirect the request
                    literal = f"[{addresses[0]}]" if ":" in addresses[0] else addresses[0]
                    response = http.post(
                        f"https://{literal}:{port}{_path_of(row['url'])}",
                        content=body,
                        headers={**headers, "Host": host},
                        extensions={"sni_hostname": host},
                    )
                else:
                    response = http.post(row["url"], content=body, headers=headers)
            finally:
                if owns_client:
                    http.close()
            status_code = response.status_code
            ok = 200 <= response.status_code < 300
            if not ok:
                error = f"receiver answered {response.status_code}"
        except UnsafeUrl:
            attempts = MAX_ATTEMPTS  # a blocked target is not retried
            error = "target not allowed"
        except httpx.HTTPError as exc:
            error = type(exc).__name__
    if ok:
        conn.execute(
            """UPDATE webhook_deliveries SET status = 'delivered', attempts = %s, last_status_code = %s, last_error = NULL,
                      delivered_at = now() WHERE id = %s""",
            (attempts, status_code, delivery_id),
        )
        return "delivered"
    if attempts >= MAX_ATTEMPTS:
        conn.execute(
            "UPDATE webhook_deliveries SET status = 'abandoned', attempts = %s, last_status_code = %s, last_error = %s WHERE id = %s",
            (attempts, status_code, error, delivery_id),
        )
        return "abandoned"
    conn.execute(
        """UPDATE webhook_deliveries SET attempts = %s, last_status_code = %s, last_error = %s,
                  next_attempt_at = now() + make_interval(secs => %s) WHERE id = %s""",
        (attempts, status_code, error, BACKOFF_SECONDS[attempts - 1], delivery_id),
    )
    return "retry"


def _path_of(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def run_due(conn: psycopg.Connection[Any], limit: int = 50, **kwargs: Any) -> dict[str, int]:
    counts = {"delivered": 0, "retry": 0, "abandoned": 0}
    ids = [
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM webhook_deliveries WHERE status = 'pending' AND next_attempt_at <= now() ORDER BY next_attempt_at LIMIT %s FOR UPDATE SKIP LOCKED",
            (limit,),
        ).fetchall()
    ]
    for delivery_id in ids:
        counts[deliver_one(conn, delivery_id, **kwargs)] += 1
        conn.commit()
    return counts
