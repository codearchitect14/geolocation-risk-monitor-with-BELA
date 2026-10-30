"""Download the Mewsli-X entity linking benchmark (optional) into data/raw/eval/mewsli_x.

Used only as a general linking sanity check outside the place domain. The dataset
card lists the Apache-2.0 license. By default only the Wikinews mention files are
fetched; --with-candidates adds the large candidate entity archive.
"""

from __future__ import annotations

import argparse
import sys

import common

SOURCE_ID = "mewsli_x"
REPO = "izhx/mewsli-x"
REVISION = "7e3723faa15c6d84cfd56d66cf6cd347be8ad00e"

log = common.get_logger("download_mewsli_x")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-candidates", action="store_true")
    args = parser.parse_args(argv)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        log.error("huggingface_hub is not installed")
        return 1

    target = common.raw_dir("eval", "mewsli_x")
    patterns = ["README.md", "wikinews_mentions/**"]
    if args.with_candidates:
        patterns.append("candidate_entities.jsonl.tar.gz")
    try:
        snapshot_download(
            REPO,
            repo_type="dataset",
            revision=REVISION,
            allow_patterns=patterns,
            local_dir=str(target),
        )
    except Exception as exc:
        log.error("mewsli-x download failed: %s", exc)
        common.write_status("mewsli_x", False, {"error": str(exc)})
        return 1
    files = [p for p in target.rglob("*") if p.is_file() and ".cache" not in p.parts]
    common.record_files(
        SOURCE_ID,
        [
            {
                "path": p.as_posix(),
                "url": f"https://huggingface.co/datasets/{REPO}",
                "size": p.stat().st_size,
                "sha256": common.sha256_file(p),
            }
            for p in files
        ],
    )
    common.write_status("mewsli_x", True, {"files": len(files)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
