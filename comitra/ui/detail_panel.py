"""Commit detail panel: metadata, branches containing the commit, diff."""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ..core import search
from ..core.textnorm import highlight_html
from . import theme
from .results_model import fmt_time
from .workers import Task, load_containing, load_diff


class DiffHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        dark = theme.is_dark()
        fmt = QTextCharFormat()
        if text.startswith("+") and not text.startswith("+++"):
            fmt.setForeground(QColor("#7ee787" if dark else "#116329"))
        elif text.startswith("-") and not text.startswith("---"):
            fmt.setForeground(QColor("#ff7b72" if dark else "#a40e26"))
        elif text.startswith("@@"):
            fmt.setForeground(QColor("#79c0ff" if dark else "#0550ae"))
        elif text.startswith(("diff --git", "+++", "---", "index ")):
            fmt.setFontWeight(QFont.Bold)
        else:
            return
        self.setFormat(0, len(text), fmt)


class DetailPanel(QWidget):
    action = Signal(str, str)        # action name, repo path
    copy_requested = Signal(str)     # text

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.row = None
        self.terms: list[tuple[str, bool]] = []
        self.date_basis = "author"
        self._tasks: set = set()
        self._containing: list[str] | None = None
        self._diff_loaded_for: int | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        self.btn_copy = QPushButton("Copy hash")
        self.btn_copy_msg = QPushButton("Copy message")
        self.btn_folder = QPushButton("Open folder")
        self.btn_term = QPushButton("Open terminal")
        self.btn_editor = QPushButton("Open in editor")
        for b in (self.btn_copy, self.btn_copy_msg, self.btn_folder, self.btn_term, self.btn_editor):
            b.setEnabled(False)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.btn_copy.clicked.connect(lambda: self.row and self.copy_requested.emit(self.row["hash"]))
        self.btn_copy_msg.clicked.connect(lambda: self.row and self.copy_requested.emit(self.row["message"]))
        self.btn_folder.clicked.connect(lambda: self.row and self.action.emit("folder", self.row["repo_path"]))
        self.btn_term.clicked.connect(lambda: self.row and self.action.emit("terminal", self.row["repo_path"]))
        self.btn_editor.clicked.connect(lambda: self.row and self.action.emit("editor", self.row["repo_path"]))

        self.tabs = QTabWidget()
        self.info = QTextBrowser()
        self.info.setOpenLinks(False)
        self.info.setOpenExternalLinks(False)
        self.diff = QPlainTextEdit(readOnly=True)
        self.diff.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        self.diff.setFont(mono)
        self._hl = DiffHighlighter(self.diff.document())
        self.tabs.addTab(self.info, "Details")
        self.tabs.addTab(self.diff, "Diff")
        self.tabs.currentChanged.connect(self._maybe_load_diff)
        lay.addWidget(self.tabs)
        self.show_empty()

    def show_empty(self) -> None:
        self.row = None
        for b in (self.btn_copy, self.btn_copy_msg, self.btn_folder, self.btn_term, self.btn_editor):
            b.setEnabled(False)
        self.info.setHtml(f"<p style='color:{theme.muted_color()}'>{html.escape('Select a commit to see its details.')}</p>")
        self.diff.setPlainText("")

    def show_commit(self, commit_id: int, terms, date_basis: str) -> None:
        rows = search.fetch_rows(self.conn, [commit_id])
        row = rows.get(commit_id)
        if row is None:
            self.show_empty()
            return
        self.row = row
        self.terms = terms
        self.date_basis = date_basis
        self._containing = None
        self._diff_loaded_for = None
        exists = os.path.isdir(row["repo_path"])
        self.btn_copy.setEnabled(True)
        self.btn_copy_msg.setEnabled(True)
        for b in (self.btn_folder, self.btn_term, self.btn_editor):
            b.setEnabled(exists)
        self._render()
        self.diff.setPlainText("")
        if exists:
            self._start(("contains", commit_id), load_containing, row["repo_path"], row["hash"])
        self._maybe_load_diff()

    # -- rendering -----------------------------------------------------------------
    def _render(self) -> None:
        r = self.row
        if r is None:
            return
        muted = theme.muted_color()
        bg, fg = theme.match_colors()
        msg_html = highlight_html(r["message"], self.terms, f'<span style="background-color:{bg};color:{fg};">', "</span>")
        msg_html = msg_html.replace("\n", "<br>")
        co = search.coauthors(self.conn, r["id"])
        files = search.commit_files(self.conn, r["id"])

        def row_(label, value):
            return (f"<tr><td style='color:{muted};padding-right:12px;white-space:nowrap;vertical-align:top'>"
                    f"{html.escape(label)}</td><td>{value}</td></tr>")

        parts = [f"<div style='font-size:110%;margin-bottom:8px'>{msg_html}</div>"]
        if not r["reachable"]:
            parts.append(f"<p style='color:#d29922'>⚠ {html.escape('This commit is no longer reachable from any branch (force-push, rebase or deleted branch).')}</p>")
        parts.append("<table cellspacing='0' cellpadding='2'>")
        parts.append(row_("Hash", f"<code>{r['hash']}</code>"))
        parts.append(row_("Repository", f"{html.escape(r['repo_name'])} <span style='color:{muted}'>{html.escape(r['repo_path'])}</span>"))
        parts.append(row_("Author", html.escape(f"{r['author_name']} <{r['author_email']}>")))
        parts.append(row_("Author date", fmt_time(r["author_time"], r["author_tz"], True)))
        if (r["committer_email"], r["committer_name"]) != (r["author_email"], r["author_name"]):
            parts.append(row_("Committer", html.escape(f"{r['committer_name']} <{r['committer_email']}>")))
        if r["commit_time"] != r["author_time"]:
            parts.append(row_("Commit date", fmt_time(r["commit_time"], r["commit_tz"], True)))
        if co:
            parts.append(row_("Co-authors", "<br>".join(html.escape(f"{n} <{e}>") for n, e in co)))
        if r["parents"]:
            parts.append(row_("Parents", " ".join(f"<code>{p[:10]}</code>" for p in r["parents"].split())))
        parts.append(row_("Found via", html.escape(r["first_ref"] or "—")))
        if self._containing is None:
            cont = f"<span style='color:{muted}'>{html.escape('Loading…')}</span>" if os.path.isdir(r["repo_path"]) else \
                f"<span style='color:{muted}'>{html.escape('Repository folder is not available.')}</span>"
        else:
            shown = self._containing[:60]
            cont = ", ".join(html.escape(b) for b in shown) or "—"
            if len(self._containing) > 60:
                cont += f" … (+{len(self._containing) - 60})"
        parts.append(row_("Contained in", cont))
        parts.append("</table>")
        if files:
            items = "".join(f"<li><code>{html.escape(f)}</code></li>" for f in files[:500])
            more = f"<li>… (+{len(files) - 500})</li>" if len(files) > 500 else ""
            parts.append(f"<p style='margin-top:10px'><b>{html.escape('Changed files')}</b> ({len(files)})</p><ul>{items}{more}</ul>")
        self.info.setHtml("".join(parts))

    # -- async loading -------------------------------------------------------------
    def _start(self, key, fn, *args) -> None:
        t = Task(key, fn, *args)
        t.signals.done.connect(self._on_done)
        t.signals.failed.connect(self._on_failed)
        self._tasks.add(t)
        t.signals.done.connect(lambda *_: self._tasks.discard(t))
        t.signals.failed.connect(lambda *_: self._tasks.discard(t))
        QThreadPool.globalInstance().start(t)

    def _maybe_load_diff(self, *_):
        r = self.row
        if r is None or self.tabs.currentWidget() is not self.diff or self._diff_loaded_for == r["id"]:
            return
        self._diff_loaded_for = r["id"]
        if not os.path.isdir(r["repo_path"]):
            self.diff.setPlainText("Repository folder is not available.")
            return
        self.diff.setPlainText("Loading…")
        self._start(("diff", r["id"]), load_diff, r["repo_path"], r["hash"])

    def _on_done(self, key, payload) -> None:
        kind, cid = key
        if self.row is None or self.row["id"] != cid:
            return
        if kind == "contains":
            self._containing = payload
            self._render()
        elif kind == "diff":
            self.diff.setPlainText(payload or "")

    def _on_failed(self, key, err: str) -> None:
        kind, cid = key
        if self.row is None or self.row["id"] != cid:
            return
        if kind == "contains":
            self._containing = []
            self._render()
        else:
            self.diff.setPlainText("Could not load: {err}".format(err=err))
