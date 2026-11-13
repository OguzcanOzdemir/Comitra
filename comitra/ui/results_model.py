"""Virtual results model: knows all matching ids, loads rows lazily in blocks."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QAbstractTextDocumentLayout, QBrush, QColor, QFont, QPalette, QTextDocument
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core import search
from ..core.textnorm import highlight_html
from . import theme

COLS = ["Date", "Repo", "Author", "Message", "Branch / ref", "Hash"]
COL_DATE, COL_REPO, COL_AUTHOR, COL_MSG, COL_BRANCH, COL_HASH = range(6)
BLOCK = 200
MAX_BLOCKS = 60
ROLE_COMMIT_ID = Qt.UserRole + 1
ROLE_IS_GROUP = Qt.UserRole + 2
ROLE_HTML = Qt.UserRole + 3


def fmt_time(ts: int, tz_min: int | None = None, with_tz: bool = False) -> str:
    try:
        if tz_min is None:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        dt = datetime.fromtimestamp(ts, timezone(timedelta(minutes=tz_min)))
        return dt.strftime("%Y-%m-%d %H:%M:%S %z" if with_tz else "%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "?"


class ResultsModel(QAbstractTableModel):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.entries: list[tuple] = []  # ("c", id) or ("g", label, count)
        self.ids: list[int] = []
        self.terms: list[tuple[str, bool]] = []
        self.date_basis = "author"
        self._blocks: OrderedDict[int, dict] = OrderedDict()
        self._entry_block: list[int] = []

    # -- data loading ----------------------------------------------------------
    def set_result(self, res: search.SearchResult, group_by: str | None, date_basis: str) -> None:
        self.beginResetModel()
        self.ids = res.ids
        self.terms = res.highlight_terms
        self.date_basis = date_basis
        self._blocks.clear()
        entries: list[tuple] = []
        if res.groups is not None and group_by:
            repo_names = {}
            if group_by == "repo":
                repo_names = {r[0]: r[1] for r in self.conn.execute("SELECT id, name FROM repos")}
            counts: dict = {}
            for g in res.groups:
                counts[g] = counts.get(g, 0) + 1
            last = object()
            for cid, g in zip(res.ids, res.groups):
                if g != last:
                    label = repo_names.get(g, "?") if group_by == "repo" else (g or "?")
                    entries.append(("g", str(label), counts[g]))
                    last = g
                entries.append(("c", cid))
        else:
            entries = [("c", cid) for cid in res.ids]
        self.entries = entries
        self.endResetModel()

    def clear(self) -> None:
        self.set_result(search.SearchResult(), None, self.date_basis)

    def refresh_rows(self) -> None:
        self._blocks.clear()
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, len(COLS) - 1))

    def _row(self, r: int):
        e = self.entries[r]
        if e[0] != "c":
            return None
        b = r // BLOCK
        block = self._blocks.get(b)
        if block is None:
            ids = [x[1] for x in self.entries[b * BLOCK : (b + 1) * BLOCK] if x[0] == "c"]
            block = search.fetch_rows(self.conn, ids)
            self._blocks[b] = block
            if len(self._blocks) > MAX_BLOCKS:
                self._blocks.popitem(last=False)
        else:
            self._blocks.move_to_end(b)
        return block.get(e[1])

    def commit_id(self, r: int) -> int | None:
        if 0 <= r < len(self.entries) and self.entries[r][0] == "c":
            return self.entries[r][1]
        return None

    def row_data(self, r: int):
        return self._row(r) if 0 <= r < len(self.entries) else None

    def is_group(self, r: int) -> bool:
        return 0 <= r < len(self.entries) and self.entries[r][0] == "g"

    # -- Qt model API --------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if self.is_group(index.row()):
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        e = self.entries[r]
        if e[0] == "g":
            if role == Qt.DisplayRole:
                return f"{e[1]}  ({e[2]})" if c == 0 else None
            if role == Qt.FontRole:
                f = QFont()
                f.setBold(True)
                return f
            if role == Qt.BackgroundRole:
                return QBrush(QColor(0x80, 0x80, 0x80, 40))
            if role == ROLE_IS_GROUP:
                return True
            return None
        if role == ROLE_COMMIT_ID:
            return e[1]
        if role == ROLE_IS_GROUP:
            return False
        row = self._row(r)
        if row is None:
            return None
        if role == Qt.DisplayRole:
            if c == COL_DATE:
                t = row["commit_time"] if self.date_basis == "committer" else row["author_time"]
                return fmt_time(t)
            if c == COL_REPO:
                return row["repo_name"]
            if c == COL_AUTHOR:
                return row["author_name"]
            if c == COL_MSG:
                return row["subject"]
            if c == COL_BRANCH:
                return row["first_ref"]
            if c == COL_HASH:
                return row["hash"][:10]
        elif role == ROLE_HTML and c == COL_MSG:
            bg, fg = theme.match_colors()
            return highlight_html(
                row["subject"], self.terms, f'<span style="background-color:{bg};color:{fg};">', "</span>"
            )
        elif role == Qt.ToolTipRole:
            if c == COL_MSG:
                msg = row["message"]
                return msg if len(msg) < 2000 else msg[:2000] + "…"
            if c == COL_AUTHOR:
                return f"{row['author_name']} <{row['author_email']}>"
            if c == COL_REPO:
                return row["repo_path"]
            if c == COL_HASH:
                return row["hash"]
        elif role == Qt.ForegroundRole and not row["reachable"]:
            return QBrush(QColor(theme.muted_color()))
        elif role == Qt.FontRole and not row["reachable"] and c == COL_MSG:
            f = QFont()
            f.setItalic(True)
            return f
        elif role == Qt.FontRole and c == COL_HASH:
            f = QFont("monospace")
            f.setStyleHint(QFont.Monospace)
            return f
        return None


class HighlightDelegate(QStyledItemDelegate):
    """Renders the message column with matched words highlighted."""

    def paint(self, painter, option, index):
        html = index.data(ROLE_HTML)
        if not html or index.data(ROLE_IS_GROUP):
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else None
        opt.text = ""
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(opt.font)
        selected = bool(opt.state & QStyle.State_Selected)
        color = opt.palette.color(QPalette.HighlightedText if selected else QPalette.Text)
        fg = index.data(Qt.ForegroundRole)
        if fg is not None and not selected:
            color = fg.color()
        doc.setHtml(f'<span style="color:{color.name()};white-space:pre;">{html}</span>')
        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget) if style else opt.rect
        painter.save()
        painter.setClipRect(text_rect)
        y = text_rect.top() + max(0, (text_rect.height() - doc.size().height()) / 2)
        painter.translate(text_rect.left(), y)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), 22))


__all__ = ["ResultsModel", "HighlightDelegate", "QRect"]
