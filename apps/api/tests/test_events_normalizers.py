import datetime as dt
from typing import Any

import pytest

from meridian.events.config import load_events_config
from meridian.events.normalizers import firms, nws, reliefweb, usgs

CFG = load_events_config()


def quake(
    magnitude: float, depth: float = 10.0, alert: str | None = None, quake_type: str = "earthquake"
) -> dict[str, Any]:
    return {
        "id": "us7000test",
        "geometry": {"type": "Point", "coordinates": [-122.0, 37.0, depth]},
        "properties": {
            "mag": magnitude,
            "place": "5 km N of Somewhere",
            "time": 1_793_362_730_000,
            "updated": 1_793_362_937_000,
            "title": f"M {magnitude} - 5 km N of Somewhere",
            "alert": alert,
            "type": quake_type,
            "tsunami": 0,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
            "status": "reviewed",
        },
    }


@pytest.mark.parametrize(
    ("magnitude", "depth", "alert", "expected"),
    [
        (3.0, 10, None, 1),
        (4.6, 10, None, 2),
        (5.8, 10, None, 3),
        (6.9, 10, None, 4),
        (6.9, 450, None, 3),  # deep events shake less
        (4.6, 10, "orange", 3),  # PAGER raises the class
        (3.0, 500, None, 1),  # never below 1
    ],
)
def test_usgs_severity(magnitude: float, depth: float, alert: str | None, expected: int) -> None:
    event = usgs.normalize(quake(magnitude, depth, alert), CFG)
    assert event is not None and event.severity == expected
    assert event.type == "natural_hazard" and event.subtype == "earthquake" and event.source_ref == "us7000test"
    assert event.geometry == {"type": "Point", "coordinates": [-122.0, 37.0]}
    assert event.occurred_at == dt.datetime(2026, 10, 30, 12, 18, 50, tzinfo=dt.UTC)


def test_usgs_rejects_other_record_types() -> None:
    assert usgs.normalize(quake(3.0, quake_type="quarry blast"), CFG) is None
    assert usgs.normalize({"id": "x", "geometry": {"coordinates": []}, "properties": {"mag": None}}, CFG) is None


def alert(
    name: str = "Flood Warning",
    severity: str = "Severe",
    certainty: str = "Observed",
    geometry: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    props = {
        "id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.abc.001.1",
        "event": name,
        "severity": severity,
        "certainty": certainty,
        "status": "Actual",
        "messageType": "Alert",
        "areaDesc": "Marshall, KS",
        "sent": "2026-10-30T07:36:00-05:00",
        "onset": "2026-10-30T07:36:00-05:00",
        "ends": "2026-10-31T05:57:00-05:00",
        "headline": f"{name} issued",
        "affectedZones": ["https://api.weather.gov/zones/county/KSC117"],
        "references": [],
        **extra,
    }
    return {"id": props["id"], "geometry": geometry, "properties": props}


SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-96.7, 39.6], [-96.5, 39.6], [-96.5, 39.8], [-96.7, 39.8], [-96.7, 39.6]]],
}


def test_nws_maps_type_and_severity() -> None:
    event = nws.normalize(alert(geometry=SQUARE), CFG)
    assert event is not None
    assert (event.type, event.subtype, event.severity, event.location_level) == ("natural_hazard", "flood", 3, "admin2")
    assert event.source_ref == "urn:oid:2.49.0.1.840.0.abc.001.1" and event.uncertainty_km == 0
    assert event.occurred_at == dt.datetime(2026, 10, 30, 12, 36, tzinfo=dt.UTC) and event.expires_at is not None


@pytest.mark.parametrize(
    ("name", "severity", "certainty", "expected"),
    [
        ("Flood Warning", "Extreme", "Observed", 4),
        ("Flood Warning", "Severe", "Possible", 2),  # uncertain certainty lowers by one
        ("Flood Watch", "Moderate", "Likely", 1),  # a watch is one level lower than a warning
        ("Dense Fog Advisory", "Severe", "Likely", 2),  # fog is capped
        ("Flood Warning", "Unknown", "Likely", 1),
    ],
)
def test_nws_severity_rules(name: str, severity: str, certainty: str, expected: int) -> None:
    event = nws.normalize(alert(name, severity, certainty, geometry=SQUARE), CFG)
    assert event is not None and event.severity == expected


def test_nws_ignores_noise_tests_and_unmapped_events() -> None:
    assert nws.normalize(alert("Small Craft Advisory", geometry=SQUARE), CFG) is None
    assert nws.normalize(alert("Test Message", geometry=SQUARE), CFG) is None
    assert nws.normalize(alert("Something Unheard Of", geometry=SQUARE), CFG) is None
    assert nws.normalize(alert(status="Test", geometry=SQUARE), CFG) is None


