"""Filter panel. Mirrors the filter part of a :class:`Query` both ways."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDateEdit, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout,
    QWidget,
)

from ..core.query import DateFilter, Query, _split_values

DATE_CHOICES = [
    ("", "Any time"), ("today", "Today"), ("yesterday", "Yesterday"), ("7d", "Last 7 days"),
    ("30d", "Last 30 days"), ("month", "This month"), ("year", "This year"),
    ("single", "Single day"), ("range", "Date range"),
]
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def _join(values: list[str]) -> str:
    return ", ".join(values)


class FilterPanel(QScrollArea):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(260)
        self._updating = False
        self._debounce = QTimer(self, singleShot=True, interval=300)
        self._debounce.timeout.connect(self._emit)
        inner = QWidget()
        self.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Authors -------------------------------------------------------------------
        g = QGroupBox("Authors")
        gl = QVBoxLayout(g)
        self.author_edit = QLineEdit(placeholderText="Add author (name or e-mail)…")
        self.author_model = QStringListModel(self)
        comp = QCompleter(self.author_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(15)
        self.author_edit.setCompleter(comp)
        comp.activated.connect(lambda text: QTimer.singleShot(0, lambda: self._add_author(text)))
        self.author_edit.returnPressed.connect(lambda: self._add_author(self.author_edit.text()))
        self.author_list = QListWidget()
        self.author_list.setMaximumHeight(90)
        self.author_list.setToolTip("Remove")
        self.author_list.itemDoubleClicked.connect(self._remove_author)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: [self._remove_author(i) for i in self.author_list.selectedItems()])
        gl.addWidget(self.author_edit)
        gl.addWidget(self.author_list)
        gl.addWidget(rm, alignment=Qt.AlignRight)
        lay.addWidget(g)

        # Date ---------------------------------------------------------------------
        g = QGroupBox("Date")
        gl = QFormLayout(g)
        self.date_combo = QComboBox()
        for key, label in DATE_CHOICES:
            self.date_combo.addItem(label, key)
        today = date.today()
        self.date_from = QDateEdit(_qdate(today - timedelta(days=30)), calendarPopup=True, displayFormat="yyyy-MM-dd")
        self.date_to = QDateEdit(_qdate(today), calendarPopup=True, displayFormat="yyyy-MM-dd")
        self.lbl_from, self.lbl_to = QLabel("From"), QLabel("To")
        gl.addRow(self.date_combo)
        gl.addRow(self.lbl_from, self.date_from)
        gl.addRow(self.lbl_to, self.date_to)
        self.date_combo.currentIndexChanged.connect(self._date_mode_changed)
        self.date_from.dateChanged.connect(self._changed_now)
        self.date_to.dateChanged.connect(self._changed_now)
        lay.addWidget(g)

        # Repos ---------------------------------------------------------------------
        g = QGroupBox("Repositories")
        gl = QVBoxLayout(g)
        self.repo_filter = QLineEdit(placeholderText="Filter repositories…")
        self.repo_filter.textChanged.connect(self._filter_repo_list)
        self.repo_list = QListWidget()
        self.repo_list.setMinimumHeight(110)
        self.repo_list.itemChanged.connect(self._changed_now)
        gl.addWidget(self.repo_filter)
        gl.addWidget(self.repo_list)
        lay.addWidget(g)

        # Text-ish filters ----------------------------------------------------------
        g = QGroupBox("Branch")
        gl = QFormLayout(g)
        self.branch_edit = QLineEdit(placeholderText="Branch patterns, e.g. main, feature/*")
        self.branch_model = QStringListModel(self)
        bc = QCompleter(self.branch_model, self)
        bc.setCaseSensitivity(Qt.CaseInsensitive)
        bc.setFilterMode(Qt.MatchContains)
        self.branch_edit.setCompleter(bc)
        self.hash_edit = QLineEdit(placeholderText="Full or short hash")
        self.file_edit = QLineEdit(placeholderText="e.g. *.py, src/auth/")
        gl.addRow(self.branch_edit)
        gl.addRow(QLabel("Commit hash"))
        gl.addRow(self.hash_edit)
        gl.addRow(QLabel("Changed file"))
        gl.addRow(self.file_edit)
        for w in (self.branch_edit, self.hash_edit, self.file_edit):
            w.textEdited.connect(self._changed_later)
            w.returnPressed.connect(self._changed_now)
        lay.addWidget(g)

        # Merge / time ------------------------------------------------------------
        g = QGroupBox("Merge commits")
        gl = QFormLayout(g)
        self.merge_combo = QComboBox()
        for key, label in (("show", "Show"), ("hide", "Hide"), ("only", "Only merges")):
            self.merge_combo.addItem(label, key)
        self.merge_combo.currentIndexChanged.connect(self._changed_now)
        gl.addRow(self.merge_combo)
        lay.addWidget(g)

        g = QGroupBox("Time of day")
        gl = QHBoxLayout(g)
        self.hour_check = QCheckBox()
        self.hour_from = QSpinBox(minimum=0, maximum=23, value=9, suffix=":00")
        self.hour_to = QSpinBox(minimum=0, maximum=24, value=12, suffix=":00")
        for w in (self.hour_from, self.hour_to):
            w.valueChanged.connect(self._hours_changed)
        self.hour_check.toggled.connect(self._changed_now)
        gl.addWidget(self.hour_check)
        gl.addWidget(self.hour_from)
        gl.addWidget(QLabel("–"))
        gl.addWidget(self.hour_to)
        gl.addStretch(1)
        lay.addWidget(g)

        g = QGroupBox("Weekdays")
        gl = QHBoxLayout(g)
        gl.setSpacing(2)
        self.day_buttons: list[QToolButton] = []
        for label in DAY_LABELS:
            b = QToolButton(text=label, checkable=True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.toggled.connect(self._changed_now)
            self.day_buttons.append(b)
            gl.addWidget(b)
        lay.addWidget(g)

        g = QGroupBox("Commits no longer on any branch")
        gl = QFormLayout(g)
        self.unreach_combo = QComboBox()
        for key, label in (("hide", "Hide"), ("include", "Include"), ("only", "Only these")):
            self.unreach_combo.addItem(label, key)
        self.unreach_combo.currentIndexChanged.connect(self._changed_now)
        gl.addRow(self.unreach_combo)
        lay.addWidget(g)

        reset = QPushButton("Reset filters")
        reset.clicked.connect(self.reset)
        lay.addWidget(reset)
        lay.addStretch(1)
        self._date_mode_changed(emit=False)

    # -- population ----------------------------------------------------------------
    def set_repos(self, repos: list[tuple[str, str, int]]) -> None:
        """repos: (name, path, commit_count)."""
        checked = set(self._checked_repos())
        self._updating = True
        self.repo_list.clear()
        seen = set()
        for name, path, count in repos:
            if name in seen:
                continue
            seen.add(name)
            it = QListWidgetItem(f"{name}")
            it.setData(Qt.UserRole, name)
            it.setToolTip(f"{path}\n{count} commits")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if name in checked else Qt.Unchecked)
            self.repo_list.addItem(it)
        for name in checked - seen:
            self._add_repo_item(name, True)
        self._updating = False
        self._filter_repo_list(self.repo_filter.text())

    def set_author_suggestions(self, values: list[str]) -> None:
        self.author_model.setStringList(values)

    def set_branch_suggestions(self, values: list[str]) -> None:
        self.branch_model.setStringList(values)

    # -- query <-> widgets ---------------------------------------------------------
    def set_query(self, q: Query) -> None:
        self._updating = True
        try:
            self.author_list.clear()
            for a in q.authors:
                self.author_list.addItem(a)
            # date
            key = ""
            if q.date and q.date.preset and self.date_combo.findData(q.date.preset) >= 0:
                key = q.date.preset
            elif q.date or q.after or q.before:
                start, end = q.date_range()
                key = "single" if start and end and end - start == timedelta(days=1) else "range"
                if start:
                    self.date_from.setDate(_qdate(start))
                if end:
                    self.date_to.setDate(_qdate(end - timedelta(days=1)))
            self.date_combo.setCurrentIndex(max(0, self.date_combo.findData(key)))
            self._date_mode_changed(emit=False)
            # repos
            wanted = set(q.repos)
            present = set()
            for i in range(self.repo_list.count()):
                it = self.repo_list.item(i)
                name = it.data(Qt.UserRole)
                present.add(name)
                it.setCheckState(Qt.Checked if name in wanted else Qt.Unchecked)
            for name in q.repos:
                if name not in present:
                    self._add_repo_item(name, True)
            self.branch_edit.setText(_join(q.branches))
            self.hash_edit.setText(_join(q.hashes))
            self.file_edit.setText(_join(q.files))
            self.merge_combo.setCurrentIndex(max(0, self.merge_combo.findData(q.merge)))
            self.hour_check.setChecked(q.hours is not None)
            if q.hours:
                self.hour_from.setValue(q.hours[0])
                self.hour_to.setValue(q.hours[1] or 24)
            for i, b in enumerate(self.day_buttons):
                b.setChecked(i in q.days)
            self.unreach_combo.setCurrentIndex(max(0, self.unreach_combo.findData(q.unreachable)))
        finally:
            self._updating = False

    def apply_to(self, base: Query) -> Query:
        """Return *base* with its filter fields replaced by the panel state."""
        q = base.copy()
        q.authors = [self.author_list.item(i).text() for i in range(self.author_list.count())]
        key = self.date_combo.currentData()
        q.after = q.before = None
        if not key:
            q.date = None
        elif key == "single":
            d = _pydate(self.date_from.date())
            q.date = DateFilter(start=d, end=d)
        elif key == "range":
            a, b = _pydate(self.date_from.date()), _pydate(self.date_to.date())
            if a > b:
                a, b = b, a
            q.date = DateFilter(start=a, end=b)
        else:
            q.date = DateFilter(preset=key)
        q.repos = self._checked_repos()
        q.branches = _split_values(self.branch_edit.text())
        q.hashes = [h.lower() for h in _split_values(self.hash_edit.text()) if h.strip()]
        q.files = _split_values(self.file_edit.text())
        q.merge = self.merge_combo.currentData()
        q.hours = None
        if self.hour_check.isChecked():
            a, b = self.hour_from.value(), self.hour_to.value() % 24
            if a != b:
                q.hours = (a, b)
        q.days = [i for i, b in enumerate(self.day_buttons) if b.isChecked()]
        q.unreachable = self.unreach_combo.currentData()
        return q

    def reset(self) -> None:
        self.set_query(Query())
        self._changed_now()

    # -- internals ---------------------------------------------------------------
    def _checked_repos(self) -> list[str]:
        out = []
        for i in range(self.repo_list.count()):
            it = self.repo_list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _add_repo_item(self, name: str, checked: bool) -> None:
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, name)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.repo_list.insertItem(0, it)

    def _filter_repo_list(self, text: str) -> None:
        t = text.lower().strip()
        for i in range(self.repo_list.count()):
            it = self.repo_list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower() and it.checkState() != Qt.Checked)

    def _add_author(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        existing = {self.author_list.item(i).text() for i in range(self.author_list.count())}
        if text not in existing:
            self.author_list.addItem(text)
            self._changed_now()
        self.author_edit.clear()

    def _remove_author(self, item) -> None:
        self.author_list.takeItem(self.author_list.row(item))
        self._changed_now()

    def _date_mode_changed(self, *_args, emit: bool = True) -> None:
        key = self.date_combo.currentData()
        show_from = key in ("single", "range")
        show_to = key == "range"
        self.date_from.setVisible(show_from)
        self.lbl_from.setVisible(show_from)
        self.lbl_from.setText("Day" if key == "single" else "From")
        self.date_to.setVisible(show_to)
        self.lbl_to.setVisible(show_to)
        if emit:
            self._changed_now()

    def _hours_changed(self, *_):
        if not self._updating:
            if not self.hour_check.isChecked():
                self._updating = True
                self.hour_check.setChecked(True)
                self._updating = False
            self._changed_now()

    def _changed_later(self, *_):
        if not self._updating:
            self._debounce.start(350)

    def _changed_now(self, *_):
        if not self._updating:
            self._debounce.start(0)

    def _emit(self) -> None:
        if not self._updating:
            self.changed.emit()
