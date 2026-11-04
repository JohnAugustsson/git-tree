"""Reading git log and printing the graph as text."""
import os
import signal
import subprocess
import sys
from collections import namedtuple

from .graph import Graph
from .style import DIM, LABEL_STYLES, RESET
from .text import age, truncate, visible_width

SEP = "\x1f"
AUTHOR_WIDTH = 16
DATE_WIDTH = 9


def labels(decoration, remotes, color):
    """Turn %D into labels, folding `origin/x` into `x ⇅` when both sit on this commit."""
    names = [d.strip() for d in decoration.split(",") if d.strip()]
    head, locals_, remotes_, tags = None, [], [], []
    for name in names:
        if name.startswith("HEAD -> "):
            head = name[len("HEAD -> "):]
            locals_.append(head)
        elif name == "HEAD":
            head = "HEAD"
        elif name.startswith("tag: "):
            tags.append(name[len("tag: "):])
        elif name.split("/", 1)[0] in remotes:
            if not name.endswith("/HEAD"):
                remotes_.append(name)
        else:
            locals_.append(name)

    out = []
    if head == "HEAD":
        out.append(("head", "HEAD"))
    for name in locals_:
        synced = [r for r in remotes_ if r.split("/", 1)[1] == name]
        for r in synced:
            remotes_.remove(r)
        text = name + (" ⇅" if synced else "")
        out.append(("head", "HEAD → " + text) if name == head else ("local", text))
    out += [("remote", r) for r in remotes_]
    out += [("tag", t) for t in tags]

    if color:
        return " ".join(f"{LABEL_STYLES[kind]} {text} {RESET}" for kind, text in out)
    return " ".join(f"[{text}]" for _, text in out)


def git_out(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          errors="replace").stdout


Commit = namedtuple("Commit", "sha short graph refs subject author ctime")


class Log:
    """Streams `git log`, laying out each commit's graph row as it is read."""

    def __init__(self, args, color, stderr=None):
        self.color = color
        self.remotes = set(git_out("remote").split())
        # Empty when there is no commit yet; HEAD can't be passed to git log then.
        head = git_out("rev-parse", "--verify", "-q", "HEAD").strip()
        self.graph = Graph(color, head)
        # --parents makes %P the rewritten parents when a pathspec simplifies
        # history, so lines connect through the commits that are actually shown.
        self.proc = subprocess.Popen(
            ["git", "log", "--topo-order", "--parents",
             "--branches", "--remotes", "--tags", *(["HEAD"] if head else []),
             f"--format=%H{SEP}%P{SEP}%h{SEP}%ct{SEP}%an{SEP}%D{SEP}%s", *args],
            stdout=subprocess.PIPE, stderr=stderr, text=True, errors="replace")

    def __iter__(self):
        for line in self.proc.stdout:
            sha, parents, short, ctime, author, decoration, subject = \
                line.rstrip("\n").split(SEP, 6)
            yield Commit(sha, short, self.graph.row(sha, parents.split()),
                         labels(decoration, self.remotes, self.color),
                         subject, author, int(ctime))

    def close(self):
        self.proc.stdout.close()
        if self.proc.poll() is None:
            self.proc.terminate()
        status = self.proc.wait()
        if self.proc.stderr:
            self.proc.stderr.close()
        return status


def format_row(commit, width, color):
    left = commit.graph + " " + (commit.refs + " " if commit.refs else "")
    meta = (f"{truncate(commit.author, AUTHOR_WIDTH):<{AUTHOR_WIDTH}}  "
            f"{age(commit.ctime):>{DATE_WIDTH}}  {commit.short}")
    if width is None:
        return f"{left}{commit.subject}  {meta}"
    room = width - visible_width(left) - len(meta) - 2
    subject = truncate(commit.subject, max(room, 0))
    pad = max(room - visible_width(subject), 0)
    dim, reset = (DIM, RESET) if color else ("", "")
    return f"{left}{subject}{' ' * pad}  {dim}{meta}{reset}"


def page(args):
    """Print the graph, through git's pager when writing to a terminal."""
    tty_out = sys.stdout.isatty()
    # A pty that never had its size set reports 0 columns.
    width = (os.get_terminal_size(sys.stdout.fileno()).columns or None) if tty_out else None
    log = Log(args, tty_out)

    out = sys.stdout
    pager = None
    if tty_out:
        env = dict(os.environ)
        env.setdefault("LESS", "FRSX")
        env.setdefault("LV", "-c")
        pager_cmd = git_out("var", "GIT_PAGER").strip()
        if pager_cmd and pager_cmd != "cat":
            pager = subprocess.Popen(pager_cmd, shell=True, stdin=subprocess.PIPE,
                                     text=True, env=env)
            out = pager.stdin
            # Like git: Ctrl-C belongs to the pager, quitting it ends the log.
            signal.signal(signal.SIGINT, signal.SIG_IGN)

    status = 0
    try:
        for commit in log:
            out.write(format_row(commit, width, tty_out) + "\n")
        status = log.proc.wait()
    except BrokenPipeError:
        pass  # the pager was quit before the end
    except KeyboardInterrupt:
        status = 130
    finally:
        log.close()
        if pager:
            try:
                pager.stdin.close()
            except BrokenPipeError:
                pass
            pager.wait()
    return status
