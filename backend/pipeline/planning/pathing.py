"""
Walkability and path checks on a level plan grid.

A cell is walkable when its ``Objects`` tile (overlay layers, 0 = empty) is
empty or walkable. Ground tiles are assumed walkable. Movement uses 8
directions, like the game (WASD / arrow combinations move diagonally).
"""
from __future__ import annotations

from collections import deque

Cell = tuple[int, int]  # (row, col)

_DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def blocked_cells(plan: dict, catalog: dict) -> set[Cell]:
    """Cells whose overlay tile is not walkable."""
    walkable = {t["id"]: t["walkable"] for t in catalog["tiles"]}
    blocked: set[Cell] = set()
    for layer in plan["layers"][1:]:
        for r, row in enumerate(layer["grid"]):
            for c, tile_id in enumerate(row):
                if tile_id != 0 and not walkable[tile_id]:
                    blocked.add((r, c))
    return blocked


def shortest_path(width: int, height: int, blocked: set[Cell], start: Cell, goal: Cell) -> list[Cell] | None:
    """BFS over 8 directions. Returns the cells from start to goal, or None."""
    if start in blocked or goal in blocked:
        return None
    previous: dict[Cell, Cell | None] = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        if cell == goal:
            path = [cell]
            while previous[path[-1]] is not None:
                path.append(previous[path[-1]])
            return path[::-1]
        r, c = cell
        for dr, dc in _DIRECTIONS:
            nxt = (r + dr, c + dc)
            if 0 <= nxt[0] < height and 0 <= nxt[1] < width and nxt not in blocked and nxt not in previous:
                previous[nxt] = cell
                queue.append(nxt)
    return None


def line_cells(start: Cell, goal: Cell) -> list[Cell]:
    """Cells on the straight line from start to goal (Bresenham)."""
    (r0, c0), (r1, c1) = start, goal
    dr, dc = abs(r1 - r0), abs(c1 - c0)
    sr, sc = (1 if r1 > r0 else -1), (1 if c1 > c0 else -1)
    err, cells = dc - dr, []
    while True:
        cells.append((r0, c0))
        if (r0, c0) == (r1, c1):
            return cells
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c0 += sc
        if e2 < dc:
            err += dc
            r0 += sr


def path_check(plan: dict, catalog: dict) -> dict:
    """``{path_found, path_length}`` from PlayerSpawn to ExitTrigger."""
    ends = {o["type"]: (o["row"], o["col"]) for o in plan["objects"]}
    props = plan["map_properties"]
    path = shortest_path(
        props["width"], props["height"], blocked_cells(plan, catalog),
        ends["PlayerSpawn"], ends["ExitTrigger"],
    )
    # Length in steps (moves), not cells.
    return {"path_found": path is not None, "path_length": len(path) - 1 if path else None}
