"""Verify files recorded in manifest.yaml against the data on disk.

Exit code 0 when every recorded file exists and matches its size and SHA-256.
Sources with no recorded files are reported as not downloaded, not as failures,
unless --strict is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import common

REQUIRED_KEYS = {"id", "name", "kind", "license", "attribution", "redistribution"}
VALID_KINDS = {"static", "harvest", "external"}


def check_structure(manifest: dict[str, Any]) -> list[str]:
    problems = []
    seen: set[str] = set()
    for source in manifest.get("sources", []):
        sid = source.get("id", "?")
        missing = REQUIRED_KEYS - source.keys()
        if missing:
            problems.append(f"{sid}: missing keys {sorted(missing)}")
        if source.get("kind") not in VALID_KINDS:
            problems.append(f"{sid}: invalid kind {source.get('kind')!r}")
        if sid in seen:
            problems.append(f"{sid}: duplicate id")
        seen.add(sid)
    return problems


def verify_files(manifest: dict[str, Any], root: Path) -> tuple[list[str], dict[str, str]]:
    problems: list[str] = []
    status: dict[str, str] = {}
    for source in manifest["sources"]:
        files = source.get("files") or []
        if source["kind"] != "static":
            continue
        if not files:
            status[source["id"]] = "not downloaded"
            continue
        bad = 0
        for entry in files:
            path = root / entry["path"]
            if not path.exists():
                problems.append(f"{source['id']}: missing {entry['path']}")
                bad += 1
            elif path.stat().st_size != entry["size"] or common.sha256_file(path) != entry["sha256"]:
                problems.append(f"{source['id']}: checksum mismatch {entry['path']}")
                bad += 1
        status[source["id"]] = f"{len(files) - bad}/{len(files)} verified"
    return problems, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="fail when a static source has no files")
    args = parser.parse_args(argv)
    manifest = common.load_manifest()
    problems = check_structure(manifest)
    file_problems, status = verify_files(manifest, common.data_dir())
    problems += file_problems
    for sid, text in status.items():
        print(f"{sid:16} {text}")
    if args.strict:
        problems += [f"{sid}: not downloaded" for sid, t in status.items() if t == "not downloaded"]
    for problem in problems:
        print(f"PROBLEM {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
