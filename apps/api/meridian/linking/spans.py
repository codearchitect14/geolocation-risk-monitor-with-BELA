"""Capitalized-span detection for the gazetteer fallback.

BELA only proposes spans it recognizes. A span that starts with a capital letter and matches a
gazetteer name is still worth resolving, so this module finds those. It works for scripts with
letter case; text in scripts without case (Chinese, Japanese, Arabic, Hindi) relies on BELA alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Lowercase words allowed inside a name: "Port of Rotterdam", "Santiago de Chile", "Stratford-upon-Avon".
CONNECTORS = {
    "of",
    "de",
    "del",
    "della",
    "di",
    "da",
    "do",
    "dos",
    "das",
    "du",
    "des",
    "la",
    "le",
    "el",
    "al",
    "van",
    "von",
    "der",
    "den",
    "the",
    "on",
    "upon",
    "y",
    "e",
    "and",
    "sur",
    "sous",
    "am",
    "an",
    "im",
}
_TOKEN = re.compile(r"[^\W\d_](?:[^\W_]|['’\-.])*", re.UNICODE)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


def _is_capitalized(word: str) -> bool:
    """Title case, or an all-capitals word (datelines such as "MANSFIELD --", abbreviations such as "UK")."""
    return word[:1].isupper() and (not word.isupper() or len(word) >= 2)


def capitalized_spans(text: str, max_words: int = 5) -> list[Span]:
    """Maximal runs of capitalized words, optionally joined by connectors. Sub-spans of long runs
    are generated so a name inside a longer run ("Mayor Bob Smith of Dayton") can still be found."""
    tokens = [(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(text)]
    runs: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    for token in tokens:
        word = token[2]
        if _is_capitalized(word) or current and word.lower() in CONNECTORS:
            current.append(token)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    spans: list[Span] = []
    seen: set[tuple[int, int]] = set()
    for run in runs:
        while run and run[-1][2].lower() in CONNECTORS:
            run = run[:-1]
        n = len(run)
        for i in range(n):
            if run[i][2].lower() in CONNECTORS:
                continue
            for j in range(min(n, i + max_words), i, -1):
                if run[j - 1][2].lower() in CONNECTORS:
                    continue
                start, end = run[i][0], run[j - 1][1]
                if (start, end) not in seen:
                    seen.add((start, end))
                    spans.append(Span(start, end, text[start:end].rstrip(".,")))
    return sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
