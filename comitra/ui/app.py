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

    _install_error_handler()
    try:
        settings = config.Settings.load()
        from . import theme

        theme.apply(settings.theme)
        from .main_window import MainWindow

        win = MainWindow(settings)
    except Exception as exc:
        _log_exception(type(exc), exc, exc.__traceback__)
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None, APP_NAME,
            f"Comitra could not start:\n\n{exc}\n\nDetails were written to:\n{_safe_log_path()}",
        )
        return 1
    if config.portable_requested() and not config.is_portable():
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            win, APP_NAME,
            "The portable folder is read-only, so Comitra stores its data in your user profile instead:\n"
            f"{config.data_dir()}",
        )
    win.show()
    return app.exec()


def _safe_log_path() -> str:
    try:
        return config.log_path()
    except Exception:
        return "(unavailable)"


def _log_exception(exc_type, exc, tb) -> None:
    import traceback
    from datetime import datetime

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        sys.__stderr__.write(text)  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        path = config.log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now().isoformat(timespec='seconds')} Comitra {__version__}\n{text}\n")
    except Exception:
        pass


def _install_error_handler() -> None:
    """Log unexpected errors and tell the user instead of failing silently."""
    shown = {"n": 0}

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _log_exception(exc_type, exc, tb)
        if shown["n"] >= 3:  # never flood the user with dialogs
            return
        shown["n"] += 1
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            QMessageBox.warning(
                QApplication.activeWindow(), APP_NAME,
                f"Something went wrong: {exc}\n\nComitra keeps running. Details were written to:\n{_safe_log_path()}",
            )
        except Exception:
            pass

    sys.excepthook = hook
