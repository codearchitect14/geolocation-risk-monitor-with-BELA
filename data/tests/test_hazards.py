import datetime as dt
from typing import Any

import httpx
import pytest

import common
import pull_firms
import pull_nws
import pull_reliefweb
import pull_usgs


def usgs_feature(event_id: str, updated: int, lon: float = -122.0, lat: float = 37.0) -> dict[str, Any]:
    return {
        "id": event_id,
        "properties": {"time": 1_700_000_000_000, "updated": updated, "mag": 4.7},
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10]},
    }


def test_usgs_store_is_idempotent_and_handles_revisions() -> None:
    directory = common.raw_dir("hazards", "usgs")
    state: dict[str, Any] = {}
    features = [usgs_feature("a", 1), usgs_feature("b", 1), usgs_feature("bad", 1, lon=500)]
    assert pull_usgs.store_features(features, state, directory) == (2, 1)
    assert pull_usgs.store_features(features, state, directory) == (0, 1)
    assert pull_usgs.store_features([usgs_feature("a", 2)], state, directory) == (1, 0)
    files = list(directory.glob("2023-11-14.jsonl"))
    assert len(files) == 1 and len(files[0].read_text(encoding="utf-8").splitlines()) == 3


def test_usgs_split_windows_cover_range() -> None:
    windows = pull_usgs.split_windows(dt.date(2026, 1, 1), dt.date(2026, 1, 20), 7)
    assert windows[0][0] == dt.date(2026, 1, 1) and windows[-1][1] == dt.date(2026, 1, 21)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:], strict=False))


def test_nws_requires_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        pull_nws.build_user_agent()
    monkeypatch.setenv("MS_CONTACT", "https://example.org/contact")
    assert "example.org" in pull_nws.build_user_agent()
    monkeypatch.setenv("NWS_USER_AGENT", "custom-agent")
    assert pull_nws.build_user_agent() == "custom-agent"


def test_nws_pull_deduplicates_by_alert_id() -> None:
    payload = {
        "features": [
            {"properties": {"id": "x1", "event": "Flood Warning"}, "geometry": None},
            {"properties": {"id": "x2", "event": "Heat Advisory"}, "geometry": {"type": "Polygon"}},
            {"properties": {"event": "no id"}},
        ]
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    first = pull_nws.pull(client, None)
    second = pull_nws.pull(client, None)
    assert (first["written"], first["rejected"], first["with_geometry"]) == (2, 1, 1)
    assert second["written"] == 0


def test_firms_url_and_window_limits() -> None:
    url = pull_firms.build_url("KEY", "VIIRS_SNPP_NRT", "world", 1, dt.date(2026, 10, 1))
    assert url.endswith("/KEY/VIIRS_SNPP_NRT/world/1/2026-10-01")
    with pytest.raises(ValueError):
        pull_firms.build_url("KEY", "S", "world", 6, None)
    plan = pull_firms.windows(dt.date(2026, 10, 1), dt.date(2026, 10, 12))
    assert [(d.isoformat(), n) for d, n in plan] == [("2026-10-01", 5), ("2026-10-06", 5), ("2026-10-11", 2)]


def test_firms_validate_csv() -> None:
    good = "latitude,longitude,acq_date,acq_time\n10.0,20.0,2026-10-01,0130\n95.0,20.0,2026-10-01,0131\n"
    assert pull_firms.validate_csv(good) == 1
    assert pull_firms.validate_csv("") == 0
    with pytest.raises(pull_firms.FirmsError):
        pull_firms.validate_csv("Invalid MAP_KEY.")


def test_firms_requires_key() -> None:
    with pytest.raises(SystemExit):
        pull_firms.run(["VIIRS_SNPP_NRT"], "world", None, None, 1)


def test_reliefweb_skips_without_appname() -> None:
    assert pull_reliefweb.main([]) == 0
    assert not list(common.raw_dir("hazards", "reliefweb").glob("*.jsonl"))


def test_reliefweb_reduces_body_to_snippet() -> None:
    record = pull_reliefweb.reduce_record("reports", {"id": "1", "fields": {"title": "t", "body": "word " * 200}})
    assert len(record["fields"]["snippet"]) == 300 and "body" not in record["fields"]
