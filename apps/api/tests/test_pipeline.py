"""End to end test of merge, hierarchy, and finalize on a small hand-built scenario."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from meridian.etl import finalize, geonames, hierarchy, merge, reference, wikidata
from meridian.geo.names import normalize_name
from meridian.geo.search import search_places

BOX_NL = "POLYGON((3 50.5, 8 50.5, 8 53.7, 3 53.7, 3 50.5))"
BOX_US = "POLYGON((-125 25, -66 25, -66 49, -125 49, -125 25))"
BOX_ZH = "POLYGON((3.9 51.6, 5 51.6, 5 52.3, 3.9 52.3, 3.9 51.6))"


def gn(
    gid: int,
    name: str,
    lat: float,
    lon: float,
    klass: str,
    code: str,
    ptype: str,
    cc: str,
    a1: str | None = None,
    a2: str | None = None,
    pop: int | None = None,
) -> tuple[Any, ...]:
    return (gid, name, normalize_name(name), lat, lon, klass, code, ptype, cc, a1, a2, pop)


def wd(
    qid: str,
    name: str,
    ptype: str,
    lat: float,
    lon: float,
    *,
    country: str | None = None,
    gid: int | None = None,
    pop: int | None = None,
    sitelinks: int = 5,
    parents: list[str] | None = None,
    desc: str | None = None,
) -> tuple[Any, ...]:
    return (qid, name, normalize_name(name), ptype, lat, lon, country, parents or [], pop, gid, None, sitelinks, desc)


@pytest.fixture
def scenario(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE ref_country_info, ref_countries, ref_admin1, place_uncertainty_rules, places CASCADE")
        cur.executemany(
            "INSERT INTO ref_country_info (iso2, iso3, name, geonames_id) VALUES (%s, %s, %s, %s)",
            [("NL", "NLD", "Netherlands", 2750405), ("US", "USA", "United States", 6252001)],
        )
        cur.execute(
            "INSERT INTO ref_countries (iso2, adm0_a3, name, wikidata_qid, geom) VALUES "
            "('NL', 'NLD', 'Netherlands', 'Q55', ST_Multi(ST_GeomFromText(%s, 4326))), "
            "('US', 'USA', 'United States', 'Q30', ST_Multi(ST_GeomFromText(%s, 4326)))",
            (BOX_NL, BOX_US),
        )
        cur.execute(
            "INSERT INTO ref_admin1 (iso2, name, geonames_id, geom) VALUES "
            "('NL', 'Zuid-Holland', 2743698, ST_Multi(ST_GeomFromText(%s, 4326)))",
            (BOX_ZH,),
        )
        reference.seed_uncertainty_rules(conn)
        cur.execute(geonames.STAGING_DDL)
        cur.execute(wikidata.STAGING_DDL)
        cur.executemany(
            "INSERT INTO stg_geonames VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                gn(2750405, "Netherlands", 52.0, 5.5, "A", "PCLI", "country", "NL"),
                gn(6252001, "United States", 39.8, -98.6, "A", "PCLI", "country", "US"),
                gn(2743698, "South Holland", 52.0, 4.5, "A", "ADM1", "admin1", "NL", "11"),
                gn(4896861, "Illinois", 40.0, -89.0, "A", "ADM1", "admin1", "US", "IL"),
                gn(4398678, "Missouri", 38.6, -92.6, "A", "ADM1", "admin1", "US", "MO"),
                gn(2747891, "Rotterdam", 51.9225, 4.47917, "P", "PPL", "city", "NL", "11", None, 650000),
                gn(4250542, "Springfield", 39.80172, -89.64371, "P", "PPLA", "city", "US", "IL", None, 116250),
                gn(4409896, "Springfield", 37.21533, -93.29824, "P", "PPLA2", "city", "US", "MO", None, 167882),
                gn(2993361, "Rotterdam The Hague Airport", 51.9569, 4.4372, "S", "AIRP", "airport", "NL", "11"),
                gn(111, "Duplicate Claim Town", 52.1, 4.6, "P", "PPL", "village", "NL", "11", None, 3000),
                gn(222, "Far Link Village", 52.2, 4.7, "P", "PPL", "village", "NL", "11", None, 2000),
            ],
        )
        cur.executemany(
            "INSERT INTO stg_geonames_alt VALUES (%s,%s,%s,%s,%s)",
            [
                (2747891, "nl", "Rotterdam", normalize_name("Rotterdam"), "preferred"),
                (2747891, "en", "Roterdam", normalize_name("Roterdam"), "alias"),
                (4250542, "en", "Springfield, Illinois", normalize_name("Springfield, Illinois"), "alias"),
                (2993361, None, "RTM", "rtm", "iata"),
            ],
        )
        cur.executemany(
            "INSERT INTO stg_wikidata VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                wd("Q55", "Netherlands", "country", 52.1, 5.3, gid=2750405, pop=17_000_000),
                wd("Q30", "United States", "country", 39.8, -98.6, gid=6252001, pop=330_000_000),
                wd(
                    "Q647",
                    "Rotterdam",
                    "city",
                    51.9225,
                    4.47917,
                    country="Q55",
                    gid=2747891,
                    pop=651000,
                    parents=["Q701"],
                    desc="city in the Netherlands",
                ),
                # no P1566: matched by name, country, and proximity to the Illinois city, not Missouri
                wd("Q40", "Springfield", "city", 39.80, -89.65, country="Q30", pop=114000, sitelinks=40),
                wd("Q41", "Springfield", "city", 37.21, -93.30, country="Q30", pop=168000, sitelinks=30),
                # a facility that only Wikidata knows
                wd("Q900", "Maasvlakte Terminal", "seaport", 51.95, 4.05, country="Q55", sitelinks=3),
                # two QIDs claiming one GeoNames ID: the one with more sitelinks wins
                wd("Q901", "Duplicate Claim Town", "village", 52.1, 4.6, country="Q55", gid=111, sitelinks=9),
                wd("Q902", "Duplicate Claim Town Alt", "village", 52.1, 4.6, country="Q55", gid=111, sitelinks=1),
                # linked by P1566 but 400 km away
                wd("Q903", "Far Link Village", "village", 48.0, 9.0, country="Q55", gid=222),
                # located in a parent that is itself a place
                wd("Q904", "Delfshaven", "village", 51.91, 4.45, country="Q55", parents=["Q647"]),
            ],
        )
        cur.executemany(
            "INSERT INTO stg_wd_names VALUES (%s,%s,%s,%s,%s)",
            [
                ("Q647", "de", "Rotterdam", "rotterdam", "label"),
                ("Q647", "en", "Rotte-dam", "rotte dam", "alias"),
                ("Q900", "en", "Maasvlakte Terminal", "maasvlakte terminal", "label"),
            ],
        )
    conn.commit()
    merge.run(conn)
    hierarchy.run(conn)
    finalize.run(conn)
    return conn


def one(conn: psycopg.Connection[Any], query: str, *params: Any) -> Any:
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    assert row is not None
    return row[0] if len(row) == 1 else row


def test_p1566_link_merges_records(scenario: psycopg.Connection[Any]) -> None:
    qid, source, method, population, description = one(
        scenario, "SELECT qid, source, merge_method, population, description FROM places WHERE geonames_id = 2747891"
    )
    assert (qid, source, method, population) == ("Q647", "merged", "p1566", 651000)
    assert description == "city in the Netherlands"


def test_name_country_proximity_picks_the_nearby_namesake(scenario: psycopg.Connection[Any]) -> None:
    assert one(scenario, "SELECT qid FROM places WHERE geonames_id = 4250542") == "Q40"
    assert one(scenario, "SELECT qid FROM places WHERE geonames_id = 4409896") == "Q41"
    assert one(scenario, "SELECT merge_method FROM places WHERE qid = 'Q40'") == "name_country_proximity"


def test_wikidata_only_places_are_inserted(scenario: psycopg.Connection[Any]) -> None:
    source, country, ptype = one(scenario, "SELECT source, country_code, type FROM places WHERE qid = 'Q900'")
    assert (source, country, ptype) == ("wikidata", "NL", "seaport")


def test_duplicate_and_far_links_go_to_review(scenario: psycopg.Connection[Any]) -> None:
    reasons = dict(one_all(scenario, "SELECT reason, count(*) FROM place_merge_review GROUP BY 1"))
    assert reasons["duplicate_geonames_link"] == 1
    assert reasons["cross_link_distance"] == 1
    assert one(scenario, "SELECT qid FROM places WHERE geonames_id = 111") == "Q901"
    assert one(scenario, "SELECT count(*) FROM places WHERE qid = 'Q902'") == 1  # kept as its own place


def one_all(conn: psycopg.Connection[Any], query: str) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def test_aliases_are_stored_without_duplicates(scenario: psycopg.Connection[Any]) -> None:
    aliases = {
        r[0]
        for r in one_all(
            scenario,
            "SELECT alias_normalized FROM place_aliases a JOIN places p ON p.id = a.place_id WHERE p.qid = 'Q647'",
        )
    }
    assert {"roterdam", "rotte dam"} <= aliases
    assert "rotterdam" not in aliases  # same as the primary name
    assert one(scenario, "SELECT alias FROM place_aliases WHERE type = 'iata'") == "RTM"


def test_hierarchy_uses_codes_then_p131_then_polygons(scenario: psycopg.Connection[Any]) -> None:
    def parent_of(qid: str) -> str:
        return one(
            scenario, "SELECT pp.name FROM places c JOIN places pp ON pp.id = c.parent_place_id WHERE c.qid = %s", qid
        )

    assert parent_of("Q647") == "South Holland"  # GeoNames admin-1 code
    assert parent_of("Q904") == "Rotterdam"  # Wikidata P131
    assert parent_of("Q900") == "South Holland"  # admin-1 polygon containment (no codes, no P131)
    assert parent_of("Q40") == "Illinois"  # GeoNames admin-1 code via the merged record
    assert one(scenario, "SELECT admin1_name FROM places WHERE qid = 'Q647'") == "South Holland"
    assert one(scenario, "SELECT count(*) FROM place_hierarchy_issues WHERE issue = 'cycle'") == 0


def test_cycle_detection() -> None:
    assert hierarchy.find_cycles({1: 2, 2: 3, 3: 1, 4: 1, 5: 6}) == [[1, 2, 3]]
    assert hierarchy.find_cycles({1: 2, 2: 3}) == []


def test_uncertainty_polygons_bbox_and_h3(scenario: psycopg.Connection[Any]) -> None:
    def row(qid: str) -> tuple[Any, ...]:
        return one(
            scenario,
            "SELECT uncertainty_km, location_level, country_level, has_polygon FROM places WHERE qid = %s",
            qid,
        )

    assert row("Q647") == (25.0, "city", False, False)
    assert row("Q900") == (2.0, "facility", False, False)
    assert row("Q55")[1:] == ("country", True, True)
    assert (
        one(
            scenario, "SELECT count(*) FROM places WHERE h3_cell IS NULL OR bbox_west IS NULL OR uncertainty_km IS NULL"
        )
        == 0
    )
    west, east = one(scenario, "SELECT bbox_west, bbox_east FROM places WHERE qid = 'Q55'")
    assert (west, east) == (3, 8)  # polygon extent for a country
    west, east = one(scenario, "SELECT bbox_west, bbox_east FROM places WHERE qid = 'Q900'")
    assert west < 4.05 < east  # circle around a point


def test_large_city_uses_the_larger_radius(scenario: psycopg.Connection[Any]) -> None:
    with scenario.cursor() as cur:
        cur.execute("UPDATE places SET population = 2000000 WHERE qid = 'Q647'")
    finalize.assign_uncertainty(scenario)
    assert one(scenario, "SELECT uncertainty_km FROM places WHERE qid = 'Q647'") == 40.0


def test_search_finds_both_springfields_and_aliases(scenario: psycopg.Connection[Any]) -> None:
    hits = search_places(scenario, "Springfield", k=5)
    assert {h.geonames_id for h in hits[:2]} == {4250542, 4409896}
    assert hits[0].geonames_id == 4409896  # larger population wins without context
    assert search_places(scenario, "Springfield", k=1, country_code="US")[0].country_code == "US"
    assert search_places(scenario, "RTM", k=1)[0].geonames_id == 2993361
    assert search_places(scenario, "Roterdam", k=1)[0].qid == "Q647"
    assert search_places(scenario, "Rotterdm", k=1)[0].qid == "Q647"  # fuzzy match


def test_merge_refuses_to_rebuild_when_events_exist(scenario: psycopg.Connection[Any]) -> None:
    with scenario.cursor() as cur:
        cur.execute(
            "INSERT INTO events (type, severity, first_seen_at, last_seen_at, title) VALUES ('flood', 1, now(), now(), 't')"
        )
    scenario.commit()
    try:
        with pytest.raises(RuntimeError):
            merge.run(scenario)
    finally:
        scenario.rollback()
        with scenario.cursor() as cur:
            cur.execute("DELETE FROM events")
        scenario.commit()


def test_incremental_merge_adds_places_without_touching_existing_ones(scenario: psycopg.Connection[Any]) -> None:
    with scenario.cursor() as cur:
        cur.execute("TRUNCATE stg_wikidata, stg_wd_names")
        cur.executemany(
            "INSERT INTO stg_wikidata VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                # a brand new place
                wd("Q777", "Hoek van Holland", "village", 51.98, 4.13, country="Q55", pop=9000),
                # claims the GeoNames id of Rotterdam, which already belongs to Q647
                wd("Q778", "Rotterdam Municipality", "admin_region", 51.92, 4.48, country="Q55", gid=2747891),
            ],
        )
    scenario.commit()
    before = one(scenario, "SELECT count(*) FROM places")
    merge.incremental(scenario)
    scenario.commit()
    assert one(scenario, "SELECT count(*) FROM places") == before + 2
    assert one(scenario, "SELECT qid FROM places WHERE geonames_id = 2747891") == "Q647"  # unchanged
    assert one(scenario, "SELECT geonames_id FROM places WHERE qid = 'Q778'") is None  # did not steal the id
    reasons = [r[0] for r in one_all(scenario, "SELECT reason FROM place_merge_review WHERE qid = 'Q778'")]
    assert "duplicate_geonames_link" in reasons
