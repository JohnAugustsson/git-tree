"""The interactive browser: graph, commit and diff views with vim-style search."""
import os
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty

from .log import Log, format_row, git_out, labels
from .style import (ADDED, BAR, CARET, DELETED, DIFF_COLORS, DIM, FILE_STATUS_COLORS,
                    RESET, SELECTED)
from .text import (ANSI, age, clip, mark, matcher, truncate_left, visible_width,
                   wrap)

# Merges are shown against their first parent, like Git Extensions does by default.
DIFF_ARGS = ["show", "--format=", "--diff-merges=first-parent", "-M"]
BACK = object()

KEYS = {
    "\x1b[A": "up", "\x1bOA": "up", "k": "up",
    "\x1b[B": "down", "\x1bOB": "down", "j": "down",
    "\x1b[5~": "pgup", "b": "pgup", "\x02": "pgup",
    "\x1b[6~": "pgdn", " ": "pgdn", "\x06": "pgdn",
    "\x1b[H": "home", "\x1bOH": "home", "\x1b[1~": "home", "g": "home",
    "\x1b[F": "end", "\x1bOF": "end", "\x1b[4~": "end", "G": "end",
    "\r": "enter", "\n": "enter",
    "\x1b": "esc", "q": "quit",
    "K": "message-up", "J": "message-down",
    "/": "search", "n": "next", "N": "previous",
}
ESCAPE_SEQUENCE = re.compile(r"\x1b(\[[0-9;?]*[ -/]*[@-~]|O.)")


def selected(line, width):
    line = clip(line, width)
    pad = max(width - visible_width(line), 0)
    return SELECTED + line.replace(RESET, RESET + SELECTED) + " " * pad + RESET


def status_bar(left, right, width):
    left, right = f" {left}", f"{right} "
    pad = width - visible_width(left) - visible_width(right)
    if pad < 1:
        right, pad = "", max(width - visible_width(left), 0)
    return clip(f"{BAR}{left}{' ' * pad}{right}{RESET}", width)


