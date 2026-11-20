"""Part 1 - informed search: A* route planning on the campus grid (Week 2).

A* expands the frontier node with the smallest f(n) = g(n) + h(n), where
g is the number of steps already walked and h is the Manhattan distance to
the goal. With 4-connected unit-cost moves the Manhattan distance never
overestimates the remaining steps, so it is admissible and consistent and
A* returns a shortest route.

Uniform-cost search (the same code with h = 0) is kept as a baseline so the
benefit of the heuristic can be measured by the number of expanded nodes.
"""

from heapq import heappop, heappush
from itertools import count


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def zero_heuristic(_a, _b):
    return 0


def astar(campus, start=None, goal=None, closed=frozenset(), heuristic=manhattan):
    """Return a dict with the path, its cost and a trace of every expansion.

    closed: cells treated as impassable for this search (e.g. a snowed-in
    passage). Ties on f are broken by smaller h, then by insertion order, so
    the result is deterministic.
    """
    start = campus.start if start is None else start
    goal = campus.goal if goal is None else goal
    closed = frozenset(closed)
    if not campus.walkable(start, closed) or not campus.walkable(goal, closed):
        raise ValueError("Start and goal must be open cells")

    serial = count()
    h0 = heuristic(start, goal)
    frontier = [(h0, h0, next(serial), start)]
    best_g = {start: 0}
    parent = {start: None}
    done = set()
    trace = []

    while frontier:
        f, h, _, node = heappop(frontier)
        if node in done:
            continue  # stale queue entry; a cheaper copy was already expanded
        done.add(node)
        g = best_g[node]
        trace.append({"node": node, "g": g, "h": h, "f": f,
                      "frontier": len(frontier)})
        if node == goal:
            path = []
            while node is not None:
                path.append(node)
                node = parent[node]
            path.reverse()
            return {"path": path, "cost": g, "expanded": len(trace),
                    "trace": trace, "closed": sorted(closed)}
        for nxt in campus.neighbors(node, closed):
            new_g = g + 1
            if new_g < best_g.get(nxt, float("inf")):
                best_g[nxt] = new_g
                parent[nxt] = node
                h_next = heuristic(nxt, goal)
                heappush(frontier, (new_g + h_next, h_next, next(serial), nxt))

    return {"path": None, "cost": float("inf"), "expanded": len(trace),
            "trace": trace, "closed": sorted(closed)}


def uniform_cost(campus, start=None, goal=None, closed=frozenset()):
    """A* with h = 0, i.e. uniform-cost search; used only for comparison."""
    return astar(campus, start, goal, closed, heuristic=zero_heuristic)


def plan_routes(campus):
    """Plan the two routes the decision step needs.

    shortcut: shortest route when the courtyard passage P is open
    stuck:    the robot follows the shortcut, finds P blocked on the cell
              just before it, and A* re-plans from there without P
    """
    shortcut = astar(campus)
    if shortcut["path"] is None or campus.passage not in shortcut["path"]:
        raise ValueError("Map design error: the shortest route must use P")
    index = shortcut["path"].index(campus.passage)
    turn_back_cell = shortcut["path"][index - 1]
    replan = astar(campus, start=turn_back_cell, closed={campus.passage})
    if replan["path"] is None:
        raise ValueError("Map design error: no route avoids P")
    stuck_steps = (index - 1) + replan["cost"]
    return {
        "shortcut": shortcut,
        "replan_from": turn_back_cell,
        "replan": replan,
        "steps_to_turn_back": index - 1,
        "stuck_steps": stuck_steps,
        "stuck_path": shortcut["path"][:index] + replan["path"][1:],
    }
