from comitra import config


def test_read_only_portable_folder_falls_back(monkeypatch):
    monkeypatch.delenv("COMITRA_HOME", raising=False)
    monkeypatch.setattr(config, "_portable_cache", None)
    config.force_portable(True)
    try:
        monkeypatch.setattr(config, "_writable_dir", lambda p: False)
        assert config.portable_requested()
        assert config.portable_dir() is None
        assert not config.is_portable()
        monkeypatch.setattr(config, "_portable_cache", None)
        monkeypatch.setattr(config, "_writable_dir", lambda p: True)
        assert config.portable_dir().endswith("comitra-data")
    finally:
        config.force_portable(False)
        config._portable_cache = None


def test_settings_ignore_bad_types(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"max_depth": "deep", "roots": ["/x"], "unknown": 1, "workers": 3}', encoding="utf-8")
    s = config.Settings.load(str(p))
    assert s.max_depth == 8 and s.roots == ["/x"] and s.workers == 3
