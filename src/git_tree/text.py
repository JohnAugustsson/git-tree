"""Measuring, cutting and highlighting text that may contain colour codes and
wide characters."""
import re
import time
import unicodedata

from .style import MATCH, RESET

ANSI = re.compile(r"\x1b\[[0-9;]*m")
TOKEN = re.compile(r"\x1b\[[0-9;]*m|.", re.S)
CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
TAB = 4


def char_width(ch, nxt):
    if unicodedata.combining(ch) or ch in "\u200d\ufe0e\ufe0f":
        return 0
    # An emoji variation selector widens text-default symbols such as ❤️.
    if unicodedata.east_asian_width(ch) in "WF" or nxt == "\ufe0f":
        return 2
    return 1


def visible_width(text):
    text = ANSI.sub("", text)
    return sum(char_width(c, text[i + 1:i + 2]) for i, c in enumerate(text))


def truncate(text, width):
    if visible_width(text) <= width:
        return text
    out, used = "", 0
    for i, c in enumerate(text):
        w = char_width(c, text[i + 1:i + 2])
        if used + w > width - 1:
            break
        out += c
        used += w
    return out + "…" if width > 0 else ""


def age(timestamp):
    seconds = max(0, time.time() - timestamp)
    for limit, size, unit in (
        (3600, 60, "min"),
        (86400, 3600, "hour"),
        (14 * 86400, 86400, "day"),
        (70 * 86400, 7 * 86400, "week"),
        (730 * 86400, 30 * 86400, "month"),
        (float("inf"), 365 * 86400, "year"),
    ):
        if seconds < limit:
            n = max(1, round(seconds / size))
            return f"{n} {unit}{'s' if n > 1 and unit != 'min' else ''}"


def wrap(line, width):
    """Split a coloured line into rows of at most `width` columns.

    The active colour carries over to the next row, tabs are expanded and other
    control characters are made visible so file contents can't move the cursor.
    """
    plain = ANSI.sub("", line)
    if plain.isascii() and not CONTROL.search(plain) and "\t" not in plain \
            and len(plain) <= width:
        return [line]
    tokens = TOKEN.findall(line)
    rows, row, used, sgr = [], "", 0, ""
    for i, token in enumerate(tokens):
        if len(token) > 1:
            row += token
            sgr = "" if token in (RESET, "\x1b[m") else sgr + token
            continue
        if token == "\t":
            token = " " * (TAB - used % TAB)
            w = len(token)
        elif CONTROL.match(token):
            token = "^" + chr((ord(token) + 64) % 128)
            w = 2
        else:
            w = char_width(token, tokens[i + 1] if i + 1 < len(tokens) else "")
        if used + w > width and used:
            rows.append(row + RESET)
            row, used = sgr, 0
        row += token
        used += w
    rows.append(row)
    return rows


def clip(line, width):
    return wrap(line, width)[0]


def truncate_left(text, width):
    """Keep the end of a path, which is the part that names the file."""
    if visible_width(text) <= width:
        return text
    while text and visible_width(text) > width - 1:
        text = text[1:]
    return "…" + text


def smartcase(query):
    """Vim's smartcase: case-insensitive unless the query has a capital in it."""
    return query == query.lower()


def matcher(query):
    if smartcase(query):
        query = query.lower()
        return lambda text: query in text.lower()
    return lambda text: query in text


def mark(line, query):
    """Highlight every occurrence of `query` in a coloured line."""
    if not query:
        return line
    tokens = TOKEN.findall(line)
    plain = "".join(t for t in tokens if len(t) == 1)
    haystack = plain.lower() if smartcase(query) else plain
    needle = query.lower() if smartcase(query) else query
    if len(haystack) != len(plain):
        haystack, needle = plain, query  # lowercasing changed the length
    hits = set()
    start = haystack.find(needle)
    while start >= 0:
        hits.update(range(start, start + len(needle)))
        start = haystack.find(needle, start + len(needle))
    if not hits:
        return line

    out, sgr, index, inside = [], "", 0, False
    for token in tokens:
        if len(token) > 1:
            sgr = "" if token in (RESET, "\x1b[m") else sgr + token
            if not inside:
                out.append(token)
            continue
        hit = index in hits
        if hit and not inside:
            out.append(MATCH)
        elif inside and not hit:
            out.append(RESET + sgr)
        inside = hit
        out.append(token)
        index += 1
    if inside:
        out.append(RESET + sgr)
    return "".join(out)
