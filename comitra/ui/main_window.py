"""Main window: search bar, filter panel, results table, detail panel."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QByteArray, QFileSystemWatcher, QItemSelectionModel, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableView, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, config
from ..core import db, query as querymod, search
from . import actions, dialogs, theme
from .detail_panel import DetailPanel
from .filter_panel import FilterPanel
from .results_model import COL_AUTHOR, COL_BRANCH, COL_DATE, COL_HASH, COL_MSG, COL_REPO, HighlightDelegate, ResultsModel
from .workers import IndexThread, SearchThread, Task, author_suggestions, export_results

MAX_WATCHED = 500


class MainWindow(QMainWindow):
    def __init__(self, settings: config.Settings):
        super().__init__()
        self.settings = settings
        self.conn = db.connect(config.db_path())
        self.query = querymod.Query()
        self.last_result: search.SearchResult | None = None
        self.gen = 0
        self.index_thread: IndexThread | None = None
        self.pending_watch_ids: set[int] = set()
        self.pending_full_update = False
        self.last_report = None
        self._tasks: set = set()
        self._watch_map: dict[str, int] = {}

        self.setWindowTitle(APP_NAME + (" (portable)" if config.is_portable() else ""))
        self.resize(1280, 800)
        self._build_ui()
        self._build_menus()

        self.search_thread = SearchThread(self)
        self.search_thread.worker.result.connect(self._on_search_result)
        self.search_thread.start()

        self.search_timer = QTimer(self, singleShot=True, interval=220)
        self.search_timer.timeout.connect(self._query_text_changed)
        self.recent_timer = QTimer(self, singleShot=True, interval=2500)
        self.recent_timer.timeout.connect(self._remember_recent)
        self.watch_timer = QTimer(self, singleShot=True, interval=4000)
        self.watch_timer.timeout.connect(self._flush_watch)
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(lambda: self.start_update(quiet=True))
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_repo_changed)

        self._restore_window()
        self.refresh_side_data()
        self._apply_runtime_settings()
        self._update_central()
        self.run_search()
        if settings.roots and settings.update_on_start:
            QTimer.singleShot(300, lambda: self.start_update(quiet=True))

    # -- UI construction ---------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 0)
        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Search commits…  e.g.  author:alice branch:feature/* date:7d "payment error" -wip')
        self.search_edit.setClearButtonEnabled(True)
        f = self.search_edit.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.search_edit.setFont(f)
        self.search_edit.setMinimumHeight(32)
        self.search_edit.textEdited.connect(lambda _t: self.search_timer.start())
        self.search_edit.textChanged.connect(lambda t: (not t) and self.search_timer.start())
        self.search_edit.returnPressed.connect(self._query_text_changed)
        self.search_edit.installEventFilter(self)
        bar.addWidget(self.search_edit, 1)

        self.sort_combo = QComboBox()
        for key, label in (("", "Auto"), ("newest", "Newest"), ("oldest", "Oldest"), ("relevance", "Relevance")):
            self.sort_combo.addItem(label, key)
        self.sort_combo.setToolTip("Sort")
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        bar.addWidget(self.sort_combo)

        self.group_combo = QComboBox()
        for key, label in (("", "No grouping"), ("repo", "Repository"), ("author", "Author"), ("day", "Day")):
            self.group_combo.addItem(label, key)
        self.group_combo.setToolTip("Group by")
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(self.settings.group_by)))
        self.group_combo.currentIndexChanged.connect(self._group_changed)
        bar.addWidget(self.group_combo)

        self.saved_btn = QToolButton(text="★")
        self.saved_btn.setToolTip("Saved searches")
        self.saved_btn.setPopupMode(QToolButton.InstantPopup)
        self.saved_menu = QMenu(self)
        self.saved_menu.aboutToShow.connect(self._fill_saved_menu)
        self.saved_btn.setMenu(self.saved_menu)
        bar.addWidget(self.saved_btn)

        help_btn = QToolButton(text="?")
        help_btn.setToolTip("Query syntax")
        help_btn.clicked.connect(lambda: dialogs.show_syntax(self))
        bar.addWidget(help_btn)
        v.addLayout(bar)

        self.info_label = QLabel()
        self.info_label.setStyleSheet(f"color:{theme.muted_color()}")
        v.addWidget(self.info_label)

        # results + detail
        self.model = ResultsModel(self.conn, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setItemDelegateForColumn(COL_MSG, HighlightDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(COL_MSG, QHeaderView.Stretch)
        for col, width in ((COL_DATE, 130), (COL_REPO, 140), (COL_AUTHOR, 150), (COL_BRANCH, 140), (COL_HASH, 95)):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().currentRowChanged.connect(self._current_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda idx: self.detail.tabs.setCurrentIndex(1))

        self.detail = DetailPanel(self.conn)
        self.detail.copy_requested.connect(self._copy)
        self.detail.action.connect(self._do_action)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        # welcome page
        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        wl.addStretch(1)
        title = QLabel("<h2>Welcome to Comitra</h2>")
        title.setAlignment(Qt.AlignCenter)
        text = QLabel("Add the folders that contain your git repositories. Comitra finds every repository inside them and indexes the commits of all branches. Everything stays on this computer.")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignCenter)
        text.setMaximumWidth(560)
        btn = QPushButton("Add folder")
        btn.setMinimumHeight(36)
        btn.clicked.connect(self.add_folder)
        wl.addWidget(title)
        wl.addWidget(text, alignment=Qt.AlignHCenter)
        wl.addSpacing(12)
        wl.addWidget(btn, alignment=Qt.AlignHCenter)
        wl.addStretch(2)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.splitter)
        self.stack.addWidget(welcome)
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # filter dock
        self.filters = FilterPanel()
        self.filters.changed.connect(self._filters_changed)
        self.filter_dock = QDockWidget("Filters", self)
        self.filter_dock.setObjectName("filters")
        self.filter_dock.setWidget(self.filters)
        self.filter_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.filter_dock)

        # status bar
        self.status_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.cancel_btn = QToolButton(text="✕")
        self.cancel_btn.setToolTip("Cancel update")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_update)
        self.report_btn = QToolButton(text="⚠")
        self.report_btn.setToolTip("Last update report…")
        self.report_btn.setVisible(False)
        self.report_btn.clicked.connect(self.show_report)
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.report_btn)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.cancel_btn)

    def _act(self, menu: QMenu, text: str, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, list):
                a.setShortcuts(shortcut)
            else:
                a.setShortcut(shortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "Add folder…", self.add_folder)
        m.addSeparator()
        self.act_update = self._act(m, "Update index", lambda: self.start_update(), QKeySequence("F5"))
        self._act(m, "Update index with fetch", lambda: self.start_update(fetch=True), QKeySequence("Shift+F5"))
        self._act(m, "Full re-check", lambda: self.start_update(force_full=True))
        self._act(m, "Cancel update", self.cancel_update)
        m.addSeparator()
        self._act(m, "Export results…", self.export, QKeySequence("Ctrl+E"))
        m.addSeparator()
        a = self._act(m, "Quit", self.close, QKeySequence.Quit)
        a.setMenuRole(QAction.QuitRole)

        m = mb.addMenu("&Search")
        self._act(m, "Focus search", self.focus_search, [QKeySequence("Ctrl+K"), QKeySequence("Ctrl+F"), QKeySequence("Ctrl+L")])
        self._act(m, "Clear search", self.clear_search)
        self._act(m, "Save search…", self.save_current_search, QKeySequence("Ctrl+S"))
        self._act(m, "Manage saved searches…", self.manage_saved)
        self.recent_menu = m.addMenu("Recent searches")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addSeparator()
        self._act(m, "Copy hash", lambda: self._copy_selected("hash"), QKeySequence("Ctrl+Shift+C"))
        self._act(m, "Open folder", lambda: self._selected_action("folder"), QKeySequence("Ctrl+Shift+O"))
        self._act(m, "Open terminal", lambda: self._selected_action("terminal"), QKeySequence("Ctrl+Shift+T"))
        self._act(m, "Open in editor", lambda: self._selected_action("editor"), QKeySequence("Ctrl+Shift+E"))

        m = mb.addMenu("&View")
        gm = m.addMenu("Group by")
        grp = QActionGroup(self)
        self.group_actions = {}
        for key, label, sc in (("", "No grouping", "Ctrl+0"), ("repo", "Repository", "Ctrl+1"),
                               ("author", "Author", "Ctrl+2"), ("day", "Day", "Ctrl+3")):
            a = QAction(label, self, checkable=True)
            a.setShortcut(QKeySequence(sc))
            a.setChecked(key == self.settings.group_by)
            a.triggered.connect(lambda _c=False, k=key: self.group_combo.setCurrentIndex(self.group_combo.findData(k)))
            grp.addAction(a)
            gm.addAction(a)
            self.group_actions[key] = a
        tm = m.addMenu("Theme")
        tgrp = QActionGroup(self)
        for key, label in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
            a = QAction(label, self, checkable=True)
            a.setChecked(self.settings.theme == key)
            a.triggered.connect(lambda _c=False, k=key: self.set_theme(k))
            tgrp.addAction(a)
            tm.addAction(a)
        m.addSeparator()
        fa = self.filter_dock.toggleViewAction()
        fa.setText("Show filter panel")
        m.addAction(fa)
        self.act_detail = QAction("Show detail panel", self, checkable=True, checked=True)
        self.act_detail.toggled.connect(self.detail.setVisible)
        m.addAction(self.act_detail)

        m = mb.addMenu("&Tools")
        self._act(m, "Repositories…", self.show_repos)
        self._act(m, "Statistics…", self.show_stats)
        self._act(m, "Last update report…", self.show_report)
        m.addSeparator()
        a = self._act(m, "Settings…", self.show_settings, QKeySequence.Preferences)
        if QKeySequence(QKeySequence.Preferences).isEmpty():
            a.setShortcut(QKeySequence("Ctrl+,"))
        a.setMenuRole(QAction.PreferencesRole)

        m = mb.addMenu("&Help")
        self._act(m, "Query syntax", lambda: dialogs.show_syntax(self), QKeySequence.HelpContents)
        self._act(m, "Keyboard shortcuts", lambda: dialogs.show_shortcuts(self))
        a = self._act(m, "About Comitra", lambda: dialogs.show_about(self))
        a.setMenuRole(QAction.AboutRole)

    # -- window state ------------------------------------------------------------
    def _restore_window(self) -> None:
        try:
            if self.settings.window_geometry:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.window_geometry.encode()))
            if self.settings.window_state:
                self.restoreState(QByteArray.fromBase64(self.settings.window_state.encode()))
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.window_state = bytes(self.saveState().toBase64()).decode()
        self.settings.group_by = self.group_combo.currentData() or ""
        try:
            self.settings.save()
        except OSError:
            pass
        if self.index_thread is not None and self.index_thread.isRunning():
            self.index_thread.cancel()
            self.index_thread.wait(10000)
        self.search_thread.quit()
        self.search_thread.wait(3000)
        QThreadPool.globalInstance().waitForDone(3000)
        super().closeEvent(event)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent

        if obj is self.search_edit and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.clear_search()
                return True
            if ev.key() in (Qt.Key_Down, Qt.Key_PageDown) and self.model.rowCount():
                self.table.setFocus()
                self._select_row(self._first_commit_row())
                return True
        return super().eventFilter(obj, ev)

    # -- runtime settings ----------------------------------------------------------
    def _apply_runtime_settings(self) -> None:
        from ..core import gitcmd

        gitcmd.set_git_path(self.settings.git_path or None)
        mins = self.settings.auto_update_minutes
        if mins > 0:
            self.auto_timer.start(mins * 60_000)
        else:
            self.auto_timer.stop()
        self._setup_watcher()

    def _setup_watcher(self) -> None:
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        self._watch_map = {}
        if not self.settings.watch_repos:
            return
        rows = self.conn.execute(
            "SELECT id, git_dir FROM repos WHERE status IN ('ok','new','error') AND git_dir IS NOT NULL ORDER BY last_indexed_at DESC LIMIT ?",
            (MAX_WATCHED,),
        ).fetchall()
        paths = []
        for rid, gd in rows:
            if gd and os.path.isdir(gd):
                self._watch_map[os.path.normpath(gd)] = rid
                paths.append(gd)
                heads = os.path.join(gd, "refs", "heads")
                if os.path.isdir(heads):
                    self._watch_map[os.path.normpath(heads)] = rid
                    paths.append(heads)
        if paths:
            self.watcher.addPaths(paths)

    def _on_repo_changed(self, path: str) -> None:
        rid = self._watch_map.get(os.path.normpath(path))
        if rid is not None:
            self.pending_watch_ids.add(rid)
            self.watch_timer.start()

    def _flush_watch(self) -> None:
        if not self.pending_watch_ids:
            return
        if self.index_thread is not None and self.index_thread.isRunning():
            self.watch_timer.start()
            return
        ids, self.pending_watch_ids = self.pending_watch_ids, set()
        self._start_thread(IndexThread(self.settings, mode="known", fetch=False, repo_ids=ids), quiet=True)

    # -- data for side widgets ------------------------------------------------------
    def refresh_side_data(self) -> None:
        repos = [(r["name"], r["path"], r["commit_count"]) for r in
                 self.conn.execute("SELECT name, path, commit_count FROM repos ORDER BY name COLLATE NOCASE")]
        self.filters.set_repos(repos)
        branches = sorted({
            r[0].split("/", 2)[-1] if r[0].startswith("refs/") else r[0]
            for r in self.conn.execute("SELECT DISTINCT name FROM refs WHERE kind IN ('branch','remote') LIMIT 20000")
        })
        self.filters.set_branch_suggestions(branches)
        t = Task("authors", author_suggestions)
        t.signals.done.connect(lambda _k, vals: self.filters.set_author_suggestions(vals))
        self._keep(t)
        QThreadPool.globalInstance().start(t)
        self._update_counts()

    def _keep(self, t: Task) -> None:
        self._tasks.add(t)
        t.signals.done.connect(lambda *_: self._tasks.discard(t))
        t.signals.failed.connect(lambda *_: self._tasks.discard(t))

    def _update_counts(self) -> None:
        n, c = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(commit_count),0) FROM repos").fetchone()
        self.repo_count_text = "{n} repositories, {c} commits".format(n=n, c=c)
        if self.index_thread is None or not self.index_thread.isRunning():
            self.status_label.setText(self.repo_count_text)

    def _update_central(self) -> None:
        has = bool(self.settings.roots) or self.conn.execute("SELECT 1 FROM repos LIMIT 1").fetchone()
        self.stack.setCurrentIndex(0 if has else 1)

    # -- searching ----------------------------------------------------------------
    def _query_text_changed(self) -> None:
        self.search_timer.stop()
        q = querymod.parse(self.search_edit.text())
        self.query = q
        self.filters.set_query(q)
        self._sync_sort_combo()
        self.run_search()

    def _filters_changed(self) -> None:
        self.query = self.filters.apply_to(self.query)
        self._set_search_text(self.query.to_string())
        self.run_search()

    def _set_search_text(self, text: str) -> None:
        if self.search_edit.text() != text:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(text)
            self.search_edit.blockSignals(False)

    def _sort_changed(self) -> None:
        key = self.sort_combo.currentData() or None
        if key != self.query.sort:
            self.query.sort = key
            self._set_search_text(self.query.to_string())
            self.run_search()

    def _sync_sort_combo(self) -> None:
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(self.query.sort or "")))
        self.sort_combo.blockSignals(False)

    def _group_changed(self) -> None:
        key = self.group_combo.currentData() or ""
        self.settings.group_by = key
        if key in self.group_actions:
            self.group_actions[key].setChecked(True)
        self.run_search()

    def run_search(self) -> None:
        self.gen += 1
        opts = {
            "query": self.query.copy(),
            "show_unreachable": self.settings.show_unreachable,
            "search": search.SearchOptions(date_basis=self.settings.date_basis,
                                           group_by=self.group_combo.currentData() or None),
        }
        self.search_thread.worker.bump(self.gen)
        self.search_thread.worker.request.emit(self.gen, self.query.to_string(), opts)
        self.recent_timer.start()

    def _on_search_result(self, gen: int, res: search.SearchResult, text: str) -> None:
        if gen != self.gen:
            return
        prev_id = self._current_commit_id()
        self.last_result = res
        group = self.group_combo.currentData() or None
        self.table.clearSpans()
        self.model.set_result(res, group, self.settings.date_basis)
        if group:
            spans = 0
            for i, e in enumerate(self.model.entries):
                if e[0] == "g":
                    self.table.setSpan(i, 0, 1, self.model.columnCount())
                    spans += 1
                    if spans >= 5000:
                        break
        n = len(res.ids)
        label = f"{n:,} results" + (" (limit reached)" if res.truncated else "")
        label += " · " + "in {ms} ms".format(ms=int(res.seconds * 1000))
        if res.warnings:
            label += " · ⚠ " + "; ".join(res.warnings[:3])
        self.info_label.setText(label)
        # keep the selection if the commit is still in the results
        row = self._row_of(prev_id) if prev_id is not None else -1
        if row < 0:
            row = self._first_commit_row()
        if row >= 0:
            self._select_row(row, scroll=prev_id is None)
        else:
            self.detail.show_empty()

    def _row_of(self, cid: int) -> int:
        try:
            if self.model.entries and len(self.model.entries) < 2_000_000:
                return self.model.entries.index(("c", cid))
        except ValueError:
            pass
        return -1

    def _first_commit_row(self) -> int:
        for i, e in enumerate(self.model.entries[:3]):
            if e[0] == "c":
                return i
        return -1

    def _select_row(self, row: int, scroll: bool = True) -> None:
        if row < 0:
            return
        idx = self.model.index(row, 0)
        self.table.selectionModel().setCurrentIndex(
            idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        if scroll:
            self.table.scrollTo(idx)

    def _current_commit_id(self) -> int | None:
        idx = self.table.selectionModel().currentIndex()
        return self.model.commit_id(idx.row()) if idx.isValid() else None

    def _current_changed(self, cur, _prev) -> None:
        cid = self.model.commit_id(cur.row()) if cur.isValid() else None
        if cid is None:
            self.detail.show_empty()
            return
        terms = self.last_result.highlight_terms if self.last_result else []
        self.detail.show_commit(cid, terms, self.settings.date_basis)

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def clear_search(self) -> None:
        self.search_edit.setText("")
        self._query_text_changed()

    def set_query_text(self, text: str) -> None:
        self.search_edit.setText(text)
        self._query_text_changed()

    # -- recent & saved -------------------------------------------------------------
    def _remember_recent(self) -> None:
        text = self.query.to_string().strip()
        if not text:
            return
        self.conn.execute(
            "INSERT INTO recent_searches(query, used_at) VALUES (?, ?) ON CONFLICT(query) DO UPDATE SET used_at=excluded.used_at",
            (text, int(time.time())),
        )
        self.conn.execute(
            "DELETE FROM recent_searches WHERE query NOT IN (SELECT query FROM recent_searches ORDER BY used_at DESC LIMIT 30)"
        )

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        rows = self.conn.execute("SELECT query FROM recent_searches ORDER BY used_at DESC LIMIT 20").fetchall()
        for (q,) in rows:
            a = self.recent_menu.addAction(q if len(q) < 80 else q[:77] + "…")
            a.triggered.connect(lambda _c=False, text=q: self.set_query_text(text))
        if rows:
            self.recent_menu.addSeparator()
            a = self.recent_menu.addAction("Clear recent searches")
            a.triggered.connect(lambda: self.conn.execute("DELETE FROM recent_searches"))

    def _fill_saved_menu(self) -> None:
        m = self.saved_menu
        m.clear()
        a = m.addAction("Save search…")
        a.triggered.connect(self.save_current_search)
        a = m.addAction("Manage saved searches…")
        a.triggered.connect(self.manage_saved)
        rows = self.conn.execute("SELECT name, query FROM saved_searches ORDER BY name COLLATE NOCASE").fetchall()
        if rows:
            m.addSeparator()
        for name, q in rows:
            act = m.addAction(name)
            act.setToolTip(q)
            act.triggered.connect(lambda _c=False, text=q: self.set_query_text(text))
        recent = self.conn.execute("SELECT query FROM recent_searches ORDER BY used_at DESC LIMIT 8").fetchall()
        if recent:
            m.addSection("Recent searches")
            for (q,) in recent:
                act = m.addAction(q if len(q) < 70 else q[:67] + "…")
                act.triggered.connect(lambda _c=False, text=q: self.set_query_text(text))

    def save_current_search(self) -> None:
        text = self.query.to_string()
        if text:
            dialogs.save_search(self.conn, self, text)

    def manage_saved(self) -> None:
        d = dialogs.SavedSearchesDialog(self.conn, self)
        d.run_query.connect(self.set_query_text)
        d.exec()

    # -- indexing -------------------------------------------------------------------
    def add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder with git repositories", os.path.expanduser("~"))
        if not d:
            return
        d = os.path.normpath(d)
        if d not in self.settings.roots:
            self.settings.roots.append(d)
            self.settings.save()
        self._update_central()
        self.start_update()

    def start_update(self, fetch: bool | None = None, force_full: bool = False, quiet: bool = False) -> None:
        if not self.settings.roots:
            if not quiet:
                self.add_folder()
            return
        if self.index_thread is not None and self.index_thread.isRunning():
            if not quiet:
                self.statusBar().showMessage("An update is already running.", 4000)
            return
        self._start_thread(IndexThread(self.settings, mode="scan", force_full=force_full, fetch=fetch), quiet=quiet)

    def reindex_repos(self, ids: set[int]) -> None:
        if self.index_thread is not None and self.index_thread.isRunning():
            self.statusBar().showMessage("An update is already running.", 4000)
            return
        self._start_thread(IndexThread(self.settings, mode="known", force_full=True, repo_ids=ids), quiet=False)

    def _start_thread(self, th: IndexThread, quiet: bool) -> None:
        self.index_thread = th
        th.progress.connect(self._on_index_progress)
        th.done.connect(lambda rep, err, q=quiet: self._on_index_done(rep, err, q))
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.cancel_btn.setVisible(True)
        th.start()

    def cancel_update(self) -> None:
        if self.index_thread is not None and self.index_thread.isRunning():
            self.index_thread.cancel()

    def _on_index_progress(self, phase: str, done: int, total: int, cur: str) -> None:
        if phase == "scan":
            self.progress.setRange(0, 0)
            self.status_label.setText("Scanning folders… {cur}".format(cur=_short(cur)))
        else:
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(done)
            self.status_label.setText("Indexing {done}/{total}: {cur}".format(done=done, total=total, cur=cur))

    def _on_index_done(self, report, err: str, quiet: bool) -> None:
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        th, self.index_thread = self.index_thread, None
        if th is not None:
            th.deleteLater()
        if err == "git-not-found":
            self.status_label.setText("git was not found")
            QMessageBox.warning(self, "git was not found",
                                "Comitra needs git. Install it from https://git-scm.com (or with your package manager) and restart, or set the path to git in Settings.")
            return
        if err:
            self.status_label.setText(f"Error: {err}")
            if not quiet:
                QMessageBox.warning(self, "Error", err)
            return
        self.last_report = report
        sm = report.summary
        self.search_thread.worker.resolver.clear()
        self.refresh_side_data()
        self._setup_watcher()
        self._update_central()
        if sm.cancelled:
            self.status_label.setText("Update cancelled")
        else:
            msg = "Index updated: {new} new commits in {secs:.1f}s".format(new=sm.new_commits, secs=sm.seconds)
            self.status_label.setText(f"{self.repo_count_text} · {msg}")
        problems = sm.count("error") + sm.count("missing") + len(sm.fetch_problems) + len(report.scan.errors)
        self.report_btn.setVisible(problems > 0)
        if problems:
            self.report_btn.setToolTip(
                "{u} updated, {s} unchanged, {e} errors, {m} missing, {f} fetch problems".format(
                    u=sm.count("updated"), s=sm.count("unchanged"), e=sm.count("error"), m=sm.count("missing"),
                    f=len(sm.fetch_problems)))
        if sm.new_commits or sm.count("updated") or any(r.unreachable for r in sm.results):
            self.model.refresh_rows()
            self.run_search()
        if not quiet and (problems or (report.scan.repos and len(sm.results) <= 200 and sm.count("updated"))):
            if problems:
                self.show_report()

    def show_report(self) -> None:
        if self.last_report is not None:
            dialogs.SummaryDialog(self.last_report, self).exec()

    # -- actions on results -------------------------------------------------------------
    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage("Hash copied" if len(text) == 40 else "Copied to clipboard", 2000)

    def _selected_rows(self) -> list:
        rows = []
        for idx in self.table.selectionModel().selectedRows(0):
            r = self.model.row_data(idx.row())
            if r is not None:
                rows.append(r)
        return rows

    def _copy_selected(self, what: str) -> None:
        rows = self._selected_rows()
        if rows:
            self._copy("\n".join(r[what] for r in rows))

    def _selected_action(self, kind: str) -> None:
        rows = self._selected_rows()
        if rows:
            self._do_action(kind, rows[0]["repo_path"])

    def _do_action(self, kind: str, path: str) -> None:
        try:
            if kind == "folder":
                actions.open_folder(path)
            elif kind == "terminal":
                actions.open_terminal(path, self.settings.terminal_command)
            elif kind == "editor":
                actions.open_editor(path, self.settings.editor_command)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, "Could not open: {err}".format(err=exc))

    def _context_menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        r = self.model.row_data(idx.row()) if idx.isValid() else None
        if r is None:
            return
        m = QMenu(self)
        m.addAction("Copy hash", lambda: self._copy_selected("hash"))
        m.addAction("Copy message", lambda: self._copy_selected("message"))
        m.addSeparator()
        m.addAction("Open folder", lambda: self._do_action("folder", r["repo_path"]))
        m.addAction("Open terminal", lambda: self._do_action("terminal", r["repo_path"]))
        m.addAction("Open in editor", lambda: self._do_action("editor", r["repo_path"]))
        m.addSeparator()
        m.addAction(f"Author: {r['author_name']}", lambda: self._add_filter("authors", r["author_email"]))
        m.addAction(f"Repository: {r['repo_name']}", lambda: self._add_filter("repos", r["repo_name"]))
        if r["first_ref"]:
            m.addAction(f"Branch: {r['first_ref']}", lambda: self._add_filter("branches", r["first_ref"]))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _add_filter(self, field: str, value: str) -> None:
        vals = getattr(self.query, field)
        if value not in vals:
            vals.append(value)
        self._set_search_text(self.query.to_string())
        self.filters.set_query(self.query)
        self.run_search()

    # -- dialogs -----------------------------------------------------------------------
    def export(self) -> None:
        if not self.last_result or not self.last_result.ids:
            QMessageBox.information(self, "Export", "No results")
            return
        path, flt = QFileDialog.getSaveFileName(
            self, "Export results…", os.path.join(os.path.expanduser("~"), "comitra-results.csv"),
            "CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        fmt = "json" if path.lower().endswith(".json") or "JSON" in flt else "csv"
        if fmt == "json" and not path.lower().endswith(".json"):
            path += ".json"
        if fmt == "csv" and not path.lower().endswith(".csv"):
            path += ".csv"
        ids = list(self.last_result.ids)
        t = Task("export", export_results, fmt, ids, path)
        t.signals.done.connect(lambda _k, n: QMessageBox.information(
            self, "Export", "Exported {n} commits to {path}".format(n=n, path=path)))
        t.signals.failed.connect(lambda _k, e: QMessageBox.warning(self, "Export", "Export failed: {err}".format(err=e)))
        self._keep(t)
        self.statusBar().showMessage("Export" + "…", 3000)
        QThreadPool.globalInstance().start(t)

    def show_settings(self) -> None:
        before = (list(self.settings.roots), self.settings.index_files, self.settings.include_tags,
                  self.settings.include_remotes, list(self.settings.exclude_names), list(self.settings.excluded_paths),
                  self.settings.max_depth, self.settings.include_bare, self.settings.follow_symlinks)
        d = dialogs.SettingsDialog(self.settings, self)
        if d.exec() != dialogs.QDialog.Accepted:
            return
        d.apply()
        self.settings.save()
        theme.apply(self.settings.theme)
        self._apply_runtime_settings()
        self._update_central()
        after = (list(self.settings.roots), self.settings.index_files, self.settings.include_tags,
                 self.settings.include_remotes, list(self.settings.exclude_names), list(self.settings.excluded_paths),
                 self.settings.max_depth, self.settings.include_bare, self.settings.follow_symlinks)
        self.model.refresh_rows()
        self.run_search()
        if before != after and self.settings.roots:
            self.start_update(quiet=True)

    def set_theme(self, mode: str) -> None:
        self.settings.theme = mode
        theme.apply(mode)
        self.info_label.setStyleSheet(f"color:{theme.muted_color()}")
        self.model.refresh_rows()
        self.settings.save()

    def show_repos(self) -> None:
        d = dialogs.ReposDialog(self.conn, self)
        d.reindex.connect(self.reindex_repos)
        d.removed.connect(lambda: (self.search_thread.worker.resolver.clear(), self.refresh_side_data(), self.run_search()))
        d.search_repo.connect(lambda name: self._add_filter("repos", name))
        d.exclude.connect(self._exclude_paths)
        d.exec()

    def _exclude_paths(self, paths: list[str]) -> None:
        for p in paths:
            if p not in self.settings.excluded_paths:
                self.settings.excluded_paths.append(p)
        self.settings.save()

    def show_stats(self) -> None:
        ids = list(self.last_result.ids) if self.last_result and not self.query.is_empty() else None
        dialogs.StatsDialog(ids, self).exec()


def _short(path: str, n: int = 70) -> str:
    return path if len(path) <= n else "…" + path[-(n - 1):]
