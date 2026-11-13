"""Discover git repositories below a set of root folders.

Handles normal repositories (``.git`` directory), submodules and linked
worktrees (``.git`` *file*), and bare repositories. Linked worktrees share
their refs with the main repository, so repositories are de-duplicated by the
real path of their *common* git directory.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

DEFAULT_EXCLUDES = [
    "node_modules", "bower_components", "venv", ".venv", "env", ".env", "__pycache__",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".gradle", ".idea",
    ".vscode", "Pods", "DerivedData", ".cache", ".npm", ".yarn", ".pnpm-store",
    ".cargo", ".rustup", "site-packages", "$RECYCLE.BIN", "System Volume Information",
    ".Trash", ".Trashes", "Library", "AppData",
]

# Skipped only directly below a drive / filesystem root (e.g. C:\Windows).
SYSTEM_ROOT_DIRS = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
    "recovery", "perflogs", "system volume information", "$windows.~bt", "$windows.~ws",
    "msocache", "intel", "amd", "nvidia",
}

# Bundles/packages that are directories but never contain user repositories.
PACKAGE_SUFFIXES = (
    ".app", ".photoslibrary", ".musiclibrary", ".tvlibrary", ".bundle", ".framework",
    ".xcassets", ".lproj", ".imovielibrary", ".fcpbundle",
)


def _windows_extra_drives() -> list[str]:
    """Fixed drives other than the system drive (for example D: and E:)."""
    try:
        import ctypes
        import string

        system = os.environ.get("SystemDrive", "C:").upper().rstrip("\\")
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = []
        for i, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << i):
                continue
            root = f"{letter}:\\"
            if f"{letter}:" == system:
                continue
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                drives.append(root)
        return drives
    except Exception:
        return []


def default_roots() -> list[str]:
    """Folders searched automatically: the user's home (and extra fixed drives on Windows)."""
    roots = [os.path.expanduser("~")]
    if sys.platform == "win32":
        roots += _windows_extra_drives()
    return [r for r in roots if r and os.path.isdir(r)]


@dataclass
class FoundRepo:
    path: str          # work tree (or bare git dir) shown to the user
    git_dir: str       # the repository's own git dir
    common_dir: str    # shared git dir (same as git_dir unless linked worktree)
    is_bare: bool = False


@dataclass
class ScanReport:
    repos: list[FoundRepo] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    dirs_visited: int = 0


def _read_gitfile(path: str) -> str | None:
    """Resolve a ``.git`` file (``gitdir: ...``) to an absolute directory."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    target = line[len("gitdir:"):].strip()
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(path), target)
    target = os.path.normpath(target)
    return target if os.path.isdir(target) else None


def _common_dir(git_dir: str) -> str:
    """Linked worktrees have a ``commondir`` file pointing to the main git dir."""
    cd_file = os.path.join(git_dir, "commondir")
    if os.path.isfile(cd_file):
        try:
            with open(cd_file, "r", encoding="utf-8", errors="replace") as fh:
                rel = fh.readline().strip()
            target = rel if os.path.isabs(rel) else os.path.join(git_dir, rel)
            target = os.path.normpath(target)
            if os.path.isdir(target):
                return target
        except OSError:
            pass
    return git_dir


def _is_bare_repo(path: str) -> bool:
    return (
        os.path.isfile(os.path.join(path, "HEAD"))
        and os.path.isdir(os.path.join(path, "objects"))
        and os.path.isdir(os.path.join(path, "refs"))
    )


def _real(p: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(p))
    except OSError:
        return os.path.normcase(os.path.abspath(p))


def scan(
    roots: Iterable[str],
    excludes: Iterable[str] = DEFAULT_EXCLUDES,
    excluded_paths: Iterable[str] = (),
    max_depth: int = 8,
    follow_symlinks: bool = False,
    include_bare: bool = True,
    skip_hidden: bool = True,
    cancel: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    report = ScanReport()
    exclude_names = {e.lower() for e in excludes}
    excluded_real = {_real(p) for p in excluded_paths if p}
    by_common: dict[str, FoundRepo] = {}
    visited: set[str] = set()

    def add(found: FoundRepo, is_main_worktree: bool) -> None:
        key = _real(found.common_dir)
        existing = by_common.get(key)
        if existing is None:
            by_common[key] = found
        elif is_main_worktree and existing.git_dir != existing.common_dir:
            # Prefer the main worktree over a linked one for display.
            by_common[key] = found

    for root in roots:
        if not root:
            continue
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            report.errors.append((root, "folder not found"))
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            if cancel is not None and cancel.is_set():
                break
            current, depth = stack.pop()
            real = _real(current)
            if real in visited or real in excluded_real:
                continue
            visited.add(real)
            report.dirs_visited += 1
            if progress is not None and report.dirs_visited % 200 == 0:
                progress(current)
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError) as exc:
                if current == root:
                    report.errors.append((current, str(exc)))
                continue

            names = {e.name for e in entries}
            if ".git" in names:
                git_entry = os.path.join(current, ".git")
                if os.path.isdir(git_entry):
                    git_dir = os.path.normpath(git_entry)
                    common = _common_dir(git_dir)
                    add(FoundRepo(current, git_dir, common), True)
                elif os.path.isfile(git_entry):
                    git_dir = _read_gitfile(git_entry)
                    if git_dir:
                        common = _common_dir(git_dir)
                        is_main = _real(common) == _real(git_dir)
                        add(FoundRepo(current, git_dir, common), is_main)
            elif include_bare and _is_bare_repo(current):
                add(FoundRepo(current, current, current, is_bare=True), True)
                continue  # nothing interesting inside a bare repo

            if depth >= max_depth:
                continue
            at_fs_root = os.path.dirname(current.rstrip("\\/")) == current.rstrip("\\/") or \
                os.path.dirname(current) == current
            for entry in entries:
                name = entry.name
                low = name.lower()
                if name == ".git" or low in exclude_names:
                    continue
                if skip_hidden and name.startswith(".") and not (include_bare and low.endswith(".git")):
                    continue
                if low.endswith(PACKAGE_SUFFIXES) or (at_fs_root and low in SYSTEM_ROOT_DIRS):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=follow_symlinks):
                        continue
                    if not follow_symlinks and entry.is_symlink():
                        continue
                except OSError:
                    continue
                stack.append((entry.path, depth + 1))

    report.repos = sorted(by_common.values(), key=lambda r: r.path.lower())
    return report
