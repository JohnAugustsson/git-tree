"""Colours. Everything is xterm-256 rather than the 16 ANSI colours: terminal
themes (pywal especially) often make those 16 near-identical, and lanes, ref
types and diff lines must stay apart."""

RESET = "\x1b[0m"
DIM = "\x1b[2m"

LANE_COLORS = [174, 179, 108, 110, 140, 73, 216, 150, 117, 182, 186, 80]

LABEL_STYLES = {
    "head": "\x1b[1;38;5;16;48;5;117m",
    "local": "\x1b[38;5;16;48;5;108m",
    "remote": "\x1b[38;5;252;48;5;239m",
    "tag": "\x1b[38;5;16;48;5;179m",
}

SELECTED = "\x1b[48;5;237m"
BAR = "\x1b[38;5;250;48;5;235m"
MATCH = "\x1b[38;5;16;48;5;222m"
CARET = "\x1b[7m \x1b[27m"
ADDED, DELETED = "\x1b[38;5;108m", "\x1b[38;5;174m"
FILE_STATUS_COLORS = {"A": 108, "D": 174, "M": 179, "R": 110, "C": 110, "T": 140}
DIFF_COLORS = ["-c", "color.diff.new=108", "-c", "color.diff.old=174",
               "-c", "color.diff.frag=110"]
