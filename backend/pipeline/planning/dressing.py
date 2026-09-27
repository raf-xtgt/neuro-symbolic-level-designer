"""
Dressing engine (Pipeline 2, ARCHITECTURE.md 4.1.4): weighted autotile-lite.
Deterministic for a given seed. No WFC yet: the packs have no socket rules,
so cliffs, water and fences (``autotile_required`` / ``fence``) are not used.

* Floors: each room uses the floor groups of its own ``dressing`` (else the
  global weights). Groups are assigned by quantiles of a smoothed noise
  field, so they form patches instead of salt and pepper. Corridors use the
  path floor (``floor.stone`` if present, else the main floor); everything
  else uses the main floor (the global floor group with the largest weight).
* Props inside rooms: obstacles and decorations from the style weights, at a
  density by room purpose (``DENSITY``). Treasure rooms take decorations
  mostly; boss rooms keep their center 3 x 3 clear. Never on corridor cells,
  entity cells, or the 8 neighbors of the spawn and exit. A blocking prop is
  only placed if every playable cell stays reachable (movement rule of
  ``pathing.py``).
* Wilderness: every cell outside rooms and corridors gets a blocking obstacle
  (trees and rock pillars, weighted toward the style), which encloses the
  playable area. Without blocking tiles in the catalog the wilderness stays
  floor and the map edge is the boundary (with a warning).
* Camera clearance (occlusion guard, 4.1.2): a sprite H px tall covers the
  cells up to about H / 16 steps of col + row behind it on screen. In front
  of a playable cell (larger col + row, similar screen x) the wilderness is
  graded by height: small rocks within ``SHORT_DEPTH`` steps, rock pillars
  (96 px) within ``PILLAR_DEPTH``, trees (up to 224 px) beyond.
"""
from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np

from pipeline.planning.catalog_digest import CatalogDigest, TileGroup
from pipeline.planning.layout import Cell, Layout
from pipeline.planning.models import RoomTopologyGraph, StyleWeight
from pipeline.planning.spawner import Placement

DENSITY = {"entrance": 0.03, "combat": 0.06, "puzzle": 0.10, "treasure": 0.08, "boss": 0.04}
TREASURE_DECORATION_SHARE = 0.8
WILDERNESS_FAMILIES = ("tree_", "rock_pillar")
WILDERNESS_BASE_WEIGHT = 0.1
SHORT_FAMILIES = ("rock_small",)
PILLAR_FAMILIES = ("rock_pillar",)
SHORT_DEPTH = 6  # steps of col + row in front of a playable cell (16 px each on screen)
PILLAR_DEPTH = 13
CLEARANCE_HALF_WIDTH = 3  # |(col - row) difference| (32 px each on screen)
PATH_FLOOR = "floor.stone"
_STEPS = [(dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0)]


@dataclass
class Dressing:
    ground: list[list[int]]
    objects: list[list[int]]
    group_counts: Counter = field(default_factory=Counter)  # tile group id -> cells
    warnings: list[str] = field(default_factory=list)


