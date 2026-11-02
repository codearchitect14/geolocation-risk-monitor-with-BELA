"""ReliefWeb disaster records to country-level events (reports are context, not events)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from meridian.events.config import EventsConfig
from meridian.events.types import NormalizedEvent, parse_time

TYPE_MAP: dict[str, tuple[str, str]] = {
    "flood": ("natural_hazard", "flood"),
    "flash flood": ("natural_hazard", "flood"),
    "tropical cyclone": ("natural_hazard", "storm"),
    "storm surge": ("natural_hazard", "flood"),
    "severe local storm": ("natural_hazard", "storm"),
    "earthquake": ("natural_hazard", "earthquake"),
    "volcano": ("natural_hazard", "volcanic"),
    "wild fire": ("natural_hazard", "wildfire"),
    "heat wave": ("natural_hazard", "heat"),
    "cold wave": ("natural_hazard", "storm"),
    "land slide": ("natural_hazard", "landslide"),
    "mud slide": ("natural_hazard", "landslide"),
    "drought": ("natural_hazard", "drought"),
    "tsunami": ("natural_hazard", "flood"),
    "epidemic": ("health_outbreak", "outbreak"),
    "technological disaster": ("industrial_accident", "other"),
    "other": ("other", "other"),
}
CountryLocator = Callable[[str], tuple[float, float, str] | None]  # iso3 -> (lat, lon, name)


def normalize(record: dict[str, Any], cfg: EventsConfig, locate_country: CountryLocator) -> NormalizedEvent | None:
    if record.get("endpoint") != "disasters":
        return None
    fields = record.get("fields") or {}
    types = [t.get("name", "").lower() for t in fields.get("type") or []]
    mapped = next((TYPE_MAP[t] for t in types if t in TYPE_MAP), ("other", "other"))
    country = (fields.get("country") or [{}])[0]
    located = locate_country(country.get("iso3", "")) if country.get("iso3") else None
    when = parse_time((fields.get("date") or {}).get("event"))
    if located is None or when is None:
        return None
    rules = cfg.raw["hazard_feeds"]["reliefweb"]
    lat, lon, name = located
    return NormalizedEvent(
        source_kind="reliefweb",
        source_ref=str(record["id"]),
        type=mapped[0],
        subtype=mapped[1],
        severity=int(rules["default_severity"]),
        title=fields.get("name") or f"Disaster in {name}",
        geometry={"type": "Point", "coordinates": [lon, lat]},
        location_level="country",
        uncertainty_km=float(rules["uncertainty_km"]),
        occurred_at=when,
        published_at=when,
        updated_at=when,
        url=fields.get("url"),
        language="en",
        location_confidence=0.5,
        details={
            "glide": fields.get("glide"),
            "status": fields.get("status"),
            "country": name,
            "reliefweb_types": types,
        },
    )
