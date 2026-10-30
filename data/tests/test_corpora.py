import json
from pathlib import Path

import shapefile

import download_eupeg as eupeg
import download_geonames
import download_natural_earth as ne

LGL = """<?xml version="1.0" encoding="utf-8"?>
<articles><article docid="7"><title>t</title><text>Alexandria woman charged in Alexandria.</text>
<toponyms count="2">
<toponym><start>0</start><end>10</end><phrase>Alexandria</phrase>
<gaztag geonameid="4314550"><name>Alexandria</name><fcode>PPL</fcode><lat>31.31</lat><lon>-92.44</lon></gaztag></toponym>
<toponym><start>27</start><end>37</end><phrase>Alexandria</phrase>
<gaztag geonameid="4314550"><name>Alexandria</name><fcode>PPL</fcode><lat>31.31</lat><lon>-92.44</lon></gaztag></toponym>
</toponyms></article></articles>"""

WIKTOR = """<?xml version='1.0' encoding='utf-8'?>
<wikiPages><page number="1"><pageTitle>Santa Maria, California</pageTitle><toponymName>Santa Maria</toponymName>
<text>Santa Maria is a city. Santa Maria is large.</text>
<toponymIndices count="2"><toponym><start>0</start><end>11</end></toponym>
<toponym><start>23</start><end>34</end></toponym></toponymIndices>
<lat>34.95</lat><lon>-120.43</lon><feature>city</feature><country>US</country></page></wikiPages>"""

GWN = """<?xml version="1.0" ?>
<articles><article file="0"><title>t</title><text>Fire on Frenchmen Street in New Orleans, said Smith.</text>
<toponyms>
<toponym><extractedName>Frenchmen Street</extractedName><normalisedName></normalisedName><type>Literal</type>
<nonLocational>No</nonLocational><start>8</start><end>24</end><geonamesID></geonamesID>
<latitude>29.98</latitude><longitude>-90.05</longitude></toponym>
<toponym><extractedName>Smith</extractedName><nonLocational>Yes</nonLocational><start>46</start><end>51</end>
<latitude>0</latitude><longitude>0</longitude></toponym>
</toponyms></article></articles>"""


def test_lgl_conversion_reports_offset_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "lgl.xml"
    source.write_text(LGL, encoding="utf-8")
    docs = list(eupeg.parse_gaztag_corpus(source, "lgl"))
    assert docs[0]["doc_id"] == "7" and len(docs[0]["toponyms"]) == 2
    first, second = docs[0]["toponyms"]
    assert first["offset_ok"] is True and first["geonames_id"] == "4314550"
    assert second["offset_ok"] is True and second["offset_repaired"] is True  # annotated one character early
    assert second["start"] == 28


def test_wiktor_and_gwn_conversion(tmp_path: Path) -> None:
    (tmp_path / "w.xml").write_text(WIKTOR, encoding="utf-8")
    (tmp_path / "g.xml").write_text(GWN, encoding="utf-8")
    wiktor = list(eupeg.parse_wiktor(tmp_path / "w.xml", "wiktor"))[0]
    assert [t["start"] for t in wiktor["toponyms"]] == [0, 23] and wiktor["toponyms"][0]["lat"] == 34.95
    gwn = list(eupeg.parse_gwn(tmp_path / "g.xml", "geowebnews"))[0]
    assert [t["surface"] for t in gwn["toponyms"]] == ["Frenchmen Street"]  # non-locational dropped


def test_convert_writes_jsonl(tmp_path: Path) -> None:
    (tmp_path / "w.xml").write_text(WIKTOR, encoding="utf-8")
    stats = eupeg.convert(tmp_path / "w.xml", tmp_path / "out.jsonl", "wiktor", eupeg.parse_wiktor)
    assert stats == {"documents": 1, "toponyms": 2, "offset_mismatches": 0, "offsets_repaired": 0}
    assert json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))["corpus"] == "wiktor"


def test_natural_earth_drops_gadm_columns(tmp_path: Path) -> None:
    base = tmp_path / "ne_10m_admin_1_states_provinces"
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as writer:
        writer.field("name", "C", size=40)
        writer.field("type_en", "C", size=20)
        writer.field("valid_from", "C", size=20)
        writer.poly([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])
        writer.record("Ohio", "State", "2020")
    dest = tmp_path / "out.geojson"
    drop = ne.drop_columns_for("ne_10m_admin_1_states_provinces")
    assert ne.convert_to_geojson(base.with_suffix(".shp"), dest, drop) == 1
    props = json.loads(dest.read_text(encoding="utf-8"))["features"][0]["properties"]
    assert props == {"name": "Ohio"}
    assert ne.drop_columns_for("ne_10m_admin_0_countries") == set()


def test_geonames_extract_skips_current_files(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "cities.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("cities.txt", "a\tb\n")
        zf.writestr("../evil.txt", "x")
    assert [p.name for p in download_geonames.extract(archive, tmp_path)] == ["cities.txt"]
    assert download_geonames.extract(archive, tmp_path) == []
    assert not (tmp_path.parent / "evil.txt").exists()


def test_byte_offsets_are_repaired() -> None:
    text = "It\u2019s Turkish news in Ankara."
    start = len(text[: text.index("Ankara")].encode("utf-8"))
    item = eupeg.make_toponym(text, start, start + 6, "Ankara", lat=39.9, lon=32.8)
    assert item is not None and item["offset_ok"] and item["offset_repaired"]
    assert text[item["start"] : item["end"]] == "Ankara"
