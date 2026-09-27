"""
Gameplay and spawner (Pipeline 2, ARCHITECTURE.md 4.1.3). Deterministic.

* ``PlayerSpawn`` at the entrance room center.
* ``ExitTrigger`` at the center of the room with the largest corridor-graph
  distance from the entrance. Ties: a boss room first, then a treasure room
  (the natural end of a level), then the largest grid distance.
* Zombies per room from ``enemy_count``, at least ``MIN_SPAWN_DISTANCE``
  cells (Chebyshev) from the spawn, spread out by farthest-point sampling
  (seeded first pick). Combat and boss rooms with 3 or more zombies move one
  of them into the connecting corridor on the approach from the entrance,
  just outside the room, where it guards the way in (the total stays as
  planned).
Dressing runs later and never covers these cells, so they stay walkable.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from pipeline.planning.layout import Cell, Layout
from pipeline.planning.models import RoomTopologyGraph

MIN_SPAWN_DISTANCE = 3
EXIT_PURPOSE_RANK = {"boss": 2, "treasure": 1}
GUARD_DISTANCE = 2  # corridor guard: cells outside the room edge


@dataclass
class Placement:
    spawn: Cell
    exit: Cell
    exit_room: str
    zombies: list[tuple[str, Cell]]  # (room id or "corridor:<a>-<b>", cell)
    warnings: list[str] = field(default_factory=list)

    def objects(self) -> list[dict]:
        """``level_plan.json`` objects (col, row)."""
        objects = [
            {"name": "spawn_player", "type": "PlayerSpawn", "col": self.spawn[0], "row": self.spawn[1]},
            {"name": "exit_trigger", "type": "ExitTrigger", "col": self.exit[0], "row": self.exit[1]},
        ]
        objects += [
            {"name": f"zombie_{i}", "type": "Zombie", "col": c, "row": r}
            for i, (_, (c, r)) in enumerate(self.zombies)
        ]
        return objects

    @property
    def cells(self) -> set[Cell]:
        return {self.spawn, self.exit, *(cell for _, cell in self.zombies)}


def chebyshev(a: Cell, b: Cell) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def place_entities(topology: RoomTopologyGraph, layout: Layout, seed: int) -> Placement:
    rng = random.Random(seed + 7919)
    warnings: list[str] = []
    entrance = topology.entrance
    spawn = layout.rooms[entrance.id].center

    distances = topology.graph_distances(entrance.id)
    exit_room = max(
        (r for r in topology.rooms if r.id != entrance.id),
        key=lambda r: (
            distances.get(r.id, -1), EXIT_PURPOSE_RANK.get(r.purpose, 0), chebyshev(layout.rooms[r.id].center, spawn),
        ),
    ).id
    exit_cell = layout.rooms[exit_room].center

    taken = {spawn, exit_cell}
    zombies: list[tuple[str, Cell]] = []
    corridor_cells = layout.corridor_cells
    for room in topology.rooms:
        if room.enemy_count == 0:
            continue
        candidates = [
            cell for cell in layout.rooms[room.id].cells()
            if cell not in taken and chebyshev(cell, spawn) >= MIN_SPAWN_DISTANCE
        ]
        wanted = room.enemy_count
        in_corridor = None
        if room.purpose in ("combat", "boss") and wanted >= 3:
            in_corridor = _corridor_cell(room.id, layout, taken, spawn, distances)
            if in_corridor is not None:
                wanted -= 1
        picked = _spread(candidates, wanted, rng, prefer_off=corridor_cells)
        if len(picked) < wanted:
            warnings.append(f"room {room.id}: room for {len(picked)} of {wanted} zombies only")
        for cell in picked:
            zombies.append((room.id, cell))
            taken.add(cell)
        if in_corridor is not None:
            zombies.append((f"corridor:{room.id}", in_corridor))
            taken.add(in_corridor)
    return Placement(spawn, exit_cell, exit_room, zombies, warnings)


def _corridor_cell(
    room_id: str, layout: Layout, taken: set[Cell], spawn: Cell, distances: dict[str, int],
) -> Cell | None:
    """
    A guard cell on a corridor of ``room_id``, outside every room, as close to
    ``GUARD_DISTANCE`` cells from the room edge as possible. Corridors toward
    the entrance (the approach) come first.
    """
    rect = layout.rooms[room_id]
    room_cells = layout.room_cells

    def edge_distance(cell: Cell) -> int:
        c, r = cell
        dc = max(rect.col - c, 0, c - (rect.col + rect.w - 1))
        dr = max(rect.row - r, 0, r - (rect.row + rect.h - 1))
        return max(dc, dr)

    def approach(corridor) -> int:
        other = corridor.to_room if corridor.from_room == room_id else corridor.from_room
        return distances.get(other, 99)

    corridors = sorted(
        (c for c in layout.corridors if room_id in (c.from_room, c.to_room)), key=approach,
    )
    for corridor in corridors:
        outside = [
            cell for cell in corridor.cells
            if cell not in room_cells and cell not in taken and chebyshev(cell, spawn) >= MIN_SPAWN_DISTANCE
        ]
        if outside:
            return min(outside, key=lambda cell: (abs(edge_distance(cell) - GUARD_DISTANCE), cell))
    return None


def _spread(candidates: list[Cell], n: int, rng: random.Random, prefer_off: set[Cell]) -> list[Cell]:
    """Farthest-point sampling: each pick maximizes the distance to earlier picks."""
    if n <= 0 or not candidates:
        return []
    # Prefer cells off the corridor strip that runs through the room.
    pool = [c for c in candidates if c not in prefer_off] or candidates
    if len(pool) < n:
        pool = candidates
    picked = [rng.choice(pool)]
    while len(picked) < min(n, len(pool)):
        best = max(
            (c for c in pool if c not in picked),
            key=lambda c: (min(chebyshev(c, p) for p in picked), rng.random()),
        )
        picked.append(best)
    return picked
