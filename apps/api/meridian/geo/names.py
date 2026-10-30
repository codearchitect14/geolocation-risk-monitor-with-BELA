"""Name normalization for place matching.

normalize_name produces the key stored in name_normalized and alias_normalized and used by
the trigram indexes. The same function must be applied to queries.

Rules, in order: Unicode NFKC, case folding, removal of combining marks on Latin, Greek and
Cyrillic letters (other scripts keep their marks because they carry meaning), apostrophes
and hyphens to spaces, other punctuation removed, whitespace collapsed, and common
abbreviations expanded (St, Ste, Mt, Ft, Pt).
"""

from __future__ import annotations

import re
import unicodedata

from unidecode import unidecode

_ABBREVIATIONS = {
    "st": "saint",
    "ste": "sainte",
    "mt": "mount",
    "mte": "monte",
    "ft": "fort",
    "pt": "point",
}
# Leading words that often appear or vanish between sources ("Port of Rotterdam", "Rotterdam").
_STRIPPABLE_PREFIXES = (
    "port of",
    "port de",
    "porto de",
    "puerto de",
    "hafen",
    "city of",
    "town of",
    "village of",
    "mount",
    "mont",
    "monte",
    "saint",
    "sainte",
    "san",
    "santa",
    "santo",
    "sankt",
    "the",
)
_APOSTROPHES = "'’‘ʼ`´"
_SPACES = re.compile(r"\s+")
_CASED_SCRIPTS = ("LATIN", "GREEK", "CYRILLIC")


def _strip_marks(text: str) -> str:
    out: list[str] = []
    base_script_ok = False
    for char in unicodedata.normalize("NFKD", text):
        if unicodedata.combining(char):
            if base_script_ok:
                continue
            out.append(char)
            continue
        out.append(char)
        try:
            base_script_ok = unicodedata.name(char).startswith(_CASED_SCRIPTS)
        except ValueError:
            base_script_ok = False
    return unicodedata.normalize("NFC", "".join(out))


def _drop_punctuation(text: str) -> str:
    """Replace punctuation and symbols with spaces; letters, digits, and combining marks stay."""
    return "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in text)


def normalize_name(text: str) -> str:
    """Return the canonical comparison key for a place name."""
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = _strip_marks(value)
    for char in _APOSTROPHES:
        value = value.replace(char, "")
    value = value.replace("-", " ").replace("–", " ")
    value = _drop_punctuation(value)
    tokens = [_ABBREVIATIONS.get(token, token) for token in _SPACES.split(value.strip()) if token]
    return " ".join(tokens)


def strip_prefix(normalized: str) -> str | None:
    """Return the name without a leading generic word, or None when nothing was removed."""
    for prefix in sorted(_STRIPPABLE_PREFIXES, key=len, reverse=True):
        if normalized.startswith(prefix + " ") and len(normalized) > len(prefix) + 2:
            return normalized[len(prefix) + 1 :]
    return None


def transliterate(text: str) -> str:
    """ASCII transliteration for display and for cross-script fallback matching."""
    return normalize_name(unidecode(text))


def name_keys(text: str) -> list[str]:
    """All lookup keys for a query: the normalized form, a prefix-stripped form, and a
    transliterated form when the text is not Latin script."""
    primary = normalize_name(text)
    keys = [primary] if primary else []
    stripped = strip_prefix(primary)
    if stripped:
        keys.append(stripped)
    ascii_form = transliterate(text)
    if ascii_form and ascii_form not in keys and not primary.isascii():
        keys.append(ascii_form)
    return keys
