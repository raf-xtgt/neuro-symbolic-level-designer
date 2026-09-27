"""
Walkability and path checks on a level plan grid.

A cell is walkable when its ``Objects`` tile (overlay layers, 0 = empty) is
empty or walkable. Ground tiles are assumed walkable. Cells outside the map
are blocked.

Movement rule, shared with the game (``lib/game/level/walkability.dart``):
8 directions (WASD / arrow combinations move diagonally), and a diagonal step
is allowed only if both orthogonal neighbors are open, so a character never
cuts a corner between two obstacles.
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


def can_step(width: int, height: int, blocked: set[Cell], cell: Cell, dr: int, dc: int) -> bool:
    """True if a character on ``cell`` may step by (dr, dc) under the movement rule."""
    r, c = cell

    def is_open(rr: int, cc: int) -> bool:
        return 0 <= rr < height and 0 <= cc < width and (rr, cc) not in blocked

    if not is_open(r + dr, c + dc):
        return False
    if dr and dc:  # diagonal: no corner cutting
        return is_open(r + dr, c) and is_open(r, c + dc)
    return True


def shortest_path(width: int, height: int, blocked: set[Cell], start: Cell, goal: Cell) -> list[Cell] | None:
    """BFS under the movement rule. Returns the cells from start to goal, or None."""
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
            if nxt not in previous and can_step(width, height, blocked, cell, dr, dc):
                previous[nxt] = cell
                queue.append(nxt)
    return None


def line_cells(start: Cell, goal: Cell) -> list[Cell]:
    """Cells on the straight line from start to goal (Bresenham, 8-connected)."""
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


def line_corridor(start: Cell, goal: Cell) -> list[Cell]:
    """
    The straight line plus, for each diagonal step, the corner cell
    ``(row of the step start, col of the step end)``. With all these cells
    open, the line is walkable without corner cutting.
    """
    cells: list[Cell] = []
    line = line_cells(start, goal)
    for a, b in zip(line, line[1:]):
        cells.append(a)
        if a[0] != b[0] and a[1] != b[1]:
            cells.append((a[0], b[1]))
    cells.append(line[-1])
    return cells


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
