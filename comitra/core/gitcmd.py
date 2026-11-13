"""Thin, safe wrapper around the ``git`` command line.

Every git call in Comitra goes through this module so that the following are
applied consistently on all platforms:

* UTF-8 output regardless of the user's locale (``i18n.logOutputEncoding``,
  ``core.quotepath=off``), decoded with ``errors="replace"``.
* No interactive prompts (``GIT_TERMINAL_PROMPT=0``, credential helpers set to
  non-interactive) so that a call can never hang waiting for a password.
* No optional locks (``GIT_OPTIONAL_LOCKS=0``) so that Comitra never competes
  with the user's own git commands for ``index.lock``.
* No console windows popping up on Windows (``CREATE_NO_WINDOW``).
* Timeouts that kill the whole process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Iterator

_BASE_CONFIG = [
    "-c", "core.quotepath=off",
    "-c", "i18n.logOutputEncoding=UTF-8",
    "-c", "log.showSignature=false",
    "-c", "color.ui=false",
    "-c", "core.pager=cat",
    "-c", "credential.interactive=never",
]

_git_path_override: str | None = None
_git_path_cache: str | None = None


class GitNotFoundError(RuntimeError):
    """Raised when no usable git executable can be located."""


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str):
        self.args_list = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(args[:3])} failed ({returncode}): {self.stderr[:500]}")

    @property
    def is_lock_error(self) -> bool:
        s = self.stderr.lower()
        return ".lock" in s or "cannot lock ref" in s or "unable to create" in s and "lock" in s


class GitTimeout(RuntimeError):
    pass


def set_git_path(path: str | None) -> None:
    """Use a specific git executable (from settings); ``None`` = auto-detect."""
    global _git_path_override, _git_path_cache
    _git_path_override = path or None
    _git_path_cache = None


def _candidate_paths() -> list[str]:
    cands: list[str] = []
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ):
            if base:
                cands.append(os.path.join(base, "Git", "cmd", "git.exe"))
                cands.append(os.path.join(base, "Git", "bin", "git.exe"))
    elif sys.platform == "darwin":
        cands += ["/opt/homebrew/bin/git", "/usr/local/bin/git", "/usr/bin/git"]
    else:
        cands += ["/usr/bin/git", "/usr/local/bin/git", "/bin/git"]
    return cands


def find_git() -> str:
    """Return the path of the git executable or raise :class:`GitNotFoundError`."""
    global _git_path_cache
    if _git_path_cache:
        return _git_path_cache
    if _git_path_override:
        if os.path.isfile(_git_path_override):
            _git_path_cache = _git_path_override
            return _git_path_cache
        raise GitNotFoundError(f"Configured git executable not found: {_git_path_override}")
    found = shutil.which("git")
    if not found:
        for cand in _candidate_paths():
            if os.path.isfile(cand):
                found = cand
                break
    if not found:
        raise GitNotFoundError("git executable not found")
    _git_path_cache = found
    return found


def git_version() -> str | None:
    try:
        return run(["--version"], timeout=10).strip()
    except (GitNotFoundError, GitError, GitTimeout, OSError):
        return None


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GCM_INTERACTIVE": "never",
            "SSH_ASKPASS_REQUIRE": "never",
            # Partial clones would otherwise download missing objects on
            # demand (e.g. for a diff) - Comitra must never touch the network
            # except for an explicit, user-enabled fetch.
            "GIT_NO_LAZY_FETCH": "1",
            "LANGUAGE": "C",
        }
    )
    # Frozen (PyInstaller) builds on Linux set LD_LIBRARY_PATH for bundled Qt;
    # git and ssh must not inherit it.
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    if extra:
        env.update(extra)
    return env


def _popen_kwargs() -> dict:
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        kw["start_new_session"] = True
    return kw


def _kill(proc: subprocess.Popen) -> None:
    try:
        if sys.platform != "win32":
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                **_popen_kwargs(),
            )
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _cmd(args: list[str], cwd: str | None) -> list[str]:
    cmd = [find_git(), *_BASE_CONFIG]
    if cwd:
        cmd += ["-C", cwd]
    return cmd + args


def run(
    args: list[str],
    cwd: str | None = None,
    timeout: float | None = 120,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> str:
    """Run git and return its decoded stdout."""
    proc = subprocess.Popen(
        _cmd(args, cwd),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(env),
        **_popen_kwargs(),
    )
    try:
        out, err = proc.communicate(
            input=input_text.encode("utf-8") if input_text is not None else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _kill(proc)
        proc.communicate()
        raise GitTimeout(f"git {' '.join(args[:2])} timed out after {timeout}s")
    if check and proc.returncode != 0:
        raise GitError(args, proc.returncode, err.decode("utf-8", "replace"))
    return out.decode("utf-8", "replace")


def run_limited(
    args: list[str],
    cwd: str | None = None,
    max_bytes: int = 2_000_000,
    timeout: float = 60,
) -> tuple[str, bool]:
    """Run git and return at most *max_bytes* of stdout and whether it was cut.

    The process is killed as soon as the limit is reached, so a gigantic diff
    can never fill the memory.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    proc = subprocess.Popen(
        _cmd(args, cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
        **_popen_kwargs(),
    )
    err_chunks: list[bytes] = []
    t_err = threading.Thread(target=lambda: err_chunks.extend(iter(lambda: proc.stderr.read(8192), b"")), daemon=True)
    t_err.start()
    timer = None
    if deadline is not None:
        timer = threading.Timer(timeout, lambda: _kill(proc))
        timer.daemon = True
        timer.start()
    out = bytearray()
    truncated = False
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(1 << 16) if hasattr(proc.stdout, "read1") else proc.stdout.read(1 << 16)
            if not chunk:
                break
            out += chunk
            if len(out) > max_bytes:
                truncated = True
                _kill(proc)
                break
    finally:
        if timer is not None:
            timer.cancel()
        rc = proc.wait()
        t_err.join(timeout=5)
    if truncated:
        return bytes(out[:max_bytes]).decode("utf-8", "replace"), True
    if deadline is not None and time.monotonic() >= deadline and rc != 0:
        raise GitTimeout(f"git {' '.join(args[:2])} timed out after {timeout}s")
    if rc != 0:
        raise GitError(args, rc, b"".join(err_chunks).decode("utf-8", "replace"))
    return bytes(out).decode("utf-8", "replace"), False


@dataclass
class StreamResult:
    returncode: int = 0
    stderr: str = ""


def stream(
    args: list[str],
    cwd: str | None = None,
    input_lines: Iterable[str] | None = None,
    sep: bytes = b"\0",
    cancel: threading.Event | None = None,
    result: StreamResult | None = None,
    chunk_size: int = 1 << 16,
) -> Iterator[str]:
    """Run git and yield decoded records separated by *sep* as they arrive.

    Raises :class:`GitError` at the end if git failed. Input lines are written
    to stdin from a helper thread to avoid pipe dead-locks on huge inputs.
    """
    proc = subprocess.Popen(
        _cmd(args, cwd),
        stdin=subprocess.PIPE if input_lines is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
        **_popen_kwargs(),
    )
    err_chunks: list[bytes] = []

    def _read_err() -> None:
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read(8192), b""):
            err_chunks.append(chunk)

    def _write_in() -> None:
        assert proc.stdin is not None
        try:
            for line in input_lines or ():
                proc.stdin.write(line.encode("utf-8") + b"\n")
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    t_err = threading.Thread(target=_read_err, daemon=True)
    t_err.start()
    t_in = None
    if input_lines is not None:
        t_in = threading.Thread(target=_write_in, daemon=True)
        t_in.start()

    buf = b""
    eof = False
    assert proc.stdout is not None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                _kill(proc)
                return
            chunk = proc.stdout.read1(chunk_size) if hasattr(proc.stdout, "read1") else proc.stdout.read(chunk_size)
            if not chunk:
                eof = True
                break
            buf += chunk
            parts = buf.split(sep)
            buf = parts.pop()
            for p in parts:
                yield p.decode("utf-8", "replace")
        if buf:
            yield buf.decode("utf-8", "replace")
    finally:
        if not eof and proc.poll() is None:
            _kill(proc)
        rc = proc.wait()
        t_err.join(timeout=5)
        if t_in is not None:
            t_in.join(timeout=5)
        stderr = b"".join(err_chunks).decode("utf-8", "replace")
        if result is not None:
            result.returncode = rc
            result.stderr = stderr
    if eof and rc != 0 and not (cancel is not None and cancel.is_set()):
        raise GitError(args, rc, stderr)
