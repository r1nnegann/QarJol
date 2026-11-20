"""The toy campus map used by every part of the project.

The map is a hypothetical 6x6 grid inspired by a winter university campus.
It is not a survey of a real campus: buildings, distances and the snow-prone
passage are classroom assumptions chosen to make the decision interesting.

Legend
    S  start: dormitory parcel point
    G  goal: AI Lab entrance
    P  open courtyard passage (short, but snow drifts can block it)
    L  library block        (impassable)
    M  main building        (impassable)
    C  canteen              (impassable)
    .  open walkway

Moves are 4-connected (up, down, left, right). Each move costs 1 step,
which we read as roughly one minute for the robot in snow.
"""

CAMPUS_ROWS = (
    "...G..",
    ".C....",
    ".MMMMP",
    "......",
    ".LL...",
    "....S.",
)

BUILDING_NAMES = {"L": "Library", "M": "Main building", "C": "Canteen"}
WALKABLE = {".", "S", "G", "P"}
MOVES = ((-1, 0), (0, 1), (1, 0), (0, -1))  # up, right, down, left


class Campus:
    """Grid world with named cells and an optional set of closed cells."""

    def __init__(self, rows=CAMPUS_ROWS):
        widths = {len(row) for row in rows}
        if len(widths) != 1:
            raise ValueError("All map rows must have the same width")
        self.rows = tuple(rows)
        self.height = len(rows)
        self.width = widths.pop()
        self.start = self._find("S")
        self.goal = self._find("G")
        self.passage = self._find("P")

    def _find(self, symbol):
        cells = [(r, c) for r, row in enumerate(self.rows)
                 for c, ch in enumerate(row) if ch == symbol]
        if len(cells) != 1:
            raise ValueError(f"Map must contain exactly one {symbol!r}")
        return cells[0]

    def symbol(self, cell):
        r, c = cell
        return self.rows[r][c]

    def in_bounds(self, cell):
        r, c = cell
        return 0 <= r < self.height and 0 <= c < self.width

    def walkable(self, cell, closed=frozenset()):
        return (self.in_bounds(cell) and self.symbol(cell) in WALKABLE
                and cell not in closed)

    def neighbors(self, cell, closed=frozenset()):
        r, c = cell
        for dr, dc in MOVES:
            nxt = (r + dr, c + dc)
            if self.walkable(nxt, closed):
                yield nxt

    def render(self, path=(), closed=frozenset()):
        """ASCII picture; '*' marks the path, 'X' marks a closed cell."""
        on_path = set(path)
        lines = []
        for r, row in enumerate(self.rows):
            out = []
            for c, ch in enumerate(row):
                cell = (r, c)
                if cell in closed:
                    out.append("X")
                elif ch in "SGP":
                    out.append(ch)
                elif cell in on_path:
                    out.append("*")
                else:
                    out.append(ch)
            lines.append(" ".join(out))
        return "\n".join(lines)
