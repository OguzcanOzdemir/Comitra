import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comitra.core import db  # noqa: E402


class Repo:
    def __init__(self, path):
        self.path = str(path)
        self.gitconfig = os.path.join(os.path.dirname(self.path), ".gitconfig-test")
        if not os.path.exists(self.gitconfig):
            os.makedirs(os.path.dirname(self.gitconfig), exist_ok=True)
            with open(self.gitconfig, "w", encoding="utf-8") as fh:
                fh.write("[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n")
        os.makedirs(self.path, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        self.counter = 0

    def git(self, *args, env=None, input=None):
        e = dict(os.environ)
        e.update(
            {
                "GIT_AUTHOR_NAME": "Alice Smith",
                "GIT_AUTHOR_EMAIL": "alice@example.com",
                "GIT_COMMITTER_NAME": "Alice Smith",
                "GIT_COMMITTER_EMAIL": "alice@example.com",
                "GIT_CONFIG_GLOBAL": self.gitconfig,
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        if env:
            e.update(env)
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.path,
            env=e,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
        ).stdout

    def commit(self, message, date="2026-10-15T10:00:00+03:00", author=None, files=None):
        self.counter += 1
        files = files or {f"file{self.counter}.txt": f"content {self.counter}\n"}
        for name, content in files.items():
            full = os.path.join(self.path, name)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.git("add", name)
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        if author:
            env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
        self.git("commit", "-q", "-F", "-", env=env, input=message)
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def make_repo(tmp_path):
    def _make(name="repo"):
        return Repo(tmp_path / "work" / name)

    return _make


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path):
    from comitra.config import Settings

    s = Settings()
    s.roots = [str(tmp_path / "work")]
    s.workers = 2
    s.index_files = True
    return s
