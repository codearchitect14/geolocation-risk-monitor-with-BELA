"""One-time preparation of the BELA entity index.

1. converts embeddings.pt (float32, 19.8 GB) to float16 (9.9 GB) next to it, streaming through a memory map
2. checks the row count against index.txt

  python services/nel/prepare_index.py [--dir data/raw/models/bela]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nel_service.index import convert_embeddings, read_ids  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "models" / "bela"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    target = args.dir / "embeddings_fp16.npy"
    if not target.exists():
        rows, dim = convert_embeddings(args.dir / "embeddings.pt", target)
        print(f"converted {rows} rows of {dim} dimensions")
    ids = read_ids(args.dir / "index.txt")
    import numpy as np

    array = np.load(str(target), mmap_mode="r")
    if array.shape[0] != ids.shape[0]:
        print(f"row mismatch: {array.shape[0]} embeddings, {ids.shape[0]} ids", file=sys.stderr)
        return 1
    print(
        f"index ready: {array.shape[0]:,} entities x {array.shape[1]} dimensions, {len(ids[ids < 0])} ids without a QID"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