def dress(
    topology: RoomTopologyGraph, layout: Layout, placement: Placement, digest: CatalogDigest, seed: int,
) -> Dressing:
    rng = random.Random(seed + 104729)
    groups = digest.by_id
    warnings: list[str] = []
    counts: Counter = Counter()
    width, height = layout.width, layout.height
    ground = [[0] * width for _ in range(height)]
    objects = [[0] * width for _ in range(height)]

    global_floors = _weights(topology.style_distribution, groups, "floor")
    if not global_floors:  # the validator of the topology prevents this
        global_floors = [(digest.floors[0], 1.0)]
    main_floor = max(global_floors, key=lambda gw: gw[1])[0]
    path_floor = groups.get(PATH_FLOOR, main_floor)

    # -- Ground ---------------------------------------------------------
    noise = _smooth_noise(width, height, rng)
    for r in range(height):
        for c in range(width):
            ground[r][c] = rng.choice(main_floor.tile_ids)
    counts[main_floor.id] += width * height
    for room in topology.rooms:
        floors = _weights(room.dressing, groups, "floor") or global_floors
        cells = layout.rooms[room.id].cells()
        for cell, group in _by_quantile(cells, floors, noise):
            _set_floor(ground, counts, cell, group, main_floor, rng)
    room_cells = layout.room_cells
    for cell in layout.corridor_cells - room_cells:
        _set_floor(ground, counts, cell, path_floor, main_floor, rng)

    # -- Props in rooms ---------------------------------------------------
    reserved = set(layout.corridor_cells) | placement.cells
    for center in (placement.spawn, placement.exit):
        reserved |= {(center[0] + dc, center[1] + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    playable = layout.playable_cells
    blocked: set[Cell] = set()

    for room in topology.rooms:
        rect = layout.rooms[room.id]
        props = _weights(room.dressing, groups, "obstacle") + _weights(room.dressing, groups, "decoration")
        if not props:
            props = (_weights(topology.style_distribution, groups, "obstacle")
                     + _weights(topology.style_distribution, groups, "decoration"))
        if not props:
            continue
        free = [cell for cell in rect.cells() if cell not in reserved]
        if room.purpose == "boss":
            cc, cr = rect.center
            free = [(c, r) for c, r in free if max(abs(c - cc), abs(r - cr)) > 1]
        rng.shuffle(free)
        wanted = round(DENSITY[room.purpose] * rect.w * rect.h)
        placed = 0
        for cell in free:
            if placed >= wanted:
                break
            group = _pick_prop(props, room.purpose, rng)
            if group.blocks and not _still_connected(playable, blocked | {cell}, placement.spawn):
                continue
            objects[cell[1]][cell[0]] = rng.choice(group.tile_ids)
            counts[group.id] += 1
            if group.blocks:
                blocked.add(cell)
            placed += 1

    # -- Wilderness -------------------------------------------------------
    wild = _wilderness_groups(topology, digest)
    if wild:
        pillars = _family_groups(topology, digest, PILLAR_FAMILIES) or wild
        short = _family_groups(topology, digest, SHORT_FAMILIES) or pillars
        depth = _clearance_depth(playable)
        for r in range(height):
            for c in range(width):
                if (c, r) not in playable:
                    d = depth.get((c, r), PILLAR_DEPTH + 1)
                    pool = short if d <= SHORT_DEPTH else pillars if d <= PILLAR_DEPTH else wild
                    group = _choose(pool, rng)
                    objects[r][c] = rng.choice(group.tile_ids)
                    counts[group.id] += 1
    else:
        warnings.append(
            "the catalog has no blocking obstacles: the wilderness stays open floor and the map edge is the boundary"
        )
    return Dressing(ground, objects, counts, warnings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weights(styles: list[StyleWeight], groups: dict[str, TileGroup], category: str) -> list[tuple[TileGroup, float]]:
    return [
        (groups[s.tile_group], s.weight) for s in styles
        if s.tile_group in groups and groups[s.tile_group].category == category
    ]


def _choose(weighted: list[tuple[TileGroup, float]], rng: random.Random) -> TileGroup:
    total = sum(w for _, w in weighted)
    if total <= 0:
        return rng.choice(weighted)[0]
    x = rng.random() * total
    for group, w in weighted:
        x -= w
        if x < 0:
            return group
    return weighted[-1][0]


def _pick_prop(props: list[tuple[TileGroup, float]], purpose: str, rng: random.Random) -> TileGroup:
    if purpose == "treasure":
        decorations = [(g, w) for g, w in props if g.category == "decoration"]
        obstacles = [(g, w) for g, w in props if g.category == "obstacle"]
        if decorations and obstacles:
            return _choose(decorations if rng.random() < TREASURE_DECORATION_SHARE else obstacles, rng)
    return _choose(props, rng)


def _smooth_noise(width: int, height: int, rng: random.Random) -> np.ndarray:
    field_ = np.array([[rng.random() for _ in range(width)] for _ in range(height)])
    for _ in range(3):  # box blur 3 x 3, edges padded
        padded = np.pad(field_, 1, mode="edge")
        field_ = sum(
            padded[1 + dr: 1 + dr + height, 1 + dc: 1 + dc + width]
            for dr in (-1, 0, 1) for dc in (-1, 0, 1)
        ) / 9
    return field_


def _by_quantile(
    cells: list[Cell], weighted: list[tuple[TileGroup, float]], noise: np.ndarray,
) -> list[tuple[Cell, TileGroup]]:
    """Assigns groups to cells in noise order, in proportion to their weights."""
    total = sum(w for _, w in weighted) or 1.0
    ordered = sorted(cells, key=lambda cell: (noise[cell[1]][cell[0]], cell))
    out, start = [], 0
    for i, (group, w) in enumerate(weighted):
        end = len(ordered) if i == len(weighted) - 1 else start + round(len(ordered) * w / total)
        out += [(cell, group) for cell in ordered[start:end]]
        start = end
    return out


def _set_floor(ground, counts: Counter, cell: Cell, group: TileGroup, main: TileGroup, rng: random.Random) -> None:
    c, r = cell
    counts[main.id] -= 1
    counts[group.id] += 1
    ground[r][c] = rng.choice(group.tile_ids)


def _still_connected(playable: set[Cell], blocked: set[Cell], start: Cell) -> bool:
    """
    Every playable cell not in ``blocked`` is reachable from ``start``, under
    the movement rule of ``pathing.py`` (8 directions, no corner cutting).
    """
    open_cells = playable - blocked
    seen = {start}
    queue = deque([start])
    while queue:
        c, r = queue.popleft()
        for dc, dr in _STEPS:
            nxt = (c + dc, r + dr)
            if nxt in seen or nxt not in open_cells:
                continue
            if dc and dr and ((c + dc, r) not in open_cells or (c, r + dr) not in open_cells):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return len(seen) == len(open_cells)


def _clearance_depth(playable: set[Cell]) -> dict[Cell, int]:
    """For cells in front of playable cells on screen: the smallest col + row step."""
    depth: dict[Cell, int] = {}
    for c, r in playable:
        for d in range(1, PILLAR_DEPTH + 1):  # col + row larger by d
            for x in range(-CLEARANCE_HALF_WIDTH, CLEARANCE_HALF_WIDTH + 1):  # col - row offset
                if (d + x) % 2:
                    continue
                cell = (c + (d + x) // 2, r + (d - x) // 2)
                if d < depth.get(cell, PILLAR_DEPTH + 1):
                    depth[cell] = d
    return depth


def _family_groups(
    topology: RoomTopologyGraph, digest: CatalogDigest, families: tuple[str, ...],
) -> list[tuple[TileGroup, float]]:
    style = topology.style_map()
    found = [g for g in digest.of_category("obstacle") if g.blocks and g.family in families]
    return [(g, style.get(g.id, 0.0) + WILDERNESS_BASE_WEIGHT) for g in found]


def _wilderness_groups(topology: RoomTopologyGraph, digest: CatalogDigest) -> list[tuple[TileGroup, float]]:
    style = topology.style_map()
    blocking = [g for g in digest.of_category("obstacle") if g.blocks]
    wild = [g for g in blocking if g.family.startswith(WILDERNESS_FAMILIES)] or blocking
    return [(g, style.get(g.id, 0.0) + WILDERNESS_BASE_WEIGHT) for g in wild]
