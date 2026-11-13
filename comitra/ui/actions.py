"""Open a repository in the file manager, a terminal or an editor."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
        for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            env.pop(k, None)
    return env


def _spawn(cmd: list[str] | str, cwd: str, shell: bool = False, console: bool = False) -> None:
    kw: dict = {"cwd": cwd, "env": _clean_env(), "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        # Terminals get a new console; everything else must not flash a window.
        kw["creationflags"] = (0x00000010 if console else 0x08000000) | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, shell=shell, **kw)


def _custom(template: str, path: str, console: bool = False) -> None:
    if "{path}" in template:
        if sys.platform == "win32":
            cmd = template.replace("{path}", f'"{path}"')
            _spawn(cmd, path, shell=True, console=console)
            return
        cmd_s = template.replace("{path}", shlex.quote(path))
        _spawn(cmd_s, path, shell=True)
    else:
        if sys.platform == "win32":
            _spawn(f'{template} "{path}"', path, shell=True, console=console)
        else:
            _spawn(shlex.split(template) + [path], path)


def open_folder(path: str) -> None:
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        raise OSError("no file manager available")


def open_terminal(path: str, template: str = "") -> None:
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    if template.strip():
        _custom(template.strip(), path, console=True)
        return
    if sys.platform == "win32":
        if shutil.which("wt"):
            _spawn(["wt", "-d", path], path)
        elif shutil.which("pwsh"):
            _spawn(["pwsh", "-NoExit"], path, console=True)
        else:
            _spawn(["cmd.exe", "/K"], path, console=True)
        return
    if sys.platform == "darwin":
        _spawn(["open", "-a", "Terminal", path], path)
        return
    for term, args in (
        ("x-terminal-emulator", []),
        ("gnome-terminal", [f"--working-directory={path}"]),
        ("konsole", ["--workdir", path]),
        ("xfce4-terminal", [f"--working-directory={path}"]),
        ("mate-terminal", [f"--working-directory={path}"]),
        ("tilix", ["-w", path]),
        ("kitty", ["--directory", path]),
        ("alacritty", ["--working-directory", path]),
        ("wezterm", ["start", "--cwd", path]),
        ("foot", [f"--working-directory={path}"]),
        ("xterm", []),
    ):
        exe = shutil.which(term)
        if exe:
            _spawn([exe, *args], path)
            return
    raise OSError("no terminal emulator found; set one in Settings")


def open_editor(path: str, template: str = "") -> None:
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    if template.strip():
        _custom(template.strip(), path)
        return
    for ed in ("code", "codium", "cursor", "zed", "subl", "idea", "pycharm", "charm"):
        exe = shutil.which(ed)
        if exe:
            if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
                _spawn(f'"{exe}" "{path}"', path, shell=True)
            else:
                _spawn([exe, path], path)
            return
    if sys.platform == "darwin":
        for app in ("Visual Studio Code", "Cursor", "Zed", "Sublime Text"):
            if os.path.isdir(f"/Applications/{app}.app"):
                _spawn(["open", "-a", app, path], path)
                return
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        cand = os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe")
        if os.path.isfile(cand):
            _spawn([cand, path], path)
            return
    open_folder(path)
