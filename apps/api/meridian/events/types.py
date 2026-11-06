"""The common shape every source is normalized into before it becomes an event."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

SOURCE_KINDS = ("news", "usgs", "nws", "firms", "reliefweb")


@dataclass
class NormalizedEvent:
    source_kind: str
    source_ref: str  # stable identifier from the source, used for idempotent updates
    type: str
    subtype: str | None
    severity: int
    title: str
    geometry: dict[str, Any]  # GeoJSON point or polygon
    location_level: str
    uncertainty_km: float
    occurred_at: dt.datetime | None
    published_at: dt.datetime
    url: str | None = None
    summary: str | None = None
    snippet: str | None = None  # at most 300 characters
    location_confidence: float = 1.0
    location_place_id: int | None = None
    language: str | None = None
    domain: str | None = None
    expires_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None  # revision time of the source record
    supersedes: list[str] = field(default_factory=list)  # source refs this record replaces (alert updates)
    details: dict[str, Any] = field(default_factory=dict)
    article_id: str | None = None
    reduced: bool = False  # built without the model server or the entity linker

    def centroid(self) -> tuple[float, float]:
        """(lat, lon) of the geometry."""
        if self.geometry["type"] == "Point":
            lon, lat = self.geometry["coordinates"][:2]
            return float(lat), float(lon)
        from shapely.geometry import shape

        point = shape(self.geometry).centroid
        return float(point.y), float(point.x)


def utc(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC) if value.tzinfo else value.replace(tzinfo=dt.UTC)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
