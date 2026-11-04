import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock

# The tests' git commands, and the ones git-tree runs, must not see the
# developer's own configuration (colours, signing, merge drivers).
ISOLATED_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class Repo:
    """A throwaway repository with commits dated `days` ago."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        self.now = int(time.time())
        self.git("init", "-q", "-b", "main")

    def git(self, *args, days=3):
        stamp = f"@{self.now - days * 86400} +0000"
        env = {**os.environ, **ISOLATED_ENV,
               "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "test@example.com",
               "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "test@example.com",
               "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        return subprocess.run(["git", *args], cwd=self.path, env=env, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, message, days=3, **files):
        for name, content in files.items():
            path = self.path / name.replace("__", "/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git("add", "-A", days=days)
        self.git("commit", "-q", "--allow-empty", "-m", message, days=days)
        return self.git("rev-parse", "HEAD").strip()

    def merge(self, branch, days=3):
        self.git("merge", "-q", "--no-ff", "-m", f"Merge {branch}", branch, days=days)

    def cleanup(self):
        self._tmp.cleanup()


class RepoTestCase:
    """Mixin: run each test inside `self.repo` with an isolated git config."""

    def enter(self, repo):
        self.repo = repo
        self.addCleanup(repo.cleanup)
        env = mock.patch.dict(os.environ, ISOLATED_ENV)
        env.start()
        self.addCleanup(env.stop)
        previous = os.getcwd()
        os.chdir(repo.path)
        self.addCleanup(os.chdir, previous)


def history():
    """Branches, a merge, a tag, an unmerged branch and a path that only one commit touches.

    Oldest first, the commits' days ago only ever decrease, so the order git
    shows them in doesn't depend on timing.
    """
    repo = Repo()
    repo.commit("root", days=10, README="hello\n")
    repo.commit("a1", days=9, app="one\n")
    repo.git("switch", "-q", "-c", "feature")
    repo.commit("f1", days=8, feature="f1\n")
    repo.commit("f2", days=7, feature="f2\n")
    repo.git("switch", "-q", "main")
    repo.commit("a2", days=6, app="two\n")
    repo.merge("feature", days=5)
    repo.git("switch", "-q", "-c", "hotfix", "main~1")
    repo.commit("h1", days=4, app="hotfix\n")
    repo.git("switch", "-q", "main")
    repo.commit("a3", days=3, docs__guide="guide\n")
    repo.git("tag", "v1")
    repo.git("mv", "app", "app.txt")
    repo.commit("rename app", days=2)
    return repo
