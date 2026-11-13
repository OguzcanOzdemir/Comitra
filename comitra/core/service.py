"""High-level operations shared by the CLI and the GUI."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable

from . import gitcmd, indexer, scanner


@dataclass
class UpdateReport:
    scan: scanner.ScanReport
    summary: indexer.IndexSummary


PhaseFn = Callable[[str, int, int, str], None]  # phase, done, total, current


def update_index(
    conn: sqlite3.Connection,
    settings,
    force_full: bool = False,
    fetch: bool | None = None,
    only_repo_ids: set[int] | None = None,
    cancel: threading.Event | None = None,
    progress: PhaseFn | None = None,
) -> UpdateReport:
    """Scan the configured roots, register repos and index them."""
    gitcmd.set_git_path(settings.git_path or None)
    gitcmd.find_git()
    cancel = cancel or threading.Event()
    writer = indexer.Writer(conn)

    if progress:
        progress("scan", 0, 0, "")
    report = scanner.scan(
        settings.scan_roots(),
        excludes=settings.exclude_names,
        excluded_paths=settings.excluded_paths,
        max_depth=settings.max_depth,
        follow_symlinks=settings.follow_symlinks,
        include_bare=settings.include_bare,
        skip_hidden=settings.skip_hidden,
        cancel=cancel,
        progress=(lambda cur: progress("scan", 0, 0, cur)) if progress else None,
    )
    repos = writer.register(report.repos)
    if only_repo_ids is None and not cancel.is_set():
        writer.mark_inactive_except({r["id"] for r in repos})
    if only_repo_ids is not None:
        repos = [r for r in repos if r["id"] in only_repo_ids]

    opts = settings.index_options(force_full=force_full, fetch=fetch)
    summary = indexer.index_repos(
        writer,
        repos,
        opts,
        cancel=cancel,
        progress=(lambda d, t, cur: progress("index", d, t, cur)) if progress else None,
    )
    return UpdateReport(report, summary)


def update_known_repos(
    conn: sqlite3.Connection,
    settings,
    repo_ids: set[int] | None = None,
    force_full: bool = False,
    fetch: bool | None = None,
    cancel: threading.Event | None = None,
    progress: PhaseFn | None = None,
) -> UpdateReport:
    """Re-index already known repositories without scanning folders."""
    gitcmd.set_git_path(settings.git_path or None)
    gitcmd.find_git()
    writer = indexer.Writer(conn)
    rows = conn.execute("SELECT * FROM repos WHERE status != 'inactive'").fetchall()
    if repo_ids is not None:
        rows = [r for r in rows if r["id"] in repo_ids]
    opts = settings.index_options(force_full=force_full, fetch=fetch)
    summary = indexer.index_repos(
        writer,
        rows,
        opts,
        cancel=cancel,
        progress=(lambda d, t, cur: progress("index", d, t, cur)) if progress else None,
    )
    return UpdateReport(scanner.ScanReport(), summary)