def test_nws_geometry_comes_from_zones_when_missing() -> None:
    assert nws.normalize(alert(), CFG) is None  # no resolver, no geometry
    seen: list[list[str]] = []

    def resolver(zones: list[str]) -> dict[str, Any]:
        seen.append(zones)
        return SQUARE

    event = nws.normalize(alert(), CFG, resolver)
    assert event is not None and seen == [["https://api.weather.gov/zones/county/KSC117"]]
    marine = alert("Gale Warning", affectedZones=["https://api.weather.gov/zones/marine/GMZ650"])
    assert nws.normalize(marine, CFG, resolver).location_level == "natural"  # type: ignore[union-attr]
    assert nws.normalize(alert(), CFG, lambda zones: None) is None


def test_nws_update_references_and_cancel() -> None:
    update = alert(messageType="Update", references=[{"identifier": "urn:oid:earlier.1", "sent": "x"}], geometry=SQUARE)
    event = nws.normalize(update, CFG)
    assert event is not None and event.supersedes == ["urn:oid:earlier.1"]
    cancelled = nws.normalize(alert(messageType="Cancel", geometry=SQUARE), CFG)
    assert cancelled is not None and cancelled.details["cancelled"] is True


FIRMS_CSV = "latitude,longitude,acq_date,acq_time,frp,confidence,satellite\n" + "\n".join(
    [
        f"34.{500 + i},-118.{300 + i},2026-10-30,0{100 + i},{40 + i},high,N20" for i in range(12)
    ]  # one dense cluster of 12
    + [f"-20.{100 + i},130.{100 + i},2026-10-30,0200,5,nominal,N20" for i in range(3)]  # a small cluster of 3
    + ["60.0,10.0,2026-10-30,0300,3,low,N20"]  # isolated
)


def test_firms_parse_and_cluster() -> None:
    rows = firms.parse_rows(FIRMS_CSV + "\n95.0,10.0,2026-10-30,0300,3,low,N20\nbad,row")
    assert len(rows) == 16  # the row with an impossible latitude and the broken row are dropped
    events = firms.cluster_events(rows, CFG)
    assert len(events) == 1  # only the big cluster is created without an asset nearby
    big = events[0]
    assert big.subtype == "wildfire" and big.details["detections"] == 12 and big.severity == 3
    assert big.geometry["type"] == "Polygon" and big.uncertainty_km >= 1.0
    near = firms.cluster_events(rows, CFG, near_assets=lambda lat, lon, km: lat < 0)
    assert len(near) == 2 and {e.details["detections"] for e in near} == {12, 3}


def test_firms_severity_classes() -> None:
    assert firms.severity_for(3, 10, CFG) == 1
    assert firms.severity_for(5, 10, CFG) == 2
    assert firms.severity_for(2, 600, CFG) == 3
    assert firms.severity_for(150, 0, CFG) == 4


def test_firms_source_ref_is_stable_for_a_growing_fire() -> None:
    rows = firms.parse_rows(FIRMS_CSV)
    first = firms.cluster_events(rows, CFG)[0].source_ref
    more = firms.parse_rows(FIRMS_CSV + "\n34.505,-118.305,2026-10-30,0900,50,high,N20")
    assert firms.cluster_events(more, CFG)[0].source_ref == first


def test_reliefweb_disaster_becomes_a_country_level_event() -> None:
    record = {
        "id": "55001",
        "endpoint": "disasters",
        "fields": {
            "name": "Pakistan: Floods - Aug 2026",
            "url": "https://reliefweb.int/d/55001",
            "date": {"event": "2026-08-20T00:00:00+00:00"},
            "country": [{"iso3": "PAK", "name": "Pakistan"}],
            "type": [{"name": "Flash Flood"}],
            "glide": "FL-2026-000100-PAK",
            "status": "ongoing",
        },
    }
    event = reliefweb.normalize(record, CFG, lambda iso3: (30.0, 70.0, "Pakistan"))
    assert (
        event is not None
        and event.location_level == "country"
        and event.subtype == "flood"
        and event.location_confidence == 0.5
    )
    assert reliefweb.normalize({**record, "endpoint": "reports"}, CFG, lambda iso3: (30.0, 70.0, "Pakistan")) is None
    assert reliefweb.normalize(record, CFG, lambda iso3: None) is None


def test_config_helpers() -> None:
    assert (
        CFG.level_for(0.72) == "critical"
        and CFG.level_for(0.5) == "high"
        and CFG.level_for(0.3) == "medium"
        and CFG.level_for(0.29) == "low"
    )
    assert (
        CFG.lambda_km("natural_hazard", "earthquake", 6.9) == 100
        and CFG.lambda_km("natural_hazard", "earthquake", 5.0) == 30
    )
    assert CFG.lambda_km("industrial_accident", "fire") == 5 and CFG.lambda_km("natural_hazard", "flood") == 25
    assert (
        CFG.half_life_hours("industrial_accident", "fire") == 24
        and CFG.half_life_hours("natural_hazard", "flood") == 72
    )
    assert round(CFG.combined_reliability(["news", "news"]), 2) == 0.84
    assert CFG.combined_reliability(["usgs", "nws", "firms"]) == 0.99
