"""Events, places, ad hoc location, and source freshness. Events and places are global and read only."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from meridian.api import db
from meridian.api.auth import Principal, get_tx, require
from meridian.api.db import Tx
from meridian.api.errors import ProblemError
from meridian.api.pagination import clamp_limit, decode_cursor, encode_cursor, page
from meridian.api.routers.common import EVENT_TYPES, feature_collection, not_found
from meridian.api.security import ratelimit
from meridian.config import get_settings
from meridian.events.resilience import DependencyHealth
from meridian.linking.nel_client import NelClient
from meridian.llm.client import LlmClient
from meridian.notify import DISCLAIMER

router = APIRouter(tags=["events and places"])

EVENT_COLUMNS = """e.id, e.type, e.subtype, e.severity, e.status, e.confirmation, e.first_seen_at, e.last_seen_at, e.occurred_at, e.title, e.summary,
                   ST_AsGeoJSON(e.geom)::json, e.uncertainty_km, e.location_level, e.location_confidence, e.reduced_confidence,
                   (SELECT count(*) FROM event_sources s WHERE s.event_id = e.id)"""


def event_view(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]), "type": r[1], "subtype": r[2], "severity": r[3], "status": r[4], "confirmation": r[5],
        "confirmation_text": "confirmed by a second source" if r[5] == "confirmed" else "reported, not yet confirmed",
        "first_seen_at": r[6], "last_seen_at": r[7], "occurred_at": r[8], "title": r[9], "summary": r[10], "geometry": r[11],
        "uncertainty_km": r[12], "location_level": r[13], "location_confidence": r[14], "reduced_confidence": r[15], "source_count": r[16],
    }  # fmt: skip


@router.get("/events", summary="List events")
def list_events(
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    type: str | None = Query(default=None, max_length=40),
    min_severity: int | None = Query(default=None, ge=1, le=4),
    status: str | None = Query(default=None, pattern="^(new|developing|ongoing|resolved)$"),
    confirmation: str | None = Query(default=None, pattern="^(confirmed|unconfirmed)$"),
    near_my_assets: bool = False,
    format: str = Query(default="json", pattern="^(json|geojson)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    where: list[str] = ["e.geom IS NOT NULL"]
    params: list[Any] = []
    if bbox:
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise ProblemError(422, "bbox needs four numbers.", code="invalid-bbox") from exc
        if not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
            raise ProblemError(422, "bbox is outside the valid range.", code="invalid-bbox")
        where.append("e.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
        params += [x0, y0, x1, y1]
    for clause, value in (
        ("e.last_seen_at >= %s", since),
        ("e.last_seen_at <= %s", until),
        ("e.type = %s", type),
        ("e.severity >= %s", min_severity),
        ("e.status = %s", status),
        ("e.confirmation = %s", confirmation),
    ):
        if value is not None:
            where.append(clause)
            params.append(value)
    if type is not None and type not in EVENT_TYPES:
        raise ProblemError(422, "Unknown event type.", code="invalid-type")
    if near_my_assets:
        where.append("EXISTS (SELECT 1 FROM exposures x WHERE x.event_id = e.id)")
    after = decode_cursor(cursor, 2)
    if after:
        where.append("(e.last_seen_at, e.id) < (%s::timestamptz, %s::uuid)")
        params += after
    rows = tx.all(
        f"SELECT {EVENT_COLUMNS} FROM events e WHERE {' AND '.join(where)} ORDER BY e.last_seen_at DESC, e.id DESC LIMIT %s",
        [*params, clamp_limit(limit) + 1],
    )  # noqa: S608
    result = page(
        [event_view(r) for r in rows],
        clamp_limit(limit),
        lambda i: encode_cursor(i["last_seen_at"].isoformat(), i["id"]),
    )
    result["disclaimer"] = DISCLAIMER
    if format == "geojson":
        return {**feature_collection(result["items"]), "next_cursor": result["next_cursor"], "disclaimer": DISCLAIMER}
    return result


def _timeline(sources: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sources and pipeline updates in time order, oldest first, for the update timeline."""
    items = [
        {"at": s["published_at"], "kind": "source", "source_kind": s["kind"], "url": s["url"], "snippet": s["snippet"]}
        for s in sources
        if s["published_at"]
    ] + [{"at": u["at"], "kind": "update", "update_type": u["type"], "detail": u["detail"]} for u in updates]
    return sorted(items, key=lambda i: i["at"])


