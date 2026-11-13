"""Query language: parsing a search string into a :class:`Query` and back.

The search box and the filter panel share a single :class:`Query` object.
``parse(text)`` and ``Query.to_string()`` round-trip, so either side can
update the other.

Syntax (keys are case-insensitive)::

    payment "exact phrase" login* -wip -"work in progress"
    author:alice,bob@example.com
    repo:billing
    branch:feature/*
    hash:a1b2c3d
    file:*.py file:src/auth/
    date:today | yesterday | 7d | 30d | month | year
    date:2026-11-10 | date:2026-10-01..2026-10-31 | date:2026-10 | date:2026
    after:2026-10-01 (inclusive)   before:2026-11-01 (exclusive)
    merge:hide | only | show        hour:09-12   day:fri,sat | day:weekend
    unreachable:include | only      sort:newest | oldest | relevance

Within one key, several values are OR-ed; different keys are AND-ed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

KEY_ALIASES = {
    "author": "author", "a": "author",
    "repo": "repo", "r": "repo", "project": "repo",
    "branch": "branch", "b": "branch",
    "hash": "hash", "h": "hash", "commit": "hash",
    "file": "file", "f": "file", "path": "file",
    "date": "date", "d": "date",
    "after": "after", "since": "after", "from": "after",
    "before": "before", "until": "before",
    "on": "on",
    "merge": "merge",
    "hour": "hour", "time": "hour",
    "day": "day", "weekday": "day",
    "unreachable": "unreachable", "lost": "unreachable",
    "sort": "sort", "order": "sort",
}

DATE_PRESETS = {
    "today": "today",
    "yesterday": "yesterday",
    "7d": "7d", "week": "7d",
    "30d": "30d",
    "month": "month", "thismonth": "month",
    "year": "year", "thisyear": "year",
}

DAY_NAMES = {
    0: ["mon", "monday", "1"],
    1: ["tue", "tuesday", "2"],
    2: ["wed", "wednesday", "3"],
    3: ["thu", "thursday", "4"],
    4: ["fri", "friday", "5"],
    5: ["sat", "saturday", "6"],
    6: ["sun", "sunday", "7"],
}
_DAY_LOOKUP = {name: d for d, names in DAY_NAMES.items() for name in names}
DAY_SHORT = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MERGE_VALUES = {"show": "show", "all": "show", "hide": "hide", "no": "hide", "only": "only", "yes": "only"}
UNREACH_VALUES = {"hide": "hide", "include": "include", "show": "include", "only": "only"}
SORT_VALUES = {"newest": "newest", "new": "newest", "oldest": "oldest", "old": "oldest",
               "relevance": "relevance", "rel": "relevance"}

_ISO_DAY = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{1,2}$")
_ISO_YEAR = re.compile(r"^\d{4}$")
_NDAYS = re.compile(r"^(\d{1,4})d$")
_HOUR_RANGE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?:\s*[-–]\s*(\d{1,2})(?::(\d{2}))?)?$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")


@dataclass
class Term:
    text: str
    negated: bool = False
    phrase: bool = False

    @property
    def prefix(self) -> bool:
        return not self.phrase and self.text.endswith("*") and len(self.text) > 1

    @property
    def bare(self) -> str:
        return self.text[:-1] if self.prefix else self.text

    def to_string(self) -> str:
        body = f'"{self.text}"' if self.phrase else self.text
        return ("-" if self.negated else "") + body


@dataclass
class DateFilter:
    """Either a preset name or an explicit inclusive day range."""

    preset: str | None = None
    start: date | None = None   # inclusive
    end: date | None = None     # inclusive

    def to_value(self) -> str:
        if self.preset:
            return self.preset
        if self.start and self.end and self.start == self.end:
            return self.start.isoformat()
        if self.start and self.end:
            return f"{self.start.isoformat()}..{self.end.isoformat()}"
        if self.start:
            return f"{self.start.isoformat()}.."
        if self.end:
            return f"..{self.end.isoformat()}"
        return ""

    def bounds(self, today: date | None = None) -> tuple[date | None, date | None]:
        """Return (inclusive start day, exclusive end day)."""
        today = today or date.today()
        p = self.preset
        if p == "today":
            return today, today + timedelta(days=1)
        if p == "yesterday":
            return today - timedelta(days=1), today
        if p == "month":
            return today.replace(day=1), today + timedelta(days=1)
        if p == "year":
            return today.replace(month=1, day=1), today + timedelta(days=1)
        if p:
            m = _NDAYS.match(p)
            if m:
                n = max(1, int(m.group(1)))
                return today - timedelta(days=n - 1), today + timedelta(days=1)
            return None, None
        return self.start, (self.end + timedelta(days=1)) if self.end else None


@dataclass
class Query:
    terms: list[Term] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    hashes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    date: DateFilter | None = None
    after: date | None = None
    before: date | None = None
    merge: str = "show"
    hours: tuple[int, int] | None = None   # [start, end) in hours, may wrap
    days: list[int] = field(default_factory=list)
    unreachable: str = "hide"
    sort: str | None = None                # None = default (relevance if text else newest)
    errors: list[str] = field(default_factory=list)

    # -- helpers ---------------------------------------------------------------
    @property
    def positive_terms(self) -> list[Term]:
        return [t for t in self.terms if not t.negated]

    @property
    def negative_terms(self) -> list[Term]:
        return [t for t in self.terms if t.negated]

    def is_empty(self) -> bool:
        return self.to_string() == ""

    def text_string(self) -> str:
        return " ".join(t.to_string() for t in self.terms)

    def effective_sort(self) -> str:
        if self.sort:
            if self.sort == "relevance" and not self.positive_terms:
                return "newest"
            return self.sort
        return "relevance" if self.positive_terms else "newest"

    def date_range(self, today: date | None = None) -> tuple[date | None, date | None]:
        """Combined (inclusive start, exclusive end) from date/after/before."""
        start, end = (None, None)
        if self.date:
            start, end = self.date.bounds(today)
        if self.after and (start is None or self.after > start):
            start = self.after
        if self.before and (end is None or self.before < end):
            end = self.before
        return start, end

    def copy(self) -> "Query":
        return replace(
            self,
            terms=[replace(t) for t in self.terms],
            authors=list(self.authors),
            repos=list(self.repos),
            branches=list(self.branches),
            hashes=list(self.hashes),
            files=list(self.files),
            date=replace(self.date) if self.date else None,
            days=list(self.days),
            errors=[],
        )

    def to_string(self) -> str:
        parts: list[str] = []

        def multi(key: str, values: list[str]) -> None:
            if values:
                parts.append(f"{key}:{','.join(_quote(v) for v in values)}")

        multi("author", self.authors)
        multi("repo", self.repos)
        multi("branch", self.branches)
        multi("hash", self.hashes)
        multi("file", self.files)
        if self.date and self.date.to_value():
            parts.append(f"date:{self.date.to_value()}")
        if self.after:
            parts.append(f"after:{self.after.isoformat()}")
        if self.before:
            parts.append(f"before:{self.before.isoformat()}")
        if self.hours:
            parts.append(f"hour:{self.hours[0]:02d}-{self.hours[1]:02d}")
        if self.days:
            parts.append("day:" + ",".join(DAY_SHORT[d] for d in sorted(set(self.days))))
        if self.merge != "show":
            parts.append(f"merge:{self.merge}")
        if self.unreachable != "hide":
            parts.append(f"unreachable:{self.unreachable}")
        if self.sort:
            parts.append(f"sort:{self.sort}")
        text = self.text_string()
        if text:
            parts.append(text)
        return " ".join(parts)


def _quote(v: str) -> str:
    if not v or any(ch.isspace() or ch in ',"' for ch in v):
        return '"' + v.replace('"', "") + '"'
    return v


# -- tokenizer -----------------------------------------------------------------

def _lex(text: str) -> list[tuple[str, bool, bool]]:
    """Split into raw tokens: (token, negated, was_quoted)."""
    out: list[tuple[str, bool, bool]] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        neg = False
        if text[i] == "-" and i + 1 < n and not text[i + 1].isspace():
            neg = True
            i += 1
        if text[i] == '"':
            j = text.find('"', i + 1)
            if j < 0:
                j = n
            out.append((text[i + 1 : j], neg, True))
            i = j + 1
            continue
        # unquoted token; a key:"quoted value" keeps the quotes inside.
        start = i
        while i < n and not text[i].isspace():
            if text[i] == '"':
                j = text.find('"', i + 1)
                i = n if j < 0 else j + 1
                continue
            i += 1
        out.append((text[start:i], neg, False))
    return out


def _split_values(raw: str) -> list[str]:
    vals: list[str] = []
    buf = ""
    inq = False
    for ch in raw:
        if ch == '"':
            inq = not inq
            continue
        if ch == "," and not inq:
            if buf.strip():
                vals.append(buf.strip())
            buf = ""
            continue
        buf += ch
    if buf.strip():
        vals.append(buf.strip())
    return vals


def _parse_day(s: str) -> date | None:
    s = s.strip()
    try:
        if _ISO_DAY.match(s):
            y, m, d = (int(x) for x in s.split("-"))
            return date(y, m, d)
        # also accept 10.11.2026 and 10/11/2026 (day first)
        m2 = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", s)
        if m2:
            return date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
    except ValueError:
        return None
    return None


def _parse_date_value(v: str) -> DateFilter | None:
    low = v.strip().lower()
    if low in DATE_PRESETS:
        return DateFilter(preset=DATE_PRESETS[low])
    if _NDAYS.match(low):
        return DateFilter(preset=low)
    if ".." in low:
        a, b = low.split("..", 1)
        sa = _parse_day(a) if a else None
        sb = _parse_day(b) if b else None
        if (a and not sa) or (b and not sb) or (not sa and not sb):
            return None
        if sa and sb and sa > sb:
            sa, sb = sb, sa
        return DateFilter(start=sa, end=sb)
    d = _parse_day(low)
    if d:
        return DateFilter(start=d, end=d)
    try:
        if _ISO_MONTH.match(low):
            y, m = (int(x) for x in low.split("-"))
            first = date(y, m, 1)
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            return DateFilter(start=first, end=nxt - timedelta(days=1))
        if _ISO_YEAR.match(low):
            y = int(low)
            return DateFilter(start=date(y, 1, 1), end=date(y, 12, 31))
    except ValueError:
        return None
    return None


def parse_hours(v: str) -> tuple[int, int] | None:
    m = _HOUR_RANGE.match(v.strip())
    if not m:
        return None
    h1 = int(m.group(1))
    if m.group(3) is None:
        h2 = (h1 + 1) % 24 if h1 < 24 else None
    else:
        h2 = int(m.group(3))
        if m.group(4) and int(m.group(4)) > 0:
            h2 += 1  # 09:00-12:30 includes the 12 o'clock hour
    if h2 is None or not (0 <= h1 <= 23) or not (0 <= h2 <= 24):
        return None
    h2 %= 24
    if h1 == h2:
        return None
    return h1, h2


def hours_set(hours: tuple[int, int]) -> list[int]:
    a, b = hours
    if a < b:
        return list(range(a, b))
    return list(range(a, 24)) + list(range(0, b))


def parse_days(v: str) -> list[int] | None:
    out: list[int] = []
    for part in _split_values(v.lower()):
        if part == "weekend":
            out += [5, 6]
        elif part in ("weekdays", "workdays"):
            out += [0, 1, 2, 3, 4]
        elif part in _DAY_LOOKUP:
            out.append(_DAY_LOOKUP[part])
        else:
            return None
    return sorted(set(out))


def parse(text: str) -> Query:
    q = Query()
    for tok, neg, quoted in _lex(text or ""):
        if not tok:
            continue
        if not quoted and ":" in tok and not neg:
            key, _, raw = tok.partition(":")
            canon = KEY_ALIASES.get(key.lower())
            if canon and raw:
                if _apply(q, canon, raw):
                    continue
                q.errors.append(f"{key}:{raw}")
                continue
        q.terms.append(Term(tok, negated=neg, phrase=quoted))
    return q


def _apply(q: Query, key: str, raw: str) -> bool:
    vals = _split_values(raw)
    if not vals:
        return False
    if key == "author":
        q.authors += [v for v in vals if v not in q.authors]
    elif key == "repo":
        q.repos += [v for v in vals if v not in q.repos]
    elif key == "branch":
        q.branches += [v for v in vals if v not in q.branches]
    elif key == "hash":
        good = [v.lower() for v in vals if HEX_RE.match(v)]
        if not good:
            return False
        q.hashes += [v for v in good if v not in q.hashes]
    elif key == "file":
        q.files += [v for v in vals if v not in q.files]
    elif key == "date" or key == "on":
        df = _parse_date_value(raw.strip('"'))
        if df is None:
            return False
        q.date = df
    elif key == "after":
        d = _parse_day(raw.strip('"'))
        if not d:
            return False
        q.after = d
    elif key == "before":
        d = _parse_day(raw.strip('"'))
        if not d:
            return False
        q.before = d
    elif key == "merge":
        v = MERGE_VALUES.get(vals[0].lower())
        if not v:
            return False
        q.merge = v
    elif key == "hour":
        h = parse_hours(raw.strip('"'))
        if h is None:
            return False
        q.hours = h
    elif key == "day":
        d = parse_days(raw)
        if not d:
            return False
        q.days = d
    elif key == "unreachable":
        v = UNREACH_VALUES.get(vals[0].lower())
        if not v:
            return False
        q.unreachable = v
    elif key == "sort":
        v = SORT_VALUES.get(vals[0].lower())
        if not v:
            return False
        q.sort = v
    else:
        return False
    return True


def today_local() -> date:
    return datetime.now().date()
