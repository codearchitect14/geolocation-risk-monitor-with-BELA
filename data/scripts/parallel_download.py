"""Download a large file with several parallel HTTP range requests, resuming a partial file.

Used for Hugging Face files of many gigabytes when a single stream is slow. The file is preallocated, blocks
are written in place, and the SHA-256 is verified at the end when one is given. Blocks that finished are
recorded in a sidecar file so an interrupted run continues where it stopped.

  parallel_download.py REPO FILENAME DEST [--sha256 HEX] [--workers 12] [--block-mb 64]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from huggingface_hub import hf_hub_url


def resolve(url: str) -> tuple[str, int]:
    """Follow redirects to the CDN address and return it with the content length."""
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        head = client.get(url, headers={"Range": "bytes=0-0"})
        head.raise_for_status()
        total = int(head.headers["Content-Range"].rsplit("/", 1)[1])
        return str(head.url), total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo")
    parser.add_argument("filename")
    parser.add_argument("dest", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--block-mb", type=int, default=64)
    parser.add_argument("--prefix-file", type=Path, help="existing partial download whose leading bytes can be reused")
    args = parser.parse_args(argv)

    block = args.block_mb * 1024 * 1024
    cdn_url, total = resolve(hf_hub_url(args.repo, args.filename))
    done_path = args.dest.with_suffix(args.dest.suffix + ".blocks")
    done: set[int] = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    if not args.dest.exists():
        with args.dest.open("wb") as handle:
            handle.truncate(total)
        if args.prefix_file and args.prefix_file.exists():
            reusable = (args.prefix_file.stat().st_size // block) - 1  # drop the possibly torn last block
            with args.prefix_file.open("rb") as src, args.dest.open("r+b") as dst:
                for index in range(max(reusable, 0)):
                    dst.write(src.read(block))
                    done.add(index)
            done_path.write_text(json.dumps(sorted(done)))
    blocks = [i for i in range((total + block - 1) // block) if i not in done]
    print(f"{total / 1e9:.2f} GB, {len(done)} blocks done, {len(blocks)} to go", flush=True)

    lock = threading.Lock()
    fetched = [0]
    started = time.monotonic()

    def fetch(index: int) -> None:
        start = index * block
        end = min(start + block, total) - 1
        for attempt in range(6):
            try:
                with httpx.stream(
                    "GET", cdn_url, headers={"Range": f"bytes={start}-{end}"}, timeout=120, follow_redirects=True
                ) as response:
                    response.raise_for_status()
                    position = start
                    fd = os.open(args.dest, os.O_WRONLY)
                    try:
                        for chunk in response.iter_bytes(1 << 20):
                            os.pwrite(fd, chunk, position)
                            position += len(chunk)
                    finally:
                        os.close(fd)
                if position != end + 1:
                    raise OSError(f"short block {index}")
                with lock:
                    done.add(index)
                    fetched[0] += end - start + 1
                    done_path.write_text(json.dumps(sorted(done)))
                    rate = fetched[0] / (time.monotonic() - started) / 1e6
                    if len(done) % 20 == 0:
                        print(f"block {index} ok, {len(done)} done, {rate:.0f} MB/s", flush=True)
                return
            except (httpx.HTTPError, OSError):
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"block {index} failed")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(fetch, blocks))

    if args.sha256:
        digest = hashlib.sha256()
        with args.dest.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 24), b""):
                digest.update(chunk)
        if digest.hexdigest() != args.sha256:
            print(f"checksum mismatch: {digest.hexdigest()}", file=sys.stderr)
            return 1
        print("sha256 verified", flush=True)
    done_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
