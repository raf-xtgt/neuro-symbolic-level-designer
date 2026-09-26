"""
Pytest tests for the Execution Pipeline first slice.

All tests run against the pre-generated output in
z_legend_game/z_legend_game_flutter/assets/tiles/starter/
(produced by the compile CLI in conftest.py).

Tests:
  1. Every GID in level.tmj exists in the tileset.
  2. Map width × height == data length for every tile layer.
  3. Every object is placed on a walkable tile.
  4. Round-trip: parse level.tmj + tileset.tsj and compare back to level_plan.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).parent.parent
FIXTURES_DIR = BACKEND_DIR / "fixtures" / "starter"
OUT_DIR = (
    BACKEND_DIR.parent
    / "z_legend_game"
    / "z_legend_game_flutter"
    / "assets"
    / "tiles"
    / "starter"
)

CATALOG_PATH  = FIXTURES_DIR / "asset_catalog.json"
PLAN_PATH     = FIXTURES_DIR / "level_plan.json"
TMJ_PATH      = OUT_DIR / "level.tmj"
TSJ_PATH      = OUT_DIR / "tileset.tsj"
TILESET_PNG   = OUT_DIR / "tileset.png"
PREVIEW_PNG   = OUT_DIR / "preview_level.png"


# ---------------------------------------------------------------------------
# Fixtures (pytest) — compile once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def catalog() -> dict[str, Any]:
    with open(CATALOG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def level_plan() -> dict[str, Any]:
    with open(PLAN_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def tmj() -> dict[str, Any]:
    assert TMJ_PATH.exists(), f"level.tmj not found – run the compiler first: {TMJ_PATH}"
    with open(TMJ_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def tsj() -> dict[str, Any]:
    assert TSJ_PATH.exists(), f"tileset.tsj not found – run the compiler first: {TSJ_PATH}"
    with open(TSJ_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _valid_gids(tmj: dict, tsj: dict) -> set[int]:
    """Return the set of all valid non-zero GIDs for this tileset.

    Works whether the tileset is embedded in the .tmj (no ``source`` key)
    or referenced externally (``source`` key present, uses tsj).
    """
    ts_entry = tmj["tilesets"][0]
    firstgid: int = ts_entry["firstgid"]
    # Embedded tileset has tilecount directly; external uses the tsj fixture.
    tilecount: int = ts_entry.get("tilecount", tsj["tilecount"])
    return set(range(firstgid, firstgid + tilecount))


# ---------------------------------------------------------------------------
# Test 1: every GID in level.tmj exists in the tileset
# ---------------------------------------------------------------------------

def test_all_gids_valid(tmj, tsj):
    valid = _valid_gids(tmj, tsj)
    for layer in tmj["layers"]:
        if layer["type"] != "tilelayer":
            continue
        for gid in layer["data"]:
            if gid == 0:
                continue
            assert gid in valid, (
                f"GID {gid} in layer '{layer['name']}' is not in the tileset "
                f"(valid range: {min(valid)}–{max(valid)})"
            )


# ---------------------------------------------------------------------------
# Test 2: width × height == data length
# ---------------------------------------------------------------------------

def test_data_length(tmj):
    expected = tmj["width"] * tmj["height"]
    for layer in tmj["layers"]:
        if layer["type"] != "tilelayer":
            continue
        actual = len(layer["data"])
        assert actual == expected, (
            f"Layer '{layer['name']}': expected {expected} cells, got {actual}"
        )


# ---------------------------------------------------------------------------
# Test 3: every object is on a walkable tile
# ---------------------------------------------------------------------------

def test_objects_on_walkable_tiles(tmj, tsj, catalog):
    # Build walkable lookup: packed_index -> walkable
    catalog_tiles = sorted(catalog["tiles"], key=lambda t: t["id"])
    packed_walkable = {idx: t["walkable"] for idx, t in enumerate(catalog_tiles)}

    firstgid = tmj["tilesets"][0]["firstgid"]
    w = tmj["width"]
    h = tmj["height"]
    tw = tmj["tilewidth"]
    th = tmj["tileheight"]

    # Get the ground tile layer data (first tilelayer)
    ground_data: list[int] = []
    for layer in tmj["layers"]:
        if layer["type"] == "tilelayer":
            ground_data = layer["data"]
            break

    assert ground_data, "No tile layer found in level.tmj"

    for layer in tmj["layers"]:
        if layer["type"] != "objectgroup":
            continue
        for obj in layer["objects"]:
            # Tiled isometric coords: x=(col+0.5)*th, y=(row+0.5)*th  → col=x/th-0.5
            col = int(obj["x"] / th - 0.5 + 1e-9)
            row = int(obj["y"] / th - 0.5 + 1e-9)
            # Clamp to map bounds
            col = max(0, min(col, w - 1))
            row = max(0, min(row, h - 1))
            gid = ground_data[row * w + col]
            assert gid != 0, (
                f"Object '{obj['name']}' at tile ({col},{row}) is on an empty cell"
            )
            packed = gid - firstgid
            assert packed_walkable.get(packed, False), (
                f"Object '{obj['name']}' at tile ({col},{row}) is on a non-walkable tile "
                f"(packed_idx={packed})"
            )


# ---------------------------------------------------------------------------
# Test 4: round-trip — parse .tmj/.tsj back and compare to level_plan.json
# ---------------------------------------------------------------------------

def test_round_trip(tmj, tsj, level_plan, catalog):
    ts_entry = tmj["tilesets"][0]
    firstgid = ts_entry["firstgid"]

    # Rebuild catalog_id lookup from packed index
    catalog_tiles = sorted(catalog["tiles"], key=lambda t: t["id"])
    packed_to_catalog_id = {idx: t["id"] for idx, t in enumerate(catalog_tiles)}

    plan_props = level_plan["map_properties"]
    assert tmj["width"]      == plan_props["width"]
    assert tmj["height"]     == plan_props["height"]
    assert tmj["tilewidth"]  == plan_props["tile_width"]
    assert tmj["tileheight"] == plan_props["tile_height"]
    assert tmj["orientation"] == "isometric"

    # Check each tile layer grid
    plan_layers = {l["name"]: l for l in level_plan["layers"]}
    for layer in tmj["layers"]:
        if layer["type"] != "tilelayer":
            continue
        name = layer["name"]
        assert name in plan_layers, f"Layer '{name}' in .tmj not in level_plan"
        plan_grid = plan_layers[name]["grid"]
        w = tmj["width"]
        for row_idx, plan_row in enumerate(plan_grid):
            for col_idx, catalog_id in enumerate(plan_row):
                gid = layer["data"][row_idx * w + col_idx]
                packed = gid - firstgid
                rt_catalog_id = packed_to_catalog_id[packed]
                assert rt_catalog_id == catalog_id, (
                    f"Round-trip mismatch at ({col_idx},{row_idx}) in layer '{name}': "
                    f"plan={catalog_id}, round-trip={rt_catalog_id}"
                )

    # Check object types and that tile coords round-trip correctly
    th = tmj["tileheight"]
    plan_objects = {o["name"]: o for o in level_plan["objects"]}
    for layer in tmj["layers"]:
        if layer["type"] != "objectgroup":
            continue
        for obj in layer["objects"]:
            name = obj["name"]
            assert name in plan_objects, f"Object '{name}' in .tmj not in level_plan"
            plan_obj = plan_objects[name]
            assert obj["type"] == plan_obj["type"]
            # Verify the Tiled iso coords encode the correct col/row
            rt_col = int(obj["x"] / th - 0.5 + 1e-9)
            rt_row = int(obj["y"] / th - 0.5 + 1e-9)
            assert rt_col == plan_obj["col"], (
                f"Object '{name}': expected col={plan_obj['col']}, got {rt_col}"
            )
            assert rt_row == plan_obj["row"], (
                f"Object '{name}': expected row={plan_obj['row']}, got {rt_row}"
            )


# ---------------------------------------------------------------------------
# Test 5: object coordinate bounds
# ---------------------------------------------------------------------------

def test_object_coordinate_bounds(tmj):
    """
    Every object in level.tmj satisfies:
        0 <= x < width  * tile_height
        0 <= y < height * tile_height
    and maps back to the correct (col, row) in the level_plan.
    """
    w   = tmj["width"]
    h   = tmj["height"]
    th  = tmj["tileheight"]
    max_x = w * th
    max_y = h * th

    for layer in tmj["layers"]:
        if layer["type"] != "objectgroup":
            continue
        for obj in layer["objects"]:
            x = obj["x"]
            y = obj["y"]
            assert 0 <= x < max_x, (
                f"Object '{obj['name']}' x={x} is outside [0, {max_x})"
            )
            assert 0 <= y < max_y, (
                f"Object '{obj['name']}' y={y} is outside [0, {max_y})"
            )


# ---------------------------------------------------------------------------
# Test 6: output files exist
# ---------------------------------------------------------------------------

def test_output_files_exist():
    assert TMJ_PATH.exists(),    f"Missing: {TMJ_PATH}"
    assert TSJ_PATH.exists(),    f"Missing: {TSJ_PATH}"
    assert TILESET_PNG.exists(), f"Missing: {TILESET_PNG}"
    assert PREVIEW_PNG.exists(), f"Missing: {PREVIEW_PNG}"


# ---------------------------------------------------------------------------
# Test 7: every tile source in the fixture catalog resolves to an existing file
# ---------------------------------------------------------------------------

def test_catalog_source_paths_exist(catalog):
    """
    Each tile's ``source`` is relative to the repository root
    (``neuro-symbolic-level-designer/``).  Verify every referenced file exists.
    """
    repo_root = BACKEND_DIR.parent  # backend/ -> repo root
    seen: set[str] = set()
    for tile in catalog["tiles"]:
        src = tile["source"]
        if src in seen:
            continue
        seen.add(src)
        resolved = (repo_root / src) if not Path(src).is_absolute() else Path(src)
        assert resolved.exists(), (
            f"Tile source '{src}' does not exist at resolved path: {resolved}"
        )