class Cursor:
    """Selected index and scroll offset of a list shown a page at a time."""

    def __init__(self):
        self.pos = 0
        self.top = 0
        self.center = False

    def move(self, key, count, page):
        step = {"up": -1, "down": 1, "pgup": -page, "pgdn": page}.get(key)
        if step:
            self.pos += step
        elif key == "home":
            self.pos = 0
        elif key == "end":
            self.pos = count - 1
        self.pos = max(0, min(self.pos, count - 1))

    def jump(self, pos):
        self.pos = pos
        self.center = True

    def window(self, height):
        # A search jump off screen lands mid-page, like vim, rather than at
        # the edge.
        if self.center and not self.top <= self.pos < self.top + height:
            self.top = max(0, self.pos - height // 2)
        self.center = False
        if self.pos < self.top:
            self.top = self.pos
        elif self.pos >= self.top + height:
            self.top = self.pos - height + 1
        return range(self.top, self.top + height)


class Search:
    """Vim-style search for a view: / opens a prompt that highlights and jumps
    to matches as it is typed, Enter keeps the search, n/N step through the
    matches (wrapping around), Esc in the prompt cancels it and Esc after a
    search clears it.

    A view provides search_text(i) (None past its last item), search_count(),
    search_pos(), search_jump(i), search_clear() and save()/restore() of its
    scroll state, so a cancelled search can put everything back.
    """

    query = ""  # what n/N look for and what stays highlighted
    prompt = None  # text typed after / while the prompt is open
    message = ""  # one-off note for the status bar

    def highlight(self):
        return self.prompt if self.prompt is not None else self.query

    def search_key(self, key):
        """Act on /, n, N and Esc; True when the key was a search key."""
        if key == "search":
            self.prompt, self.origin = "", self.save()
            return True
        if key in ("next", "previous") and self.query:
            step = 1 if key == "next" else -1
            pos = self.search_pos()
            found = self.find(self.query, pos + step, step)
            if found is None:
                self.message = f"not found: {self.query}"
                return True
            if (found - pos) * step <= 0:
                self.message = ("hit bottom, continuing at top" if step > 0
                                else "hit top, continuing at bottom")
            self.search_jump(found)
            return True
        if key == "esc" and self.query:
            self.query = ""
            self.search_clear()
            return True
        return False

    def type(self, raw):
        """Edit the open prompt with one raw key."""
        if raw == "\x1b" or (raw in ("\x7f", "\x08") and not self.prompt):
            self.prompt = None
            self.restore(self.origin)
            return
        if raw in ("\r", "\n"):
            # An empty prompt repeats the last search, as in vim.
            query = self.prompt or self.query
            self.prompt = None
            self.restore(self.origin)
            if query:
                self.query = query
                found = self.find(query, self.search_pos() + 1, 1)
                if found is None:
                    self.message = f"not found: {query}"
                else:
                    self.search_jump(found)
            return
        if raw in ("\x7f", "\x08"):
            self.prompt = self.prompt[:-1]
        elif raw == "\x15":  # Ctrl-U
            self.prompt = ""
        elif len(raw) == 1 and raw.isprintable():
            self.prompt += raw
        else:
            return
        self.restore(self.origin)
        if self.prompt:
            found = self.find(self.prompt, self.search_pos() + 1, 1)
            if found is not None:
                self.search_jump(found)

    def find(self, query, start, step):
        """First item from `start` in direction `step` that matches, wrapping once."""
        hit = matcher(query)
        i = start
        for _ in range(2):
            while i >= 0:
                text = self.search_text(i)
                if text is None:
                    break
                if hit(text):
                    return i
                i += step
            i = 0 if step > 0 else self.search_count() - 1
        return None

    def status(self, info, hints, width):
        if self.prompt is not None:
            return status_bar(f"/{self.prompt}{CARET}", "⏎ search  esc cancel", width)
        if self.message:
            info = f"{info}  {self.message}"
        if self.query:
            return status_bar(f"{info}  /{self.query}", "n/N next/prev  esc clear search", width)
        return status_bar(info, f"{hints}  / search", width)


class ListSearch(Search):
    """Search over a view whose items have a Cursor."""

    def search_pos(self):
        return self.cursor.pos

    def search_jump(self, i):
        self.cursor.jump(i)

    def search_clear(self):
        pass

    def save(self):
        return self.cursor.pos, self.cursor.top

    def restore(self, saved):
        self.cursor.pos, self.cursor.top = saved
        self.cursor.center = False


class GraphView(ListSearch):
    def __init__(self, log):
        self.log = log
        self.source = iter(log)
        self.rows = []
        self.texts = []
        self.done = False
        self.cursor = Cursor()
        self.page = 1

    def ensure(self, index):
        """Read commits from the log until row `index` exists or it runs out."""
        while not self.done and len(self.rows) <= index:
            try:
                commit = next(self.source)
            except StopIteration:
                self.done = True
                break
            self.rows.append(commit)
            # What the row shows, minus the graph, so a search finds what is seen.
            self.texts.append(" ".join([ANSI.sub("", commit.refs), commit.subject,
                                        commit.author, age(commit.ctime), commit.short]))

    def search_text(self, i):
        self.ensure(i)
        return self.texts[i] if i < len(self.texts) else None

    def search_count(self):
        self.ensure(float("inf"))
        return len(self.rows)

    def render(self, width, height):
        self.page = height - 1
        window = self.cursor.window(self.page)
        self.ensure(window.stop)
        query = self.highlight()
        lines = []
        for i in window:
            if i >= len(self.rows):
                lines.append("")
                continue
            line = mark(format_row(self.rows[i], width, True), query)
            lines.append(selected(line, width) if i == self.cursor.pos else line)
        total = f"{len(self.rows)}{'' if self.done else '+'}"
        lines.append(self.status(f"{self.cursor.pos + 1}/{total}",
                                 "↑↓ move  ⏎ open  esc quit", width))
        return lines

    def handle(self, key):
        if self.search_key(key):
            return None
        if key == "esc":
            return BACK
        if key == "enter":
            return CommitView(self.rows[self.cursor.pos], self.log.remotes)
        if key == "end":
            self.ensure(float("inf"))
        else:
            self.ensure(self.cursor.pos + (self.page if key == "pgdn" else 1))
        self.cursor.move(key, len(self.rows), self.page)
        return None


def changed_files(sha):
    """[status, old path, new path, added, deleted] for each file the commit changed."""
    names = git_out(*DIFF_ARGS, "-z", "--name-status", sha).split("\0")
    counts = git_out(*DIFF_ARGS, "-z", "--numstat", sha).split("\0")
    files, i = [], 0
    while i < len(names) and names[i]:
        status = names[i][0]
        if status in "RC":
            files.append([status, names[i + 1], names[i + 2], "", ""])
            i += 3
        else:
            files.append([status, names[i + 1], names[i + 1], "", ""])
            i += 2
    # numstat lists the same files in the same order; a rename's paths follow
    # its counts as two extra fields.
    i = 0
    for entry in files:
        if i >= len(counts) or not counts[i]:
            break
        added, deleted, path = counts[i].split("\t", 2)
        entry[3:] = added, deleted
        i += 1 if path else 3
    return files


def file_path(entry):
    status, old, new = entry[:3]
    return new if old == new else f"{old} → {new}"


def format_file(entry, width, query):
    status, added = entry[0], entry[3]
    stat = "binary" if added == "-" else f"{ADDED}+{added}{RESET} {DELETED}−{entry[4]}{RESET}"
    room = width - 4 - visible_width(stat) - 2
    path = truncate_left(file_path(entry), max(room, 1))
    pad = max(room - visible_width(path), 0)
    color = FILE_STATUS_COLORS.get(status, 250)
    return f" \x1b[38;5;{color}m{status}{RESET}  {mark(path, query)}{' ' * pad}  {stat}"


class CommitView(ListSearch):
    """Full commit information on top, its changed files below."""

    def __init__(self, commit, remotes):
        self.commit = commit
        fields = git_out("show", "-s", "--format=%H%x00%P%x00%an%x00%ae%x00%at%x00"
                         "%cn%x00%ce%x00%ct%x00%D%x00%B", commit.sha)
        full, parents, an, ae, at, cn, ce, ct, decoration, message = fields.split("\0", 9)

        def field(name, value):
            return f"{DIM}{name:<10}{RESET}{value}"

        def when(timestamp):
            timestamp = int(timestamp)
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
            return f"{stamp}  {DIM}{age(timestamp)} ago{RESET}"

        self.info = [field("commit", f"\x1b[38;5;179m{full}{RESET}")]
        if parents:
            short = len(commit.short)
            self.info.append(field("parents", " ".join(p[:short] for p in parents.split())))
        self.info.append(field("author", f"{an} <{ae}>  {when(at)}"))
        if (cn, ce, ct) != (an, ae, at):
            self.info.append(field("committer", f"{cn} <{ce}>  {when(ct)}"))
        if decoration:
            self.info.append(field("refs", labels(decoration, remotes, True)))
        subject, _, body = message.rstrip("\n").partition("\n")
        self.info += ["", f"\x1b[1m{subject}{RESET}", *body.split("\n")]

        self.files = changed_files(commit.sha)
        self.cursor = Cursor()
        self.info_top = 0
        self.page = 1
        self.wrapped = (None, [])

    def search_text(self, i):
        return file_path(self.files[i]) if i < len(self.files) else None

    def search_count(self):
        return len(self.files)

    def render(self, width, height):
        if self.wrapped[0] != width:
            self.wrapped = (width, [row for line in self.info for row in wrap(line, width - 1)])
        info = self.wrapped[1]
        body = height - 1
        # The message gets the room the file list doesn't need, and at least
        # half the screen; the file list always keeps two rows.
        info_height = min(len(info), max(body - len(self.files) - 1, body // 2), body - 3)
        info_height = max(info_height, 0)
        self.info_top = max(0, min(self.info_top, len(info) - info_height))
        self.page = body - info_height - 1

        lines = [" " + row for row in info[self.info_top:self.info_top + info_height]]
        lines.append(self._separator(width, len(info) > info_height))
        query = self.highlight()
        for i in self.cursor.window(self.page):
            if i >= len(self.files):
                lines.append("")
                continue
            line = format_file(self.files[i], width, query)
            lines.append(selected(line, width) if i == self.cursor.pos else line)
        if not self.files:
            lines[info_height + 1] = f"  {DIM}no changes against the first parent{RESET}"
        position = f"{self.cursor.pos + 1}/{len(self.files)}" if self.files else "0/0"
        lines.append(self.status(f"{self.commit.short}  file {position}",
                                 "↑↓ move  ⏎ diff  J/K scroll message  esc back", width))
        return lines

    def _separator(self, width, more_message):
        added = sum(int(f[3]) for f in self.files if f[3].isdigit())
        deleted = sum(int(f[4]) for f in self.files if f[4].isdigit())
        count = len(self.files)
        text = (f"{DIM}── {count} file{'' if count == 1 else 's'}  {RESET}"
                f"{ADDED}+{added}{RESET} {DELETED}−{deleted}{RESET}{DIM} ")
        hint = " J/K for more message ──" if more_message else ""
        fill = max(width - visible_width(text) - len(hint), 0)
        return f"{text}{'─' * fill}{hint}{RESET}"

    def handle(self, key):
        if self.search_key(key):
            return None
        if key == "esc":
            return BACK
        if key in ("message-up", "message-down"):
            self.info_top += 1 if key == "message-down" else -1
            return None
        if key == "enter":
            return DiffView(self.commit, self.files[self.cursor.pos]) if self.files else None
        self.cursor.move(key, len(self.files), self.page)
        return None


class DiffView(Search):
    def __init__(self, commit, entry):
        status, old, new = entry[:3]
        # Both paths of a rename, so git can still pair them up.
        paths = [old] if old == new else [old, new]
        diff = git_out(*DIFF_COLORS, *DIFF_ARGS, "--color=always", commit.sha, "--", *paths)
        self.lines = diff.rstrip("\n").split("\n")
        self.plain = [ANSI.sub("", line) for line in self.lines]
        self.path = new
        self.top = 0
        self.top_line = 0
        self.page = 1
        self.wrapped = (None, [], [])
        # The diff line the search is on, shown like a selected row.
        self.current = None
        self.reveal = False

    def search_text(self, i):
        return self.plain[i] if i < len(self.plain) else None

    def search_count(self):
        return len(self.plain)

    def search_pos(self):
        # Before any match, searching starts with the top line on screen.
        return self.current if self.current is not None else self.top_line - 1

    def search_jump(self, i):
        self.current, self.reveal = i, True

    def search_clear(self):
        self.current = None

    def save(self):
        return self.current, self.top

    def restore(self, saved):
        (self.current, self.top), self.reveal = saved, False

    def render(self, width, height):
        if self.wrapped[0] != width:
            rows, starts = [], []
            for index, line in enumerate(self.lines):
                starts.append(len(rows))
                rows += [(index, row) for row in wrap(line, width)]
            self.wrapped = (width, rows, starts)
        _, rows, starts = self.wrapped
        self.page = height - 1
        if self.reveal and self.current is not None:
            first = starts[self.current]
            last = starts[self.current + 1] - 1 if self.current + 1 < len(starts) else len(rows) - 1
            if not (self.top <= first and last < self.top + self.page):
                self.top = first - self.page // 3
        self.reveal = False
        self.top = max(0, min(self.top, len(rows) - self.page))
        self.top_line = rows[self.top][0] if rows else 0

        query = self.highlight()
        lines = []
        for index, row in rows[self.top:self.top + self.page]:
            row = mark(row, query)
            lines.append(selected(row, width) if index == self.current else row)
        lines += [""] * (self.page - len(lines))
        shown = f"{self.top + 1}-{min(self.top + self.page, len(rows))}/{len(rows)}"
        hints = "↑↓ scroll  space/b page  esc back"
        room = width - visible_width(hints) - len(shown) - 15
        lines.append(self.status(f"{truncate_left(self.path, max(room, 1))}  {shown}",
                                 hints, width))
        return lines

    def handle(self, key):
        if self.search_key(key):
            return None
        if key == "esc":
            return BACK
        step = {"up": -1, "down": 1, "pgup": -self.page, "pgdn": self.page,
                "home": -len(self.lines) * 99, "end": len(self.lines) * 99}.get(key)
        if step:
            self.top += step  # clamped when drawn
        return None


def read_keys(fd, timeout):
    """[(name or None, raw text)] for each key pressed; the raw text feeds the
    search prompt."""
    if not select.select([fd], [], [], timeout)[0]:
        return []
    data = os.read(fd, 1024)
    # A lone ESC may be the first byte of an arrow key split across reads.
    if data == b"\x1b" and select.select([fd], [], [], 0.03)[0]:
        data += os.read(fd, 1024)
    text = data.decode(errors="replace")
    keys, i = [], 0
    while i < len(text):
        match = ESCAPE_SEQUENCE.match(text, i)
        token = match.group() if match else text[i]
        keys.append((KEYS.get(token), token))
        i += len(token)
    return keys


def draw(lines, width):
    frame = []
    for line in lines:
        line = clip(line, width)
        # Erasing to the end of a full row would wipe its last column, since
        # autowrap is off and the cursor stays on it.
        frame.append(line + RESET + ("\x1b[K" if visible_width(line) < width else ""))
    sys.stdout.write("\x1b[H" + "\r\n".join(frame))
    sys.stdout.flush()


def browse(args):
    log = Log(args, True, stderr=subprocess.PIPE)
    graph = GraphView(log)
    graph.ensure(0)
    if not graph.rows:
        # Nothing to browse: an empty repository, or git log failed.
        error = log.proc.stderr.read()
        status = log.close()
        sys.stderr.write(error)
        return status

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    out = sys.stdout
    stack = [graph]
    size = None

    def enter_screen():
        tty.setcbreak(fd)
        # Alternate screen, hidden cursor, no autowrap.
        out.write("\x1b[?1049h\x1b[?25l\x1b[?7l")
        out.flush()

    def leave_screen():
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        out.write("\x1b[?7h\x1b[?25h\x1b[?1049l")
        out.flush()

    def suspend(signum, frame):
        # Ctrl-Z: hand the terminal back as it was, stop, and take it over
        # again once resumed with fg.
        nonlocal size
        leave_screen()
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)
        signal.signal(signal.SIGTSTP, suspend)
        enter_screen()
        size = None

    try:
        enter_screen()
        signal.signal(signal.SIGTSTP, suspend)
        dirty = True
        while stack:
            # Polled rather than SIGWINCH so a resize can't interrupt a draw.
            current = os.get_terminal_size(out.fileno())
            if current != size:
                size, dirty = current, True
                out.write("\x1b[2J")
            if dirty:
                draw(stack[-1].render(size.columns, size.lines), size.columns)
                dirty = False
            for key, raw in read_keys(fd, 0.2):
                dirty = True
                view = stack[-1]
                view.message = ""
                if view.prompt is not None:
                    view.type(raw)
                    continue
                if key == "quit":
                    stack.clear()
                    break
                if key == "enter":
                    # Opening a commit or diff with thousands of files takes a moment.
                    out.write(f"\x1b[{size.lines};1H" + status_bar("loading…", "", size.columns))
                    out.flush()
                result = view.handle(key) if key else None
                if result is BACK:
                    stack.pop()
                    if not stack:
                        break
                elif result is not None:
                    stack.append(result)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        leave_screen()
        log.close()
    return 0
