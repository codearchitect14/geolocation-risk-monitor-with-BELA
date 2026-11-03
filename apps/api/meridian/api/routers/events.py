"""Events, places, ad hoc location, and source freshness. Events and places are global and read only."""

from __future__ import annotations

import datetime as dt
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
    return {
        **event_view(row),
        "sources": [
            {"kind": s[0], "url": s[1], "published_at": s[2], "snippet": s[3], "reliability": s[4]} for s in sources
        ],
        "updates": [{"type": u[0], "detail": u[1], "at": u[2]} for u in updates],
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


@router.get("/sources", summary="Data sources with freshness, counts, and license notes")
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
            }  # fmt: skip
        )
    return {"items": items, "disclaimer": DISCLAIMER}
