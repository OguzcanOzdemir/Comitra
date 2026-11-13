"""Optional ``git fetch`` before indexing, with the safety rules from the design:

* never prompts (``GIT_TERMINAL_PROMPT=0``, SSH ``BatchMode=yes``)
* per-repo timeout, then the repo is skipped (local data is still indexed)
* ``--no-prune`` always, even if the user's config enables pruning
* lock conflicts with the user's own git commands are retried once
* only remote-tracking refs are touched; work tree and local branches are not
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import gitcmd


@dataclass
class FetchResult:
    ok: bool
    reason: str = ""   # "" | timeout | auth | network | lock | error
    message: str = ""


_AUTH_HINTS = (
    "authentication failed", "permission denied", "could not read username",
    "terminal prompts disabled", "access denied", "403", "401", "host key verification failed",
)
_NET_HINTS = (
    "could not resolve host", "connection timed out", "connection refused", "network is unreachable",
    "unable to access", "operation timed out", "no route to host", "could not connect",
)


def _ssh_env(path: str) -> dict[str, str]:
    if os.environ.get("GIT_SSH_COMMAND") or os.environ.get("GIT_SSH"):
        return {}
    try:
        configured = gitcmd.run(["config", "--get", "core.sshCommand"], cwd=path, timeout=15, check=False).strip()
    except (gitcmd.GitTimeout, OSError):
        configured = ""
    if configured:
        return {}
    return {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15"}


def classify(stderr: str) -> str:
    s = stderr.lower()
    if ".lock" in s or "cannot lock ref" in s:
        return "lock"
    if any(h in s for h in _AUTH_HINTS):
        return "auth"
    if any(h in s for h in _NET_HINTS):
        return "network"
    return "error"


def fetch_repo(path: str, timeout: float = 60, retries: int = 1) -> FetchResult:
    env = _ssh_env(path)
    args = ["fetch", "--all", "--no-prune", "--no-recurse-submodules", "--quiet", "--no-write-fetch-head"]
    attempt = 0
    while True:
        try:
            gitcmd.run(args, cwd=path, timeout=timeout, env=env)
            return FetchResult(True)
        except gitcmd.GitTimeout:
            return FetchResult(False, "timeout", f"fetch timed out after {int(timeout)}s")
        except gitcmd.GitError as exc:
            if "no-write-fetch-head" in exc.stderr and "unknown option" in exc.stderr:
                args.remove("--no-write-fetch-head")  # git < 2.29
                continue
            reason = classify(exc.stderr)
            if reason == "lock" and attempt < retries:
                attempt += 1
                time.sleep(2.0)
                continue
            return FetchResult(False, reason, exc.stderr[:1000])
        except OSError as exc:
            return FetchResult(False, "error", str(exc))
