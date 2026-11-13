"""GUI entry point."""

from __future__ import annotations

import os
import sys

from .. import APP_NAME, __version__, config


def _icon_path() -> str | None:
    base = getattr(sys, "_MEIPASS", None)
    cands = []
    if base:
        cands.append(os.path.join(base, "comitra", "ui", "resources", "icon.png"))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icon.png"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def run_gui() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Comitra.Comitra")
        except Exception:
            pass
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("comitra")
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))

    settings = config.Settings.load()
    from . import theme

    theme.apply(settings.theme)
    from .main_window import MainWindow

    win = MainWindow(settings)
    win.show()
    return app.exec()