def _location(tx: Tx, event_id: str) -> dict[str, Any] | None:
    r = tx.one(
        """SELECT ST_AsGeoJSON(e.geom)::json, e.uncertainty_km, e.location_level, e.location_confidence,
                  CASE WHEN e.geom IS NOT NULL AND e.uncertainty_km > 0
                       THEN ST_AsGeoJSON(ST_Buffer(ST_Centroid(e.geom)::geography, e.uncertainty_km * 1000, 24)::geometry, 5)::json END,
                  p.id, p.name, p.type, p.country_code, p.admin1_name
             FROM events e LEFT JOIN places p ON p.id = e.location_place_id WHERE e.id = %s""",
        (event_id,),
    )
    if r is None or r[0] is None:
        return None
    return {
        "geometry": r[0],
        "uncertainty_km": r[1],
        "level": r[2],
        "confidence": r[3],
        "uncertainty_circle": r[4],
        "place": None
        if r[5] is None
        else {"id": r[5], "name": r[6], "type": r[7], "country_code": r[8], "admin1": r[9]},
    }


def _linked_places(tx: Tx, event_id: str) -> list[dict[str, Any]]:
    rows = tx.all(
        """SELECT p.id, p.name, p.type, p.country_code, p.admin1_name, count(*) AS mentions, p.id = e.location_place_id
             FROM events e JOIN event_sources s ON s.event_id = e.id JOIN mentions m ON m.article_id = s.article_id
             JOIN places p ON p.id = m.place_id WHERE e.id = %s AND m.route <> 'unresolved'
            GROUP BY p.id, e.location_place_id ORDER BY 7 DESC, 6 DESC, p.name LIMIT 20""",
        (event_id,),
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "type": r[2],
            "country_code": r[3],
            "admin1": r[4],
            "mentions": r[5],
            "is_event_location": r[6],
        }
        for r in rows
    ]


def _location_candidates(tx: Tx, event_id: str) -> list[dict[str, Any]]:
    """Place mentions in the source articles with every candidate considered and its score components."""
    mentions = tx.all(
        """SELECT m.id, m.surface, m.route, m.decision, m.place_id, count(*) OVER () AS total
             FROM events e JOIN event_sources s ON s.event_id = e.id JOIN mentions m ON m.article_id = s.article_id
            WHERE e.id = %s ORDER BY m.el_score DESC NULLS LAST, m.id LIMIT 12""",
        (event_id,),
    )
    out: list[dict[str, Any]] = []
    for mid, surface, route, decision, chosen, _ in mentions:
        cands = tx.all(
            """SELECT c.rank, p.id, p.name, p.type, p.country_code, c.bela_score, c.gazetteer_score, c.context_score,
                      c.blink_score, c.llm_label
                 FROM mention_candidates c JOIN places p ON p.id = c.place_id WHERE c.mention_id = %s
                ORDER BY c.rank LIMIT 5""",
            (mid,),
        )
        out.append(
            {
                "surface": surface,
                "route": route,
                "decision": decision,
                "chosen_place_id": chosen,
                "candidates": [
                    {
                        "rank": c[0],
                        "place_id": c[1],
                        "name": c[2],
                        "type": c[3],
                        "country_code": c[4],
                        "bela_score": c[5],
                        "gazetteer_score": c[6],
                        "context_score": c[7],
                        "blink_score": c[8],
                        "llm_label": c[9],
                    }
                    for c in cands
                ],
            }
        )
    return out


