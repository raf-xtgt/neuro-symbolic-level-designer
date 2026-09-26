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
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter

WIDTH, HEIGHT = 20, 20
ZOMBIE_COUNT = 3
PREFERRED_PATH_MATERIAL = "stone"


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

    return {
        "map_properties": {
            "width": WIDTH,
            "height": HEIGHT,
            "tile_width": catalog["tile_size"]["width"],
            "tile_height": catalog["tile_size"]["height"],
            "orientation": "isometric",
        },
        "layers": [{"name": "Ground", "elevation": 0, "grid": grid}],
        "objects": objects,
    }
