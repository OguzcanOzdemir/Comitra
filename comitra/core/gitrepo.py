"""Repository-level git queries: refs, commit log parsing, reachability."""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

from . import gitcmd
from .textnorm import normalize

FIELD_SEP = "\x1f"
LOG_FORMAT = FIELD_SEP.join(
    ["%H", "%P", "%aN", "%aE", "%at", "%ai", "%cN", "%cE", "%ct", "%ci", "%S", "%B"]
)
CO_AUTHOR_RE = re.compile(r"^\s*co-authored-by:\s*(.*?)\s*<([^>]+)>\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Ref:
    name: str    # full ref name, e.g. refs/heads/main, or HEAD
    kind: str    # branch | remote | tag | head
    target: str  # commit hash (peeled)

    @property
    def short(self) -> str:
        return short_ref(self.name)

    def match_names(self) -> list[str]:
        """Names a branch pattern is matched against."""
        s = self.short
        if self.kind == "remote" and "/" in s:
            return [s, s.split("/", 1)[1]]
        return [s]


def short_ref(name: str) -> str:
    for prefix in ("refs/heads/", "refs/remotes/", "refs/tags/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


@dataclass
class ParsedCommit:
    hash: str
    parents: str
    parent_count: int
    author_name: str
    author_email: str
    author_time: int
    author_tz: int
    author_hour: int
    author_wday: int
    committer_name: str
    committer_email: str
    commit_time: int
    commit_tz: int
    commit_hour: int
    commit_wday: int
    subject: str
    message: str
    first_ref: str
    coauthors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def msg_norm(self) -> str:
        return normalize(self.message)

    @property
    def people_norm(self) -> str:
        parts = [self.author_name, self.author_email]
        for n, e in self.coauthors:
            parts += [n, e]
        return normalize(" ".join(parts))


def list_refs(path: str, include_tags: bool = True, include_remotes: bool = True) -> list[Ref]:
    patterns = ["refs/heads"]
    if include_remotes:
        patterns.append("refs/remotes")
    if include_tags:
        patterns.append("refs/tags")
    out = gitcmd.run(
        [
            "for-each-ref",
            "--format=%(refname)%00%(objecttype)%00%(objectname)%00%(*objecttype)%00%(*objectname)",
            *patterns,
        ],
        cwd=path,
        timeout=120,
    )
    refs: list[Ref] = []
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) < 5:
            continue
        name, otype, oid, ptype, poid = parts[:5]
        if name.endswith("/HEAD") and name.startswith("refs/remotes/"):
            continue
        if otype == "commit":
            target = oid
        elif otype == "tag" and ptype == "commit":
            target = poid
        else:
            continue  # tags of trees/blobs, nested tags etc.
        if name.startswith("refs/heads/"):
            kind = "branch"
        elif name.startswith("refs/remotes/"):
            kind = "remote"
        else:
            kind = "tag"
        refs.append(Ref(name, kind, target))
    # Detached HEAD keeps commits alive that no branch points to.
    try:
        gitcmd.run(["symbolic-ref", "-q", "HEAD"], cwd=path, timeout=30)
    except gitcmd.GitError:
        try:
            head = gitcmd.run(["rev-parse", "--verify", "-q", "HEAD^{commit}"], cwd=path, timeout=30).strip()
            if head:
                refs.append(Ref("HEAD", "head", head))
        except gitcmd.GitError:
            pass
    return refs


def fingerprint(refs: Iterable[Ref], salt: str = "") -> str:
    h = hashlib.sha1(salt.encode())
    for r in sorted(refs, key=lambda r: r.name):
        h.update(f"{r.name}\0{r.target}\n".encode("utf-8", "replace"))
    return h.hexdigest()


def remote_url(path: str) -> str:
    try:
        remotes = gitcmd.run(["remote"], cwd=path, timeout=30).split()
    except (gitcmd.GitError, gitcmd.GitTimeout):
        return ""
    if not remotes:
        return ""
    name = "origin" if "origin" in remotes else remotes[0]
    try:
        return gitcmd.run(["config", "--get", f"remote.{name}.url"], cwd=path, timeout=30).strip()
    except gitcmd.GitError:
        return ""


def has_remotes(path: str) -> bool:
    try:
        return bool(gitcmd.run(["remote"], cwd=path, timeout=30).strip())
    except (gitcmd.GitError, gitcmd.GitTimeout):
        return False


def root_commit(path: str) -> str:
    """Lowest-hash root commit reachable from HEAD (a stable repo identity)."""
    try:
        out = gitcmd.run(["rev-list", "--max-parents=0", "HEAD"], cwd=path, timeout=300)
    except (gitcmd.GitError, gitcmd.GitTimeout):
        return ""
    roots = sorted(out.split())
    return roots[0] if roots else ""


def existing_objects(path: str, hashes: Iterable[str]) -> set[str]:
    """Return the subset of *hashes* that still exist as commits in the repo."""
    hashes = list(hashes)
    if not hashes:
        return set()
    out = gitcmd.run(
        ["cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=path,
        input_text="\n".join(hashes) + "\n",
        timeout=300,
    )
    found = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "commit":
            found.add(parts[0])
    return found


def rev_list(
    path: str,
    include: Iterable[str],
    exclude: Iterable[str] = (),
    cancel: threading.Event | None = None,
) -> Iterator[str]:
    lines = list(include) + [f"^{h}" for h in exclude]
    if not any(not l.startswith("^") for l in lines):
        return iter(())
    return (
        h.strip()
        for h in gitcmd.stream(["rev-list", "--stdin"], cwd=path, input_lines=lines, sep=b"\n", cancel=cancel)
        if h.strip()
    )


def _tz_minutes(iso: str) -> int:
    # "%ai" looks like "2026-11-10 14:03:22 +0300"
    tok = iso.rsplit(" ", 1)[-1] if iso else ""
    if len(tok) == 5 and tok[0] in "+-" and tok[1:].isdigit():
        mins = int(tok[1:3]) * 60 + int(tok[3:5])
        return -mins if tok[0] == "-" else mins
    return 0


def _local_parts(ts: int, tz_min: int) -> tuple[int, int]:
    try:
        dt = datetime.fromtimestamp(ts, timezone(timedelta(minutes=tz_min)))
    except (OverflowError, OSError, ValueError):
        return 0, 0
    return dt.hour, dt.weekday()


def _to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return 0


def parse_record(rec: str) -> ParsedCommit | None:
    rec = rec.lstrip("\n")
    if not rec:
        return None
    parts = rec.split(FIELD_SEP, 11)
    if len(parts) < 12:
        return None
    (h, parents, an, ae, at, ai, cn, ce, ct, ci, source, body) = parts
    if len(h) < 40:
        return None
    message = body.rstrip("\n")
    at_i, ct_i = _to_int(at), _to_int(ct)
    atz, ctz = _tz_minutes(ai), _tz_minutes(ci)
    ah, aw = _local_parts(at_i, atz)
    ch, cw = _local_parts(ct_i, ctz)
    subject = message.split("\n", 1)[0].strip()
    coauthors = [(m.group(1).strip(), m.group(2).strip()) for m in CO_AUTHOR_RE.finditer(message)]
    plist = parents.split()
    return ParsedCommit(
        hash=h,
        parents=" ".join(plist),
        parent_count=len(plist),
        author_name=an,
        author_email=ae,
        author_time=at_i,
        author_tz=atz,
        author_hour=ah,
        author_wday=aw,
        committer_name=cn,
        committer_email=ce,
        commit_time=ct_i,
        commit_tz=ctz,
        commit_hour=ch,
        commit_wday=cw,
        subject=subject,
        message=message,
        first_ref=short_ref(source.strip()),
        coauthors=coauthors,
    )


def log_commits(
    path: str,
    include: Iterable[str],
    exclude: Iterable[str] = (),
    cancel: threading.Event | None = None,
) -> Iterator[ParsedCommit]:
    """Yield commits reachable from *include* refs but not from *exclude* hashes."""
    lines = list(include) + [f"^{h}" for h in exclude]
    if not any(not l.startswith("^") for l in lines):
        return
    for rec in gitcmd.stream(
        ["log", "--stdin", "--source", "-z", "--no-color", "--encoding=UTF-8", f"--format={LOG_FORMAT}"],
        cwd=path,
        input_lines=lines,
        sep=b"\0",
        cancel=cancel,
    ):
        c = parse_record(rec)
        if c is not None:
            yield c


def changed_files(
    path: str, hashes: Iterable[str], cancel: threading.Event | None = None
) -> Iterator[tuple[str, list[str]]]:
    """Yield ``(hash, [paths])`` for the given commits (no merge diffs)."""
    hashes = list(hashes)
    if not hashes:
        return
    current: str | None = None
    files: list[str] = []
    for rec in gitcmd.stream(
        ["log", "--no-walk=unsorted", "--stdin", "--name-only", "-z", "--no-renames", "--format=%x01%H"],
        cwd=path,
        input_lines=hashes,
        sep=b"\0",
        cancel=cancel,
    ):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        if rec.startswith("\x01"):
            if current is not None:
                yield current, files
            current, files = rec[1:].strip(), []
        elif current is not None:
            files.append(rec)
    if current is not None:
        yield current, files


def show_commit(path: str, h: str, max_bytes: int = 2_000_000, timeout: float = 60) -> str:
    """Diff of a commit for the detail view (never stored in the database)."""
    out = gitcmd.run(
        ["show", "--no-color", "--stat", "--patch", "--find-renames", "--format=", h],
        cwd=path,
        timeout=timeout,
    )
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n\n… (diff truncated)\n"
    return out


def branches_containing(path: str, h: str, timeout: float = 30) -> list[str]:
    out = gitcmd.run(
        ["for-each-ref", "--contains", h, "--format=%(refname)", "refs/heads", "refs/remotes"],
        cwd=path,
        timeout=timeout,
    )
    names = [short_ref(n) for n in out.splitlines() if n and not n.endswith("/HEAD")]
    return names
