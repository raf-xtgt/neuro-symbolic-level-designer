"""
Layout builder (Pipeline 2, ARCHITECTURE.md 4.1.1): room graph -> grid
footprint. Deterministic for a given seed.

* Room sizes: small 5 x 5, medium 7 x 7, large 9 x 9, each side with a seeded
  jitter of +/- 1.
* Bearings are screen directions in isometric view, as grid steps
  (dcol, drow): north = up on screen = (-1, -1), south = (+1, +1),
  east = (+1, -1), west = (-1, +1), center = the origin. Several rooms with
  the same bearing are placed further out along it, with a perpendicular
  offset.
* Overlapping rooms are pushed apart until at least ``GAP`` cells separate
  every pair. Then every room slides back toward the center along its own
  bearing (so it keeps its screen direction) until it would come closer than
  ``GAP`` to another room: a compact map.
* Corridors are 2 cells wide (a 2 x 2 brush along the path): ``straight`` is
  the shortest L-shape (the bend side that crosses fewer other rooms),
  ``winding`` has 2 or 3 bends (seeded), ``bridge`` is drawn straight with a
  warning (no bridge tiles yet).
* Map size: the bounding box plus ``MARGIN`` cells on each side, at least
  ``MIN_MAP`` per axis (content centered). Larger than ``MAX_MAP`` is an
  error the topology must fix.

Cells are (col, row) here. ``pathing.py`` uses (row, col).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from pipeline.planning.models import RoomTopologyGraph

Cell = tuple[int, int]  # (col, row)

SIZES = {"small": 5, "medium": 7, "large": 9}
BEARINGS: dict[str, Cell] = {
    "north": (-1, -1), "south": (1, 1), "east": (1, -1), "west": (-1, 1), "center": (0, 0),
}
GAP = 2
MARGIN = 3
MIN_MAP, MAX_MAP = 20, 48
STEP = 8  # initial distance along a bearing, per room
MAX_SEPARATION_ROUNDS = 400


class LayoutError(Exception):
    """The room graph cannot be laid out. ``fixable``: a new seed may help."""

    def __init__(self, check: str, detail: str, fixable: bool):
        super().__init__(detail)
        self.check, self.detail, self.fixable = check, detail, fixable


@dataclass
class RoomRect:
    id: str
    col: int  # top-left
    row: int
    w: int
    h: int

    @property
    def center(self) -> Cell:
        return self.col + self.w // 2, self.row + self.h // 2

    def cells(self) -> list[Cell]:
        return [(c, r) for r in range(self.row, self.row + self.h) for c in range(self.col, self.col + self.w)]

    def contains(self, cell: Cell) -> bool:
        c, r = cell
        return self.col <= c < self.col + self.w and self.row <= r < self.row + self.h

    def gap_to(self, other: RoomRect) -> int:
        """Empty cells between the two rooms along the separating axis (<0: overlap)."""
        gap_c = max(other.col - (self.col + self.w), self.col - (other.col + other.w))
        gap_r = max(other.row - (self.row + self.h), self.row - (other.row + other.h))
        return max(gap_c, gap_r)

    def shift(self, dc: int, dr: int) -> None:
        self.col += dc
        self.row += dr

    def as_dict(self) -> dict:
        return {"id": self.id, "col": self.col, "row": self.row, "w": self.w, "h": self.h}


@dataclass
class CorridorPath:
    from_room: str
    to_room: str
    corridor_type: str
    cells: list[Cell]  # 2 cells wide, ordered along the path, no duplicates
    bends: int

    def as_dict(self) -> dict:
        return {
            "from_room": self.from_room, "to_room": self.to_room, "corridor_type": self.corridor_type,
            "bends": self.bends, "cells": [list(c) for c in self.cells],
        }


@dataclass
class Layout:
    width: int
    height: int
    seed: int
    rooms: dict[str, RoomRect]
    corridors: list[CorridorPath]
    warnings: list[str] = field(default_factory=list)

    @property
    def room_cells(self) -> set[Cell]:
        return {cell for room in self.rooms.values() for cell in room.cells()}

    @property
    def corridor_cells(self) -> set[Cell]:
        return {cell for c in self.corridors for cell in c.cells}

    @property
    def playable_cells(self) -> set[Cell]:
        return self.room_cells | self.corridor_cells

    def room_at(self, cell: Cell) -> str | None:
        return next((r.id for r in self.rooms.values() if r.contains(cell)), None)

    def as_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height, "seed": self.seed,
            "rooms": [r.as_dict() for r in self.rooms.values()],
            "corridors": [c.as_dict() for c in self.corridors],
            "warnings": self.warnings,
        }


def build_layout(topology: RoomTopologyGraph, seed: int) -> Layout:
    rng = random.Random(seed)
    warnings: list[str] = []
    rooms = _place_rooms(topology, rng)
    _separate(rooms)
    _compact(rooms, {r.id: BEARINGS[r.relative_position] for r in topology.rooms})
    for a, b in _pairs(list(rooms.values())):
        if a.gap_to(b) < GAP:
            raise LayoutError(
                "rooms_layout", f"rooms {a.id} and {b.id} still overlap after separation", fixable=True,
            )

    corridors = []
    for c in topology.corridors:
        if c.corridor_type == "bridge":
            warnings.append(f"corridor {c.from_room} -> {c.to_room}: no bridge tiles yet, drawn as a straight path")
        corridors.append(_route(c.from_room, c.to_room, c.corridor_type, rooms, rng))

    width, height = _fit_to_map(rooms, corridors)
    return Layout(width, height, seed, rooms, corridors, warnings)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

def _place_rooms(topology: RoomTopologyGraph, rng: random.Random) -> dict[str, RoomRect]:
    rooms: dict[str, RoomRect] = {}
    per_bearing: dict[str, int] = {}
    for room in topology.rooms:
        w = SIZES[room.size] + rng.choice((-1, 0, 1))
        h = SIZES[room.size] + rng.choice((-1, 0, 1))
        k = per_bearing.get(room.relative_position, 0)
        per_bearing[room.relative_position] = k + 1

        dc, dr = BEARINGS[room.relative_position]
        pc, pr = (1, -1) if (dc, dr) == (0, 0) else (-dr, dc)  # perpendicular (screen left/right)
        side = 1 if k % 2 else -1
        spread = (k + 1) // 2 * STEP  # 0, 8, 8, 16, 16, ...
        if (dc, dr) == (0, 0):
            cc, cr = side * spread * pc, side * spread * pr
        else:
            along = STEP * (1 + k // 2 + (1 if k else 0))
            cc = dc * along + side * spread * pc // 2
            cr = dr * along + side * spread * pr // 2
        cc += rng.choice((-1, 0, 1))
        cr += rng.choice((-1, 0, 1))
        rooms[room.id] = RoomRect(room.id, cc - w // 2, cr - h // 2, w, h)
    return rooms


def _pairs(items: list) -> list[tuple]:
    return [(a, b) for i, a in enumerate(items) for b in items[i + 1:]]


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _separate(rooms: dict[str, RoomRect]) -> None:
    """Pushes rooms apart, one cell at a time, until every pair is ``GAP`` apart."""
    order = list(rooms.values())
    for _ in range(MAX_SEPARATION_ROUNDS):
        moved = False
        for a, b in _pairs(order):
            if a.gap_to(b) >= GAP:
                continue
            # Move the room further from the origin, away from the other one.
            (ac, ar), (bc, br) = a.center, b.center
            mover, other = (b, a) if abs(bc) + abs(br) >= abs(ac) + abs(ar) else (a, b)
            (mc, mr), (oc, orow) = mover.center, other.center
            dc, dr = _sign(mc - oc), _sign(mr - orow)
            if (dc, dr) == (0, 0):
                dc, dr = _sign(mc) or 1, _sign(mr) or 1
            mover.shift(dc, dr)
            moved = True
        if not moved:
            return


def _compact(rooms: dict[str, RoomRect], bearings: dict[str, Cell]) -> None:
    """Slides rooms toward the origin along their bearing while every gap stays >= ``GAP``."""
    order = sorted(rooms.values(), key=lambda r: abs(r.center[0]) + abs(r.center[1]))
    moved = True
    while moved:
        moved = False
        for room in order:
            dc, dr = bearings[room.id]
            if (dc, dr) == (0, 0):
                continue
            c, r = room.center
            if (c - dc) * dc + (r - dr) * dr <= 0:  # would reach or cross the center
                continue
            room.shift(-dc, -dr)
            if any(room.gap_to(other) < GAP for other in rooms.values() if other is not room):
                room.shift(dc, dr)
            else:
                moved = True


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------

def _brush(path: list[Cell]) -> list[Cell]:
    """A 2-cell wide corridor: a 2 x 2 block at every path cell, in order."""
    seen: set[Cell] = set()
    cells = []
    for c, r in path:
        for cell in ((c, r), (c + 1, r), (c, r + 1), (c + 1, r + 1)):
            if cell not in seen:
                seen.add(cell)
                cells.append(cell)
    return cells


def _segment(a: Cell, b: Cell) -> list[Cell]:
    """Straight cells from a to b (same col or same row), both included."""
    (c0, r0), (c1, r1) = a, b
    if c0 == c1:
        step = _sign(r1 - r0) or 1
        return [(c0, r) for r in range(r0, r1 + step, step)]
    step = _sign(c1 - c0) or 1
    return [(c, r0) for c in range(c0, c1 + step, step)]


def _through(points: list[Cell]) -> list[Cell]:
    path: list[Cell] = []
    for a, b in zip(points, points[1:]):
        for cell in _segment(a, b):
            if not path or path[-1] != cell:
                path.append(cell)
    return path


def _bends(points: list[Cell]) -> int:
    pts = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    dirs = []
    for (c0, r0), (c1, r1) in zip(pts, pts[1:]):
        d = "h" if r0 == r1 else "v"
        if not dirs or dirs[-1] != d:
            dirs.append(d)
    return max(0, len(dirs) - 1)


def _route(
    from_id: str, to_id: str, kind: str, rooms: dict[str, RoomRect], rng: random.Random,
) -> CorridorPath:
    a, b = rooms[from_id].center, rooms[to_id].center
    others = [r for rid, r in rooms.items() if rid not in (from_id, to_id)]

    def crossings(points: list[Cell]) -> int:
        return sum(1 for cell in _brush(_through(points)) for r in others if r.contains(cell))

    (c0, r0), (c1, r1) = a, b
    if kind == "winding":
        points = _winding(a, b, rng)
    else:
        options = [[a, (c1, r0), b], [a, (c0, r1), b]]  # col first, row first
        points = min(options, key=crossings)
    return CorridorPath(from_id, to_id, kind, _brush(_through(points)), _bends(points))


def _winding(a: Cell, b: Cell, rng: random.Random) -> list[Cell]:
    """2 or 3 bends between a and b."""
    (c0, r0), (c1, r1) = a, b
    dc, dr = c1 - c0, r1 - r0

    def between(x0: int, x1: int) -> int:
        lo, hi = sorted((x0, x1))
        return rng.randint(lo + 1, hi - 1)

    if abs(dc) >= 2 and abs(dr) >= 2 and rng.random() < 0.5:
        m, n = between(c0, c1), between(r0, r1)
        return [a, (m, r0), (m, n), (c1, n), b]  # 3 bends
    if abs(dc) >= 2:
        m = between(c0, c1)
        if dr:
            return [a, (m, r0), (m, r1), b]  # 2 bends
        off = rng.choice((-4, 4))  # same row: detour sideways
        return [a, (c0, r0 + off), (c1, r0 + off), b]
    if abs(dr) >= 2:
        n = between(r0, r1)
        if dc:
            return [a, (c0, n), (c1, n), b]
        off = rng.choice((-4, 4))
        return [a, (c0 + off, r0), (c0 + off, r1), b]
    return [a, (c1, r0), b]


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def _fit_to_map(rooms: dict[str, RoomRect], corridors: list[CorridorPath]) -> tuple[int, int]:
    """Moves everything inside the map with the margin; returns the map size."""
    cells = [cell for r in rooms.values() for cell in r.cells()] + [x for c in corridors for x in c.cells]
    min_c, max_c = min(c for c, _ in cells), max(c for c, _ in cells)
    min_r, max_r = min(r for _, r in cells), max(r for _, r in cells)
    w, h = max_c - min_c + 1 + 2 * MARGIN, max_r - min_r + 1 + 2 * MARGIN
    if w > MAX_MAP or h > MAX_MAP:
        raise LayoutError(
            "map_size",
            f"the layout needs {w} x {h} cells; the maximum is {MAX_MAP} x {MAX_MAP}. "
            "Use fewer or smaller rooms, or fewer rooms on the same bearing",
            fixable=False,
        )
    width, height = max(w, MIN_MAP), max(h, MIN_MAP)
    dc = MARGIN - min_c + (width - w) // 2
    dr = MARGIN - min_r + (height - h) // 2
    for room in rooms.values():
        room.shift(dc, dr)
    for corridor in corridors:
        corridor.cells = [(c + dc, r + dr) for c, r in corridor.cells]
    return width, height
