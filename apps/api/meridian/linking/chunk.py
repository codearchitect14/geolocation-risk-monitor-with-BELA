"""Split article text into passages that fit the entity linker, at sentence boundaries."""

from __future__ import annotations

from dataclasses import dataclass

import pysbd

_SEGMENTERS: dict[str, pysbd.Segmenter] = {}


@dataclass(frozen=True)
class Chunk:
    start: int  # character offset of the chunk in the article text
    text: str


def _segmenter(lang: str) -> pysbd.Segmenter:
    code = lang if lang in pysbd.languages.LANGUAGE_CODES else "en"
    if code not in _SEGMENTERS:
        _SEGMENTERS[code] = pysbd.Segmenter(language=code, clean=False, char_span=True)
    return _SEGMENTERS[code]


def sentences(text: str, lang: str = "en") -> list[tuple[int, int]]:
    """Character spans of the sentences in text."""
    spans = [(s.start, s.end) for s in _segmenter(lang).segment(text)]
    return spans or [(0, len(text))]


def make_chunks(text: str, lang: str = "en", max_chars: int = 700, overlap_sentences: int = 1) -> list[Chunk]:
    """Group sentences into chunks of at most max_chars, repeating the last sentences of a chunk
    at the start of the next one so mentions near the boundary keep their context."""
    if len(text) <= max_chars:
        return [Chunk(0, text)]
    units: list[tuple[int, int]] = []
    for start, end in sentences(text, lang):
        if end - start > max_chars:
            units.extend(_cut_at_whitespace(text, start, end, max_chars))
        else:
            units.append((start, end))
    chunks: list[Chunk] = []
    current: list[tuple[int, int]] = []
    for unit in units:
        if current and unit[1] - current[0][0] > max_chars:
            chunks.append(Chunk(current[0][0], text[current[0][0] : current[-1][1]]))
            current = current[-overlap_sentences:] if overlap_sentences else []
            if current and unit[1] - current[0][0] > max_chars:
                current = []
        current.append(unit)
    if current:
        chunks.append(Chunk(current[0][0], text[current[0][0] : current[-1][1]]))
    return chunks


def _cut_at_whitespace(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    pieces = []
    while end - start > max_chars:
        cut = text.rfind(" ", start + max_chars // 2, start + max_chars)
        cut = start + max_chars if cut == -1 else cut + 1
        pieces.append((start, cut))
        start = cut
    pieces.append((start, end))
    return pieces
