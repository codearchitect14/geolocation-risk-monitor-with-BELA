from typing import Any

import psycopg
import pytest

from meridian.etl.embeddings import vector_literal
from meridian.geo.search import search_by_embedding


def unit(index: int, dim: int = 1024) -> list[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


@pytest.fixture
def embedded(conn: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE places CASCADE")
        for i, name in enumerate(["Alpha", "Beta"]):
            cur.execute(
                """INSERT INTO places (geonames_id, name, name_normalized, type, lat, lon, centroid, geom, source)
                   VALUES (%s, %s, %s, 'city', 0, %s, ST_SetSRID(ST_MakePoint(%s, 0), 4326),
                           ST_SetSRID(ST_MakePoint(%s, 0), 4326), 'geonames') RETURNING id""",
                (i + 1, name, name.lower(), i, i, i),
            )
            row = cur.fetchone()
            assert row is not None
            for kind, vec in (("name", unit(i)), ("alias", unit(i))):
                cur.execute(
                    "INSERT INTO place_embeddings (place_id, kind, text, model, embedding) VALUES (%s, %s, %s, 'test', %s)",
                    (row[0], kind, name, vector_literal(vec)),
                )
    conn.commit()
    return conn


def test_vector_search_collapses_rows_per_place(embedded: psycopg.Connection[Any]) -> None:
    near_alpha = unit(0)
    near_alpha[1] = 0.2
    hits = search_by_embedding(embedded, near_alpha, k=5)
    assert len(hits) == 2  # two places, although there are four embedding rows
    assert hits[0][1] > hits[1][1]
    with embedded.cursor() as cur:
        cur.execute("SELECT name FROM places WHERE id = %s", (hits[0][0],))
        assert cur.fetchone() == ("Alpha",)


def test_wrong_vector_dimension_is_rejected(embedded: psycopg.Connection[Any]) -> None:
    with embedded.cursor() as cur, pytest.raises(psycopg.errors.DataException):
        cur.execute(
            "INSERT INTO place_embeddings (place_id, kind, text, model, embedding) "
            "SELECT id, 'name', 'x', 'test', '[1,2,3]' FROM places LIMIT 1"
        )
    embedded.rollback()
