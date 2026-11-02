"""Download per-language slices of Multilingual CC-News into data/raw/news/cc_news.

The main branch of the Hugging Face dataset only ships a loading script. The parquet
files live on the auto-converted revision, which is pinned here by commit. Small languages have one
file under <lang>/train/, large ones several under <lang>/partial-train/. Fields:
title, maintext, url, date_publish. Use for load tests and backfill only; show title,
snippet, and link. Publisher copyright applies and use is limited to non-commercial
testing.
"""

from __future__ import annotations

import argparse
import sys

import common

SOURCE_ID = "cc_news"
REPO = "intfloat/multilingual_cc_news"
REVISION = "c769fea281affc73eaa0f248126cfeef2cae0372"  # refs/convert/parquet
DEFAULT_LANGUAGES = ["en", "es", "fr", "de"]

log = common.get_logger("download_cc_news")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", action="append", help="ISO 639-1 code, repeatable")
    parser.add_argument(
        "--shards", type=int, default=1, help="parquet shards per language (large ones have ten of ~300 MB)"
    )
    args = parser.parse_args(argv)
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        log.error("huggingface_hub is not installed")
        return 1

    languages = args.language or DEFAULT_LANGUAGES
    target = common.raw_dir("news", "cc_news")
    try:
        files = [s.rfilename for s in HfApi().dataset_info(REPO, revision=REVISION).siblings or []]
        for lang in languages:
            shards = sorted(f for f in files if f.startswith(f"{lang}/") and f.endswith(".parquet"))[: args.shards]
            if not shards:
                log.warning("no parquet files for language %s", lang)
            for name in shards:
                hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION, local_dir=str(target))
    except Exception as exc:
        log.error("cc-news download failed: %s", exc)
        common.write_status("cc_news", False, {"error": str(exc)})
        return 1
    found = [p for p in target.rglob("*.parquet")]
    common.record_files(
        SOURCE_ID,
        [
            {
                "path": p.as_posix(),
                "url": f"https://huggingface.co/datasets/{REPO}",
                "size": p.stat().st_size,
                "sha256": common.sha256_file(p),
            }
            for p in found
        ],
    )
    common.write_status("cc_news", True, {"files": len(found)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
