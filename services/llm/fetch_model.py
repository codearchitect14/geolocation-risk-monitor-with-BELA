"""Download the local language model and verify its checksum.

The model is Qwen3-4B-Instruct-2507 (Apache-2.0) quantized to Q4_K_M, from the unsloth GGUF
repository (the model authors publish no GGUF files). The file is fetched at a pinned revision
and its SHA-256 is compared with the digest the Hub reports for the stored file.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
FILENAME = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
EXPECTED_SHA256_PREFIX = "3605803b982cb64a"  # first 16 hex characters of the Hub's LFS digest
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "models" / "llm"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)

    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi().model_info(REPO, files_metadata=True)
    entry = next(s for s in info.siblings if s.rfilename == FILENAME)
    expected = entry.lfs.sha256 if entry.lfs else None
    if not expected or not expected.startswith(EXPECTED_SHA256_PREFIX):
        print(f"unexpected digest for {FILENAME}: {expected}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = Path(hf_hub_download(REPO, FILENAME, revision=info.sha, local_dir=str(args.out)))
    actual = sha256_file(path)
    if actual != expected:
        print(f"checksum mismatch: {actual} != {expected}", file=sys.stderr)
        return 1
    print(f"{path} sha256={actual} revision={info.sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
