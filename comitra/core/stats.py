"""Aggregate statistics for the statistics screen and the CLI."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Stats:
    total_commits: int
    total_repos: int
    total_authors: int
    unreachable: int
    first_time: int | None
    last_time: int | None
    by_repo: list[tuple[str, int]]
    by_author: list[tuple[str, str, int]]
    by_month: list[tuple[str, int]]
    by_weekday: list[tuple[int, int]]
    by_hour: list[tuple[int, int]]


def compute(conn: sqlite3.Connection, ids: list[int] | None = None, top: int = 100) -> Stats:
    """Statistics over all reachable commits, or over the given commit ids."""
    if ids is not None:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_stat_ids(id INTEGER PRIMARY KEY)")
        conn.execute("DELETE FROM tmp_stat_ids")
        conn.executemany("INSERT OR IGNORE INTO tmp_stat_ids(id) VALUES (?)", ((i,) for i in ids))
        scope = "c.id IN (SELECT id FROM tmp_stat_ids)"
    else:
        scope = "c.reachable = 1"
    one = conn.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT c.repo_id), COUNT(DISTINCT lower(c.author_email)), MIN(c.author_time), MAX(c.author_time) FROM commits c WHERE {scope}"
    ).fetchone()
    unreachable = conn.execute("SELECT COUNT(*) FROM commits WHERE reachable = 0").fetchone()[0]
    by_repo = [
        (r[0], r[1])
        for r in conn.execute(
            f"SELECT r.name, COUNT(*) n FROM commits c JOIN repos r ON r.id=c.repo_id WHERE {scope} GROUP BY c.repo_id ORDER BY n DESC LIMIT ?",
            (top,),
        )
    ]
    by_author = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            f"SELECT MAX(c.author_name), lower(c.author_email) e, COUNT(*) n FROM commits c WHERE {scope} GROUP BY e ORDER BY n DESC LIMIT ?",
            (top,),
        )
    ]
    by_month = [
        (r[0], r[1])
        for r in conn.execute(
            f"SELECT strftime('%Y-%m', c.author_time, 'unixepoch', 'localtime') m, COUNT(*) FROM commits c WHERE {scope} GROUP BY m ORDER BY m"
        )
    ]
    by_weekday = [(r[0], r[1]) for r in conn.execute(f"SELECT c.author_wday, COUNT(*) FROM commits c WHERE {scope} GROUP BY 1 ORDER BY 1")]
    by_hour = [(r[0], r[1]) for r in conn.execute(f"SELECT c.author_hour, COUNT(*) FROM commits c WHERE {scope} GROUP BY 1 ORDER BY 1")]
    return Stats(one[0], one[1], one[2], unreachable, one[3], one[4], by_repo, by_author, by_month, by_weekday, by_hour)
