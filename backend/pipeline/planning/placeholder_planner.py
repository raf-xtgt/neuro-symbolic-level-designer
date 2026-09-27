"""
Placeholder planner. TEMPORARY: stands in for Pipeline 2 (ARCHITECTURE.md
section 4) until the neuro-symbolic planner exists. It ignores the prompt
except as a random seed.

Layout (any catalog with walkable floor tiles):
  - 20 x 20 ground layer of random variants of the main floor material.
  - A path from corner (0, 0) to corner (19, 19) in the path material
    (``stone`` when the catalog has it).
  - PlayerSpawn at the path start, ExitTrigger at the path end, and 3 Zombie
    objects on walkable ground cells off the path.
  - If the catalog has obstacle or decoration tiles (without the tags
    ``autotile_required`` and ``fence``): an ``Objects`` layer (0 = empty cell) with
    obstacles on about 8% and decorations on about 5% of the cells, never on
    the path, the entity cells, or the 8 neighbors of the spawn and the exit.
    A BFS (movement rule in ``pathing.py``, no corner cutting) then checks
    that the exit is reachable; if not, obstacles on the straight spawn-exit
    line and its diagonal corner cells are removed until it is. The result is recorded
    in the plan's ``summary``.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter

from pipeline.planning.pathing import Cell, line_corridor, shortest_path

WIDTH, HEIGHT = 20, 20
ZOMBIE_COUNT = 3
PREFERRED_PATH_MATERIAL = "stone"
OBSTACLE_SHARE = 0.08
DECORATION_SHARE = 0.05
AUTOTILE_TAG = "autotile_required"
# Directional fence connectors look odd one by one; they need a fence planner.
FENCE_TAG = "fence"
SCATTER_EXCLUDED_TAGS = {AUTOTILE_TAG, FENCE_TAG}


def seed_from_prompt(prompt: str) -> int:
    """Stable across processes, unlike ``hash()``."""
    return int.from_bytes(hashlib.sha256(prompt.encode("utf-8")).digest()[:4], "big")


def _floor_ids_by_material(catalog: dict) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for tile in catalog["tiles"]:
        if tile["category"] == "floor" and tile["walkable"]:
            groups.setdefault(tile.get("material", "default"), []).append(tile["id"])
    if not groups:
        raise ValueError("catalog has no walkable floor tiles")
    return groups


def _pick_materials(groups: dict[str, list[int]]) -> tuple[str, str]:
    """Returns (ground material, path material). Ties keep catalog order."""
    by_size = [m for m, _ in Counter({m: len(ids) for m, ids in groups.items()}).most_common()]
    if PREFERRED_PATH_MATERIAL in groups and len(groups) > 1:
        path = PREFERRED_PATH_MATERIAL
    else:
        path = by_size[1] if len(by_size) > 1 else by_size[0]
    ground = next((m for m in by_size if m != path), path)
    return ground, path


def plan_level(catalog: dict, seed: int) -> dict:
    """Builds a level_plan.json dict (ARCHITECTURE.md section 6.3)."""
    groups = _floor_ids_by_material(catalog)
    ground_material, path_material = _pick_materials(groups)
    ground_ids, path_ids = groups[ground_material], groups[path_material]

    rng = random.Random(seed)
    grid = [[rng.choice(ground_ids) for _ in range(WIDTH)] for _ in range(HEIGHT)]

    path_cells = [(i, i) for i in range(min(WIDTH, HEIGHT))]  # (row, col)
    path_rng = random.Random(seed + 1)
    for row, col in path_cells:
        grid[row][col] = path_rng.choice(path_ids)

    path_set = set(path_cells)
    free_cells = [(r, c) for r in range(HEIGHT) for c in range(WIDTH) if (r, c) not in path_set]
    zombie_cells = rng.sample(free_cells, min(ZOMBIE_COUNT, len(free_cells)))

    (start_row, start_col), (end_row, end_col) = path_cells[0], path_cells[-1]
    objects = [
        {"name": "spawn_player", "type": "PlayerSpawn", "col": start_col, "row": start_row},
        {"name": "exit_trigger", "type": "ExitTrigger", "col": end_col, "row": end_row},
    ] + [
        {"name": f"zombie_{i}", "type": "Zombie", "col": c, "row": r}
        for i, (r, c) in enumerate(zombie_cells)
    ]

    layers = [{"name": "Ground", "elevation": 0, "grid": grid}]
    summary = None
    obstacle_ids = _overlay_ids(catalog, "obstacle")
    decoration_ids = _overlay_ids(catalog, "decoration")
    if obstacle_ids or decoration_ids:
        entity_cells = {(o["row"], o["col"]) for o in objects}
        overlay, summary = _plan_overlay(
            seed, catalog, obstacle_ids, decoration_ids,
            path_set, entity_cells, path_cells[0], path_cells[-1],
        )
        layers.append({"name": "Objects", "elevation": 0, "grid": overlay})

    plan = {
        "map_properties": {
            "width": WIDTH,
            "height": HEIGHT,
            "tile_width": catalog["tile_size"]["width"],
            "tile_height": catalog["tile_size"]["height"],
            "orientation": "isometric",
        },
        "layers": layers,
        "objects": objects,
    }
    if summary is not None:
        plan["summary"] = summary
    return plan


def _overlay_ids(catalog: dict, category: str) -> list[int]:
    """Tiles of ``category`` the placeholder planner may scatter (no autotiles, no fences)."""
    return [
        t["id"] for t in catalog["tiles"]
        if t["category"] == category and not SCATTER_EXCLUDED_TAGS & set(t.get("tags", []))
    ]


def _neighbors(cell: Cell) -> set[Cell]:
    r, c = cell
    return {(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)}


def _plan_overlay(
    seed: int,
    catalog: dict,
    obstacle_ids: list[int],
    decoration_ids: list[int],
    path_cells: set[Cell],
    entity_cells: set[Cell],
    spawn: Cell,
    exit_: Cell,
) -> tuple[list[list[int]], dict]:
    """Objects layer grid (0 = empty) and the plan summary."""
    # A separate stream, so the ground, path and zombies stay as they were.
    rng = random.Random(seed + 2)
    forbidden = path_cells | entity_cells | _neighbors(spawn) | _neighbors(exit_)
    free = [(r, c) for r in range(HEIGHT) for c in range(WIDTH) if (r, c) not in forbidden]
    rng.shuffle(free)

    n_obstacles = round(OBSTACLE_SHARE * WIDTH * HEIGHT) if obstacle_ids else 0
    n_decorations = round(DECORATION_SHARE * WIDTH * HEIGHT) if decoration_ids else 0
    grid = [[0] * WIDTH for _ in range(HEIGHT)]
    for r, c in free[:n_obstacles]:
        grid[r][c] = rng.choice(obstacle_ids)
    for r, c in free[n_obstacles : n_obstacles + n_decorations]:
        grid[r][c] = rng.choice(decoration_ids)

    walkable = {t["id"]: t["walkable"] for t in catalog["tiles"]}
    removed, path = ensure_path(grid, walkable, spawn, exit_)
    summary = {
        "obstacles_placed": sum(1 for row in grid for v in row if v and not walkable[v]),
        "decorations_placed": sum(1 for row in grid for v in row if v and walkable[v]),
        "obstacles_removed": removed,
        "path_found": path is not None,
        "path_length": len(path) - 1 if path else None,
    }
    return grid, summary


def ensure_path(
    grid: list[list[int]], walkable: dict[int, bool], spawn: Cell, exit_: Cell
) -> tuple[int, list[Cell] | None]:
    """
    Removes blocking tiles on the straight spawn-exit line and its diagonal
    corner cells (``line_corridor``), one at a time, until the BFS finds a
    path. Mutates ``grid``. Returns (tiles removed, path).
    """
    height, width = len(grid), len(grid[0])

    def search() -> list[Cell] | None:
        blocked = {
            (r, c) for r in range(height) for c in range(width)
            if grid[r][c] and not walkable[grid[r][c]]
        }
        return shortest_path(width, height, blocked, spawn, exit_)

    removed, path = 0, search()
    for r, c in line_corridor(spawn, exit_):
        if path is not None:
            break
        if grid[r][c] and not walkable[grid[r][c]]:
            grid[r][c] = 0
            removed += 1
            path = search()
    return removed, path
