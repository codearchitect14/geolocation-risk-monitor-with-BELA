"""Download the GeoNames gazetteer dump files into data/raw/gazetteer/geonames.

Files are fetched resumably, extracted when they are zip archives, and their sizes
and SHA-256 checksums are written to data/manifest.yaml. GeoNames publishes no
checksums, so the recorded hash is the first verified download and later runs
compare against it.

GeoNames data is licensed under Creative Commons Attribution. Credit GeoNames in
the application footer and on the methodology page.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import common

SOURCE_ID = "geonames"
BASE_URL = "https://download.geonames.org/export/dump"

# name -> approximate size class, used by --small to skip the large files
FILES: dict[str, str] = {
    "countryInfo.txt": "small",
    "admin1CodesASCII.txt": "small",
    "admin2Codes.txt": "small",
    "featureCodes_en.txt": "small",
    "iso-languagecodes.txt": "small",
    "cities15000.zip": "small",
    "hierarchy.zip": "medium",
    "allCountries.zip": "large",
    "alternateNamesV2.zip": "large",
}

log = common.get_logger("download_geonames")


def extract(archive: Path, target: Path) -> list[Path]:
    """Extract a zip archive next to itself, skipping members that are already current."""
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            if member.is_dir() or "/" in member.filename or member.filename.startswith(".."):
                continue
            out = target / member.filename
            if out.exists() and out.stat().st_size == member.file_size:
                continue
            with zf.open(member) as src, out.open("wb") as dst:
                while chunk := src.read(common.CHUNK_SIZE):
                    dst.write(chunk)
            extracted.append(out)
    return extracted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--small", action="store_true", help="skip the large files")
    parser.add_argument("--only", action="append", help="download only these file names")
    parser.add_argument("--no-extract", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    names = [n for n, size in FILES.items() if not (args.small and size == "large")]
    if args.only:
        unknown = set(args.only) - set(FILES)
        if unknown:
            parser.error(f"unknown file(s): {', '.join(sorted(unknown))}")
        names = args.only

    target = common.raw_dir("gazetteer", "geonames")
    manifest = common.load_manifest()
    known = next(s for s in manifest["sources"] if s["id"] == SOURCE_ID).get("files") or []
    recorded = {Path(f["path"]).name: f["sha256"] for f in known}

    artifacts = []
    try:
        with common.make_client(timeout=300.0) as client:
            for name in names:
                dest = target / name
                artifact = common.download_file(
                    client,
                    f"{BASE_URL}/{name}",
                    dest,
                    expected_sha256=recorded.get(name),
                    force=args.force,
                    logger=log,
                )
                artifacts.append(artifact)
                if name.endswith(".zip") and not args.no_extract:
                    for path in extract(dest, target):
                        log.info("extracted %s", path.name)
    except Exception as exc:
        log.error("geonames download failed: %s", exc)
        common.write_status("geonames", False, {"error": str(exc)})
        return 1
    common.record_files(SOURCE_ID, artifacts)
    common.write_status("geonames", True, {"files": len(artifacts)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
