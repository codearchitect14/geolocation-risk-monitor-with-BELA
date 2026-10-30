"""Fail when the Unicode em dash (U+2014) appears in any tracked or project text file."""

from __future__ import annotations

import sys
from pathlib import Path

EM_DASH = chr(0x2014)
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
SKIP_PREFIXES = (("data", "raw"), ("data", "processed"))
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".mdx",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".toml",
    ".xml",
    ".ts",
    ".tsx",
    ".js",
    ".css",
    ".html",
    ".sql",
    ".cfg",
    ".ini",
    ".sh",
    ".example",
}


def iter_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).parts
        if not path.is_file() or any(p in SKIP_DIRS for p in rel):
            continue
        if any(rel[: len(prefix)] == prefix for prefix in SKIP_PREFIXES):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in {"Makefile", ".gitignore"}:
            found.append(path)
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    failures = 0
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if EM_DASH in line:
                print(f"{path.relative_to(root)}:{number}: contains U+2014")
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
