"""Settings and data locations, including portable mode.

Portable mode keeps settings and the database next to the application
instead of in the user's profile. It is enabled when any of these is true:

* ``--portable`` on the command line
* the environment variable ``COMITRA_HOME`` is set (its value is the data dir)
* a file named ``comitra-portable.txt`` exists next to the executable (or,
  on macOS, next to ``Comitra.app``)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields

from . import APP_ID, APP_NAME
from .core.scanner import DEFAULT_EXCLUDES

PORTABLE_MARKER = "comitra-portable.txt"
_forced_portable = False


def force_portable(enabled: bool = True) -> None:
    global _forced_portable
    _forced_portable = enabled


def app_dir() -> str:
    """Directory containing the executable (or the source checkout)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if sys.platform == "darwin" and exe_dir.endswith(os.path.join("Contents", "MacOS")):
            # .../Comitra.app/Contents/MacOS -> folder containing Comitra.app
            return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def portable_dir() -> str | None:
    env = os.environ.get("COMITRA_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    base = app_dir()
    if _forced_portable or os.path.isfile(os.path.join(base, PORTABLE_MARKER)):
        return os.path.join(base, "comitra-data")
    return None


def is_portable() -> bool:
    return portable_dir() is not None


def data_dir() -> str:
    p = portable_dir()
    if p:
        return p
    from platformdirs import user_data_dir

    return user_data_dir(APP_NAME, appauthor=False, roaming=False)


def config_dir() -> str:
    p = portable_dir()
    if p:
        return p
    from platformdirs import user_config_dir

    return user_config_dir(APP_NAME, appauthor=False, roaming=True)


def db_path() -> str:
    return os.path.join(data_dir(), f"{APP_ID}.sqlite3")


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def default_workers() -> int:
    return max(2, min(8, (os.cpu_count() or 4)))


@dataclass
class Settings:
    roots: list[str] = field(default_factory=list)
    exclude_names: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    excluded_paths: list[str] = field(default_factory=list)
    max_depth: int = 8
    follow_symlinks: bool = False
    include_bare: bool = True

    workers: int = field(default_factory=default_workers)
    include_tags: bool = True
    include_remotes: bool = True
    index_files: bool = False
    keep_unreachable: bool = True

    fetch_before_scan: bool = False
    fetch_timeout: int = 60
    fetch_workers: int = 3

    update_on_start: bool = True
    auto_update_minutes: int = 0
    watch_repos: bool = True

    date_basis: str = "author"   # author | committer
    show_unreachable: bool = False
    page_size: int = 500

    git_path: str = ""
    terminal_command: str = ""   # "" = auto; may contain {path}
    editor_command: str = ""     # "" = auto (VS Code if found); may contain {path}
    theme: str = "system"        # system | light | dark

    window_geometry: str = ""
    window_state: str = ""
    group_by: str = ""
    first_run_done: bool = False

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or settings_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls()
        for k, v in raw.items() if isinstance(raw, dict) else ():
            if k in known and isinstance(v, type(getattr(s, k))):
                setattr(s, k, v)
        return s

    def save(self, path: str | None = None) -> None:
        path = path or settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def index_options(self, force_full: bool = False, fetch: bool | None = None):
        from .core.indexer import IndexOptions

        return IndexOptions(
            workers=self.workers,
            include_tags=self.include_tags,
            include_remotes=self.include_remotes,
            index_files=self.index_files,
            keep_unreachable=self.keep_unreachable,
            fetch=self.fetch_before_scan if fetch is None else fetch,
            fetch_timeout=self.fetch_timeout,
            fetch_workers=self.fetch_workers,
            force_full=force_full,
        )
