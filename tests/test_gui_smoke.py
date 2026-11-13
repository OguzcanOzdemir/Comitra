"""Offscreen smoke test of the GUI: build every window and run a search."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    try:
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    except Exception as exc:  # pragma: no cover - no Qt platform available
        pytest.skip(f"Qt not usable: {exc}")
    return app


def _wait(app, cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_main_window_end_to_end(qapp, tmp_path, monkeypatch, make_repo):
    monkeypatch.setenv("COMITRA_HOME", str(tmp_path / "home"))
    r = make_repo("shop")
    r.commit("Fix café payment error")
    r.commit("Shopping cart page")

    from comitra.config import Settings
    from comitra.core.indexer import IndexSummary, RepoResult
    from comitra.core.scanner import ScanReport
    from comitra.core.service import UpdateReport
    from comitra.ui import dialogs
    from comitra.ui.main_window import MainWindow

    s = Settings()
    s.roots = [str(tmp_path / "work")]
    s.auto_discover = False
    s.save()
    w = MainWindow(Settings.load())
    w.show()
    assert _wait(qapp, lambda: w.index_thread is None and w.model.rowCount() == 2), w.status_label.text()

    w.search_edit.setText("cafe")
    w._query_text_changed()
    assert _wait(qapp, lambda: w.model.rowCount() == 1)
    assert w.detail.row is not None and w.detail.row["subject"] == "Fix café payment error"

    # panel -> search box
    w.filters.merge_combo.setCurrentIndex(w.filters.merge_combo.findData("hide"))
    assert _wait(qapp, lambda: "merge:hide" in w.search_edit.text())
    # search box -> panel
    w.search_edit.setText("date:7d repo:shop")
    w._query_text_changed()
    assert w.filters.date_combo.currentData() == "7d"

    # dialogs construct without errors
    dialogs.SettingsDialog(w.settings, w).apply()
    dialogs.ReposDialog(w.conn, w).load()
    dialogs.SavedSearchesDialog(w.conn, w).load()
    st = dialogs.StatsDialog(None, w)
    assert _wait(qapp, lambda: st.t_repo.rowCount() == 1)
    rep = UpdateReport(ScanReport(), IndexSummary(results=[RepoResult(1, "shop", r.path, status="updated")]))
    dialogs.SummaryDialog(rep, w)

    for mode in ("dark", "light", "system"):
        w.set_theme(mode)
    w.close()
