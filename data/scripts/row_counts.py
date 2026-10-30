"""Print and store row counts for every acquired source.

Counts JSONL lines, CSV rows, GeoJSON features, and parquet rows under data/raw
and writes data/processed/row_counts.json and row_counts.md.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

import common


def count_lines(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        return sum(1 for line in handle if line.strip())


def count_file(path: Path) -> int | None:
    name = path.name
    if name.startswith("_") or name.endswith((".part", ".tmp")):
        return None
    if name.endswith((".jsonl", ".jsonl.gz")):
        return count_lines(path)
    if name.endswith(".csv"):
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    if name.endswith(".parquet"):
        return int(pq.ParquetFile(path).metadata.num_rows)
    if name.endswith(".geojson"):
        with path.open(encoding="utf-8") as handle:
            return len(json.load(handle).get("features", []))
    if name.endswith(".txt") and path.parent.name == "geonames":
        return count_lines(path)
    return None


def collect(root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for source in common.load_manifest()["sources"]:
        local = source.get("local_path")
        if not local or not local.startswith("raw/"):
            continue
        directory = root / local
        files: dict[str, int] = {}
        size = 0
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or "_work" in path.parts:
                    continue
                size += path.stat().st_size
                count = count_file(path)
                if count is not None:
                    files[path.relative_to(directory).as_posix()] = count
        report[source["id"]] = {
            "files": len(files),
            "rows": sum(files.values()),
            "bytes": size,
            "largest": dict(sorted(files.items(), key=lambda kv: -kv[1])[:5]),
        }
    return report


def main() -> int:
    report = collect(common.data_dir())
    out = common.processed_dir()
    payload = {"generated_at": common.iso_now(), "sources": report}
    common.write_json(out / "row_counts.json", payload)
    lines = ["| source | files | rows | bytes |", "|---|---:|---:|---:|"]
    for sid, row in report.items():
        lines.append(f"| {sid} | {row['files']:,} | {row['rows']:,} | {row['bytes']:,} |")
    table = "\n".join(lines) + "\n"
    common.atomic_write_text(out / "row_counts.md", f"Generated {payload['generated_at']}\n\n{table}")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
