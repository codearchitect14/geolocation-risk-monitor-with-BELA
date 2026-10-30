"""Download public geoparsing corpora from the EUPEG repository and convert them.

Files are fetched from a pinned commit of github.com/geoai-lab/EUPEG and converted to
one common JSONL per corpus under data/raw/eval/eupeg/. Each line is one document:

  {"corpus", "doc_id", "text", "toponyms": [
      {"start", "end", "surface", "lat", "lon", "geonames_id", "qid", "place_name",
       "place_type", "offset_ok", "offset_repaired"}]}

The text is kept exactly as annotated, including leading whitespace, because offsets
count from the first character. Offsets are character offsets, end exclusive. offset_ok reports whether
text[start:end] equals the annotated surface form. TR-News gives UTF-8 byte offsets into text with CRLF
line breaks and has small drifts elsewhere; these are repaired by trying known
conventions, then the nearest occurrence within 12 characters, and flagged with
offset_repaired. Gold coordinates are mapped to Wikidata places later by nearest label
match and review, so qid is null here.
GeoCorpora is excluded because it provides tweet IDs only. Hu2014 and Ju2016 hold
sentence level files without character offsets or gold coordinates and are
downloaded unconverted.

The EUPEG repository is GPL-3.0. Each corpus keeps the license of its authors:
confirm it before any redistribution. These files are used for evaluation only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

import common

SOURCE_ID = "eupeg"
COMMIT = "97d5b6c74887fa3e7ab515899b625fc586e7ba5f"
RAW_BASE = f"https://raw.githubusercontent.com/geoai-lab/EUPEG/{COMMIT}/corpora"

log = common.get_logger("download_eupeg")

Toponym = dict[str, Any]
Document = dict[str, Any]


def _root(path: Path) -> Element:
    root = ET.parse(path).getroot()
    if root is None:
        raise ValueError(f"{path.name}: empty XML document")
    return root


def _text(element: Element | None, tag: str, *, keep_whitespace: bool = False) -> str:
    child = element.find(tag) if element is not None else None
    if child is None or not child.text:
        return ""
    return child.text if keep_whitespace else child.text.strip()


def _float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def make_toponym(
    text: str,
    start: int | None,
    end: int | None,
    surface: str,
    *,
    lat: float | None,
    lon: float | None,
    geonames_id: str | None = None,
    place_name: str | None = None,
    place_type: str | None = None,
) -> Toponym | None:
    if start is None or end is None or end <= start or start < 0:
        return None
    repaired = False
    if surface and text[start:end] != surface:
        fixed = _from_byte_offsets(text, start, end, surface)
        if fixed:
            start, end = fixed
            repaired = True
    if end > len(text):
        return None
    if lat is not None and not -90 <= lat <= 90 or lon is not None and not -180 <= lon <= 180:
        lat = lon = None
    return {
        "start": start,
        "end": end,
        "surface": surface or text[start:end],
        "lat": lat,
        "lon": lon,
        "geonames_id": geonames_id or None,
        "qid": None,
        "place_name": place_name or None,
        "place_type": place_type or None,
        "offset_ok": text[start:end] == surface if surface else True,
        "offset_repaired": repaired,
    }


def _from_byte_offsets(text: str, start: int, end: int, surface: str) -> tuple[int, int] | None:
    """Recover offsets given in another convention than characters of the parsed text.

    TR-News counts UTF-8 bytes in text that still has CRLF line breaks; XML parsing
    normalizes those to LF. Try each convention and map the match back to the parsed text.
    """
    for crlf in (False, True):
        original = text.replace("\n", "\r\n") if crlf else text
        encoded = original.encode("utf-8")
        for unit_bytes in (True, False):
            if unit_bytes:
                if end > len(encoded) or encoded[start:end].decode("utf-8", errors="ignore") != surface:
                    continue
                char_start = len(encoded[:start].decode("utf-8", errors="ignore"))
            else:
                if original[start:end] != surface:
                    continue
                char_start = start
            mapped = len(original[:char_start].replace("\r\n", "\n")) if crlf else char_start
            if text[mapped : mapped + len(surface)] == surface:
                return mapped, mapped + len(surface)
    return _nearest_occurrence(text, start, surface)


def _nearest_occurrence(text: str, start: int, surface: str, window: int = 12) -> tuple[int, int] | None:
    """Last resort for small drifts: the closest occurrence of the surface form within a window."""
    candidates = [
        i for i in range(max(0, start - window), min(len(text), start + window) + 1) if text.startswith(surface, i)
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda i: abs(i - start))
    return best, best + len(surface)


def _gaztag_toponyms(article: Element, text: str) -> list[Toponym]:
    result = []
    for node in article.iter("toponym"):
        gaz = node.find("gaztag")
        item = make_toponym(
            text,
            _int(_text(node, "start")),
            _int(_text(node, "end")),
            _text(node, "phrase"),
            lat=_float(_text(gaz, "lat")),
            lon=_float(_text(gaz, "lon")),
            geonames_id=gaz.get("geonameid") if gaz is not None else None,
            place_name=_text(gaz, "name"),
            place_type=_text(gaz, "fcode"),
        )
        if item:
            result.append(item)
    return result


def parse_gaztag_corpus(path: Path, corpus: str) -> Iterator[Document]:
    """LGL and TR-News: toponyms with gazetteer tags."""
    for index, article in enumerate(_root(path).iter("article")):
        text = _text(article, "text", keep_whitespace=True)
        yield {
            "corpus": corpus,
            "doc_id": article.get("docid") or str(index),
            "text": text,
            "toponyms": _gaztag_toponyms(article, text),
        }


def parse_geovirus(path: Path, corpus: str) -> Iterator[Document]:
    for index, article in enumerate(_root(path).iter("article")):
        text = _text(article, "text", keep_whitespace=True)
        toponyms = []
        for node in article.iter("location"):
            item = make_toponym(
                text,
                _int(_text(node, "start")),
                _int(_text(node, "end")),
                "",
                lat=_float(_text(node, "lat")),
                lon=_float(_text(node, "lon")),
                place_name=_text(node, "name"),
            )
            if item:
                item["surface"] = text[item["start"] : item["end"]]
                item["offset_ok"] = True
                toponyms.append(item)
        yield {"corpus": corpus, "doc_id": str(index), "text": text, "toponyms": toponyms}


def parse_gwn(path: Path, corpus: str) -> Iterator[Document]:
    for index, article in enumerate(_root(path).iter("article")):
        text = _text(article, "text", keep_whitespace=True)
        toponyms = []
        for node in article.iter("toponym"):
            if _text(node, "nonLocational").lower() == "yes":
                continue
            item = make_toponym(
                text,
                _int(_text(node, "start")),
                _int(_text(node, "end")),
                _text(node, "extractedName"),
                lat=_float(_text(node, "latitude")),
                lon=_float(_text(node, "longitude")),
                geonames_id=_text(node, "geonamesID"),
                place_name=_text(node, "normalisedName"),
                place_type=_text(node, "type"),
            )
            if item:
                toponyms.append(item)
        yield {"corpus": corpus, "doc_id": article.get("file") or str(index), "text": text, "toponyms": toponyms}


def parse_wiktor(path: Path, corpus: str) -> Iterator[Document]:
    for page in _root(path).iter("page"):
        text = _text(page, "text", keep_whitespace=True)
        surface = _text(page, "toponymName")
        lat, lon = _float(_text(page, "lat")), _float(_text(page, "lon"))
        toponyms = []
        for node in page.iter("toponym"):
            item = make_toponym(
                text,
                _int(_text(node, "start")),
                _int(_text(node, "end")),
                surface,
                lat=lat,
                lon=lon,
                place_name=_text(page, "pageTitle"),
                place_type=_text(page, "feature"),
            )
            if item:
                toponyms.append(item)
        yield {"corpus": corpus, "doc_id": page.get("number") or "", "text": text, "toponyms": toponyms}


CORPORA: dict[str, tuple[str, Callable[[Path, str], Iterator[Document]]]] = {
    "lgl": ("lgl.xml", parse_gaztag_corpus),
    "geovirus": ("GeoVirus.xml", parse_geovirus),
    "tr-news": ("TR-News.xml", parse_gaztag_corpus),
    "geowebnews": ("GWN.xml", parse_gwn),
    "wiktor": ("WikToR.xml", parse_wiktor),
}
UNCONVERTED = [
    "Hu2014/GreenVille.txt",
    "Hu2014/Washington.txt",
    "Ju2016/testing_sentence_city_ambiPlaceName.csv",
]


def convert(source: Path, dest: Path, corpus: str, parser: Callable[[Path, str], Iterator[Document]]) -> dict[str, int]:
    stats = {"documents": 0, "toponyms": 0, "offset_mismatches": 0, "offsets_repaired": 0}
    tmp = dest.with_name(dest.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as out:
        for document in parser(source, corpus):
            stats["documents"] += 1
            stats["toponyms"] += len(document["toponyms"])
            stats["offset_mismatches"] += sum(1 for t in document["toponyms"] if not t["offset_ok"])
            stats["offsets_repaired"] += sum(1 for t in document["toponyms"] if t["offset_repaired"])
            out.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(dest)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", action="append", choices=sorted(CORPORA))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    root = common.raw_dir("eval", "eupeg")
    originals = root / "original"
    originals.mkdir(exist_ok=True)
    manifest = common.load_manifest()
    known = next(s for s in manifest["sources"] if s["id"] == SOURCE_ID).get("files") or []
    recorded = {Path(f["path"]).name: f["sha256"] for f in known}

    artifacts = []
    summary: dict[str, dict[str, int]] = {}
    try:
        with common.make_client(timeout=120.0) as client:
            selected = args.corpus or list(CORPORA)
            for name in selected:
                filename, parse = CORPORA[name]
                source = originals / filename
                artifacts.append(
                    common.download_file(
                        client,
                        f"{RAW_BASE}/{filename}",
                        source,
                        expected_sha256=recorded.get(filename),
                        force=args.force,
                        logger=log,
                    )
                )
                dest = root / f"{name}.jsonl"
                summary[name] = convert(source, dest, name, parse)
                artifacts.append(
                    {
                        "path": dest.as_posix(),
                        "url": None,
                        "size": dest.stat().st_size,
                        "sha256": common.sha256_file(dest),
                    }
                )
                log.info("%s: %s", name, summary[name])
            if not args.corpus:
                for relative in UNCONVERTED:
                    dest = originals / Path(relative).name
                    artifacts.append(
                        common.download_file(
                            client,
                            f"{RAW_BASE}/{relative}",
                            dest,
                            expected_sha256=recorded.get(dest.name),
                            force=args.force,
                            logger=log,
                        )
                    )
    except Exception as exc:
        log.error("eupeg download failed: %s", exc)
        common.write_status("eupeg", False, {"error": str(exc)})
        return 1
    common.record_files(SOURCE_ID, artifacts)
    common.write_status("eupeg", True, {"corpora": summary})
    return 0


if __name__ == "__main__":
    sys.exit(main())
