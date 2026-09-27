"""
Dressing engine (Pipeline 2, ARCHITECTURE.md 4.1.4): weighted autotile-lite.
Deterministic for a given seed. No WFC yet: the packs have no socket rules,
so cliffs, water and fences (``autotile_required`` / ``fence``) are not used.

* Floors: each room uses the floor groups of its own ``dressing`` (else the
  global weights). Groups are assigned by quantiles of a smoothed noise
  field, so they form patches instead of salt and pepper. Corridors use the
  path floor (``floor.stone`` if present, else the main floor); everything
  else uses the main floor (the global floor group with the largest weight).
* Structures: a ``structure.*`` group named in a room's ``dressing`` is
  placed once in that room, on free cells covering its footprint (east
  diagonal ``(col + i, row - i)``), all footprint cells kept free of props.
  The sprite goes on the middle footprint cell: its anchor is the bottom
  center of the whole building.
* Props inside rooms: obstacles and decorations from the style weights, in
  clusters of 2 to 4 cells of one group with at least 1 open cell between
  clusters, up to a density by room purpose (``DENSITY``). A room with its
  own non-floor ``dressing`` gets at least ``MIN_OWN_CLUSTERS`` clusters of
  it. Treasure rooms take decorations mostly; boss rooms keep their center
  3 x 3 clear. Never on corridor cells, entity cells, or the 8 neighbors of
  the spawn and exit. Blocking props and structures are only placed if every
  playable cell stays reachable (movement rule of ``pathing.py``).
* Wilderness (every cell outside rooms and corridors):
  - Hedge: the ring of ``HEDGE_THICKNESS`` cells around the playable area
    (8-connected), all blocking, but 1 cell thick in front of a playable cell
    (within ``SHORT_DEPTH`` steps). The inner ring alone encloses the area
    under the movement rule. Front hedge cells take natural low blockers
    (``LOW_FAMILIES``: rocks, stumps, logs), never the same variant as an
    8-neighbor where the family has more; hedge cells further in front take
    rock pillars; the others take trees and rock pillars.
  - Front zone (beyond the hedge, within ``PILLAR_DEPTH`` steps in front of
    a playable cell): open main floor with sparse decorations
    (``FRONT_DECORATION_DENSITY``). It is unreachable behind the hedge.
  - Back and side zones: dense trees and rock pillars.
  Trees favor the style: when the style names tree groups, at least
  ``STYLE_TREE_SHARE`` of the trees come from them. A catalog without tree,
  pillar or low-blocker families (a farm or an indoor set) uses any blocking
  obstacle group (else blocking decoration group) for all of these. Without blocking tiles in
  the catalog the wilderness stays floor and the map edge is the boundary
  (with a warning).
* Camera clearance (occlusion guard, 4.1.2): a sprite H px tall covers the
  cells up to about H / 16 steps of col + row behind it on screen, so the
  cells in front of a playable cell (larger col + row, similar screen x) only
  take low sprites.
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

DENSITY = {"entrance": 0.04, "combat": 0.08, "puzzle": 0.12, "treasure": 0.10, "boss": 0.06}
TREASURE_DECORATION_SHARE = 0.8
CLUSTER_SIZE = (2, 4)
MIN_OWN_CLUSTERS = 2
TREE_PREFIX = "tree_"
WILDERNESS_BASE_WEIGHT = 0.1
LOW_FAMILIES = {"rock_small": 0.5, "stump": 0.3, "logs": 0.2}  # family -> weight (renormalized)
PILLAR_FAMILIES = ("rock_pillar",)
PILLAR_SHARE = 0.2  # of the trees-and-pillars cells
STYLE_TREE_SHARE = 0.9
FRONT_DECORATION_DENSITY = 0.15
HEDGE_THICKNESS = 2
SHORT_DEPTH = 3  # steps of col + row in front of a playable cell (16 px each on screen)
PILLAR_DEPTH = 8
CLEARANCE_HALF_WIDTH = 3  # |(col - row) difference| (32 px each on screen)
PATH_FLOOR = "floor.stone"
_STEPS = [(dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0)]
_ORTHOGONAL = [(1, 0), (-1, 0), (0, 1), (0, -1)]

Weighted = list[tuple[TileGroup, float]]


@dataclass
class Dressing:
    ground: list[list[int]]
    objects: list[list[int]]
    group_counts: Counter = field(default_factory=Counter)  # tile group id -> cells
    warnings: list[str] = field(default_factory=list)
    structures: dict[str, list[Cell]] = field(default_factory=dict)  # "<room>:<group>" -> footprint cells


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
    structures: dict[str, list[Cell]] = {}

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

    # -- Structures and props in rooms -------------------------------------
    reserved = set(layout.corridor_cells) | placement.cells
    for center in (placement.spawn, placement.exit):
        reserved |= {(center[0] + dc, center[1] + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    playable = layout.playable_cells
    blocked: set[Cell] = set()
    taken: set[Cell] = set()  # prop and structure cells and their 8 neighbors

    def put(cell: Cell, group: TileGroup, variants: tuple[int, ...] | None = None) -> None:
        objects[cell[1]][cell[0]] = rng.choice(variants or group.tile_ids)
        counts[group.id] += 1

    def claim(cells: list[Cell], group: TileGroup) -> None:
        if group.blocks:
            blocked.update(cells)
        taken.update((c + dc, r + dr) for c, r in cells for dc in (-1, 0, 1) for dr in (-1, 0, 1))

    for room in topology.rooms:
        rect = layout.rooms[room.id]
        free = {cell for cell in rect.cells() if cell not in reserved}
        if room.purpose == "boss":
            cc, cr = rect.center
            free = {(c, r) for c, r in free if max(abs(c - cc), abs(r - cr)) > 1}

        for s in room.dressing:
            group = groups.get(s.tile_group)
            if group is None or not group.is_structure or s.weight <= 0:
                continue
            cells = _structure_cells(group, free, taken, playable, blocked, placement.spawn, rng)
            if cells is None:
                warnings.append(f"room {room.id}: no free space for {group.id}")
                continue
            put(cells[(len(cells) - 1) // 2], group)
            claim(cells, group)
            structures[f"{room.id}:{group.id}"] = cells

        own = _weights(room.dressing, groups, "obstacle") + _weights(room.dressing, groups, "decoration")
        props = own or (_weights(topology.style_distribution, groups, "obstacle")
                        + _weights(topology.style_distribution, groups, "decoration"))
        if not props:
            continue
        wanted = round(DENSITY[room.purpose] * rect.w * rect.h)
        min_clusters = MIN_OWN_CLUSTERS if own else 0
        starts = sorted(free)
        rng.shuffle(starts)
        placed = clusters = 0
        for start in starts:
            if placed >= wanted and clusters >= min_clusters:
                break
            if start in taken:
                continue
            group = _pick_prop(props, room.purpose, rng)
            cluster = _grow(start, rng.randint(*CLUSTER_SIZE), free, taken, rng)
            if group.blocks:  # drop cells until every playable cell stays reachable
                while len(cluster) >= CLUSTER_SIZE[0] and not _still_connected(
                    playable, blocked | set(cluster), placement.spawn,
                ):
                    cluster.pop()
            if len(cluster) < CLUSTER_SIZE[0]:
                continue
            for cell in cluster:
                put(cell, group)
            claim(cluster, group)
            placed += len(cluster)
            clusters += 1
        if clusters < min_clusters:
            warnings.append(f"room {room.id}: only {clusters} prop clusters fit")

    # -- Wilderness -------------------------------------------------------
    wild = _WildPicker(topology, digest, rng)
    if wild.any:
        depth = _clearance_depth(playable)
        hedge = _hedge(playable, width, height, depth)
        decorations = _front_decorations(topology, digest)
        for r in range(height):
            for c in range(width):
                cell = (c, r)
                if cell in playable:
                    continue
                d = depth.get(cell)
                if cell in hedge and d is not None and d <= SHORT_DEPTH:
                    near = {
                        objects[r + dr][c + dc] for dc in (-1, 0, 1) for dr in (-1, 0, 1)
                        if 0 <= r + dr < height and 0 <= c + dc < width
                    }
                    put(cell, *wild.low(near))
                    continue
                if cell in hedge:
                    group = wild.pillar() if d is not None else wild.tall()
                elif d is not None:  # front zone: open, sparse decorations
                    if not decorations or rng.random() >= FRONT_DECORATION_DENSITY:
                        continue
                    group = _choose(decorations, rng)
                else:
                    group = wild.tall()
                put(cell, group)
    else:
        warnings.append(
            "the catalog has no blocking obstacles: the wilderness stays open floor and the map edge is the boundary"
        )
    return Dressing(ground, objects, counts, warnings, structures)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weights(styles: list[StyleWeight], groups: dict[str, TileGroup], category: str) -> Weighted:
    return [
        (groups[s.tile_group], s.weight) for s in styles
        if s.tile_group in groups and groups[s.tile_group].category == category
    ]


def _choose(weighted: Weighted, rng: random.Random) -> TileGroup:
    total = sum(w for _, w in weighted)
    if total <= 0:
        return rng.choice(weighted)[0]
    x = rng.random() * total
    for group, w in weighted:
        x -= w
        if x < 0:
            return group
    return weighted[-1][0]


def _pick_prop(props: Weighted, purpose: str, rng: random.Random) -> TileGroup:
    if purpose == "treasure":
        decorations = [(g, w) for g, w in props if g.category == "decoration"]
        obstacles = [(g, w) for g, w in props if g.category == "obstacle"]
        if decorations and obstacles:
            return _choose(decorations if rng.random() < TREASURE_DECORATION_SHARE else obstacles, rng)
    return _choose(props, rng)


def _grow(start: Cell, size: int, free: set[Cell], taken: set[Cell], rng: random.Random) -> list[Cell]:
    """A 4-connected cluster of up to ``size`` free cells from ``start``, avoiding ``taken``."""
    cluster = [start]
    while len(cluster) < size:
        options = sorted({
            (c + dc, r + dr) for c, r in cluster for dc, dr in _ORTHOGONAL
            if (c + dc, r + dr) in free and (c + dc, r + dr) not in taken and (c + dc, r + dr) not in cluster
        })
        if not options:
            break
        cluster.append(rng.choice(options))
    return cluster


def _structure_cells(
    group: TileGroup, free: set[Cell], taken: set[Cell], playable: set[Cell], blocked: set[Cell], spawn: Cell,
    rng: random.Random,
) -> list[Cell] | None:
    """Footprint cells ``(col + i, row - i)`` for a free spot, or None."""
    starts = sorted(free)
    rng.shuffle(starts)
    for c, r in starts:
        cells = [(c + i, r - i) for i in range(group.footprint)]
        if any(cell not in free or cell in taken for cell in cells):
            continue
        if group.blocks and not _still_connected(playable, blocked | set(cells), spawn):
            continue
        return cells
    return None


def _smooth_noise(width: int, height: int, rng: random.Random) -> np.ndarray:
    field_ = np.array([[rng.random() for _ in range(width)] for _ in range(height)])
    for _ in range(3):  # box blur 3 x 3, edges padded
        padded = np.pad(field_, 1, mode="edge")
        field_ = sum(
            padded[1 + dr: 1 + dr + height, 1 + dc: 1 + dc + width]
            for dr in (-1, 0, 1) for dc in (-1, 0, 1)
        ) / 9
    return field_


def _by_quantile(cells: list[Cell], weighted: Weighted, noise: np.ndarray) -> list[tuple[Cell, TileGroup]]:
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


def _hedge(playable: set[Cell], width: int, height: int, depth: dict[Cell, int]) -> set[Cell]:
    """
    Non-playable cells within ``HEDGE_THICKNESS`` (Chebyshev) of a playable
    cell, but only the inner ring in front (``depth`` <= ``SHORT_DEPTH``).
    Every step out of the playable area lands on the inner ring, so it
    encloses the area on its own.
    """
    def ring(k: int) -> set[Cell]:
        return {
            (c + dc, r + dr) for c, r in playable for dc in range(-k, k + 1) for dr in range(-k, k + 1)
            if 0 <= c + dc < width and 0 <= r + dr < height
        } - playable

    inner = ring(1)
    outer = {cell for cell in ring(HEDGE_THICKNESS) - inner if depth.get(cell, SHORT_DEPTH + 1) > SHORT_DEPTH}
    return inner | outer


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


def _front_decorations(topology: RoomTopologyGraph, digest: CatalogDigest) -> Weighted:
    """Walkable decorations of the style, else every walkable decoration group."""
    styled = [(g, w) for g, w in _weights(topology.style_distribution, digest.by_id, "decoration") if g.walkable]
    return styled or [(g, 1.0) for g in digest.of_category("decoration") if g.walkable]


class _WildPicker:
    """Blocking wilderness groups: low blockers, rock pillars, trees (style weighted)."""

    def __init__(self, topology: RoomTopologyGraph, digest: CatalogDigest, rng: random.Random):
        self.rng = rng
        style = topology.style_map()
        # Structures are never wilderness (their own category; slices are
        # not in the digest). Catalogs without blocking obstacles (an indoor
        # set) fall back to blocking decorations.
        blocking = [g for g in digest.of_category("obstacle") if g.blocks] or [
            g for g in digest.of_category("decoration") if g.blocks
        ]

        def weighted(found: list[TileGroup]) -> Weighted:
            return [(g, style.get(g.id, 0.0) + WILDERNESS_BASE_WEIGHT) for g in found]

        trees = [g for g in blocking if g.family.startswith(TREE_PREFIX)]
        self.pillars = weighted([g for g in blocking if g.family in PILLAR_FAMILIES])
        if not trees and not self.pillars:  # for example hay bales, crates, bookcases
            trees = blocking
        self.trees = weighted(trees)
        self.style_trees = [(g, style[g.id]) for g in trees if style.get(g.id, 0.0) > 0]
        self.short = (
            [(g, LOW_FAMILIES[g.family]) for g in blocking if g.family in LOW_FAMILIES] or self.pillars or self.trees
        )

    @property
    def any(self) -> bool:
        return bool(self.trees or self.pillars)

    def low(self, avoid: set[int] = frozenset()) -> tuple[TileGroup, tuple[int, ...]]:
        """A low blocker and its allowed variants (not in ``avoid`` when possible)."""
        group = _choose(self.short, self.rng)
        variants = tuple(i for i in group.tile_ids if i not in avoid)
        if not variants:
            options = [(g, w) for g, w in self.short if set(g.tile_ids) - avoid]
            if not options:
                return group, group.tile_ids
            group = _choose(options, self.rng)
            variants = tuple(i for i in group.tile_ids if i not in avoid)
        return group, variants

    def pillar(self) -> TileGroup:
        return _choose(self.pillars, self.rng) if self.pillars else self.low()[0]

    def tall(self) -> TileGroup:
        if self.pillars and (not self.trees or self.rng.random() < PILLAR_SHARE):
            return _choose(self.pillars, self.rng)
        if self.style_trees and self.rng.random() < STYLE_TREE_SHARE:
            return _choose(self.style_trees, self.rng)
        return _choose(self.trees, self.rng)
