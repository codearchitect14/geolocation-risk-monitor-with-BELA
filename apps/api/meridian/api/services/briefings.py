"""Briefing evidence and narrative. The narrative is built from stored fields only; a model written narrative is accepted
only when every number and link in it appears in the evidence."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import Any

from meridian.api.db import Tx
from meridian.notify import DISCLAIMER

TEMPLATE_VERSION = "briefing_template_v1"
LEVELS = ("critical", "high", "medium", "low")


def build_evidence(tx: Tx, start: dt.datetime, end: dt.datetime, limit: int = 15) -> dict[str, Any]:
    counts = dict.fromkeys(LEVELS, 0)
    for level, n in tx.all(
        "SELECT level, count(*) FROM alerts WHERE created_at >= %s AND created_at < %s GROUP BY level", (start, end)
    ):
        counts[level] = n
    rows = tx.all(
        """SELECT a.id, a.level, a.status, a.last_score, e.id, e.title, e.type, e.severity, e.confirmation,
                  s.name, x.distance_km,
                  (SELECT es.url FROM event_sources es WHERE es.event_id = e.id AND es.url IS NOT NULL ORDER BY es.published_at LIMIT 1)
             FROM alerts a JOIN events e ON e.id = a.event_id LEFT JOIN assets s ON s.id = a.asset_id
             LEFT JOIN exposures x ON x.event_id = a.event_id AND x.asset_id = a.asset_id
            WHERE a.created_at >= %s AND a.created_at < %s
            ORDER BY array_position(ARRAY['critical','high','medium','low'], a.level), a.last_score DESC NULLS LAST LIMIT %s""",
        (start, end, limit),
    )
    items = [
        {
            "alert_id": str(r[0]),
            "level": r[1],
            "status": r[2],
            "score": round(float(r[3] or 0), 2),
            "event_id": str(r[4]),
            "title": r[5],
            "type": r[6],
            "severity": r[7],
            "confirmation": "confirmed by a second source" if r[8] == "confirmed" else "reported, not yet confirmed",
            "asset": r[9],
            "distance_km": round(float(r[10]), 1) if r[10] is not None else None,
            "source_url": r[11],
        }
        for r in rows
    ]
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "alerts_by_level": counts,
        "total_alerts": sum(counts.values()),
        "items": items,
        "disclaimer": DISCLAIMER,
    }


def template_narrative(evidence: dict[str, Any]) -> str:
    counts = evidence["alerts_by_level"]
    lines = [
        f"Between {evidence['period_start'][:16]} and {evidence['period_end'][:16]} UTC, {evidence['total_alerts']} alerts were raised: "
        + ", ".join(f"{counts[level]} {level}" for level in LEVELS)
        + "."
    ]
    for item in evidence["items"]:
        where = (
            f" near {item['asset']} ({item['distance_km']} km)"
            if item["asset"] and item["distance_km"] is not None
            else (f" near {item['asset']}" if item["asset"] else " in a watch zone")
        )
        lines.append(
            f"- {item['level'].capitalize()}: {item['title']}{where}; {item['confirmation']}. Source: {item['source_url'] or 'not available'}."
        )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _allowed_numbers(evidence: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    blob = repr(evidence)
    values.update(re.findall(r"\d+(?:\.\d+)?", blob))
    return values


def validate_narrative(text: str, evidence: dict[str, Any]) -> bool:
    """Every number and URL in the text must come from the evidence."""
    if DISCLAIMER not in text:
        return False
    allowed = _allowed_numbers(evidence)
    for number in re.findall(r"\d+(?:\.\d+)?", text.replace(DISCLAIMER, "")):
        if number not in allowed:
            return False
    urls = {i["source_url"] for i in evidence["items"] if i["source_url"]}
    return all(u in urls for u in re.findall(r"https?://\S+?(?=[\s,;)]|\.\s|\.$|$)", text))


def narrative_for(evidence: dict[str, Any], writer: Callable[[dict[str, Any]], str] | None = None) -> tuple[str, str]:
    """(narrative, version). Falls back to the template when the writer fails validation."""
    if writer is not None:
        try:
            candidate = writer(evidence)
        except Exception:  # noqa: BLE001 - any writer failure falls back to the template
            candidate = ""
        if candidate and validate_narrative(candidate, evidence):
            return candidate, "local_model_validated_v1"
    return template_narrative(evidence), TEMPLATE_VERSION
