"""Export search results to CSV or JSON."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from .search import fetch_rows

FIELDS = [
    "repo", "repo_path", "hash", "author_name", "author_email", "author_date",
    "committer_name", "committer_email", "commit_date", "branch", "parents", "on_branch", "subject", "message",
]


def iso(ts: int, tz_min: int) -> str:
    try:
        return datetime.fromtimestamp(ts, timezone(timedelta(minutes=tz_min))).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _records(conn: sqlite3.Connection, ids: list[int], progress: Callable[[int], None] | None) -> Iterable[dict]:
    for i in range(0, len(ids), 1000):
        ch = ids[i : i + 1000]
        rows = fetch_rows(conn, ch)
        for cid in ch:
            r = rows.get(cid)
            if r is None:
                continue
            yield {
                "repo": r["repo_name"],
                "repo_path": r["repo_path"],
                "hash": r["hash"],
                "author_name": r["author_name"],
                "author_email": r["author_email"],
                "author_date": iso(r["author_time"], r["author_tz"]),
                "committer_name": r["committer_name"],
                "committer_email": r["committer_email"],
                "commit_date": iso(r["commit_time"], r["commit_tz"]),
                "branch": r["first_ref"],
                "parents": r["parents"],
                "on_branch": bool(r["reachable"]),
                "subject": r["subject"],
                "message": r["message"],
            }
        if progress:
            progress(min(i + 1000, len(ids)))


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """Commit data comes from other people: stop spreadsheet apps from running it as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def export_csv(conn: sqlite3.Connection, ids: list[int], path: str, progress=None) -> int:
    n = 0
    # utf-8-sig so that Excel on Windows detects UTF-8 correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for rec in _records(conn, ids, progress):
            w.writerow({k: _safe_cell(v) for k, v in rec.items()})
            n += 1
    return n


def export_json(conn: sqlite3.Connection, ids: list[int], path: str, progress=None) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[\n")
        for rec in _records(conn, ids, progress):
            if n:
                fh.write(",\n")
            fh.write(json.dumps(rec, ensure_ascii=False))
            n += 1
        fh.write("\n]\n")
    return n
