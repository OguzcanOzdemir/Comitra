"""Command line interface.

    comitra                      start the GUI
    comitra gui                  start the GUI
    comitra add PATH...          add root folders to scan
    comitra remove PATH...       remove root folders
    comitra roots                list root folders
    comitra update [--fetch] [--full]   scan folders and update the index
    comitra search QUERY [--limit N] [--format table|json|csv] [--group repo|author|day]
    comitra repos                list indexed repositories
    comitra stats                show statistics
    comitra info                 show data locations and versions

Global options: --portable, --data-dir DIR
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
from datetime import datetime

from . import APP_NAME, __version__, config


def _conn():
    from .core import db

    return db.connect(config.db_path())


def _fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "?"


def cmd_add(args, s: config.Settings) -> int:
    for p in args.paths:
        ap = os.path.abspath(os.path.expanduser(p))
        if not os.path.isdir(ap):
            print(f"not a folder: {ap}", file=sys.stderr)
            continue
        if ap not in s.roots:
            s.roots.append(ap)
            print(f"added: {ap}")
    s.save()
    return 0


def cmd_remove(args, s: config.Settings) -> int:
    for p in args.paths:
        ap = os.path.abspath(os.path.expanduser(p))
        if ap in s.roots:
            s.roots.remove(ap)
            print(f"removed: {ap}")
    s.save()
    return 0


def cmd_roots(args, s: config.Settings) -> int:
    for r in s.roots:
        print(r)
    if not s.roots:
        print("(no folders configured; use: comitra add PATH)")
    return 0


def cmd_update(args, s: config.Settings) -> int:
    from .core import gitcmd, service

    if not s.roots:
        print("No folders configured. Use: comitra add PATH", file=sys.stderr)
        return 2
    conn = _conn()
    cancel = threading.Event()
    last = {"line": ""}

    def progress(phase, done, total, cur):
        if not sys.stderr.isatty():
            return
        line = f"\r{phase}: {done}/{total} {cur}"[:100] if phase == "index" else f"\rscanning… {cur}"[:100]
        sys.stderr.write(line.ljust(len(last["line"])))
        sys.stderr.flush()
        last["line"] = line

    try:
        rep = service.update_index(conn, s, force_full=args.full, fetch=True if args.fetch else None,
                                   cancel=cancel, progress=progress)
    except gitcmd.GitNotFoundError:
        print("\ngit was not found. Install git (https://git-scm.com) or set its path in settings.", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        cancel.set()
        print("\ncancelled", file=sys.stderr)
        return 130
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 100 + "\r")
    sm = rep.summary
    print(
        f"{len(sm.results)} repositories in {sm.seconds:.1f}s: {sm.count('updated')} updated, "
        f"{sm.count('unchanged')} unchanged, {sm.count('error')} errors, {sm.count('missing')} missing; "
        f"{sm.new_commits} new commits"
    )
    for r in sm.results:
        if r.status in ("error", "missing"):
            print(f"  [{r.status}] {r.path}: {r.message}")
        if r.fetch is not None and not r.fetch.ok:
            print(f"  [fetch {r.fetch.reason}] {r.path}: {r.fetch.message.splitlines()[0] if r.fetch.message else ''}")
    for path, err in rep.scan.errors:
        print(f"  [scan] {path}: {err}")
    return 0 if not sm.count("error") else 1


def cmd_search(args, s: config.Settings) -> int:
    from .core import export, query, search

    conn = _conn()
    q = query.parse(" ".join(args.query))
    if s.show_unreachable and q.unreachable == "hide":
        q.unreachable = "include"
    res = search.search(conn, q, search.SearchOptions(date_basis=s.date_basis, group_by=args.group, limit=args.limit))
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.format == "json":
        recs = list(export._records(conn, res.ids, None))
        json.dump(recs, sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif args.format == "csv":
        w = csv.DictWriter(sys.stdout, fieldnames=export.FIELDS)
        w.writeheader()
        for rec in export._records(conn, res.ids, None):
            w.writerow(rec)
    else:
        rows = search.fetch_rows(conn, res.ids)
        last_group = object()
        for i, cid in enumerate(res.ids):
            r = rows[cid]
            if res.groups is not None and res.groups[i] != last_group:
                last_group = res.groups[i]
                label = r["repo_name"] if args.group == "repo" else last_group
                print(f"\n== {label} ==")
            t = r["author_time"] if s.date_basis == "author" else r["commit_time"]
            print(f"{r['hash'][:10]}  {_fmt_time(t)}  {r['repo_name'][:20]:20}  {r['author_name'][:20]:20}  {r['subject']}")
        print(f"\n{len(res.ids)} result(s){' (truncated)' if res.truncated else ''} in {res.seconds * 1000:.0f} ms",
              file=sys.stderr)
    return 0


def cmd_repos(args, s: config.Settings) -> int:
    conn = _conn()
    for r in conn.execute("SELECT * FROM repos ORDER BY name COLLATE NOCASE"):
        last = _fmt_time(r["last_indexed_at"]) if r["last_indexed_at"] else "never"
        print(f"{r['name'][:30]:30} {r['commit_count']:>8}  {r['status']:8} {last:16}  {r['path']}")
    return 0


def cmd_stats(args, s: config.Settings) -> int:
    from .core import stats

    st = stats.compute(_conn(), top=args.top)
    print(f"commits: {st.total_commits}  repos: {st.total_repos}  authors: {st.total_authors}  "
          f"not on any branch: {st.unreachable}")
    if st.first_time:
        print(f"range: {_fmt_time(st.first_time)} – {_fmt_time(st.last_time)}")
    print("\nTop repositories:")
    for name, n in st.by_repo:
        print(f"  {n:>8}  {name}")
    print("\nTop authors:")
    for name, email, n in st.by_author:
        print(f"  {n:>8}  {name} <{email}>")
    return 0


def cmd_info(args, s: config.Settings) -> int:
    from .core import gitcmd

    gitcmd.set_git_path(s.git_path or None)
    print(f"{APP_NAME} {__version__}")
    print(f"portable:  {config.is_portable()}")
    print(f"settings:  {config.settings_path()}")
    print(f"database:  {config.db_path()}")
    print(f"git:       {gitcmd.git_version() or 'NOT FOUND'}")
    import sqlite3

    print(f"sqlite:    {sqlite3.sqlite_version}")
    return 0


def cmd_gui(args, s: config.Settings) -> int:
    from .ui.app import run_gui

    return run_gui()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="comitra", description="Search commits across all local git repositories.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    p.add_argument("--portable", action="store_true", help="store settings and data next to the application")
    p.add_argument("--data-dir", help="store settings and data in this folder")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="start the graphical interface")
    a = sub.add_parser("add", help="add root folders to scan")
    a.add_argument("paths", nargs="+")
    rm = sub.add_parser("remove", help="remove root folders")
    rm.add_argument("paths", nargs="+")
    sub.add_parser("roots", help="list root folders")
    u = sub.add_parser("update", help="scan folders and update the index")
    u.add_argument("--fetch", action="store_true", help="run 'git fetch --all' before indexing")
    u.add_argument("--full", action="store_true", help="re-check every repository from scratch")
    se = sub.add_parser("search", help="search commits")
    se.add_argument("query", nargs="*")
    se.add_argument("--limit", type=int, default=50)
    se.add_argument("--format", choices=["table", "json", "csv"], default="table")
    se.add_argument("--group", choices=["repo", "author", "day"])
    sub.add_parser("repos", help="list indexed repositories")
    st = sub.add_parser("stats", help="show statistics")
    st.add_argument("--top", type=int, default=15)
    sub.add_parser("info", help="show data locations and versions")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # macOS passes -psn_* when launched from Finder.
    argv = [a for a in argv if not a.startswith("-psn_")]
    # Windowed builds have no console streams; keep print() from crashing.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ["COMITRA_HOME"] = os.path.abspath(args.data_dir)
    if args.portable:
        config.force_portable(True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    s = config.Settings.load()
    handlers = {
        None: cmd_gui, "gui": cmd_gui, "add": cmd_add, "remove": cmd_remove, "roots": cmd_roots,
        "update": cmd_update, "search": cmd_search, "repos": cmd_repos, "stats": cmd_stats, "info": cmd_info,
    }
    return handlers[args.cmd](args, s)
