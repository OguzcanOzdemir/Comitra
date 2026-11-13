import os

from comitra.config import Settings
from comitra.core import scanner


def test_auto_discovery_scans_home(tmp_path, monkeypatch, make_repo):
    home = tmp_path / "work"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    make_repo("projects/api").commit("x")
    make_repo("Documents/client/site").commit("y")
    make_repo(".oh-my-zsh").commit("tool repo")            # hidden: skipped
    make_repo("Tools.app/Contents/repo").commit("bundle")   # app bundle: skipped
    make_repo("projects/web/node_modules/dep").commit("z")  # excluded name: skipped

    s = Settings()
    assert s.auto_discover
    assert os.path.normpath(str(home)) in [os.path.normpath(r) for r in s.scan_roots()]

    rep = scanner.scan(s.scan_roots(), excludes=s.exclude_names, skip_hidden=s.skip_hidden)
    # On Windows other fixed drives are scanned too (e.g. the CI checkout on D:);
    # only look at what was found inside the fake home folder.
    home_s = os.path.normcase(os.path.normpath(str(home)))
    inside = [r.path for r in rep.repos if os.path.normcase(os.path.normpath(r.path)).startswith(home_s + os.sep)]
    found = sorted(os.path.relpath(p, home).replace(os.sep, "/") for p in inside)
    assert found == ["Documents/client/site", "projects/api"]

    rep = scanner.scan([str(home)], excludes=s.exclude_names, skip_hidden=False)
    assert ".oh-my-zsh" in [os.path.basename(r.path) for r in rep.repos]


def test_auto_discovery_off_uses_only_added_folders(tmp_path):
    s = Settings()
    s.auto_discover = False
    assert s.scan_roots() == []
    s.roots = [str(tmp_path)]
    assert s.scan_roots() == [str(tmp_path)]
