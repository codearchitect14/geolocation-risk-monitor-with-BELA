from typing import Any

import psycopg
import pytest

from meridian.linking.event_location import has_cue, select_event_location
from meridian.linking.types import MentionResult, PlaceRecord


def place(
    pid: int, name: str, ptype: str, cc: str, lat: float, lon: float, level: str, km: float, pop: int | None = None
) -> PlaceRecord:
    return PlaceRecord(
        pid, name, ptype, cc, None, pop, lat, lon, km, location_level=level, country_level=(level == "country")
    )


def mention(start: int, p: PlaceRecord) -> MentionResult:
    return MentionResult(start, start + len(p.name), p.name, "bela", 0.9, 0.9, 0.5, "accept", p, confidence=0.9)


@pytest.fixture
def hierarchy(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE places CASCADE")
        for pid, name, parent in (
            (1, "Netherlands", None),
            (2, "South Holland", 1),
            (3, "Rotterdam", 2),
            (4, "Germany", None),
        ):
            cur.execute(
                """INSERT INTO places (id, geonames_id, name, name_normalized, type, lat, lon, centroid, geom, source, parent_place_id)
                   OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, 'city', 0, 0, ST_SetSRID(ST_MakePoint(0, 0), 4326),
                                                   ST_SetSRID(ST_MakePoint(0, 0), 4326), 'geonames', %s)""",
                (pid, pid, name, name.lower(), parent),
            )
    conn.commit()
    return conn


def test_cue_detection() -> None:
    sentence = "A fire broke out in Rotterdam"
    assert has_cue(sentence, sentence.index("Rotterdam"))
    spanish = "Un incendio en Valencia"
    assert has_cue(spanish, spanish.index("Valencia"))
    assert not has_cue("Rotterdam police said", 0)
    assert not has_cue("said Mayor Smith, Rotterdam", 18)


def test_specific_place_inside_the_stated_country_wins(hierarchy: psycopg.Connection[Any]) -> None:
    nl = place(1, "Netherlands", "country", "NL", 52.1, 5.3, "country", 300)
    rotterdam = place(3, "Rotterdam", "city", "NL", 51.92, 4.48, "city", 25, 650000)
    text = "Fire at port in Rotterdam, Netherlands officials said. The Netherlands has no comment."
    mentions = [
        mention(text.index("Rotterdam"), rotterdam),
        mention(text.index("Netherlands"), nl),
        mention(text.rindex("Netherlands"), nl),
    ]
    result = select_event_location(hierarchy, mentions, text, title_chars=50)
    assert result is not None and result.place.name == "Rotterdam"
    assert result.level == "city" and not result.country_level and result.uncertainty_km == 25.0


def test_country_only_article_is_country_level(hierarchy: psycopg.Connection[Any]) -> None:
    nl = place(1, "Netherlands", "country", "NL", 52.1, 5.3, "country", 300)
    text = "Strike halts traffic across the Netherlands on Monday."
    result = select_event_location(hierarchy, [mention(text.index("Netherlands"), nl)], text, title_chars=len(text))
    assert result is not None and result.country_level and result.level == "country"


def test_unrelated_places_widen_the_uncertainty(hierarchy: psycopg.Connection[Any]) -> None:
    rotterdam = place(3, "Rotterdam", "city", "NL", 51.92, 4.48, "city", 25, 650000)
    berlin = place(5, "Berlin", "city", "DE", 52.52, 13.40, "city", 25, 3600000)
    text = "Storm hits Rotterdam and Berlin in Europe on Monday."
    mentions = [mention(text.index("Rotterdam"), rotterdam), mention(text.index("Berlin"), berlin)]
    result = select_event_location(hierarchy, mentions, text, title_chars=len(text))
    assert result is not None and result.widened and result.uncertainty_km > 500


def test_no_resolved_places_gives_no_location(hierarchy: psycopg.Connection[Any]) -> None:
    assert select_event_location(hierarchy, [], "Nothing here.") is None
