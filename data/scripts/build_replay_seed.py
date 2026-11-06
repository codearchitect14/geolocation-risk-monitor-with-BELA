"""Build the committed replay seed from harvested USGS earthquake records.

python data/scripts/build_replay_seed.py [--min-magnitude 4.5] [--limit 160]

The USGS feed is a public domain product of the U.S. Geological Survey. Only the fields the normalizer reads are kept.
The file is re-timed when it is replayed (see `make replay`), so the incidents it creates are labeled as replays.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEEP = ("mag", "place", "time", "updated", "url", "alert", "status", "tsunami", "title", "type", "felt")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-magnitude", type=float, default=4.5)
    ap.add_argument("--limit", type=int, default=160)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "seed" / "replays" / "usgs_earthquakes.jsonl")
    args = ap.parse_args()
    features: dict[str, dict[str, object]] = {}
    for path in sorted((ROOT / "data" / "raw" / "hazards" / "usgs").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            feature = json.loads(line)["feature"]
            props = feature.get("properties") or {}
            if (props.get("mag") or 0) >= args.min_magnitude and feature.get("geometry"):
                features[feature["id"]] = {
                    "type": "Feature",
                    "id": feature["id"],
                    "properties": {k: props.get(k) for k in KEEP},
                    "geometry": feature["geometry"],
                }
    ordered = sorted(features.values(), key=lambda f: f["properties"]["time"])  # type: ignore[index]
    chosen = ordered[-args.limit :]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for feature in chosen:
            handle.write(json.dumps({"feature": feature}, separators=(",", ":")) + "\n")
    print(f"wrote {len(chosen)} records to {args.out.relative_to(ROOT)} ({args.out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
