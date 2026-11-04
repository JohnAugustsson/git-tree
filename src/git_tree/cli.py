"""Command line entry point: git tree [git log arguments]."""
import sys

from . import __version__
from .browser import browse
from .log import page

USAGE = """\
usage: git tree [<git log options>] [<revision>...] [[--] <path>...]

Draw the commit graph of every branch, remote branch and tag. In a terminal it
opens an interactive browser; piped, it prints the graph as plain text.
Arguments go straight to git log, e.g. `git tree -n 50` or `git tree -- src/`.

Browser keys:
  Up/Down, j/k            move
  PgUp/PgDn, b/Space      page
  Home/End, g/G           first/last
  Enter                   open the commit, or the selected file's diff
  J/K                     scroll a long commit message
  /                       search; Enter keeps it, n/N step, Esc clears
  Esc                     back one level; quits from the graph
  q                       quit

Options:
  -h, --help              show this help
  --version               show the version
"""


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] in (["-h"], ["--help"]):
        sys.stdout.write(USAGE)
        return 0
    if args[:1] == ["--version"]:
        print(f"git-tree {__version__}")
        return 0
    if sys.stdin.isatty() and sys.stdout.isatty():
        return browse(args)
    return page(args)


if __name__ == "__main__":
    sys.exit(main())
