"""Light / dark / system themes."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

_original_style: str | None = None
_original_palette: QPalette | None = None


def _dark_palette() -> QPalette:
    p = QPalette()
    base, alt, text = QColor("#1e1f22"), QColor("#2b2d31"), QColor("#e6e6e6")
    p.setColor(QPalette.Window, QColor("#26282c"))
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, alt)
    p.setColor(QPalette.ToolTipBase, alt)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor("#303236"))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor("#ff6b6b"))
    p.setColor(QPalette.Link, QColor("#6cb6ff"))
    p.setColor(QPalette.Highlight, QColor("#2f6fd0"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#8a8d93"))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#6b6e74"))
    return p


def _light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f3f4f6"))
    p.setColor(QPalette.WindowText, QColor("#1f2328"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#f6f8fa"))
    p.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipText, QColor("#1f2328"))
    p.setColor(QPalette.Text, QColor("#1f2328"))
    p.setColor(QPalette.Button, QColor("#f6f8fa"))
    p.setColor(QPalette.ButtonText, QColor("#1f2328"))
    p.setColor(QPalette.Link, QColor("#0969da"))
    p.setColor(QPalette.Highlight, QColor("#0969da"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#8c959f"))
    return p


DARK_QSS = """
QCheckBox::indicator, QAbstractItemView::indicator, QGroupBox::indicator {
    width: 13px; height: 13px; border: 1px solid #8a8d93; border-radius: 3px; background: #1e1f22;
}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked, QGroupBox::indicator:checked {
    background: #2f6fd0; border-color: #6cb6ff;
}
QCheckBox::indicator:disabled { border-color: #4a4d52; }
QToolButton:checked { background: #2f6fd0; color: #ffffff; }
"""


def apply(mode: str) -> None:
    global _original_style, _original_palette
    app = QApplication.instance()
    if app is None:
        return
    if _original_style is None:
        _original_style = app.style().name()
        _original_palette = QPalette(app.palette())
    if mode == "dark":
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(_dark_palette())
        app.setStyleSheet(DARK_QSS)
        return
    app.setStyleSheet("")
    if mode == "light":
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(_light_palette())
    else:
        if _original_style:
            app.setStyle(QStyleFactory.create(_original_style) or QStyleFactory.create("Fusion"))
        if _original_palette is not None:
            app.setPalette(_original_palette)


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Window).lightness() < 128


def match_colors() -> tuple[str, str]:
    """Background and foreground used to highlight matched words."""
    return ("#7a5b00", "#ffffff") if is_dark() else ("#fff3a3", "#000000")


def muted_color() -> str:
    return "#8a8d93" if is_dark() else "#6e7781"
