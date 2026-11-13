"""Incremental, ref-based indexing of repositories into SQLite.

Update algorithm for one repository (dates are never used to decide what is
new, so old-dated commits arriving via fetch are never missed):

1. Read the tracked refs (local branches, remote branches, tags, detached
   HEAD). If their fingerprint equals the stored one, the repo is skipped.
2. ``old`` = stored tips that still exist as objects, ``new`` = current tips.
3. New commits: ``git log new --not old`` → inserted (duplicates are ignored
   by the ``(repo_id, hash)`` unique key; previously unreachable commits that
   reappear are marked reachable again).
4. Commits that became unreachable (force-push, rebase, deleted branch):
   ``git rev-list old --not new`` → marked ``reachable = 0`` (kept, not
   deleted, unless the user disabled keeping them).
5. If some stored tips no longer exist (garbage collected), a full
   reachability pass is done instead of step 4.

All database writes go through a single :class:`Writer` holding a lock, in
batched transactions. Git work for different repos runs in parallel threads.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import db, gitcmd, gitrepo
from .fetcher import FetchResult, fetch_repo
from .scanner import FoundRepo
from .textnorm import normalize

BATCH = 2000
INDEX_SALT = "v1"


@dataclass
class IndexOptions:
    workers: int = 4
    include_tags: bool = True
    include_remotes: bool = True
    index_files: bool = False
    keep_unreachable: bool = True
    fetch: bool = False
    fetch_timeout: float = 60
    fetch_workers: int = 3
    force_full: bool = False


@dataclass
class RepoResult:
    repo_id: int
    name: str
    path: str
    status: str = "unchanged"  # updated | unchanged | error | missing | cancelled
    new_commits: int = 0
    unreachable: int = 0
    message: str = ""
    fetch: FetchResult | None = None
    seconds: float = 0.0


@dataclass
class IndexSummary:
    results: list[RepoResult] = field(default_factory=list)
    seconds: float = 0.0
    cancelled: bool = False

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def new_commits(self) -> int:
        return sum(r.new_commits for r in self.results)

    @property
    def fetch_problems(self) -> list[RepoResult]:
        return [r for r in self.results if r.fetch is not None and not r.fetch.ok]


ProgressFn = Callable[[int, int, str], None]


class Writer:
    """Serialises all writes to one connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.lock = threading.Lock()

    # -- repos -----------------------------------------------------------------
    def register(self, found: Iterable[FoundRepo]) -> list[sqlite3.Row]:
        """Insert/refresh repository rows; detect moved repositories."""
        now = int(time.time())
        found = list(found)
        with self.lock:
            c = self.conn
            known = {os.path.normcase(r["path"]): r for r in c.execute("SELECT * FROM repos")}
            missing = [r for r in known.values() if not os.path.exists(r["path"])]
            for r in missing:
                if r["status"] != "missing":
                    c.execute("UPDATE repos SET status='missing' WHERE id=?", (r["id"],))
            for f in found:
                path = os.path.normpath(f.path)
                name = os.path.basename(path.rstrip("/\\")) or path
                if f.is_bare and name.endswith(".git"):
                    name = name[:-4] or name
                row = known.get(os.path.normcase(path))
                if row is not None:
                    c.execute(
                        "UPDATE repos SET git_dir=?, is_bare=?, status=CASE WHEN status IN ('missing','inactive') THEN 'ok' ELSE status END WHERE id=?",
                        (f.git_dir, int(f.is_bare), row["id"]),
                    )
                    continue
                moved_from = None
                with_roots = [m for m in missing if m["root_commit"]]
                if with_roots:
                    # A moved repository still contains the root commit we saw
                    # before. One cat-file call answers that for all candidates.
                    try:
                        present = gitrepo.existing_objects(path, {m["root_commit"] for m in with_roots})
                    except (gitcmd.GitError, gitcmd.GitTimeout, OSError):
                        present = set()
                    cands = [m for m in with_roots if m["root_commit"] in present]
                    if len(cands) > 1:
                        url = gitrepo.remote_url(path)
                        if url:
                            cands = [m for m in cands if m["remote_url"] == url] or cands
                    if cands:
                        moved_from = cands[0]
                if moved_from is not None:
                    c.execute(
                        "UPDATE repos SET path=?, name=?, name_norm=?, git_dir=?, is_bare=?, status='ok' WHERE id=?",
                        (path, name, normalize(name + " " + path), f.git_dir, int(f.is_bare), moved_from["id"]),
                    )
                    missing = [m for m in missing if m["id"] != moved_from["id"]]
                else:
                    c.execute(
                        "INSERT INTO repos(path, name, name_norm, git_dir, is_bare, status, added_at) VALUES (?,?,?,?,?, 'new', ?)",
                        (path, name, normalize(name + " " + path), f.git_dir, int(f.is_bare), now),
                    )
            found_paths = {os.path.normcase(os.path.normpath(f.path)) for f in found}
            rows = c.execute("SELECT * FROM repos ORDER BY name COLLATE NOCASE").fetchall()
            return [r for r in rows if os.path.normcase(r["path"]) in found_paths]

    def mark_inactive_except(self, active_ids: set[int]) -> None:
        with self.lock:
            for (rid,) in self.conn.execute("SELECT id FROM repos WHERE status NOT IN ('missing','inactive')").fetchall():
                if rid not in active_ids:
                    self.conn.execute("UPDATE repos SET status='inactive' WHERE id=?", (rid,))

    def set_repo(self, repo_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE repos SET {cols} WHERE id=?", (*fields.values(), repo_id))

    def stored_refs(self, repo_id: int) -> list[gitrepo.Ref]:
        with self.lock:
            return [
                gitrepo.Ref(r["name"], r["kind"], r["target"])
                for r in self.conn.execute("SELECT name, kind, target FROM refs WHERE repo_id=?", (repo_id,))
            ]

    def save_refs(self, repo_id: int, refs: list[gitrepo.Ref]) -> None:
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                c.execute("DELETE FROM refs WHERE repo_id=?", (repo_id,))
                c.executemany(
                    "INSERT OR REPLACE INTO refs(repo_id, name, kind, target) VALUES (?,?,?,?)",
                    [(repo_id, r.name, r.kind, r.target) for r in refs],
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    # -- commits ---------------------------------------------------------------
    def write_commits(self, repo_id: int, batch: list[gitrepo.ParsedCommit]) -> list[str]:
        """Insert a batch; return hashes that were *newly* inserted."""
        if not batch:
            return []
        now = int(time.time())
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                hashes = [b.hash for b in batch]
                existing: dict[str, tuple[int, int]] = {}
                for ch in db.chunks(hashes, 500):
                    for row in c.execute(
                        f"SELECT id, hash, reachable FROM commits WHERE repo_id=? AND hash IN ({db.placeholders(len(ch))})",
                        (repo_id, *ch),
                    ):
                        existing[row[1]] = (row[0], row[2])
                revive = [(eid,) for eid, reach in existing.values() if not reach]
                if revive:
                    c.executemany("UPDATE commits SET reachable=1 WHERE id=?", revive)
                fresh = [b for b in batch if b.hash not in existing]
                seen: set[str] = set()
                fresh = [b for b in fresh if not (b.hash in seen or seen.add(b.hash))]
                if fresh:
                    c.executemany(
                        """INSERT OR IGNORE INTO commits(
                            repo_id, hash, parents, parent_count, author_name, author_email,
                            author_time, author_tz, author_hour, author_wday,
                            committer_name, committer_email, commit_time, commit_tz,
                            commit_hour, commit_wday, subject, message, people_norm,
                            first_ref, reachable, indexed_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                        [
                            (
                                repo_id, b.hash, b.parents, b.parent_count, b.author_name, b.author_email,
                                b.author_time, b.author_tz, b.author_hour, b.author_wday,
                                b.committer_name, b.committer_email, b.commit_time, b.commit_tz,
                                b.commit_hour, b.commit_wday, b.subject, b.message, b.people_norm,
                                b.first_ref, now,
                            )
                            for b in fresh
                        ],
                    )
                    ids: dict[str, int] = {}
                    for ch in db.chunks([b.hash for b in fresh], 500):
                        for row in c.execute(
                            f"SELECT id, hash FROM commits WHERE repo_id=? AND hash IN ({db.placeholders(len(ch))})",
                            (repo_id, *ch),
                        ):
                            ids[row[1]] = row[0]
                    c.executemany(
                        "INSERT INTO commits_fts(rowid, msg) VALUES (?, ?)",
                        [(ids[b.hash], b.msg_norm) for b in fresh if b.hash in ids],
                    )
                    co = [
                        (ids[b.hash], n, e)
                        for b in fresh
                        if b.hash in ids
                        for n, e in b.coauthors
                    ]
                    if co:
                        c.executemany("INSERT OR IGNORE INTO coauthors(commit_id, name, email) VALUES (?,?,?)", co)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return [b.hash for b in fresh]

    def mark_unreachable(self, repo_id: int, hashes: list[str], keep: bool) -> int:
        if not hashes:
            return 0
        n = 0
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                for ch in db.chunks(hashes, 500):
                    ph = db.placeholders(len(ch))
                    if keep:
                        cur = c.execute(
                            f"UPDATE commits SET reachable=0 WHERE repo_id=? AND reachable=1 AND hash IN ({ph})",
                            (repo_id, *ch),
                        )
                    else:
                        c.execute(
                            f"DELETE FROM commits_fts WHERE rowid IN (SELECT id FROM commits WHERE repo_id=? AND hash IN ({ph}))",
                            (repo_id, *ch),
                        )
                        cur = c.execute(f"DELETE FROM commits WHERE repo_id=? AND hash IN ({ph})", (repo_id, *ch))
                    n += cur.rowcount
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return n

    def reset_reachability(self, repo_id: int, reachable: set[str], keep: bool) -> int:
        """Full pass: everything not in *reachable* becomes unreachable."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT hash FROM commits WHERE repo_id=? AND reachable=1", (repo_id,)
            ).fetchall()
        gone = [r[0] for r in rows if r[0] not in reachable]
        return self.mark_unreachable(repo_id, gone, keep)

    def repo_hashes(self, repo_id: int, reachable_only: bool = False) -> list[str]:
        sql = "SELECT hash FROM commits WHERE repo_id=?" + (" AND reachable=1" if reachable_only else "")
        with self.lock:
            return [r[0] for r in self.conn.execute(sql, (repo_id,))]

    def write_files(self, repo_id: int, items: list[tuple[str, list[str]]]) -> None:
        if not items:
            return
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                all_paths = sorted({p for _, files in items for p in files})
                c.executemany(
                    "INSERT OR IGNORE INTO paths(path, path_norm) VALUES (?, ?)",
                    [(p, normalize(p)) for p in all_paths],
                )
                pid: dict[str, int] = {}
                for ch in db.chunks(all_paths, 500):
                    for row in c.execute(f"SELECT id, path FROM paths WHERE path IN ({db.placeholders(len(ch))})", ch):
                        pid[row[1]] = row[0]
                hashes = [h for h, _ in items]
                cid: dict[str, int] = {}
                for ch in db.chunks(hashes, 500):
                    for row in c.execute(
                        f"SELECT id, hash FROM commits WHERE repo_id=? AND hash IN ({db.placeholders(len(ch))})",
                        (repo_id, *ch),
                    ):
                        cid[row[1]] = row[0]
                c.executemany(
                    "INSERT OR IGNORE INTO commit_files(commit_id, path_id) VALUES (?, ?)",
                    [(cid[h], pid[p]) for h, files in items if h in cid for p in files if p in pid],
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def finish_repo(self, repo_id: int) -> None:
        with self.lock:
            c = self.conn
            count = c.execute("SELECT COUNT(*) FROM commits WHERE repo_id=? AND reachable=1", (repo_id,)).fetchone()[0]
            root = c.execute(
                "SELECT hash FROM commits WHERE repo_id=? AND parent_count=0 ORDER BY hash LIMIT 1", (repo_id,)
            ).fetchone()
            c.execute(
                "UPDATE repos SET commit_count=?, root_commit=COALESCE(?, root_commit), last_indexed_at=? WHERE id=?",
                (count, root[0] if root else None, int(time.time()), repo_id),
            )


def _index_one(
    writer: Writer,
    repo: sqlite3.Row,
    opts: IndexOptions,
    cancel: threading.Event,
    fetch_sem: threading.Semaphore,
) -> RepoResult:
    t0 = time.monotonic()
    rid, path = repo["id"], repo["path"]
    res = RepoResult(rid, repo["name"], path)
    if not os.path.exists(path):
        res.status = "missing"
        res.message = "path not found"
        writer.set_repo(rid, status="missing")
        return res
    try:
        if opts.fetch and gitrepo.has_remotes(path):
            with fetch_sem:
                if cancel.is_set():
                    res.status = "cancelled"
                    return res
                res.fetch = fetch_repo(path, timeout=opts.fetch_timeout)

        refs = gitrepo.list_refs(path, include_tags=opts.include_tags, include_remotes=opts.include_remotes)
        salt = f"{INDEX_SALT}|t{int(opts.include_tags)}|r{int(opts.include_remotes)}"
        fp = gitrepo.fingerprint(refs, salt)
        need_files = opts.index_files and not repo["files_indexed"]
        if not opts.force_full and fp == repo["refs_fingerprint"] and not need_files and repo["status"] == "ok":
            res.status = "unchanged"
            res.seconds = time.monotonic() - t0
            return res

        old_refs = [] if opts.force_full else writer.stored_refs(rid)
        old_tips = {r.target for r in old_refs}
        new_tips = {r.target for r in refs}
        alive_old = gitrepo.existing_objects(path, old_tips) if old_tips else set()
        lost_tips = old_tips - alive_old

        include = [r.name for r in refs]
        # Use tip hashes, not names, for negatives: refs may have moved.
        exclude = sorted(alive_old)
        batch: list[gitrepo.ParsedCommit] = []
        new_hashes: list[str] = []
        for commit in gitrepo.log_commits(path, include, exclude, cancel=cancel):
            batch.append(commit)
            if len(batch) >= BATCH:
                new_hashes += writer.write_commits(rid, batch)
                batch = []
            if cancel.is_set():
                break
        new_hashes += writer.write_commits(rid, batch)
        res.new_commits = len(new_hashes)
        if cancel.is_set():
            res.status = "cancelled"
            return res

        # Reachability bookkeeping. A cancelled rev-list stops early without an
        # error, so the (partial) result must never be written.
        if opts.force_full or lost_tips:
            reachable = set(gitrepo.rev_list(path, sorted(new_tips), cancel=cancel))
            if cancel.is_set():
                res.status = "cancelled"
                return res
            res.unreachable = writer.reset_reachability(rid, reachable, opts.keep_unreachable)
        elif alive_old - new_tips:
            gone = list(gitrepo.rev_list(path, sorted(alive_old - new_tips), sorted(new_tips), cancel=cancel))
            if cancel.is_set():
                res.status = "cancelled"
                return res
            res.unreachable = writer.mark_unreachable(rid, gone, opts.keep_unreachable)

        if opts.index_files:
            targets = writer.repo_hashes(rid, reachable_only=True) if need_files else new_hashes
            items: list[tuple[str, list[str]]] = []
            for h, files in gitrepo.changed_files(path, targets, cancel=cancel):
                items.append((h, files))
                if len(items) >= BATCH:
                    writer.write_files(rid, items)
                    items = []
            writer.write_files(rid, items)
            if cancel.is_set():
                res.status = "cancelled"
                return res

        writer.save_refs(rid, refs)
        writer.set_repo(
            rid,
            refs_fingerprint=fp,
            status="ok",
            last_error=None,
            files_indexed=int(opts.index_files),
            remote_url=gitrepo.remote_url(path) or None,
        )
        writer.finish_repo(rid)
        res.status = "updated" if (res.new_commits or res.unreachable or repo["status"] != "ok") else "unchanged"
    except gitcmd.GitNotFoundError:
        raise
    except (gitcmd.GitError, gitcmd.GitTimeout, OSError, UnicodeError) as exc:
        res.status = "error"
        res.message = str(exc)
        writer.set_repo(rid, status="error", last_error=str(exc)[:2000])
    res.seconds = time.monotonic() - t0
    return res


def index_repos(
    writer: Writer,
    repos: list[sqlite3.Row],
    opts: IndexOptions,
    cancel: threading.Event | None = None,
    progress: ProgressFn | None = None,
) -> IndexSummary:
    """Index the given repositories in parallel and return a summary."""
    gitcmd.find_git()  # fail early with a clear error
    cancel = cancel or threading.Event()
    summary = IndexSummary()
    t0 = time.monotonic()
    total = len(repos)
    fetch_sem = threading.Semaphore(max(1, opts.fetch_workers))
    workers = max(1, min(opts.workers, 32))
    done = 0
    if progress:
        progress(0, total, "")
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="comitra-index") as pool:
        futures = {pool.submit(_index_one, writer, r, opts, cancel, fetch_sem): r for r in repos}
        for fut in as_completed(futures):
            repo = futures[fut]
            try:
                res = fut.result()
            except gitcmd.GitNotFoundError:
                cancel.set()
                raise
            except Exception as exc:  # never let one repo kill the run
                res = RepoResult(repo["id"], repo["name"], repo["path"], status="error", message=repr(exc))
            summary.results.append(res)
            done += 1
            if progress:
                progress(done, total, repo["name"])
    summary.results.sort(key=lambda r: (r.status != "error", r.name.lower()))
    summary.cancelled = cancel.is_set()
    summary.seconds = time.monotonic() - t0
    return summary
