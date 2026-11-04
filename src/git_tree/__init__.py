"""A commit graph for the terminal, laid out like Git Extensions' revision grid.

One row per commit. Every line of history keeps its own column and colour, a
branch-off is drawn on its fork point's row (●─╯) and a merge on the merge
commit's row (○─╮), so lines stay in their column instead of drifting between
rows. Refs are coloured labels and author/date/hash sit in aligned columns on
the right.
"""

__version__ = "0.1.0"
