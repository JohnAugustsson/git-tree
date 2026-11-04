import unittest

from git_tree.style import MATCH, RESET
from git_tree.text import ANSI, matcher, mark, truncate, truncate_left, visible_width, wrap

GREEN = "\x1b[32m"


class WidthTests(unittest.TestCase):
    def test_colour_codes_take_no_room(self):
        self.assertEqual(visible_width(f"{GREEN}abc{RESET}"), 3)

    def test_emoji_take_two_columns(self):
        self.assertEqual(visible_width("✨ new"), 6)
        self.assertEqual(visible_width("❤️"), 2)  # text symbol + emoji presentation

    def test_truncate_marks_the_cut(self):
        self.assertEqual(truncate("abcdef", 4), "abc…")
        self.assertEqual(truncate("abc", 4), "abc")

    def test_truncate_left_keeps_the_file_name(self):
        self.assertEqual(truncate_left("src/deep/path/file.py", 10), "…h/file.py")


class WrapTests(unittest.TestCase):
    def test_colour_carries_over_to_the_next_row(self):
        rows = wrap(f"{GREEN}abcdef{RESET}", 4)
        self.assertEqual([ANSI.sub("", r) for r in rows], ["abcd", "ef"])
        self.assertTrue(rows[1].startswith(GREEN))

    def test_tabs_expand_and_control_characters_show(self):
        self.assertEqual(wrap("a\tb\r", 20), ["a   b^M"])

    def test_wide_characters_are_not_split(self):
        self.assertEqual([ANSI.sub("", r) for r in wrap("ab✨c", 3)], ["ab", "✨c"])


class SearchTextTests(unittest.TestCase):
    def test_smartcase(self):
        self.assertTrue(matcher("fix")("Fix the build"))
        self.assertFalse(matcher("Fix")("fix the build"))

    def test_mark_highlights_inside_colour_and_restores_it(self):
        line = f"{GREEN}fix the fix{RESET}"
        marked = mark(line, "fix")
        self.assertEqual(marked.count(MATCH), 2)
        self.assertEqual(ANSI.sub("", marked), "fix the fix")
        # After a match the line's own colour comes back.
        self.assertIn(f"{RESET}{GREEN} the ", marked)

    def test_mark_without_a_match_returns_the_line(self):
        self.assertEqual(mark("abc", "zz"), "abc")


if __name__ == "__main__":
    unittest.main()
