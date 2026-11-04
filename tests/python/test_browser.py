import os
import subprocess
import unittest

import helpers
from git_tree.browser import BACK, CommitView, DiffView, GraphView, read_keys
from git_tree.log import Log
from git_tree.style import MATCH, SELECTED
from git_tree.text import visible_width

WIDTH, HEIGHT = 80, 8


def typed(view, text):
    view.handle("search")
    for char in text:
        view.type(char)


class BrowserTestCase(helpers.RepoTestCase, unittest.TestCase):
    def setUp(self):
        self.enter(helpers.history())
        log = Log([], True, stderr=subprocess.PIPE)
        self.addCleanup(log.close)
        self.graph = GraphView(log)

    def subjects(self):
        return [c.subject for c in self.graph.rows]

    def selected_subject(self):
        return self.graph.rows[self.graph.cursor.pos].subject

    def render(self, view, width=WIDTH, height=HEIGHT):
        lines = view.render(width, height)
        self.assertEqual(len(lines), height)
        for line in lines:
            self.assertLessEqual(visible_width(line), width)
        return lines


class GraphViewTests(BrowserTestCase):
    def test_rows_load_as_they_are_needed(self):
        self.render(self.graph)
        self.assertFalse(self.graph.done)
        self.graph.handle("end")
        self.assertEqual(self.selected_subject(), "root")

    def test_enter_opens_the_commit_and_esc_quits(self):
        self.render(self.graph)
        self.graph.handle("down")
        view = self.graph.handle("enter")
        self.assertIsInstance(view, CommitView)
        self.assertEqual(view.commit.subject, "a3")
        self.assertIs(self.graph.handle("esc"), BACK)


class SearchTests(BrowserTestCase):
    # Queries use letters that can't occur in a hash, since the short hash is
    # part of what a row shows and so of what it matches.

    def test_typing_jumps_to_the_first_match_after_the_cursor(self):
        self.render(self.graph)
        typed(self.graph, "feat")
        self.assertEqual(self.selected_subject(), "Merge feature")
        self.assertTrue(any(MATCH in line for line in self.render(self.graph)))

    def test_n_and_shift_n_step_and_wrap(self):
        self.render(self.graph)
        typed(self.graph, "feature")
        self.graph.type("\r")
        self.assertEqual(self.selected_subject(), "Merge feature")
        self.graph.handle("next")
        self.assertEqual(self.selected_subject(), "f2")
        self.graph.handle("next")
        self.assertEqual(self.selected_subject(), "Merge feature")
        self.assertIn("continuing at top", self.graph.message)
        self.graph.handle("previous")
        self.assertEqual(self.selected_subject(), "f2")
        self.assertIn("continuing at bottom", self.graph.message)

    def test_esc_in_the_prompt_puts_the_cursor_back(self):
        self.render(self.graph)
        self.graph.handle("down")
        typed(self.graph, "root")
        self.assertEqual(self.selected_subject(), "root")
        self.graph.type("\x1b")
        self.assertEqual(self.selected_subject(), "a3")
        self.assertIsNone(self.graph.prompt)
        self.assertEqual(self.graph.query, "")

    def test_esc_clears_a_search_before_going_back(self):
        self.render(self.graph)
        typed(self.graph, "root")
        self.graph.type("\r")
        self.assertIsNone(self.graph.handle("esc"))
        self.assertEqual(self.graph.query, "")
        self.assertIs(self.graph.handle("esc"), BACK)

    def test_a_missing_match_says_so(self):
        self.render(self.graph)
        typed(self.graph, "nothing like this")
        self.graph.type("\r")
        self.assertEqual(self.graph.cursor.pos, 0)
        self.assertIn("not found", self.graph.message)


class CommitAndDiffTests(BrowserTestCase):
    def open(self, subject):
        self.graph.ensure(float("inf"))
        commit = next(c for c in self.graph.rows if c.subject == subject)
        return CommitView(commit, set())

    def test_a_rename_is_listed_with_both_paths(self):
        view = self.open("rename app")
        self.assertEqual([f[:3] for f in view.files], [["R", "app", "app.txt"]])
        lines = self.render(view, height=12)
        self.assertTrue(any("app → app.txt" in line for line in lines))

    def test_a_merge_is_shown_against_its_first_parent(self):
        view = self.open("Merge feature")
        self.assertEqual([f[2] for f in view.files], ["feature"])

    def test_diff_search_selects_the_matching_line(self):
        view = self.open("a2")
        diff = view.handle("enter")
        self.assertIsInstance(diff, DiffView)
        self.render(diff)
        typed(diff, "+two")
        diff.type("\r")
        lines = self.render(diff)
        self.assertEqual(diff.plain[diff.current], "+two")
        self.assertTrue(any(line.startswith(SELECTED) for line in lines))
        self.assertIsNone(diff.handle("esc"))
        self.assertIsNone(diff.current)
        self.assertIs(diff.handle("esc"), BACK)


class KeyTests(unittest.TestCase):
    def test_sequences_and_characters_are_told_apart(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        os.write(write, "\x1b[Bj/é\x1b".encode())
        os.close(write)
        self.assertEqual(read_keys(read, 0), [
            ("down", "\x1b[B"), ("down", "j"), ("search", "/"), (None, "é"), ("esc", "\x1b"),
        ])


if __name__ == "__main__":
    unittest.main()
