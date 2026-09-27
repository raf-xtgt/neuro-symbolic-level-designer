"""
Tileset images wrap into rows (flame_tiled packs them into one atlas of at
most 4096 x 4096 px on the web), and the ``atlas_too_large`` guard.

``build_multirow_bundle`` also writes the Flutter fixture
``z_legend_game_flutter/test/fixtures/multirow_tileset/``:
    uv run python -m tests.test_tileset_rows
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from pipeline.errors import StageError
from pipeline.execution.compile import run_compile
from pipeline.execution.tileset_compiler import check_atlas

FLOORS = 82  # the floor group of the recorded grassland upload
SIZE = 10  # map cols and rows
FLUTTER_FIXTURE = (
    Path(__file__).resolve().parents[2] / "z_legend_game" / "z_legend_game_flutter" / "test" / "fixtures" / "multirow_tileset"
)


def _color(i: int) -> tuple[int, int, int, int]:
    return (i * 3 % 256, 255 - i * 3 % 256, i * 7 % 256, 255)


def build_multirow_bundle(out: Path) -> Path:
    """A 10 x 10 level whose ground uses 82 floor tiles of one 64 x 32 group. Returns the bundle dir."""
    src = out / "src"
    src.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (64 * 10, 32 * 9))
    tiles = []
    for i in range(FLOORS):
        x, y = (i % 10) * 64, (i // 10) * 32
        sheet.paste(Image.new("RGBA", (64, 32), _color(i)), (x, y))
        tiles.append({
            "id": i, "name": f"floor_{i:02d}", "source": "sheet.png", "category": "floor", "walkable": True,
            "material": "grass", "rect": {"x": x, "y": y, "w": 64, "h": 32}, "anchor": {"x": 32, "y": 16},
            "tags": ["grass"],
        })
    sheet.save(src / "sheet.png")
    catalog = {
        "tile_size": {"width": 64, "height": 32}, "tiles": tiles,
        "entities": [
            {"type": "PlayerSpawn", "name": "Player Spawn", "category": "player", "width": 64, "height": 32},
            {"type": "ExitTrigger", "name": "Exit Trigger", "category": "trigger", "width": 64, "height": 32},
        ],
    }
    plan = {
        "map_properties": {"width": SIZE, "height": SIZE, "tile_width": 64, "tile_height": 32, "orientation": "isometric"},
        "layers": [
            {"name": "Ground", "elevation": 0, "grid": [[(r * SIZE + c) % FLOORS for c in range(SIZE)] for r in range(SIZE)]},
            {"name": "Objects", "elevation": 0, "grid": [[0] * SIZE for _ in range(SIZE)]},
        ],
        "objects": [
            {"name": "spawn_player", "type": "PlayerSpawn", "col": 1, "row": 1},
            {"name": "exit_trigger", "type": "ExitTrigger", "col": 8, "row": 8},
        ],
    }
    (src / "asset_catalog.json").write_text(json.dumps(catalog))
    (src / "level_plan.json").write_text(json.dumps(plan))
    bundle = out / "bundle"
    with contextlib.redirect_stdout(io.StringIO()):
        run_compile(str(src / "level_plan.json"), str(src / "asset_catalog.json"), str(bundle), source_root=src)
    return bundle


def test_82_floor_tiles_wrap_into_rows(tmp_path):
    bundle = build_multirow_bundle(tmp_path)
    tsj = json.loads((bundle / "tileset.tsj").read_text())
    image = Image.open(bundle / "tileset.png").convert("RGBA")
    assert (tsj["columns"], tsj["tilecount"], tsj["imagewidth"], tsj["imageheight"]) == (32, FLOORS, 2048, 96)
    assert image.size == (2048, 96)

    tmj = json.loads((bundle / "level.tmj").read_text())
    embedded = tmj["tilesets"][0]
    assert (embedded["columns"], embedded["imagewidth"], embedded["imageheight"]) == (32, 2048, 96)
    ground = next(layer for layer in tmj["layers"] if layer["name"] == "Ground")["data"]
    sheet = Image.open(tmp_path / "src" / "sheet.png").convert("RGBA")
    for catalog_id in (0, 31, 32, 33, 70, 81):  # rows 0, 1 and 2
        gid = ground[catalog_id]  # the plan puts catalog id i on cell i
        local = gid - embedded["firstgid"]
        x, y = (local % 32) * 64, (local // 32) * 32
        src = sheet.crop(((catalog_id % 10) * 64, (catalog_id // 10) * 32, (catalog_id % 10) * 64 + 64, (catalog_id // 10) * 32 + 32))
        assert image.crop((x, y, x + 64, y + 32)).tobytes() == src.tobytes(), catalog_id


def _group(w: int, h: int, n: int) -> list[dict]:
    return [{"id": i, "rect": {"x": 0, "y": 0, "w": w, "h": h}, "anchor": {"x": w // 2, "y": h - 16}} for i in range(n)]


def test_atlas_guard():
    check_atlas([_group(64, 32, FLOORS), _group(128, 256, 40)])  # fits
    with pytest.raises(StageError) as side:
        check_atlas([_group(2048, 1024, 5)])  # one column, 5120 px high
    assert side.value.code == "atlas_too_large" and "5120" in side.value.message
    with pytest.raises(StageError) as area:
        check_atlas([_group(2048, 2048, 1) for _ in range(4)])  # 16.8 megapixels
    assert area.value.code == "atlas_too_large" and "megapixels" in area.value.message


if __name__ == "__main__":  # regenerate the Flutter fixture
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        bundle = build_multirow_bundle(Path(tmp))
        FLUTTER_FIXTURE.mkdir(parents=True, exist_ok=True)
        for name in ("level.tmj", "tileset.png"):
            shutil.copyfile(bundle / name, FLUTTER_FIXTURE / name)
    print(f"wrote {FLUTTER_FIXTURE}", file=sys.stderr)
