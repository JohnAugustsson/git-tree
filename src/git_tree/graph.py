"""Lane layout: one row per commit, every line of history in its own column."""
from .style import LANE_COLORS, RESET

COMMIT, MERGE = "●", "○"
UP, DOWN, LEFT, RIGHT = 1, 2, 4, 8
GLYPHS = {
    UP | DOWN: "│", LEFT | RIGHT: "─",
    UP | LEFT: "╯", UP | RIGHT: "╰", DOWN | LEFT: "╮", DOWN | RIGHT: "╭",
    UP | DOWN | LEFT: "┤", UP | DOWN | RIGHT: "├",
    UP | LEFT | RIGHT: "┴", DOWN | LEFT | RIGHT: "┬",
    UP | DOWN | LEFT | RIGHT: "┼",
}

# A line with no commit of its own on a row only jogs left (╭───╯) across a gap
# at least this wide; narrower gaps are left alone so lines stay put.
MIN_JOG = 3


class Graph:
    """Assigns each commit a column and draws its row.

    `lanes[i]` is the commit that the line in column i is heading down to, or
    None for a free column. Free columns are reused, and an occupied one only
    moves left to close a gap, which keeps every branch in a straight line.
    """

    def __init__(self, color, head):
        self.next_color = 0
        self.color = color
        # Column 0 is held for HEAD from the top, and the line through HEAD and
        # its first parents wins every join, so the checked-out branch runs
        # straight down the left edge with everything else branching off it.
        self.head = head
        self.reserved = bool(head)
        self.head_column = 0 if head else None
        self.lanes = [head] if head else []
        self.colors = [None] * len(self.lanes)
        if head:
            self._paint(0)

    def _free_column(self, start, avoid):
        for i in range(start, len(self.lanes)):
            if self.lanes[i] is None and i not in avoid:
                return i
        self.lanes.append(None)
        self.colors.append(None)
        return len(self.lanes) - 1

    def _paint(self, column):
        # Rotate through the palette, skipping the neighbours' colours so
        # adjacent lines stay distinguishable.
        near = {self.colors[i] for i in (column - 1, column + 1)
                if 0 <= i < len(self.colors) and self.lanes[i] is not None}
        for _ in LANE_COLORS:
            color = LANE_COLORS[self.next_color % len(LANE_COLORS)]
            self.next_color += 1
            if color not in near:
                break
        self.colors[column] = color

    def row(self, sha, parents):
        before = list(self.lanes)
        # Until HEAD's row, or a merge of HEAD above it, column 0 is only a
        # reservation and is not drawn.
        hide_up = self.reserved

        expecting = [i for i, lane in enumerate(self.lanes) if lane == sha]
        if expecting:
            column = expecting[0]
            if self.head_column in expecting:
                column = self.head_column
        else:
            column = self._free_column(0, ())
            self._paint(column)

        # Other children's lines end here: they branched off this commit.
        targets = {}
        for i in expecting:
            if i == column:
                continue
            self.lanes[i] = None
            targets[i] = self.colors[i]

        dot_color = self.colors[column]
        self.lanes[column] = parents[0] if parents else None
        if column == self.head_column and not parents:
            self.head_column = None

        # Slide the line left through free columns (╭─●) so gaps left by
        # finished branches close up. It never crosses another line.
        free = column
        while (free > 0 and self.lanes[free - 1] is None
               and before[free - 1] is None and free - 1 not in targets):
            free -= 1
        if parents and free < column:
            self.lanes[free], self.lanes[column] = self.lanes[column], None
            self.colors[free] = self.colors[column]
            if self.head_column == column:
                self.head_column = free
            targets[free] = self.colors[free]

        # Further parents of a merge: join a line already heading there, or
        # open a new one (to the right where possible, as Git Extensions does).
        for parent in parents[1:]:
            if parent in self.lanes:
                i = self.lanes.index(parent)
            else:
                i = self._free_column(column + 1, set(expecting))
                self.lanes[i] = parent
                self._paint(i)
            targets[i] = self.colors[i]

        span = range(min([column, *targets]), max([column, *targets]) + 1)
        jogs = []
        for i in range(len(self.lanes)):
            if self.lanes[i] is None or i >= len(before) or before[i] is None or i in span:
                continue
            free = i
            while (free > 0 and self.lanes[free - 1] is None
                   and before[free - 1] is None and free - 1 not in span):
                free -= 1
            if i - free >= MIN_JOG:
                self.lanes[free], self.lanes[i] = self.lanes[i], None
                self.colors[free] = self.colors[i]
                if self.head_column == i:
                    self.head_column = free
                jogs.append((free, i))

        while self.lanes and self.lanes[-1] is None:
            self.lanes.pop()
            self.colors.pop()

        if sha == self.head or 0 in targets:
            self.reserved = False
        hide_down = self.reserved

        width = max(len(before), len(self.lanes), max(targets, default=-1) + 1)
        cells = [[0, None] for _ in range(width)]
        gaps = [[" ", None] for _ in range(width)]
        for i in range(width):
            if i < len(before) and before[i] is not None and not (i == 0 and hide_up):
                cells[i][0] |= UP
            if i < len(self.lanes) and self.lanes[i] is not None and not (i == 0 and hide_down):
                cells[i][0] |= DOWN
            if cells[i][0] and i < len(self.colors):
                cells[i][1] = self.colors[i]

        # Farthest connection first so nearer ones overwrite the shared span
        # with their own colour.
        for target in sorted(targets, key=lambda t: -abs(t - column)):
            color = targets[target]
            step = 1 if target > column else -1
            cells[target][0] |= LEFT if step > 0 else RIGHT
            cells[target][1] = color
            for i in range(column + step, target, step):
                # An unrelated line crossing the span stays unbroken on top.
                if i in targets or cells[i][0] & (UP | DOWN) != UP | DOWN:
                    cells[i][0] |= LEFT | RIGHT
                    cells[i][1] = color
            for i in range(min(column, target), max(column, target)):
                gaps[i] = ["─", color]
        # A target with a farther one beyond it is a junction on the span.
        for target in targets:
            if target > column and any(t > target for t in targets):
                cells[target][0] |= RIGHT
            if target < column and any(t < target for t in targets):
                cells[target][0] |= LEFT
        for left, right in jogs:
            color = self.colors[left]
            cells[left] = [DOWN | RIGHT, color]
            cells[right] = [UP | LEFT, color]
            for i in range(left + 1, right):
                cells[i] = [LEFT | RIGHT, color]
            for i in range(left, right):
                gaps[i] = ["─", color]

        out = []
        for i in range(width):
            mask, color = cells[i]
            if i == column:
                glyph, color = (MERGE if len(parents) > 1 else COMMIT), dot_color
            else:
                glyph = GLYPHS.get(mask, " ")
            out.append(self._colored(glyph, color))
            if i < width - 1:
                out.append(self._colored(*gaps[i]))
        return "".join(out).rstrip()

    def _colored(self, text, color):
        if not self.color or color is None or text == " ":
            return text
        return f"\x1b[38;5;{color}m{text}{RESET}"
