import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers
from git_tree import __version__

GIT_TREE = Path(__file__).resolve().parents[2] / "bin" / "git-tree"


def run(*args, cwd):
    env = {**os.environ, **helpers.ISOLATED_ENV}
    return subprocess.run([str(GIT_TREE), *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


class CommandLineTests(unittest.TestCase):
    def test_piped_output_is_plain_text(self):
        repo = helpers.history()
        self.addCleanup(repo.cleanup)
        result = run(cwd=repo.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 9)
        self.assertNotIn("\x1b", result.stdout)
        self.assertTrue(lines[0].startswith("● [HEAD → main] rename app  Test Author"))
        self.assertTrue(lines[6].startswith("●─│─╯ a2  "))
        self.assertIn("2 days", lines[0])

    def test_arguments_go_to_git_log(self):
        repo = helpers.history()
        self.addCleanup(repo.cleanup)
        result = run("-n", "2", cwd=repo.path)
        self.assertEqual(len(result.stdout.splitlines()), 2)

    def test_git_errors_are_passed_on(self):
        with tempfile.TemporaryDirectory() as empty:
            result = run(cwd=empty)
        self.assertEqual(result.returncode, 128)
        self.assertIn("not a git repository", result.stderr)

    def test_a_repository_without_commits_prints_nothing(self):
        repo = helpers.Repo()
        self.addCleanup(repo.cleanup)
        result = run(cwd=repo.path)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_help_and_version(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertIn("usage: git tree", run("-h", cwd=empty).stdout)
            self.assertEqual(run("--version", cwd=empty).stdout.strip(),
                             f"git-tree {__version__}")


if __name__ == "__main__":
    unittest.main()
