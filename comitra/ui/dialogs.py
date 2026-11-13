"""Settings, repositories, update report, saved searches, statistics, about."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QRect, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QStyledItemDelegate, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, config
from ..core import db, query as querymod
from .results_model import fmt_time
from .workers import Task, compute_stats


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(False)
    return t


def _item(value, align_right: bool = False, data=None) -> QTableWidgetItem:
    it = QTableWidgetItem()
    if isinstance(value, (int, float)):
        it.setData(Qt.DisplayRole, value)
    else:
        it.setText(str(value))
    if align_right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


# -- settings --------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: config.Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(640, 560)
        self.s = settings
        tabs = QTabWidget()

        # Folders
        w = QWidget()
        f = QVBoxLayout(w)
        from ..core.scanner import default_roots

        self.auto = QCheckBox("Find repositories automatically", checked=settings.auto_discover)
        auto_where = ", ".join(default_roots()) or "—"
        hint = QLabel(f"Searches {auto_where} (system folders, hidden folders and app bundles are skipped).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        f.addWidget(self.auto)
        f.addWidget(hint)
        f.addSpacing(6)
        f.addWidget(QLabel("Additional folders to scan"))
        self.roots = QListWidget()
        self.roots.addItems(settings.roots)
        f.addWidget(self.roots)
        row = QHBoxLayout()
        b_add, b_rm = QPushButton("Add…"), QPushButton("Remove")
        b_add.clicked.connect(self._add_root)
        b_rm.clicked.connect(lambda: [self.roots.takeItem(self.roots.row(i)) for i in self.roots.selectedItems()])
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch(1)
        f.addLayout(row)
        f.addWidget(QLabel("Excluded folder names (one per line)"))
        self.excl_names = QPlainTextEdit("\n".join(settings.exclude_names))
        f.addWidget(self.excl_names)
        f.addWidget(QLabel("Excluded paths (one per line)"))
        self.excl_paths = QPlainTextEdit("\n".join(settings.excluded_paths))
        self.excl_paths.setMaximumHeight(80)
        f.addWidget(self.excl_paths)
        form = QFormLayout()
        self.max_depth = QSpinBox(minimum=1, maximum=50, value=settings.max_depth)
        self.follow = QCheckBox(checked=settings.follow_symlinks)
        self.bare = QCheckBox(checked=settings.include_bare)
        self.hidden = QCheckBox(checked=settings.skip_hidden)
        form.addRow("Maximum folder depth", self.max_depth)
        form.addRow("Follow symbolic links", self.follow)
        form.addRow("Include bare repositories", self.bare)
        form.addRow("Skip hidden folders (.config, .cache …)", self.hidden)
        f.addLayout(form)
        tabs.addTab(w, "Folders")

        # Indexing
        w = QWidget()
        form = QFormLayout(w)
        self.workers = QSpinBox(minimum=1, maximum=32, value=settings.workers)
        self.tags = QCheckBox(checked=settings.include_tags)
        self.remotes = QCheckBox(checked=settings.include_remotes)
        self.files = QCheckBox("Index changed file paths (enables file: search, slower first indexing)",
                               checked=settings.index_files)
        self.keep = QCheckBox("Keep commits that are no longer on any branch", checked=settings.keep_unreachable)
        self.fetch = QCheckBox("Run 'git fetch --all' before updating (needs network)",
                               checked=settings.fetch_before_scan)
        self.fetch_timeout = QSpinBox(minimum=5, maximum=3600, value=settings.fetch_timeout)
        self.fetch_workers = QSpinBox(minimum=1, maximum=16, value=settings.fetch_workers)
        self.on_start = QCheckBox(checked=settings.update_on_start)
        self.auto_min = QSpinBox(minimum=0, maximum=1440, value=settings.auto_update_minutes)
        self.watch = QCheckBox(checked=settings.watch_repos)
        form.addRow("Parallel workers", self.workers)
        form.addRow("Index tags", self.tags)
        form.addRow("Index remote branches", self.remotes)
        form.addRow(self.files)
        form.addRow(self.keep)
        form.addRow(self.fetch)
        form.addRow("Fetch timeout (seconds)", self.fetch_timeout)
        form.addRow("Parallel fetches", self.fetch_workers)
        form.addRow("Update index on start", self.on_start)
        form.addRow("Update automatically every (minutes, 0 = off)", self.auto_min)
        form.addRow("Watch repositories for changes", self.watch)
        tabs.addTab(w, "Indexing")

        # Search & display
        w = QWidget()
        form = QFormLayout(w)
        self.basis = QComboBox()
        self.basis.addItem("Author date (when it was written)", "author")
        self.basis.addItem("Commit date (when it was applied)", "committer")
        self.basis.setCurrentIndex(max(0, self.basis.findData(settings.date_basis)))
        self.show_unreach = QCheckBox(checked=settings.show_unreachable)
        self.theme = QComboBox()
        for k, label in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
            self.theme.addItem(label, k)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form.addRow("Date used for filters and sorting", self.basis)
        form.addRow("Show commits no longer on any branch by default", self.show_unreach)
        form.addRow("Theme", self.theme)
        tabs.addTab(w, "Search & display")

        # Integrations
        w = QWidget()
        form = QFormLayout(w)
        self.git_path = QLineEdit(settings.git_path)
        gp = QHBoxLayout()
        gp.addWidget(self.git_path)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse_git)
        gp.addWidget(b)
        self.term_cmd = QLineEdit(settings.terminal_command, placeholderText="wt -d {path}  |  open -a iTerm {path}  |  konsole --workdir {path}")
        self.editor_cmd = QLineEdit(settings.editor_command, placeholderText="code {path}")
        form.addRow("git executable (empty = automatic)", gp)
        form.addRow("Terminal command (empty = automatic, {path} = folder)", self.term_cmd)
        form.addRow("Editor command (empty = automatic, {path} = folder)", self.editor_cmd)
        loc = QLabel(f"{config.db_path()}<br>{config.settings_path()}")
        loc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        loc.setWordWrap(True)
        form.addRow("Data location", loc)
        form.addRow("Portable mode", QLabel("Yes" if config.is_portable() else "No"))
        compact = QPushButton("Compact database")
        compact.clicked.connect(self._compact)
        form.addRow(compact)
        tabs.addTab(w, "Integrations")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _add_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder with git repositories", os.path.expanduser("~"))
        if d:
            d = os.path.normpath(d)
            if d not in [self.roots.item(i).text() for i in range(self.roots.count())]:
                self.roots.addItem(d)

    def _browse_git(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "git", "", "git (git git.exe);;*")
        if p:
            self.git_path.setText(p)

    def _compact(self) -> None:
        conn = db.connect(config.db_path())
        try:
            db.vacuum(conn)
        finally:
            conn.close()
        QMessageBox.information(self, APP_NAME, "Database compacted.")

    def apply(self) -> config.Settings:
        s = self.s
        s.auto_discover = self.auto.isChecked()
        s.skip_hidden = self.hidden.isChecked()
        s.roots = [self.roots.item(i).text() for i in range(self.roots.count())]
        s.exclude_names = [l.strip() for l in self.excl_names.toPlainText().splitlines() if l.strip()]
        s.excluded_paths = [l.strip() for l in self.excl_paths.toPlainText().splitlines() if l.strip()]
        s.max_depth = self.max_depth.value()
        s.follow_symlinks = self.follow.isChecked()
        s.include_bare = self.bare.isChecked()
        s.workers = self.workers.value()
        s.include_tags = self.tags.isChecked()
        s.include_remotes = self.remotes.isChecked()
        s.index_files = self.files.isChecked()
        s.keep_unreachable = self.keep.isChecked()
        s.fetch_before_scan = self.fetch.isChecked()
        s.fetch_timeout = self.fetch_timeout.value()
        s.fetch_workers = self.fetch_workers.value()
        s.update_on_start = self.on_start.isChecked()
        s.auto_update_minutes = self.auto_min.value()
        s.watch_repos = self.watch.isChecked()
        s.date_basis = self.basis.currentData()
        s.show_unreachable = self.show_unreach.isChecked()
        s.theme = self.theme.currentData()
        s.git_path = self.git_path.text().strip()
        s.terminal_command = self.term_cmd.text().strip()
        s.editor_command = self.editor_cmd.text().strip()
        return s


# -- repositories --------------------------------------------------------------------

class ReposDialog(QDialog):
    reindex = Signal(object)          # set of repo ids
    removed = Signal()
    search_repo = Signal(str)
    exclude = Signal(list)            # paths

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Repositories")
        self.resize(900, 520)
        self.table = _table(["Name", "Commits", "Status", "Last indexed", "Path"])
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._search_selected)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for label, fn in (
            ("Search in this repository", self._search_selected),
            ("Re-index selected", self._reindex),
            ("Remove from index", self._remove),
            ("Exclude and remove", self._exclude),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.load()

    def load(self) -> None:
        rows = self.conn.execute("SELECT * FROM repos ORDER BY name COLLATE NOCASE").fetchall()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        total = 0
        for i, r in enumerate(rows):
            total += r["commit_count"]
            self.table.setItem(i, 0, _item(r["name"], data=r["id"]))
            self.table.setItem(i, 1, _item(r["commit_count"], True))
            st = _item(r["status"])
            if r["status"] in ("error", "missing"):
                st.setForeground(QColor("#d1242f"))
                st.setToolTip(r["last_error"] or "")
            self.table.setItem(i, 2, st)
            self.table.setItem(i, 3, _item(fmt_time(r["last_indexed_at"]) if r["last_indexed_at"] else "never"))
            self.table.setItem(i, 4, _item(r["path"]))
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.summary.setText("{n} repositories, {c} commits".format(n=len(rows), c=total))

    def _selected(self) -> list[tuple[int, str, str]]:
        out = []
        for idx in self.table.selectionModel().selectedRows(0):
            it = self.table.item(idx.row(), 0)
            out.append((it.data(Qt.UserRole), it.text(), self.table.item(idx.row(), 4).text()))
        return out

    def _search_selected(self, *_):
        sel = self._selected()
        if sel:
            self.search_repo.emit(sel[0][1])
            self.accept()

    def _reindex(self) -> None:
        sel = self._selected()
        if sel:
            self.reindex.emit({s[0] for s in sel})

    def _remove(self, exclude: bool = False) -> bool:
        sel = self._selected()
        if not sel:
            return False
        if QMessageBox.question(self, APP_NAME, "Remove {n} repositories and their commits from the index?".format(n=len(sel))) != QMessageBox.Yes:
            return False
        for rid, _, _ in sel:
            db.delete_repo(self.conn, rid)
        if exclude:
            self.exclude.emit([s[2] for s in sel])
        self.removed.emit()
        self.load()
        return True

    def _exclude(self) -> None:
        self._remove(exclude=True)


# -- update report -------------------------------------------------------------------

class SummaryDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update report")
        self.resize(900, 500)
        sm = report.summary
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "{u} updated, {s} unchanged, {e} errors, {m} missing, {f} fetch problems".format(
                u=sm.count("updated"), s=sm.count("unchanged"), e=sm.count("error"), m=sm.count("missing"),
                f=len(sm.fetch_problems))
            + f" — {sm.new_commits} new, {sm.seconds:.1f} s"
        ))
        t = _table(["Repository", "Status", "New", "Unreachable", "Fetch", "Seconds", "Message"])
        t.setRowCount(len(sm.results))
        for i, r in enumerate(sm.results):
            t.setItem(i, 0, _item(r.name))
            t.item(i, 0).setToolTip(r.path)
            st = _item(r.status)
            if r.status in ("error", "missing"):
                st.setForeground(QColor("#d1242f"))
            t.setItem(i, 1, st)
            t.setItem(i, 2, _item(r.new_commits, True))
            t.setItem(i, 3, _item(r.unreachable, True))
            fetch = "—" if r.fetch is None else ("ok" if r.fetch.ok else r.fetch.reason)
            fi = _item(fetch)
            if r.fetch is not None and not r.fetch.ok:
                fi.setForeground(QColor("#d29922"))
                fi.setToolTip(r.fetch.message)
            t.setItem(i, 4, fi)
            t.setItem(i, 5, _item(round(r.seconds, 2), True))
            msg = r.message or (r.fetch.message.splitlines()[0] if r.fetch and r.fetch.message else "")
            t.setItem(i, 6, _item(msg))
            t.item(i, 6).setToolTip(r.message or (r.fetch.message if r.fetch else ""))
        t.resizeColumnsToContents()
        t.setSortingEnabled(True)
        lay.addWidget(t)
        if report.scan.errors:
            lay.addWidget(QLabel("Scan problems"))
            box = QPlainTextEdit(readOnly=True)
            box.setPlainText("\n".join(f"{p}: {e}" for p, e in report.scan.errors))
            box.setMaximumHeight(100)
            lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


# -- saved searches ---------------------------------------------------------------------

class SavedSearchesDialog(QDialog):
    run_query = Signal(str)

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Saved searches")
        self.resize(700, 400)
        self.table = _table(["Name", "Query"])
        self.table.doubleClicked.connect(self._run)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for label, fn in (("Run", self._run), ("Delete", self._delete)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        c = QPushButton("Close")
        c.clicked.connect(self.accept)
        row.addWidget(c)
        lay.addLayout(row)
        self.load()

    def load(self) -> None:
        rows = self.conn.execute("SELECT id, name, query FROM saved_searches ORDER BY name COLLATE NOCASE").fetchall()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, _item(r["name"], data=r["id"]))
            self.table.setItem(i, 1, _item(r["query"]))
        self.table.resizeColumnToContents(0)

    def _current(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        return self.table.item(r, 0).data(Qt.UserRole), self.table.item(r, 1).text()

    def _run(self, *_):
        cur = self._current()
        if cur:
            self.run_query.emit(cur[1])
            self.accept()

    def _delete(self) -> None:
        cur = self._current()
        if cur:
            self.conn.execute("DELETE FROM saved_searches WHERE id=?", (cur[0],))
            self.load()


def save_search(conn, parent, query_text: str) -> str | None:
    name, ok = QInputDialog.getText(parent, "Save search…", "Name for this search:")
    name = name.strip()
    if not ok or not name:
        return None
    conn.execute(
        "INSERT INTO saved_searches(name, query, created_at) VALUES (?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET query=excluded.query",
        (name, query_text, int(time.time())),
    )
    return name


# -- statistics -----------------------------------------------------------------------

class BarDelegate(QStyledItemDelegate):
    def __init__(self, max_value: int, parent=None):
        super().__init__(parent)
        self.max_value = max(1, max_value)

    def paint(self, painter, option, index):
        v = index.data(Qt.DisplayRole) or 0
        try:
            frac = float(v) / self.max_value
        except (TypeError, ValueError):
            frac = 0
        r = option.rect
        bar = QRect(r.left() + 2, r.top() + 4, int((r.width() - 4) * frac), r.height() - 8)
        painter.save()
        painter.fillRect(bar, QColor(47, 111, 208, 110))
        painter.restore()
        super().paint(painter, option, index)


class StatsDialog(QDialog):
    def __init__(self, ids: list[int] | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.resize(820, 600)
        self.ids = ids
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.only_results = QCheckBox("Current results only")
        self.only_results.setEnabled(ids is not None)
        self.only_results.toggled.connect(self.reload)
        top.addWidget(self.only_results)
        top.addStretch(1)
        lay.addLayout(top)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.overview = QLabel("Loading…")
        self.overview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.overview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.t_repo = _table(["Repository", "Count"])
        self.t_author = _table(["Author", "E-mail", "Count"])
        self.t_month = _table(["Month", "Count"])
        self.t_wday = _table(["Day", "Count"])
        self.t_hour = _table(["Hour", "Count"])
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self.t_repo, "By repository")
        self.tabs.addTab(self.t_author, "By author")
        self.tabs.addTab(self.t_month, "By month")
        self.tabs.addTab(self.t_wday, "By weekday")
        self.tabs.addTab(self.t_hour, "By hour")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._task = None
        self.reload()

    def reload(self, *_):
        ids = self.ids if self.only_results.isChecked() else None
        self.overview.setText("Loading…")
        t = Task("stats", compute_stats, ids)
        t.signals.done.connect(self._show)
        t.signals.failed.connect(lambda _k, e: self.overview.setText(e))
        self._task = t
        QThreadPool.globalInstance().start(t)

    def _fill(self, table: QTableWidget, rows: list[tuple], count_col: int) -> None:
        table.setRowCount(len(rows))
        mx = max((r[count_col] for r in rows), default=1)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                table.setItem(i, j, _item(v, j == count_col))
        table.setItemDelegateForColumn(count_col, BarDelegate(mx, table))
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(count_col, QHeaderView.Stretch)

    def _show(self, _key, st) -> None:
        fmt = lambda ts: fmt_time(ts) if ts else "—"  # noqa: E731
        self.overview.setText(
            f"<table cellpadding='4'>"
            f"<tr><td>Total commits</td><td><b>{st.total_commits}</b></td></tr>"
            f"<tr><td>Repositories</td><td><b>{st.total_repos}</b></td></tr>"
            f"<tr><td>Authors</td><td><b>{st.total_authors}</b></td></tr>"
            f"<tr><td>Commits no longer on any branch</td><td><b>{st.unreachable}</b></td></tr>"
            f"<tr><td>First commit</td><td>{fmt(st.first_time)}</td></tr>"
            f"<tr><td>Last commit</td><td>{fmt(st.last_time)}</td></tr></table>"
        )
        self._fill(self.t_repo, st.by_repo, 1)
        self._fill(self.t_author, st.by_author, 2)
        self._fill(self.t_month, list(reversed(st.by_month)), 1)
        days = [d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
        self._fill(self.t_wday, [(days[d], n) for d, n in st.by_weekday], 1)
        self._fill(self.t_hour, [(f"{h:02d}:00", n) for h, n in st.by_hour], 1)


# -- help ---------------------------------------------------------------------------

SYNTAX_HELP = """<h3>Query syntax</h3>
<table cellpadding="3">
<tr><td><code>payment error</code></td><td>all words (case- and accent-insensitive: <i>cafe</i> finds <i>Café</i>)</td></tr>
<tr><td><code>"payment error"</code></td><td>exact phrase</td></tr>
<tr><td><code>login*</code></td><td>prefix</td></tr>
<tr><td><code>-wip</code>, <code>-"work in progress"</code></td><td>exclude</td></tr>
<tr><td><code>author:alice,bob@example.com</code></td><td>author or co-author name / e-mail contains</td></tr>
<tr><td><code>repo:billing</code></td><td>repository name or path contains</td></tr>
<tr><td><code>branch:main branch:feature/*</code></td><td>commits reachable from matching branches (wildcards)</td></tr>
<tr><td><code>hash:a1b2c3d</code></td><td>full or short hash (a bare hash also works)</td></tr>
<tr><td><code>file:*.py file:src/auth/</code></td><td>changed file (needs file index)</td></tr>
<tr><td><code>date:today|yesterday|7d|30d|month|year</code></td><td>date presets</td></tr>
<tr><td><code>date:2026-11-10</code>, <code>date:2026-10-01..2026-10-31</code>, <code>date:2026-10</code></td><td>day, range, month</td></tr>
<tr><td><code>after:2026-10-01 before:2026-11-01</code></td><td>after is inclusive, before is exclusive</td></tr>
<tr><td><code>hour:09-12</code>, <code>hour:22-06</code></td><td>time of day (in the author's time zone)</td></tr>
<tr><td><code>day:fri</code>, <code>day:weekend</code></td><td>weekday</td></tr>
<tr><td><code>merge:hide|only</code></td><td>merge commits</td></tr>
<tr><td><code>unreachable:include|only</code></td><td>commits no longer on any branch</td></tr>
<tr><td><code>sort:newest|oldest|relevance</code></td><td>sort order</td></tr>
</table>
<p>Several values of the same filter are OR-ed, different filters are AND-ed.</p>"""

SHORTCUTS = [
    ("Ctrl/⌘+K, Ctrl/⌘+F", "Focus search"),
    ("Esc", "Clear search"),
    ("F5", "Update index"),
    ("Shift+F5", "Update index with fetch"),
    ("Ctrl/⌘+S", "Save search…"),
    ("Ctrl/⌘+E", "Export results…"),
    ("Ctrl/⌘+Shift+C", "Copy hash"),
    ("Ctrl/⌘+Shift+O", "Open folder"),
    ("Ctrl/⌘+Shift+T", "Open terminal"),
    ("Ctrl/⌘+Shift+E", "Open in editor"),
    ("Ctrl/⌘+1 / 2 / 3 / 0", "Group by"),
    ("Ctrl/⌘+,", "Settings…"),
]


def show_syntax(parent) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("Query syntax")
    box.setTextFormat(Qt.RichText)
    box.setText(SYNTAX_HELP)
    box.exec()


def show_shortcuts(parent) -> None:
    rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in SHORTCUTS)
    QMessageBox.information(parent, "Keyboard shortcuts", f"<table cellpadding='3'>{rows}</table>")


def show_about(parent) -> None:
    from ..core import gitcmd
    import sqlite3

    QMessageBox.about(
        parent,
        "About Comitra",
        f"<h3>{APP_NAME}</h3><p>{'Version {v}'.format(v=__version__)}</p>"
        f"<p>Comitra – search commits across all your local git repositories.</p>"
        f"<p>Works fully offline. Your data never leaves this computer.</p>"
        f"<p style='color:gray'>{gitcmd.git_version() or 'git: —'}<br>SQLite {sqlite3.sqlite_version}</p>",
    )


__all__ = [
    "SettingsDialog", "ReposDialog", "SummaryDialog", "SavedSearchesDialog", "StatsDialog",
    "save_search", "show_syntax", "show_shortcuts", "show_about", "querymod",
]
