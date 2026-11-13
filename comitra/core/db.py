"""SQLite storage: connection setup, schema and migrations.

Design notes (see docs/DESIGN.md):

* Branch membership is **not** stored per commit. A commit is reachable from
  every branch that descends from it, so a per-branch table explodes and goes
  stale on fast-forward merges. Instead the tracked refs and their tips are
  stored (``refs``), each commit stores the ref it was first discovered from
  (``first_ref``) and whether any tracked ref still reaches it
  (``reachable``). Branch filters are resolved against git at query time.
* Both author and committer dates are stored as UTC epoch seconds plus the
  original UTC offset in minutes, together with pre-computed local hour and
  weekday in the commit's own time zone.
* ``commits_fts`` holds the *normalised* message (see textnorm); its rowid is
  ``commits.id``.
* The schema version lives in ``PRAGMA user_version``; migrations run in
  order on connect.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Iterable, Sequence

FTS_TOKENIZE = "unicode61 remove_diacritics 0 tokenchars '_'"

SCHEMA_V1 = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS repos (
    id               INTEGER PRIMARY KEY,
    path             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    name_norm        TEXT NOT NULL,
    git_dir          TEXT,
    is_bare          INTEGER NOT NULL DEFAULT 0,
    root_commit      TEXT,
    remote_url       TEXT,
    status           TEXT NOT NULL DEFAULT 'new',
    last_error       TEXT,
    refs_fingerprint TEXT,
    files_indexed    INTEGER NOT NULL DEFAULT 0,
    added_at         INTEGER,
    last_indexed_at  INTEGER,
    commit_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS refs (
    repo_id  INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    target   TEXT NOT NULL,
    PRIMARY KEY (repo_id, name)
);

CREATE TABLE IF NOT EXISTS commits (
    id              INTEGER PRIMARY KEY,
    repo_id         INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    hash            TEXT NOT NULL,
    parents         TEXT NOT NULL DEFAULT '',
    parent_count    INTEGER NOT NULL DEFAULT 0,
    author_name     TEXT NOT NULL DEFAULT '',
    author_email    TEXT NOT NULL DEFAULT '',
    author_time     INTEGER NOT NULL DEFAULT 0,
    author_tz       INTEGER NOT NULL DEFAULT 0,
    author_hour     INTEGER NOT NULL DEFAULT 0,
    author_wday     INTEGER NOT NULL DEFAULT 0,
    committer_name  TEXT NOT NULL DEFAULT '',
    committer_email TEXT NOT NULL DEFAULT '',
    commit_time     INTEGER NOT NULL DEFAULT 0,
    commit_tz       INTEGER NOT NULL DEFAULT 0,
    commit_hour     INTEGER NOT NULL DEFAULT 0,
    commit_wday     INTEGER NOT NULL DEFAULT 0,
    subject         TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    people_norm     TEXT NOT NULL DEFAULT '',
    first_ref       TEXT NOT NULL DEFAULT '',
    reachable       INTEGER NOT NULL DEFAULT 1,
    indexed_at      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (repo_id, hash)
);
CREATE INDEX IF NOT EXISTS ix_commits_author_time ON commits(author_time);
CREATE INDEX IF NOT EXISTS ix_commits_commit_time ON commits(commit_time);
CREATE INDEX IF NOT EXISTS ix_commits_hash ON commits(hash);
CREATE INDEX IF NOT EXISTS ix_commits_repo_time ON commits(repo_id, author_time);

CREATE TABLE IF NOT EXISTS coauthors (
    commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    email     TEXT NOT NULL,
    PRIMARY KEY (commit_id, email, name)
);
CREATE INDEX IF NOT EXISTS ix_coauthors_email ON coauthors(email);

CREATE TABLE IF NOT EXISTS paths (
    id        INTEGER PRIMARY KEY,
    path      TEXT NOT NULL UNIQUE,
    path_norm TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commit_files (
    commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
    path_id   INTEGER NOT NULL REFERENCES paths(id),
    PRIMARY KEY (commit_id, path_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_commit_files_path ON commit_files(path_id);

CREATE VIRTUAL TABLE IF NOT EXISTS commits_fts USING fts5(
    msg,
    tokenize = "{FTS_TOKENIZE}"
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    query      TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS recent_searches (
    query   TEXT PRIMARY KEY,
    used_at INTEGER NOT NULL
);
"""

MIGRATIONS: list[str] = [SCHEMA_V1]
SCHEMA_VERSION = len(MIGRATIONS)

_init_lock = threading.Lock()


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    """Open the database, enable WAL and run pending migrations."""
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -32000")
    if not readonly:
        migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    with _init_lock:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{version} is newer than this Comitra build (v{SCHEMA_VERSION})."
            )
        for i in range(version, SCHEMA_VERSION):
            conn.execute("BEGIN")
            try:
                for stmt in _split_sql(MIGRATIONS[i]):
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {i + 1}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise


def _split_sql(script: str) -> list[str]:
    stmts: list[str] = []
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                stmts.append(buf.strip())
            buf = ""
    if buf.strip():
        stmts.append(buf.strip())
    return stmts


def chunks(seq: Sequence, size: int = 500) -> Iterable[Sequence]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def placeholders(n: int) -> str:
    return ",".join("?" * n)


def delete_repo(conn: sqlite3.Connection, repo_id: int) -> None:
    conn.execute("BEGIN")
    try:
        conn.execute(
            "DELETE FROM commits_fts WHERE rowid IN (SELECT id FROM commits WHERE repo_id = ?)",
            (repo_id,),
        )
        conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM paths WHERE id NOT IN (SELECT DISTINCT path_id FROM commit_files)")
    conn.execute("INSERT INTO commits_fts(commits_fts) VALUES('optimize')")
    conn.execute("VACUUM")
