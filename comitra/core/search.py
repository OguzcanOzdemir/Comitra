"""Search service: turns a :class:`Query` into SQL and returns ordered ids.

The result of a search is the full, ordered list of matching commit ids (plus
an optional group key). Rows are fetched lazily by id for display, which keeps
the UI fast for huge result sets (virtual scrolling) and gives exact counts.
"""

from __future__ import annotations

import fnmatch
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime

from . import gitcmd, gitrepo
from .query import HEX_RE, Query, Term, hours_set
from .textnorm import normalize, tokens

MAX_RESULTS = 2_000_000


@dataclass
class SearchOptions:
    date_basis: str = "author"     # author | committer
    group_by: str | None = None    # None | repo | author | day
    limit: int = MAX_RESULTS


@dataclass
class SearchResult:
    ids: list[int] = field(default_factory=list)
    groups: list[object] | None = None
    highlight_terms: list[tuple[str, bool]] = field(default_factory=list)
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False


# -- FTS expression building ---------------------------------------------------

def _fts_phrase(term: Term) -> str | None:
    toks = tokens(normalize(term.bare))
    if not toks:
        return None
    body = '"' + " ".join(toks) + '"'
    return body + "*" if term.prefix else body


def fts_expression(terms: list[Term], joiner: str) -> str | None:
    parts = [p for p in (_fts_phrase(t) for t in terms) if p]
    if not parts:
        return None
    return f" {joiner} ".join(parts)


def highlight_terms(q: Query) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for t in q.positive_terms:
        toks = tokens(normalize(t.bare))
        for i, tok in enumerate(toks):
            out.append((tok, t.prefix and i == len(toks) - 1))
    return out


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# -- branch resolution ---------------------------------------------------------

