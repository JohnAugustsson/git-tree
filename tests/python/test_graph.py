import unittest

import helpers
from git_tree.graph import Graph
from git_tree.log import Log, labels


def layout(commits, head=""):
    """Graph rows for (sha, parents) pairs given newest first."""
    graph = Graph(False, head)
    return [graph.row(sha, parents) for sha, parents in commits]


class GraphLayoutTests(unittest.TestCase):
    def test_linear_history_is_one_straight_line(self):
        rows = layout([("c", ["b"]), ("b", ["a"]), ("a", [])], head="c")
        self.assertEqual(rows, ["●", "●", "●"])

    def test_merge_opens_a_lane_and_the_fork_point_closes_it(self):
        rows = layout([("m", ["a2", "f"]), ("f", ["a1"]), ("a2", ["a1"]), ("a1", [])], head="m")
        self.assertEqual(rows, ["○─╮", "│ ●", "● │", "●─╯"])

    def test_column_zero_is_held_for_head_until_its_row(self):
        rows = layout([("tip", ["h"]), ("h", ["r"]), ("r", [])], head="h")
        self.assertEqual(rows, ["  ●", "●─╯", "●"])

    def test_head_line_wins_a_join_even_when_it_is_not_leftmost(self):
        # x is drawn first in column 1 (column 0 is held for HEAD); when both
        # lines reach their shared parent, HEAD's column stays and x's ends.
        rows = layout([("x", ["p"]), ("h", ["p"]), ("p", [])], head="h")
        self.assertEqual(rows, ["  ●", "● │", "●─╯"])

    def test_an_unrelated_line_crossing_a_join_stays_unbroken(self):
        rows = layout([("a", ["base"]), ("b", ["z"]), ("c", ["base"]),
                       ("base", ["z"]), ("z", [])], head="a")
        self.assertEqual(rows, ["●", "│ ●", "│ │ ●", "●─│─╯", "●─╯"])

    def test_wide_gaps_close_up_with_a_jog(self):
        # Three branches end at p and leave a gap of three columns; the line
        # passing on the right moves into it on the next row.
        rows = layout([("t0", ["p"]), ("t1", ["p"]), ("t2", ["p"]), ("t3", ["p"]),
                       ("t4", ["q"]), ("p", ["o"]), ("o", ["q"]), ("q", [])], head="t0")
        self.assertEqual(rows[5:], ["●─┴─┴─╯ │", "● ╭─────╯", "●─╯"])


class LabelTests(unittest.TestCase):
    def test_a_local_branch_absorbs_its_remote_on_the_same_commit(self):
        text = labels("HEAD -> main, origin/main, origin/HEAD, tag: v1", {"origin"}, False)
        self.assertEqual(text, "[HEAD → main ⇅] [v1]")

    def test_remote_only_and_detached_head(self):
        text = labels("HEAD, origin/feature/x, topic", {"origin"}, False)
        self.assertEqual(text, "[HEAD] [topic] [origin/feature/x]")

    def test_a_slash_in_a_local_branch_is_not_a_remote(self):
        self.assertEqual(labels("feature/y", {"origin"}, False), "[feature/y]")


class LogTests(helpers.RepoTestCase, unittest.TestCase):
    def setUp(self):
        self.enter(helpers.history())

    def rows(self, *args):
        log = Log(list(args), False)
        self.addCleanup(log.close)
        return [(c.graph, c.refs, c.subject) for c in log]

    def test_history_layout(self):
        self.assertEqual(self.rows(), [
            ("●", "[HEAD → main]", "rename app"),
            ("●", "[v1]", "a3"),
            ("○─╮", "", "Merge feature"),
            ("│ ●", "[feature]", "f2"),
            ("│ ●", "", "f1"),
            ("│ │ ●", "[hotfix]", "h1"),
            ("●─│─╯", "", "a2"),
            ("●─╯", "", "a1"),
            ("●", "", "root"),
        ])

    def test_a_pathspec_connects_through_the_commits_shown(self):
        # Only a1, a2, h1 and the rename touch `app`; parent rewriting keeps
        # the hotfix joined to a2 even though the commits between are hidden.
        self.assertEqual(self.rows("--", "app"), [
            ("●", "[HEAD → main]", "rename app"),
            ("│ ●", "[hotfix]", "h1"),
            ("●─╯", "", "a2"),
            ("●", "", "a1"),
        ])


if __name__ == "__main__":
    unittest.main()
