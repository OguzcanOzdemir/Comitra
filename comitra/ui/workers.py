"""Background workers so that indexing and searching never freeze the UI.

Every worker thread uses its own SQLite connection (WAL mode allows readers
while the indexer writes).
"""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

from .. import config
from ..core import db, gitcmd, gitrepo, query, search, service, stats


class IndexThread(QThread):
    progress = Signal(str, int, int, str)
    done = Signal(object, str)  # UpdateReport | None, error code/message

    def __init__(self, settings, mode: str = "scan", force_full: bool = False, fetch: bool | None = None,
                 repo_ids: set[int] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.mode = mode
        self.force_full = force_full
        self.fetch = fetch
        self.repo_ids = repo_ids
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        conn = None
        try:
            conn = db.connect(config.db_path())
            cb = lambda p, d, t, c: self.progress.emit(p, d, t, c)  # noqa: E731
            if self.mode == "known":
                rep = service.update_known_repos(conn, self.settings, self.repo_ids, self.force_full, self.fetch,
                                                 self.cancel_event, cb)
            else:
                rep = service.update_index(conn, self.settings, self.force_full, self.fetch, None,
                                           self.cancel_event, cb)
            self.done.emit(rep, "")
        except gitcmd.GitNotFoundError:
            self.done.emit(None, "git-not-found")
        except Exception as exc:  # pragma: no cover - reported to the user
            traceback.print_exc()
            self.done.emit(None, f"{type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()


class SearchWorker(QObject):
    """Lives in its own thread; runs one search at a time, newest wins."""

    result = Signal(int, object, str)  # generation, SearchResult, query string
    request = Signal(int, str, object)  # generation, query string, SearchOptions

    def __init__(self):
        super().__init__()
        self._conn = None
        self._latest = 0
        self._lock = threading.Lock()
        self.resolver = search.BranchResolver()
        self.request.connect(self._run)

    def bump(self, gen: int) -> None:
        with self._lock:
            self._latest = gen

    @Slot(int, str, object)
    def _run(self, gen: int, text: str, opts) -> None:
        with self._lock:
            if gen < self._latest:
                return  # a newer request is already queued
        if self._conn is None:
            self._conn = db.connect(config.db_path())
        q, show_unreachable = opts["query"], opts["show_unreachable"]
        if show_unreachable and q.unreachable == "hide":
            q = q.copy()
            q.unreachable = "include"
        try:
            res = search.search(self._conn, q, opts["search"], self.resolver)
        except Exception as exc:  # pragma: no cover
            res = search.SearchResult(warnings=[f"{type(exc).__name__}: {exc}"])
        self.result.emit(gen, res, text)

    @Slot()
    def clear_cache(self) -> None:
        self.resolver.clear()


class SearchThread(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = SearchWorker()
        self.worker.moveToThread(self)


class _Signals(QObject):
    done = Signal(object, object)  # key, payload
    failed = Signal(object, str)


class Task(QRunnable):
    """Run a callable in the global thread pool and report back by signal."""

    def __init__(self, key, fn, *args):
        super().__init__()
        self.key = key
        self.fn = fn
        self.args = args
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            out = self.fn(*self.args)
        except Exception as exc:
            self.signals.failed.emit(self.key, str(exc))
            return
        self.signals.done.emit(self.key, out)


def load_diff(path: str, h: str) -> str:
    return gitrepo.show_commit(path, h)


def load_containing(path: str, h: str) -> list[str]:
    return gitrepo.branches_containing(path, h)


def compute_stats(ids):
    conn = db.connect(config.db_path())
    try:
        return stats.compute(conn, ids)
    finally:
        conn.close()


def export_results(fmt: str, ids: list[int], path: str) -> int:
    from ..core import export

    conn = db.connect(config.db_path())
    try:
        if fmt == "json":
            return export.export_json(conn, ids, path)
        return export.export_csv(conn, ids, path)
    finally:
        conn.close()


def ref_stamps(repos: list[tuple[int, str]]) -> dict[int, str]:
    """Compute cheap ref fingerprints for (repo id, git dir) pairs."""
    out: dict[int, str] = {}
    for rid, git_dir in repos:
        st = gitrepo.ref_stamp(git_dir)
        if st is not None:
            out[rid] = st
    return out


def author_suggestions() -> list[str]:
    conn = db.connect(config.db_path())
    try:
        return search.author_suggestions(conn, "", 5000)
    finally:
        conn.close()


__all__ = ["IndexThread", "SearchThread", "Task", "query"]
