"""Alert notifications shared by the event pipeline and the API: webhook queueing and live stream publishing.

The pipeline calls these after it creates or updates alerts. Payloads carry the asset name and distance and never the asset
coordinates unless the tenant and the webhook both opt in. Publishing is best effort: a missing broker never blocks ingestion.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
from typing import Any

import psycopg

log = logging.getLogger("meridian.notify")
DISCLAIMER = (
    "Signals are situational awareness derived from public news and public data feeds. They are not official warnings. "
    "Verify with local authorities and follow their guidance."
)
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# -- live stream ----------------------------------------------------------------------------------------------------
class _LocalBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[queue.Queue[str]]] = {}

    def subscribe(self, channel: str) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(channel, []).append(q)
        return q

    def unsubscribe(self, channel: str, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._subs.get(channel, []):
                self._subs[channel].remove(q)

    def publish(self, channel: str, message: str) -> None:
        with self._lock:
            targets = list(self._subs.get(channel, []))
        for q in targets:
            with contextlib.suppress(queue.Full):
                q.put_nowait(message)


LOCAL = _LocalBroker()
_valkey: Any = None


def _client() -> Any:
    global _valkey
    url = os.environ.get("MS_VALKEY_URL")
    if not url:
        return None
    if _valkey is None:
        try:
            import valkey

            _valkey = valkey.Valkey.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        except Exception:  # noqa: BLE001
            return None
    return _valkey


def publish(channel: str, payload: dict[str, Any]) -> None:
    message = json.dumps(payload, default=str)
    LOCAL.publish(channel, message)
    client = _client()
    if client is not None:
        try:
            client.publish(channel, message)
        except Exception as exc:  # noqa: BLE001
            log.warning("stream publish failed: %s", type(exc).__name__)


class Subscription:
    """Messages for one channel from Valkey when configured, otherwise from the in-process broker."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._queue: queue.Queue[str] | None = None
        self._pubsub: Any = None
        client = _client()
        if client is not None:
            try:
                self._pubsub = client.pubsub(ignore_subscribe_messages=True)
                self._pubsub.subscribe(channel)
            except Exception:  # noqa: BLE001
                self._pubsub = None
        if self._pubsub is None:
            self._queue = LOCAL.subscribe(channel)

    def get(self, timeout: float = 1.0) -> str | None:
        if self._pubsub is not None:
            try:
                message = self._pubsub.get_message(timeout=timeout)
            except Exception:  # noqa: BLE001
                return None
            if message and message.get("type") == "message":
                data = message["data"]
                return data.decode() if isinstance(data, bytes) else str(data)
            return None
        assert self._queue is not None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                self._pubsub.close()
        if self._queue is not None:
            LOCAL.unsubscribe(self.channel, self._queue)


# -- alert payloads -------------------------------------------------------------------------------------------------
def alert_payload(conn: psycopg.Connection[Any], alert_id: str, include_coordinates: bool) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT a.id, a.tenant_id, a.level, a.status, a.last_score, e.id, e.type, e.subtype, e.severity, e.title, e.status,
                  e.confirmation, e.last_seen_at, s.name, x.distance_km, ST_Y(s.geom::geometry), ST_X(s.geom::geometry)
             FROM alerts a JOIN events e ON e.id = a.event_id
             LEFT JOIN assets s ON s.id = a.asset_id
             LEFT JOIN exposures x ON x.event_id = a.event_id AND x.asset_id = a.asset_id
            WHERE a.id = %s""",
        (alert_id,),
    ).fetchone()
    if row is None:
        return None
    payload: dict[str, Any] = {
        "alert": {"id": str(row[0]), "level": row[2], "status": row[3], "score": round(float(row[4] or 0), 3)},
        "event": {
            "id": str(row[5]),
            "type": row[6],
            "subtype": row[7],
            "severity": row[8],
            "title": row[9],
            "status": row[10],
            "confirmation": "confirmed by a second source" if row[11] == "confirmed" else "reported, not yet confirmed",
            "last_seen_at": row[12].isoformat(),
        },
        "asset": {"name": row[13], "distance_km": round(float(row[14]), 1) if row[14] is not None else None},
        "disclaimer": DISCLAIMER,
        "link": f"/app/alerts/{row[0]}",
    }
    if include_coordinates and row[15] is not None:
        payload["asset"]["latitude"], payload["asset"]["longitude"] = round(row[15], 5), round(row[16], 5)
    return payload


def enqueue_webhooks(conn: psycopg.Connection[Any], alert_ids: list[str], kind: str = "alert") -> int:
    """Queue one delivery per matching webhook. Runs inside the caller's transaction."""
    queued = 0
    for alert_id in alert_ids:
        row = conn.execute("SELECT tenant_id, level FROM alerts WHERE id = %s", (alert_id,)).fetchone()
        if row is None:
            continue
        tenant_id, level = row
        settings = conn.execute("SELECT settings FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
        tenant_allows = bool(
            ((settings[0] if settings else {}) or {}).get("risk_config", {}).get("include_coordinates", False)
        )
        for hook_id, min_level, hook_coords in conn.execute(
            "SELECT id, min_level, include_coordinates FROM webhooks WHERE tenant_id = %s AND enabled", (tenant_id,)
        ).fetchall():
            if LEVEL_RANK[level] < LEVEL_RANK[min_level]:
                continue
            payload = alert_payload(conn, alert_id, bool(hook_coords) and tenant_allows)
            if payload is None:
                continue
            conn.execute(
                "INSERT INTO webhook_deliveries (webhook_id, tenant_id, alert_id, kind, payload) VALUES (%s, %s, %s, %s, %s)",
                (hook_id, tenant_id, alert_id, kind, json.dumps(payload)),
            )
            queued += 1
    return queued


def publish_alerts(conn: psycopg.Connection[Any], alert_ids: list[str]) -> None:
    for alert_id in alert_ids:
        payload = alert_payload(conn, alert_id, include_coordinates=False)
        row = conn.execute("SELECT tenant_id FROM alerts WHERE id = %s", (alert_id,)).fetchone()
        if payload is None or row is None:
            continue
        publish(f"alerts:{row[0]}", payload)
        publish(f"events:{row[0]}", {"event": payload["event"], "disclaimer": DISCLAIMER})
