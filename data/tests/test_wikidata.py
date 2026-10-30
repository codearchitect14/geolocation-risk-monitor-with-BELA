import bz2
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

import build_wikidata_subset as wd


def item(
    qid: str,
    *,
    p31: list[str] | None = None,
    p279: list[str] | None = None,
    coord: tuple[float, float] | None = None,
    label: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    claims: dict[str, Any] = {}

    def entity_claims(ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "rank": "normal",
                "mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": i}, "type": "wikibase-entityid"}},
            }
            for i in ids
        ]

    if p31:
        claims["P31"] = entity_claims(p31)
    if p279:
        claims["P279"] = entity_claims(p279)
    if coord:
        claims["P625"] = [
            {
                "rank": "normal",
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"latitude": coord[0], "longitude": coord[1]}},
                },
            }
        ]
    if "country" in extra:
        claims["P17"] = entity_claims([extra["country"]])
    if "population" in extra:
        claims["P1082"] = [
            {
                "rank": "normal",
                "mainsnak": {"snaktype": "value", "datavalue": {"value": {"amount": f"+{extra['population']}"}}},
            }
        ]
    if "geonames" in extra:
        claims["P1566"] = [
            {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"value": extra["geonames"]}}}
        ]
    labels = {"en": {"language": "en", "value": label}} if label else {}
    if "label_de" in extra:
        labels["de"] = {"language": "de", "value": extra["label_de"]}
    return {
        "id": qid,
        "claims": claims,
        "labels": labels,
        "descriptions": {"en": {"language": "en", "value": f"description of {label}"}} if label else {},
        "aliases": {"en": [{"language": "en", "value": f"{label} alias"}]} if label else {},
        "sitelinks": {"enwiki": {}},
    }


# Class graph: Q_BIGCITY subclass of Q515 (city); Q_PORTTERM subclass of Q44782 (port)
ENTITIES = [
    item("Q515", p279=["Q56061"], label="city"),
    item("Q_BIGCITY", p279=["Q515"], label="big city"),
    item("Q_PORTTERM", p279=["Q44782"], label="port terminal"),
    item(
        "Q1",
        p31=["Q_BIGCITY"],
        coord=(51.9, 4.5),
        label="Rotterdam",
        country="Q55",
        population=650000,
        geonames="2747891",
        label_de="Rotterdam",
    ),
    item("Q2", p31=["Q_PORTTERM"], coord=(51.95, 4.1), label="Port of Rotterdam", country="Q55"),
    item("Q3", p31=["Q5"], coord=(10.0, 10.0), label="A person with coordinates"),
    item("Q4", p31=["Q515"], label="City without coordinates"),
    item("Q5", p31=["Q515"], coord=(95.0, 10.0), label="Bad latitude"),
    item("Q6", p31=["Q4022"], coord=(1.0, 2.0), label="Some river"),
]


def dump_lines() -> list[bytes]:
    lines = [b"["]
    lines += [json.dumps(e).encode() + b"," for e in ENTITIES]
    lines.append(b"]")
    return lines


def test_pipeline_filters_by_class_closure(tmp_path: Path) -> None:
    work = tmp_path / "work"
    counts = wd.scan(dump_lines(), work, {"en", "de"}, None)
    assert counts["edges"] == 3 and counts["candidates"] == 4
    result = wd.filter_candidates(work, tmp_path)
    assert result["by_type"] == {"city": 1, "seaport": 1, "river": 1}
    places = pq.read_table(tmp_path / "places.parquet").to_pylist()
    rotterdam = next(p for p in places if p["qid"] == "Q1")
    assert rotterdam["place_type"] == "city" and rotterdam["population"] == 650000
    assert rotterdam["geonames_id"] == "2747891" and rotterdam["country_qid"] == "Q55"
    names = pq.read_table(tmp_path / "names.parquet").to_pylist()
    assert {"qid": "Q1", "lang": "de", "kind": "label", "text": "Rotterdam"} in names
    assert any(n["kind"] == "alias" and n["qid"] == "Q1" for n in names)


def test_class_priority_prefers_facility_over_city() -> None:
    class_map = wd.build_class_map({"Qboth": ["Q515", "Q44782"]})
    assert wd.place_type_for(["Qboth"], class_map) == "seaport"


def test_every_seed_class_id_is_wikidata_format() -> None:
    for _, ids in wd.SEED_CLASSES:
        assert all(i.startswith("Q") and i[1:].isdigit() for i in ids)


def test_bz2_multistream_roundtrip() -> None:
    payload = b"\n".join(b'{"id": "Q%d"}' % i for i in range(1000)) + b"\n"
    half = len(payload) // 2
    blob = bz2.compress(payload[:half]) + bz2.compress(payload[half:])
    chunks = [blob[i : i + 97] for i in range(0, len(blob), 97)]
    lines = list(wd.split_lines(wd.bz2_chunks(chunks)))
    assert len(lines) == 1000 and lines[-1] == b'{"id": "Q999"}'


def test_local_bz2_file_lines(tmp_path: Path) -> None:
    path = tmp_path / "dump.json.bz2"
    path.write_bytes(bz2.compress(b"\n".join(dump_lines())))
    assert wd.entity_from_line(next(iter(wd.file_lines(path)))) is None  # the "[" line
