"""
Tests for the grassland_full pack, multi-tileset compilation, the planner's
Objects layer, and the Pipeline 1 slicer.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

from pipeline.execution.compile import run_compile
from pipeline.execution.tileset_compiler import tile_offset
from pipeline.ingestion.flare import parse_flare_definition
from pipeline.ingestion.slicer import iou, slice_spritesheet
from pipeline.planning.pathing import can_step, line_cells, line_corridor, shortest_path
from pipeline.planning.placeholder_planner import ensure_path, plan_level, seed_from_prompt

BACKEND_DIR = Path(__file__).parent.parent
REPO_ROOT = BACKEND_DIR.parent
PACK_DIR = BACKEND_DIR / "asset_packs" / "grassland_full"
FULL_CATALOG = PACK_DIR / "asset_catalog.json"
STARTER_CATALOG = BACKEND_DIR / "fixtures" / "starter" / "asset_catalog.json"
STARTER_PLAN = BACKEND_DIR / "fixtures" / "starter" / "level_plan.json"
STARTER_BUNDLE = REPO_ROOT / "z_legend_game" / "z_legend_game_flutter" / "assets" / "tiles" / "starter"
SHEET = REPO_ROOT / "game-assets" / "grassland_tiles.png"
FLARE_DEF = REPO_ROOT / "game-assets" / "grassland_tiles.flare_v0.15_tilesetdef.txt"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _compile(plan: dict, catalog_path: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    plan_path = out / "level_plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        return run_compile(str(plan_path), str(catalog_path), str(out / "bundle"))


@pytest.fixture(scope="module")
def full_catalog() -> dict:
    return _load(FULL_CATALOG)


@pytest.fixture(scope="module")
def full_plan(full_catalog) -> dict:
    return plan_level(full_catalog, seed_from_prompt("graveyard with a cabin"))


# ---------------------------------------------------------------------------
# Pack builder
# ---------------------------------------------------------------------------

def test_build_pack_is_reproducible(tmp_path):
    subprocess.run(
        [sys.executable, str(PACK_DIR / "build_pack.py"), "--out", str(tmp_path)],
        check=True, capture_output=True,
    )
    for name in ("asset_catalog.json", "pack.json", "contact_sheet.png"):
        assert (tmp_path / name).read_bytes() == (PACK_DIR / name).read_bytes(), name


def test_catalog_matches_answer_key(full_catalog):
    jsonschema.validate(full_catalog, _load(BACKEND_DIR / "pipeline" / "schemas" / "asset_catalog.schema.json"))
    tiles = full_catalog["tiles"]
    assert [t["id"] for t in tiles] == list(range(136))
    assert Counter(t["category"] for t in tiles) == {
        "floor": 32, "wall": 24, "water": 16, "obstacle": 48, "decoration": 16,
    }
    by_name = {t["name"]: t for t in tiles}
    assert by_name["grass_tiles_00"]["source_ref"] == "flare:tile=16"
    assert by_name["cliffs_23"]["tags"] == ["autotile_required"]  # second "# cliffs" block
    assert by_name["water_tiles_00"]["anchor"] == {"x": 32, "y": -16}
    assert by_name["tall_town_objects_00"]["tags"] == ["prop", "tall", "stump"]
    assert by_name["shrubs_and_grass_tufts_00"]["walkable"] is True
    assert by_name["fluffy_trees_03"]["tags"] == ["tree", "tall", "tree_fluffy"]
    fences = [t["name"] for t in tiles if "fence" in t.get("tags", [])]
    assert fences == [f"town_objects_{i:02d}" for i in range(8, 16)]
    assert [by_name[n]["source_ref"] for n in fences] == [f"flare:tile={i}" for i in range(104, 112)]
    assert by_name["town_objects_08"]["tags"] == ["prop", "fence"]
    assert by_name["town_objects_07"]["tags"] == ["prop", "anvil"]


def test_every_obstacle_and_decoration_has_one_family_tag(full_catalog):
    generic = {"prop", "tall", "tree", "autotile_required"}
    families = {}
    for t in full_catalog["tiles"]:
        if t["category"] in ("obstacle", "decoration"):
            (family,) = [tag for tag in t["tags"] if tag not in generic]
            families.setdefault(family, []).append(t["name"])
    assert families["gravestone"] == [f"tall_town_objects_{i:02d}" for i in range(4, 8)]
    assert families["rock_pillar"] == [f"rocks_{i:02d}" for i in range(4, 8)]
    assert families["campfire"] == ["town_objects_06"]
    assert families["dry_grass"] == [f"shrubs_and_grass_tufts_{i:02d}" for i in range(12, 16)]
    assert {f for f in families if f.startswith("tree_")} == {"tree_blue", "tree_dead", "tree_tall", "tree_fluffy"}
    assert len(families) == 21  # 20 planner families + fence


def test_pack_manifest_lists_exclusions_and_empty_rects():
    pack = _load(PACK_DIR / "pack.json")
    excluded = {e["section"]: e["reason"] for e in pack["excluded_sections"]}
    assert excluded["riverbanks"] == "needs autotile rules"
    assert excluded["indicators"] == "editor markers"
    assert sorted(e["flare_id"] for e in pack["empty_rects"]) == [76, 77, 78, 79, 92, 93, 94, 95, 174, 175]


# ---------------------------------------------------------------------------
# Tileset compiler
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("size", "anchor", "offset"),
    [
        ((64, 32), (32, 16), (0, 0)),      # floor
        ((64, 32), (32, -16), (0, 32)),    # water sits a tile lower
        ((64, 96), (32, 80), (0, 0)),      # cliff
        ((128, 224), (64, 208), (32, 0)),  # tall tree
    ],
)
def test_tile_offset(size, anchor, offset):
    assert tile_offset(*size, *anchor, 64, 32) == offset


def test_starter_output_is_byte_identical(tmp_path):
    """Regression rule: the committed starter bundle still compiles to the same bytes."""
    _compile(_load(STARTER_PLAN), STARTER_CATALOG, tmp_path)
    for name in ("level.tmj", "tileset.tsj", "tileset.png"):
        assert (tmp_path / "bundle" / name).read_bytes() == (STARTER_BUNDLE / name).read_bytes(), name
    assert not (tmp_path / "bundle" / "tileset_1.png").exists()


def test_multi_tileset_compile(tmp_path, full_plan):
    tmj = _compile(full_plan, FULL_CATALOG, tmp_path)["tmj"]
    bundle = tmp_path / "bundle"
    tilesets = tmj["tilesets"]
    assert len(tilesets) > 1
    assert [ts["name"] for ts in tilesets] == ["tileset"] + [f"tileset_{i}" for i in range(1, len(tilesets))]

    next_gid = 1
    for ts in tilesets:
        assert ts["firstgid"] == next_gid
        next_gid += ts["tilecount"]
        assert (bundle / ts["image"]).is_file()
        assert (bundle / f"{ts['name']}.tsj").is_file()
        assert "source" not in ts
    trees = [ts for ts in tilesets if ts["tilewidth"] == 128]
    assert trees and all(ts["tileoffset"] == {"x": 32, "y": 0} for ts in trees)

    ground, objects = [l for l in tmj["layers"] if l["type"] == "tilelayer"]
    assert (ground["name"], objects["name"]) == ("Ground", "Objects")
    assert 0 not in ground["data"]
    assert all(0 <= gid < next_gid for gid in objects["data"])
    assert 0 < sum(1 for gid in objects["data"] if gid) < 400
    assert (bundle / "preview_level.png").is_file()


# ---------------------------------------------------------------------------
# Placeholder planner
# ---------------------------------------------------------------------------

def test_starter_plans_are_unchanged():
    starter = _load(STARTER_CATALOG)
    assert plan_level(starter, 42) == _load(STARTER_PLAN)
    plan = plan_level(starter, seed_from_prompt("anything"))
    assert [l["name"] for l in plan["layers"]] == ["Ground"]
    assert "summary" not in plan


def test_full_plan_objects_layer(full_catalog, full_plan):
    jsonschema.validate(full_plan, _load(BACKEND_DIR / "pipeline" / "schemas" / "level_plan.schema.json"))
    by_id = {t["id"]: t for t in full_catalog["tiles"]}
    ground, objects = full_plan["layers"]
    assert objects["name"] == "Objects" and objects["elevation"] == 0

    placed = [(r, c, v) for r, row in enumerate(objects["grid"]) for c, v in enumerate(row) if v]
    categories = Counter(by_id[v]["category"] for _, _, v in placed)
    assert categories == {"obstacle": 32, "decoration": 20}  # 8% and 5% of 400
    assert not any("autotile_required" in by_id[v].get("tags", []) for _, _, v in placed)
    assert not any("fence" in by_id[v].get("tags", []) for _, _, v in placed)

    ends = {o["type"]: (o["row"], o["col"]) for o in full_plan["objects"]}
    forbidden = {(i, i) for i in range(20)}  # the path
    forbidden |= {(o["row"], o["col"]) for o in full_plan["objects"]}
    for r, c in (ends["PlayerSpawn"], ends["ExitTrigger"]):
        forbidden |= {(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
    assert not forbidden & {(r, c) for r, c, _ in placed}

    assert full_plan["summary"] == {
        "obstacles_placed": 32, "decorations_placed": 20, "obstacles_removed": 0,
        "path_found": True, "path_length": 22,  # no corner cutting around the diagonal path
    }


def test_full_plan_is_seeded_by_prompt(full_catalog, full_plan):
    again = plan_level(full_catalog, seed_from_prompt("graveyard with a cabin"))
    other = plan_level(full_catalog, seed_from_prompt("a haunted swamp at night"))
    assert again == full_plan
    assert other["layers"][1] != full_plan["layers"][1]


def test_ensure_path_removes_obstacles_on_the_line():
    # A full wall across a 5 x 5 map (row 2) blocks every route.
    wall, floor = 7, 1
    grid = [[0] * 5 for _ in range(5)]
    grid[2] = [wall] * 5
    removed, path = ensure_path(grid, {wall: False, floor: True}, (0, 0), (4, 4))
    assert removed == 1 and path is not None
    assert grid[2].count(wall) == 4  # only the cell on the straight line is cleared
    assert (2, 2) in line_cells((0, 0), (4, 4))


def test_fence_tiles_are_never_scattered(full_catalog):
    fence_ids = {t["id"] for t in full_catalog["tiles"] if "fence" in t.get("tags", [])}
    assert len(fence_ids) == 8
    for prompt in ("graveyard with a cabin", "a haunted swamp at night", "a", "b", "c", "d", "e", "f"):
        grid = plan_level(full_catalog, seed_from_prompt(prompt))["layers"][1]["grid"]
        assert not fence_ids & {v for row in grid for v in row}, prompt


def test_ensure_path_clears_diagonal_corners():
    # Blocks on both corners of every diagonal step of the straight line:
    # the line cells are open, but the line cannot be walked without cutting
    # corners, and there is no other route.
    rock = 7
    grid = [[rock] * 3 for _ in range(3)]
    for i in range(3):
        grid[i][i] = 0
    removed, path = ensure_path(grid, {rock: False}, (0, 0), (2, 2))
    assert path is not None
    assert removed == 2
    assert line_corridor((0, 0), (2, 2)) == [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)]


def test_shortest_path_uses_8_directions():
    path = shortest_path(5, 5, set(), (0, 0), (4, 4))
    assert len(path) - 1 == 4


def test_diagonal_step_needs_both_orthogonal_neighbors_open():
    # (row, col). Stepping (0, 0) -> (1, 1) passes the corners (1, 0) and (0, 1).
    assert can_step(3, 3, set(), (0, 0), 1, 1)
    assert not can_step(3, 3, {(1, 0)}, (0, 0), 1, 1)
    assert not can_step(3, 3, {(0, 1)}, (0, 0), 1, 1)
    assert not can_step(3, 3, {(1, 0), (0, 1)}, (0, 0), 1, 1)
    # Orthogonal steps only need the target cell.
    assert can_step(3, 3, {(1, 1)}, (0, 0), 0, 1)
    assert not can_step(3, 3, {(0, 1)}, (0, 0), 0, 1)


def test_out_of_bounds_is_blocked():
    assert not can_step(3, 3, set(), (0, 0), -1, 0)
    assert not can_step(3, 3, set(), (0, 0), 0, -1)
    assert not can_step(3, 3, set(), (2, 2), 1, 1)
    # A diagonal along the map edge: the corner outside the map blocks it.
    assert not can_step(3, 3, set(), (0, 1), -1, 1)


def test_shortest_path_does_not_cut_corners():
    # Two obstacles touch at a corner; the path must go around, not between.
    #   S X .
    #   X . .
    #   . . G
    blocked = {(0, 1), (1, 0)}
    assert shortest_path(3, 3, blocked, (0, 0), (2, 2)) is None
    # With one corner open, the walk goes through it: 3 steps, not 2.
    path = shortest_path(3, 3, {(1, 0)}, (0, 0), (2, 2))
    assert len(path) - 1 == 3
    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        assert can_step(3, 3, {(1, 0)}, (r0, c0), r1 - r0, c1 - c0)


def test_no_corner_cutting_leaves_open_maps_unchanged():
    # Without obstacles, every diagonal is allowed, so path lengths stay
    # Chebyshev distances (the grassland_starter case).
    for goal in ((19, 19), (0, 19), (19, 0), (7, 13)):
        path = shortest_path(20, 20, set(), (0, 0), goal)
        assert len(path) - 1 == max(goal)


# ---------------------------------------------------------------------------
# Slicer
# ---------------------------------------------------------------------------

def test_slicer_grid_fallback_finds_floor_rows():
    floor = [t for t in parse_flare_definition(FLARE_DEF) if t.section in ("grass_tiles", "old_stonework_path")]
    assert len(floor) == 32
    grid_chips = [c for c in slice_spritesheet(SHEET) if c.strategy == "grid"]
    for t in floor:
        best = max(iou(c.rect, t.rect) for c in grid_chips)
        assert best >= 0.9, (t.section, t.flare_id, best)


def test_tight_box_shrinks_to_opaque_pixels():
    sys.path.insert(0, str(BACKEND_DIR / "tools"))
    from evaluate_slicer import tight_box
    from pipeline.ingestion.flare import FlareTile
    import numpy as np

    alpha = np.zeros((64, 128), dtype=np.uint8)
    alpha[40:50, 70:80] = 255  # a small sprite inside the padded cell (64, 0, 64, 64)
    alpha[5, 5] = 255          # an opaque pixel outside the cell is ignored
    padded = FlareTile("shrubs", 1, 64, 0, 64, 64, 32, 48)
    tight = tight_box(alpha, padded)
    assert tight.rect == (70, 40, 10, 10)
    assert (tight.section, tight.flare_id, tight.anchor_x) == ("shrubs", 1, 32)