SIMILAR_RADIUS_KM = 100
SIMILAR_WINDOW_DAYS = 365


def _similar(tx: Tx, event_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Earlier events of the same type within 100 km during the previous year."""
    rows = tx.all(
        """SELECT o.id, o.title, o.type, o.subtype, o.severity, o.status, o.first_seen_at,
                  ST_Distance(o.geom::geography, e.geom::geography) / 1000.0
             FROM events e JOIN events o ON o.id <> e.id AND o.type = e.type AND o.geom IS NOT NULL
                  AND o.first_seen_at < e.first_seen_at AND o.first_seen_at >= e.first_seen_at - make_interval(days => %s)
                  AND ST_DWithin(o.geom::geography, e.geom::geography, %s)
            WHERE e.id = %s AND e.geom IS NOT NULL ORDER BY 8 LIMIT %s""",
        (SIMILAR_WINDOW_DAYS, SIMILAR_RADIUS_KM * 1000, event_id, limit),
    )
    return [
        {
            "id": str(r[0]),
            "title": r[1],
            "type": r[2],
            "subtype": r[3],
            "severity": r[4],
            "status": r[5],
            "first_seen_at": r[6],
            "distance_km": round(float(r[7]), 1),
        }
        for r in rows
    ]


@router.get("/events/{event_id}", summary="One event with its sources, updates, and exposures for this tenant")
def get_event(
    event_id: uuid.UUID, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    row = tx.one(f"SELECT {EVENT_COLUMNS} FROM events e WHERE e.id = %s", (str(event_id),))  # noqa: S608
    if row is None:
        raise not_found("Event")
    sources = tx.all(
        "SELECT source_kind, url, published_at, snippet, reliability FROM event_sources WHERE event_id = %s ORDER BY published_at NULLS LAST",
        (str(event_id),),
    )
    updates = tx.all(
        "SELECT update_type, detail, created_at FROM event_updates WHERE event_id = %s ORDER BY created_at DESC LIMIT 50",
        (str(event_id),),
    )
    exposures = tx.all(
        """SELECT a.id, a.name, x.distance_km, x.score, x.level, x.components FROM exposures x JOIN assets a ON a.id = x.asset_id
            WHERE x.event_id = %s ORDER BY x.score DESC LIMIT 100""",
        (str(event_id),),
    )
    sources_view = [
        {"kind": s[0], "url": s[1], "published_at": s[2], "snippet": s[3], "reliability": s[4]} for s in sources
    ]
    updates_view = [{"type": u[0], "detail": u[1], "at": u[2]} for u in updates]
    return {
        **event_view(row),
        "sources": sources_view,
        "updates": updates_view,
        "timeline": _timeline(sources_view, updates_view),
        "location": _location(tx, str(event_id)),
        "linked_places": _linked_places(tx, str(event_id)),
        "location_candidates": _location_candidates(tx, str(event_id)),
        "similar_past_incidents": _similar(tx, str(event_id)),
        "exposures": [
            {
                "asset_id": str(e[0]),
                "asset_name": e[1],
                "distance_km": round(float(e[2]), 2),
                "score": round(float(e[3]), 4),
                "level": e[4],
                "components": e[5],
            }
            for e in exposures
        ],
        "disclaimer": DISCLAIMER,
    }


# -- places ---------------------------------------------------------------------------------------------------------
@router.get("/places/search", summary="Search the place knowledge base")
def search_places_endpoint(
    q: str = Query(min_length=1, max_length=120),
    country: str | None = Query(default=None, pattern="^[A-Za-z]{2}$"),
    limit: int = Query(default=10, ge=1, le=25),
    principal: Principal = Depends(require("view")),
    tx: Tx = Depends(get_tx),
) -> dict[str, Any]:
    from meridian.geo.search import search_places

    hits = search_places(tx.conn, q, k=limit, country_code=country.upper() if country else None)
    return {
        "items": [
            {
                "id": h.place_id,
                "name": h.name,
                "type": h.type,
                "country_code": h.country_code,
                "admin1": h.admin1_name,
                "population": h.population,
                "lat": h.lat,
                "lon": h.lon,
                "uncertainty_km": h.uncertainty_km,
                "qid": h.qid,
                "score": round(h.score, 3),
            }
            for h in hits
        ]
    }


@router.get("/places/{place_id}", summary="One place")
def get_place(
    place_id: int, principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)
) -> dict[str, Any]:
    r = tx.one(
        "SELECT id, name, type, country_code, admin1_name, population, lat, lon, uncertainty_km, qid, location_level FROM places WHERE id = %s",
        (place_id,),
    )
    if r is None:
        raise not_found("Place")
    aliases = [
        a[0] for a in tx.all("SELECT alias FROM place_aliases WHERE place_id = %s ORDER BY alias LIMIT 30", (place_id,))
    ]
    return {
        "id": r[0],
        "name": r[1],
        "type": r[2],
        "country_code": r[3],
        "admin1": r[4],
        "population": r[5],
        "lat": r[6],
        "lon": r[7],
        "uncertainty_km": r[8],
        "qid": r[9],
        "location_level": r[10],
        "aliases": aliases,
    }


# -- locate ---------------------------------------------------------------------------------------------------------
class LocateBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    title: str = Field(default="", max_length=500)
    lang: str | None = Field(default=None, pattern="^[a-z]{2,3}$")
    outlet_country: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Fire at chemical plant in Springfield, Illinois",
                "text": "A fire broke out on Sunday at a plant in Springfield, Illinois.",
                "lang": "en",
            }
        }
    }


Locator = Callable[[LocateBody], dict[str, Any]]


def default_locator() -> Locator:
    """Builds the linking pipeline on demand. Raises a 503 problem when the entity linker is not running."""

    def locate_text(body: LocateBody) -> dict[str, Any]:
        from meridian.config import get_settings
        from meridian.linking.config import load_config
        from meridian.linking.context import CountryIndex
        from meridian.linking.locate import locate
        from meridian.linking.nel_client import NelClient
        from meridian.linking.pipeline import LinkingPipeline, Stages
        from meridian.linking.reranker import Reranker
        from meridian.llm.client import LlmClient

        nel = NelClient()
        if not nel.healthy():
            raise ProblemError(503, "The place linking service is not available.", code="linker-unavailable")
        llm = LlmClient()
        with db.system_connection() as conn:  # places are global reference data
            reranker = Reranker.load(get_settings().data_dir / "processed" / "eval" / "reranker_geo_config_v1.joblib")
            pipeline = LinkingPipeline(
                conn, nel, load_config(), reranker, llm if llm.healthy() else None, CountryIndex.load(conn)
            )
            result = locate(
                pipeline,
                body.text,
                title=body.title,
                lang=body.lang,
                outlet_country=body.outlet_country,
                stages=Stages(llm=llm.healthy()),
            )
        mentions = [
            {
                "surface": m.surface,
                "start": m.start,
                "end": m.end,
                "route": m.route,
                "place_id": m.decision.place_id if m.decision else None,
                "name": m.decision.name if m.decision else None,
            }
            for m in result.article.mentions
        ]
        loc = result.event_location
        return {
            "mentions": mentions,
            "event_location": None
            if loc is None
            else {
                "place_id": loc.place.place_id,
                "name": loc.place.name,
                "lat": loc.lat,
                "lon": loc.lon,
                "uncertainty_km": loc.uncertainty_km,
                "level": loc.level,
                "confidence": loc.confidence,
            },
        }

    return locate_text


def get_locator() -> Locator:
    return default_locator()


@router.post("/locate", summary="Link places in ad hoc text and choose the event location")
def locate_endpoint(
    body: LocateBody, principal: Principal = Depends(require("view")), locator: Locator = Depends(get_locator)
) -> dict[str, Any]:
    ratelimit.check(
        f"locate:{principal.user_id or principal.api_key_id}",
        30,
        60,
        detail="Locate requests are limited to 30 per minute.",
    )
    result = locator(body)
    result["disclaimer"] = DISCLAIMER
    return result


# -- sources --------------------------------------------------------------------------------------------------------
SOURCE_NOTES = {
    "usgs": (
        "U.S. Geological Survey earthquakes",
        "Public domain. Automated records; confirm with official channels.",
        3600,
    ),
    "nws": (
        "National Weather Service alerts",
        "Open data. Alerts are official products of the issuing office; the platform restates them.",
        3600,
    ),
    "firms": (
        "NASA FIRMS active fire detections",
        "Free with MAP_KEY. Satellite detections are not confirmed fires.",
        4 * 3600 * 3,
    ),
    "reliefweb": (
        "ReliefWeb disasters",
        "Open access; some content belongs to original sources. Country level only.",
        86400,
    ),
    "news": (
        "Public news reports",
        "Publisher copyright. Titles, snippets of at most 300 characters, and links only.",
        6 * 3600,
    ),
}


FEED_JOBS = {"usgs": "usgs", "nws": "nws", "firms": "firms", "reliefweb": "reliefweb", "news": "gdelt"}
_health = DependencyHealth(NelClient(), LlmClient())  # probes are cached for 20 seconds


def feed_state(kind: str) -> dict[str, Any]:
    """Harvest job health for a source, from the status file the job writes after every run."""
    path = get_settings().data_dir / "raw" / "_status" / f"{FEED_JOBS[kind]}.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "not running", "consecutive_failures": 0, "last_success": None, "last_error": None}
    failures = int(state.get("consecutive_failures", 0))
    error = (state.get("last_error") or {}).get("error")
    return {
        "state": "failing" if failures >= 3 else ("retrying" if failures else "ok"),
        "consecutive_failures": failures,
        "last_success": state.get("last_success"),
        "last_error": str(error)[:200] if failures and error else None,
    }


@router.get("/sources", summary="Data sources with freshness, counts, license notes, and pipeline component status")
def list_sources(principal: Principal = Depends(require("view")), tx: Tx = Depends(get_tx)) -> dict[str, Any]:
    rows = {
        r[0]: r
        for r in tx.all(
            """SELECT source_kind, max(created_at), count(*), count(*) FILTER (WHERE created_at > now() - interval '24 hours')
                 FROM event_sources GROUP BY source_kind"""
        )
    }
    now = dt.datetime.now(dt.UTC)
    items = []
    for kind, (name, note, stale_after) in SOURCE_NOTES.items():
        r = rows.get(kind)
        last = r[1] if r else None
        age = (now - last).total_seconds() if last else None
        items.append(
            {
                "kind": kind,
                "name": name,
                "license_note": note,
                "last_record_at": last,
                "records_total": r[2] if r else 0,
                "records_24h": r[3] if r else 0,
                "freshness": "no data" if age is None else ("current" if age <= stale_after else "stale"),
                "feed": feed_state(kind),
            }  # fmt: skip
        )
    reduced = tx.one(
        "SELECT count(*) FROM events WHERE reduced_confidence AND last_seen_at > now() - interval '7 days'"
    )
    queue = {str(r[0]): int(r[1]) for r in tx.all("SELECT status, count(*) FROM dead_letters GROUP BY status")}
    pipeline = {
        "model_server": "up" if _health.up("llm") else "down",
        "entity_linker": "up" if _health.up("nel") else "down",
        "reduced_confidence_events_7d": int(reduced[0]) if reduced else 0,
        "dead_letters": {"queued": queue.get("queued", 0), "abandoned": queue.get("abandoned", 0)},
        "note": "When the model server or the entity linker is down, news reports are still processed with headline rules and "
        "gazetteer matching, and the resulting incidents are marked reduced confidence.",
    }
    return {"items": items, "pipeline": pipeline, "disclaimer": DISCLAIMER}
