"""Download Natural Earth vector layers and convert them to GeoJSON.

Layers are fetched from the Natural Earth CDN, extracted under
data/raw/boundaries/natural_earth/<layer>/, and converted to GeoJSON next to the
shapefile. For the admin-1 layer the columns that depend on GADM data (type_en,
valid_from, valid_to) are dropped from the GeoJSON to avoid license restrictions.

Natural Earth is public domain in the United States. Check local law elsewhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import shapefile

import common

SOURCE_ID = "natural_earth"
BASE_URL = "https://naciscdn.org/naturalearth"
LAYERS: dict[str, str] = {
    "ne_10m_admin_0_countries": "10m/cultural",
    "ne_50m_admin_0_countries": "50m/cultural",
    "ne_10m_admin_1_states_provinces": "10m/cultural",
    "ne_10m_populated_places": "10m/cultural",
    "ne_50m_land": "50m/physical",
}
GADM_DEPENDENT = {"type_en", "valid_from", "valid_to", "gadm_level"}

log = common.get_logger("download_natural_earth")


def drop_columns_for(layer: str) -> set[str]:
    return GADM_DEPENDENT if "admin_1" in layer else set()


def convert_to_geojson(shp_path: Path, dest: Path, drop: set[str]) -> int:
    """Write a GeoJSON FeatureCollection from a shapefile. Returns the feature count."""
    count = 0
    tmp = dest.with_name(dest.name + ".tmp")
    with shapefile.Reader(str(shp_path), encoding="utf-8") as reader, tmp.open("w", encoding="utf-8") as out:
        out.write('{"type":"FeatureCollection","features":[\n')
        for index, shape_record in enumerate(reader.iterShapeRecords()):
            feature: dict[str, Any] = shape_record.__geo_interface__
            props = feature.get("properties", {})
            feature["properties"] = {k: v for k, v in props.items() if k.lower() not in drop}
            out.write(("," if index else "") + json.dumps(feature, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
        out.write("]}\n")
    tmp.replace(dest)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--layer", action="append", choices=sorted(LAYERS))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    manifest = common.load_manifest()
    known = next(s for s in manifest["sources"] if s["id"] == SOURCE_ID).get("files") or []
    recorded = {Path(f["path"]).name: f["sha256"] for f in known}
    root = common.raw_dir("boundaries", "natural_earth")

    artifacts = []
    try:
        with common.make_client(timeout=300.0) as client:
            for layer in args.layer or list(LAYERS):
                directory = root / layer
                directory.mkdir(exist_ok=True)
                archive = directory / f"{layer}.zip"
                url = f"{BASE_URL}/{LAYERS[layer]}/{layer}.zip"
                artifacts.append(
                    common.download_file(
                        client, url, archive, expected_sha256=recorded.get(archive.name), force=args.force, logger=log
                    )
                )
                shp = directory / f"{layer}.shp"
                geojson = directory / f"{layer}.geojson"
                if not shp.exists():
                    with zipfile.ZipFile(archive) as zf:
                        for member in zf.namelist():
                            if "/" not in member:
                                zf.extract(member, directory)
                if not geojson.exists() or args.force:
                    count = convert_to_geojson(shp, geojson, drop_columns_for(layer))
                    log.info("%s: %d features", layer, count)
                artifacts.append(
                    {
                        "path": geojson.as_posix(),
                        "url": None,
                        "size": geojson.stat().st_size,
                        "sha256": common.sha256_file(geojson),
                    }
                )
    except Exception as exc:
        log.error("natural earth download failed: %s", exc)
        common.write_status("natural_earth", False, {"error": str(exc)})
        return 1
    common.record_files(SOURCE_ID, artifacts)
    common.write_status("natural_earth", True, {"layers": len(artifacts) // 2})
    return 0


if __name__ == "__main__":
    sys.exit(main())