class BranchResolver:
    """Resolve ``branch:`` patterns to commit ids via ``git rev-list``.

    Results are cached per (repo, ref tips), so repeated searches are cheap
    and the cache invalidates itself when a branch moves.
    """

    def __init__(self, max_entries: int = 64):
        self._cache: dict[tuple, list[int]] = {}
        self._hash_ids: dict[tuple[int, int], dict[str, int]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def _ids_for_repo(self, conn: sqlite3.Connection, repo_id: int, stamp: int) -> dict[str, int]:
        key = (repo_id, stamp)
        with self._lock:
            got = self._hash_ids.get(key)
        if got is not None:
            return got
        m = {h: i for i, h in conn.execute("SELECT id, hash FROM commits WHERE repo_id=?", (repo_id,))}
        with self._lock:
            for k in [k for k in self._hash_ids if k[0] == repo_id]:
                del self._hash_ids[k]
            self._hash_ids[key] = m
        return m

    @staticmethod
    def matches(ref: gitrepo.Ref, patterns: list[str]) -> bool:
        names = [n.lower() for n in ref.match_names()]
        for p in patterns:
            pl = p.lower()
            if any(ch in pl for ch in "*?["):
                if any(fnmatch.fnmatchcase(n, pl) for n in names):
                    return True
            elif pl in names:
                return True
        return False

    def resolve(
        self, conn: sqlite3.Connection, patterns: list[str], repo_ids: list[int] | None, warnings: list[str]
    ) -> list[int]:
        sql = "SELECT r.id, r.path, r.last_indexed_at, f.name, f.kind, f.target FROM refs f JOIN repos r ON r.id = f.repo_id WHERE f.kind != 'tag'"
        rows = conn.execute(sql).fetchall()
        per_repo: dict[int, tuple[str, int, list[gitrepo.Ref]]] = {}
        for rid, path, stamp, name, kind, target in rows:
            if repo_ids is not None and rid not in repo_ids:
                continue
            ref = gitrepo.Ref(name, kind, target)
            if self.matches(ref, patterns):
                per_repo.setdefault(rid, (path, stamp or 0, []))[2].append(ref)
        out: list[int] = []
        for rid, (path, stamp, refs) in per_repo.items():
            tips = tuple(sorted({r.target for r in refs}))
            key = (rid, tips)
            with self._lock:
                cached = self._cache.get(key)
            if cached is None:
                cached = self._compute(conn, rid, path, stamp, tips, refs, patterns, warnings)
                with self._lock:
                    if len(self._cache) >= self._max:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = cached
            out.extend(cached)
        return out

    def _compute(self, conn, rid, path, stamp, tips, refs, patterns, warnings) -> list[int]:
        if os.path.isdir(path):
            try:
                id_map = self._ids_for_repo(conn, rid, stamp)
                return [id_map[h] for h in gitrepo.rev_list(path, list(tips)) if h in id_map]
            except (gitcmd.GitError, gitcmd.GitTimeout, gitcmd.GitNotFoundError, OSError) as exc:
                warnings.append(f"branch filter fallback for {path}: {exc}")
        # Fallback without git: use the ref each commit was discovered from.
        names = {r.short for r in refs}
        qmarks = ",".join("?" * len(names))
        return [
            r[0]
            for r in conn.execute(
                f"SELECT id FROM commits WHERE repo_id=? AND first_ref IN ({qmarks})", (rid, *names)
            )
        ]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hash_ids.clear()


_default_resolver = BranchResolver()


# -- main entry point ----------------------------------------------------------

def _day_ts(d) -> int:
    return int(datetime.combine(d, dtime()).timestamp())


def build_sql(conn: sqlite3.Connection, q: Query, opts: SearchOptions, resolver: BranchResolver | None = None,
              warnings: list[str] | None = None) -> tuple[str, list, bool]:
    """Return (sql, params, uses_score)."""
    warnings = warnings if warnings is not None else []
    resolver = resolver or _default_resolver
    tcol = "c.commit_time" if opts.date_basis == "committer" else "c.author_time"
    hcol = "c.commit_hour" if opts.date_basis == "committer" else "c.author_hour"
    wcol = "c.commit_wday" if opts.date_basis == "committer" else "c.author_wday"
    where: list[str] = []
    params: list = []
    joins: list[str] = []
    jparams: list = []
    uses_score = False

    pos = q.positive_terms
    pos_expr = fts_expression(pos, "AND")
    hex_only = len(pos) == 1 and not pos[0].phrase and not pos[0].prefix and HEX_RE.match(pos[0].text) and len(pos[0].text) >= 7
    if pos_expr:
        if hex_only:
            h = pos[0].text.lower()
            where.append("((c.hash >= ? AND c.hash < ?) OR c.id IN (SELECT rowid FROM commits_fts WHERE commits_fts MATCH ?))")
            params += [h, h + "g", pos_expr]
        else:
            joins.append(
                "JOIN (SELECT rowid AS fid, bm25(commits_fts) AS score FROM commits_fts WHERE commits_fts MATCH ?) f ON f.fid = c.id"
            )
            jparams.append(pos_expr)
            uses_score = True
    elif pos:
        warnings.append("search text has no searchable words")
    neg_expr = fts_expression(q.negative_terms, "OR")
    if neg_expr:
        where.append("c.id NOT IN (SELECT rowid FROM commits_fts WHERE commits_fts MATCH ?)")
        params.append(neg_expr)

    if q.authors:
        conds = []
        for a in q.authors:
            conds.append("c.people_norm LIKE ? ESCAPE '\\'")
            params.append(f"%{_like_escape(normalize(a))}%")
        where.append("(" + " OR ".join(conds) + ")")

    repo_ids: list[int] | None = None
    if q.repos:
        conds, rparams = [], []
        for r in q.repos:
            conds.append("name_norm LIKE ? ESCAPE '\\'")
            rparams.append(f"%{_like_escape(normalize(r))}%")
        repo_ids = [row[0] for row in conn.execute(f"SELECT id FROM repos WHERE {' OR '.join(conds)}", rparams)]
        if repo_ids:
            where.append(f"c.repo_id IN ({','.join(str(i) for i in repo_ids)})")
        else:
            where.append("0")

    if q.branches:
        ids = resolver.resolve(conn, q.branches, repo_ids, warnings)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS tmp_branch_ids(id INTEGER PRIMARY KEY)")
        conn.execute("DELETE FROM tmp_branch_ids")
        conn.executemany("INSERT OR IGNORE INTO tmp_branch_ids(id) VALUES (?)", ((i,) for i in ids))
        where.append("c.id IN (SELECT id FROM tmp_branch_ids)")

    if q.hashes:
        conds = []
        for h in q.hashes:
            conds.append("(c.hash >= ? AND c.hash < ?)")
            params += [h, h + "g"]
        where.append("(" + " OR ".join(conds) + ")")

    if q.files:
        has_files = conn.execute("SELECT 1 FROM commit_files LIMIT 1").fetchone()
        if not has_files:
            warnings.append("file index is empty (enable 'Index changed file paths' in settings)")
        conds = []
        for f in q.files:
            fn = normalize(f.replace("\\", "/"))
            if any(ch in fn for ch in "*?["):
                pat = fn if fn.startswith("*") or "/" in fn else "*" + fn
                if "/" in fn and not fn.startswith("*"):
                    conds.append("(p.path_norm GLOB ? OR p.path_norm GLOB ?)")
                    params += [fn, "*/" + fn]
                else:
                    conds.append("p.path_norm GLOB ?")
                    params.append(pat)
            elif fn.endswith("/"):
                conds.append("(p.path_norm LIKE ? ESCAPE '\\' OR p.path_norm LIKE ? ESCAPE '\\')")
                params += [_like_escape(fn) + "%", "%/" + _like_escape(fn) + "%"]
            else:
                conds.append("p.path_norm LIKE ? ESCAPE '\\'")
                params.append(f"%{_like_escape(fn)}%")
        where.append(
            "c.id IN (SELECT cf.commit_id FROM commit_files cf JOIN paths p ON p.id = cf.path_id WHERE "
            + " OR ".join(conds)
            + ")"
        )

    start, end = q.date_range()
    if start:
        where.append(f"{tcol} >= ?")
        params.append(_day_ts(start))
    if end:
        where.append(f"{tcol} < ?")
        params.append(_day_ts(end))

    if q.hours:
        hs = hours_set(q.hours)
        where.append(f"{hcol} IN ({','.join(str(h) for h in hs)})")
    if q.days:
        where.append(f"{wcol} IN ({','.join(str(int(d)) for d in q.days)})")

    if q.merge == "hide":
        where.append("c.parent_count <= 1")
    elif q.merge == "only":
        where.append("c.parent_count > 1")

    if q.unreachable == "hide":
        where.append("c.reachable = 1")
    elif q.unreachable == "only":
        where.append("c.reachable = 0")

    group_expr = "NULL"
    if opts.group_by == "repo":
        group_expr = "c.repo_id"
    elif opts.group_by == "author":
        group_expr = "c.author_name"
    elif opts.group_by == "day":
        group_expr = f"date({tcol}, 'unixepoch', 'localtime')"

    sort = q.effective_sort()
    if sort == "relevance" and uses_score:
        order = f"f.score ASC, {tcol} DESC, c.id DESC"
    elif sort == "oldest":
        order = f"{tcol} ASC, c.id ASC"
    else:
        order = f"{tcol} DESC, c.id DESC"

    sql = (
        f"SELECT c.id, {group_expr} AS g FROM commits c {' '.join(joins)}"
        + (f" WHERE {' AND '.join(where)}" if where else "")
        + f" ORDER BY {order} LIMIT ?"
    )
    return sql, jparams + params + [opts.limit + 1], uses_score


def search(
    conn: sqlite3.Connection,
    q: Query,
    opts: SearchOptions | None = None,
    resolver: BranchResolver | None = None,
) -> SearchResult:
    opts = opts or SearchOptions()
    t0 = time.monotonic()
    res = SearchResult(highlight_terms=highlight_terms(q))
    if q.errors:
        res.warnings += [f"ignored filter: {e}" for e in q.errors]
    sql, params, _ = build_sql(conn, q, opts, resolver, res.warnings)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        res.warnings.append(f"query error: {exc}")
        rows = []
    if len(rows) > opts.limit:
        rows = rows[: opts.limit]
        res.truncated = True
    res.ids = [r[0] for r in rows]
    if opts.group_by:
        keyed = list(rows)
        if opts.group_by == "day":
            reverse = q.effective_sort() != "oldest"
            keyed.sort(key=lambda r: r[1] or "", reverse=reverse)
        elif opts.group_by == "author":
            keyed.sort(key=lambda r: (r[1] or "").lower())
        else:
            names = {i: n.lower() for i, n in conn.execute("SELECT id, name FROM repos")}
            keyed.sort(key=lambda r: names.get(r[1], ""))
        res.ids = [r[0] for r in keyed]
        res.groups = [r[1] for r in keyed]
    res.seconds = time.monotonic() - t0
    return res


ROW_SQL = """
SELECT c.id, c.repo_id, c.hash, c.parents, c.parent_count, c.author_name, c.author_email,
       c.author_time, c.author_tz, c.committer_name, c.committer_email, c.commit_time, c.commit_tz,
       c.subject, c.message, c.first_ref, c.reachable, r.name AS repo_name, r.path AS repo_path
FROM commits c JOIN repos r ON r.id = c.repo_id
WHERE c.id IN ({})
"""


def fetch_rows(conn: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
    out: dict[int, sqlite3.Row] = {}
    for i in range(0, len(ids), 500):
        ch = ids[i : i + 500]
        for row in conn.execute(ROW_SQL.format(",".join("?" * len(ch))), ch):
            out[row["id"]] = row
    return out


def coauthors(conn: sqlite3.Connection, commit_id: int) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in conn.execute("SELECT name, email FROM coauthors WHERE commit_id=?", (commit_id,))]


def commit_files(conn: sqlite3.Connection, commit_id: int) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT p.path FROM commit_files cf JOIN paths p ON p.id = cf.path_id WHERE cf.commit_id=? ORDER BY p.path",
            (commit_id,),
        )
    ]


def author_suggestions(conn: sqlite3.Connection, prefix: str = "", limit: int = 50) -> list[str]:
    """Distinct author names and e-mails for autocompletion."""
    rows = conn.execute(
        """SELECT v, COUNT(*) AS n FROM (
               SELECT author_name AS v FROM commits UNION ALL SELECT author_email FROM commits
               UNION ALL SELECT name FROM coauthors UNION ALL SELECT email FROM coauthors)
           WHERE v != '' GROUP BY v ORDER BY n DESC LIMIT 5000"""
    ).fetchall()
    p = normalize(prefix)
    vals = [r[0] for r in rows if not p or p in normalize(r[0])]
    return vals[:limit]
