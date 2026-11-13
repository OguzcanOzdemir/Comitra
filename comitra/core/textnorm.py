"""Text normalisation shared by indexing, querying and highlighting.

Comitra does its own normalisation instead of relying on the FTS5 tokenizer's
case folding, because plain Unicode lower-casing is not 1:1 for some letters
(e.g. dotted capital I) and because search should be accent-insensitive
("cafe" finds "Café").

The normalisation is *length preserving*: every input character maps to exactly
one output character. That lets the highlighter find match positions in the
normalised text and apply them to the original text unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Characters whose plain lower() is wrong for search purposes or not 1:1.
_SPECIAL = {
    "I": "i",
    "İ": "i",
    "ı": "i",
    "ß": "s",
    "ẞ": "s",
    "Æ": "a",
    "æ": "a",
    "Œ": "o",
    "œ": "o",
    "Ø": "o",
    "ø": "o",
    "Đ": "d",
    "đ": "d",
    "Ł": "l",
    "ł": "l",
    "Þ": "t",
    "þ": "t",
}


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    special = _SPECIAL.get(ch)
    if special is not None:
        return special
    low = ch.lower()
    if len(low) != 1:
        low = low[0]
    if low.isascii():
        return low
    decomposed = unicodedata.normalize("NFD", low)
    base = decomposed[0]
    if len(decomposed) > 1 and unicodedata.category(base)[0] in "LN":
        return base
    return low


def normalize(text: str) -> str:
    """Lower-case, fold dotted/dotless i variants and strip diacritics (1:1)."""
    if not text:
        return ""
    if text.isascii():
        return text.lower()
    return "".join(_fold_char(c) for c in text)


# A token is a run of letters, digits or underscores (after normalisation).
TOKEN_RE = re.compile(r"[^\W]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    """Split already-normalised text into search tokens."""
    return TOKEN_RE.findall(text)


def highlight_spans(text: str, terms: list[tuple[str, bool]]) -> list[tuple[int, int]]:
    """Return merged (start, end) spans of *text* that match the search terms.

    ``terms`` is a list of ``(normalised_token, is_prefix)``.
    """
    if not text or not terms:
        return []
    norm = normalize(text)
    exact = {t for t, p in terms if not p}
    prefixes = [t for t, p in terms if p]
    spans: list[tuple[int, int]] = []
    for m in TOKEN_RE.finditer(norm):
        tok = m.group(0)
        if tok in exact or any(tok.startswith(p) for p in prefixes):
            spans.append((m.start(), m.end()))
    return spans


def highlight_html(text: str, terms: list[tuple[str, bool]], open_tag: str, close_tag: str) -> str:
    """HTML-escape *text* and wrap matching tokens in the given tags."""
    import html

    spans = highlight_spans(text, terms)
    if not spans:
        return html.escape(text)
    out: list[str] = []
    pos = 0
    for start, end in spans:
        out.append(html.escape(text[pos:start]))
        out.append(open_tag + html.escape(text[start:end]) + close_tag)
        pos = end
    out.append(html.escape(text[pos:]))
    return "".join(out)
