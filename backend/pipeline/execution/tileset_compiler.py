"""
Tileset Compiler
================
Reads the asset_catalog.json and produces one Tiled tileset per tile group
(ARCHITECTURE.md 5.2):
  - tileset.tsj / tileset.png       – first group
  - tileset_1.tsj / tileset_1.png   – second group, and so on

Tiles are grouped by sprite size and anchor ``(w, h, anchor.x, anchor.y)``.
A group is compiled when the level uses at least one of its tiles, and then
contains every catalog tile of the group (ascending id), laid out in rows of
``columns = min(tilecount, 2048 // tilewidth)`` tiles, so Tiled indexes local
tile i at ``(i % columns, i // columns)``. Groups are ordered by their smallest
catalog id, so floor tiles (the first ids) get ``tileset.png``.

flame_tiled packs every tileset image into one atlas of at most 4096 x 4096 px
on the web. Rows keep each image narrow; a level whose images cannot fit
(``ATLAS_FILL`` of the atlas area, or a side above ``ATLAS_SIDE``) fails with
``atlas_too_large`` instead of producing a bundle that crashes the game.

Usage (via CLI module):
    python -m pipeline.execution.compile --plan ... --catalog ... --out ...

Public API:
    compile_tilesets(catalog, used_ids, out_dir, source_resolver) -> list[CompiledTileset]
    tile_offset(w, h, anchor_x, anchor_y, tile_w, tile_h) -> (x, y)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image

from pipeline.errors import StageError

MAX_ROW_WIDTH = 2048  # px per tileset image row
ATLAS_SIDE = 4096  # flame_tiled atlas limit on the web (tile_atlas.dart)
ATLAS_FILL = 0.8  # share of the atlas area the tileset images may use

GroupKey = tuple[int, int, int, int]  # (w, h, anchor.x, anchor.y)


@dataclass
class CompiledTileset:
    tsj: dict[str, Any]
    image_name: str
    json_name: str
    catalog_ids: list[int]  # position in the list = local tile id

    @property
    def tilecount(self) -> int:
        return len(self.catalog_ids)


def tile_offset(w: int, h: int, anchor_x: int, anchor_y: int, tile_w: int, tile_h: int) -> tuple[int, int]:
    """
    Tiled ``tileoffset`` that puts a sprite's anchor on the tile center.

    Derivation (flame_tiled 3.1.2, ``FlameIsometricTileLayer.cacheTiles``):
    the renderer computes the tile center
        (W/2 * (tx - ty) + mapHeight * W/2,  H/2 * (tx + ty) + H/2),
    adds ``tileset.tileOffset``, and draws the sprite with its pixel
        (w - W/2, h - H/2)
    on that point (``anchorX = src.width - halfMapTile.x``, same for y).
    So sprite pixel p lands on ``center + offset + p - (w - W/2, h - H/2)``.
    Setting p = anchor and requiring it to land on the center gives
        offset = (w - W/2 - anchor.x, h - H/2 - anchor.y).
    A 64 x 32 floor tile with anchor (32, 16) gets offset (0, 0).
    """
    return (w - tile_w // 2 - anchor_x, h - tile_h // 2 - anchor_y)


def group_key(tile: dict[str, Any]) -> GroupKey:
    return (tile["rect"]["w"], tile["rect"]["h"], tile["anchor"]["x"], tile["anchor"]["y"])


def tileset_names(index: int) -> tuple[str, str]:
    """(image name, json name) of the index-th tileset."""
    stem = "tileset" if index == 0 else f"tileset_{index}"
    return f"{stem}.png", f"{stem}.tsj"


def _tile_properties(tile: dict[str, Any]) -> list[dict[str, Any]]:
    props: list[dict] = [
        {"name": "catalog_id", "type": "int",    "value": tile["id"]},
        {"name": "category",   "type": "string", "value": tile["category"]},
        {"name": "walkable",   "type": "bool",   "value": tile["walkable"]},
    ]
    if "material" in tile:
        props.append({"name": "material", "type": "string", "value": tile["material"]})
    if "elevation" in tile:
        props.append({"name": "elevation", "type": "int", "value": tile["elevation"]})
    if tile.get("tags"):
        props.append({"name": "tags", "type": "string", "value": ",".join(tile["tags"])})
    return props


def _collision_objectgroup(tile: dict[str, Any], local_id: int) -> dict[str, Any]:
    return {
        "draworder": "index",
        "id": local_id + 1,
        "name": "",
        "objects": [
            {
                "id": 1,
                "polygon": tile["collision_polygon"],
                "rotation": 0,
                "type": "",
                "visible": True,
                "x": 0,
                "y": 0,
            }
        ],
        "opacity": 1,
        "type": "objectgroup",
        "visible": True,
        "x": 0,
        "y": 0,
    }


def grid_size(tilecount: int, tilewidth: int) -> tuple[int, int]:
    """(columns, rows) of a tileset image."""
    columns = min(tilecount, max(1, MAX_ROW_WIDTH // tilewidth))
    return columns, -(-tilecount // columns)


def check_atlas(groups: list[list[dict[str, Any]]]) -> None:
    """Raises ``atlas_too_large`` if the tileset images cannot fit in the game's atlas."""
    total = 0
    for tiles in groups:
        w, h, _, _ = group_key(tiles[0])
        columns, rows = grid_size(len(tiles), w)
        iw, ih = columns * w, rows * h
        if iw > ATLAS_SIDE or ih > ATLAS_SIDE:
            raise StageError(
                "atlas_too_large",
                f"a tileset image of {iw} x {ih} px ({len(tiles)} tiles of {w} x {h}) exceeds the game's "
                f"{ATLAS_SIDE} x {ATLAS_SIDE} px texture atlas",
            )
        total += iw * ih
    limit = ATLAS_FILL * ATLAS_SIDE * ATLAS_SIDE
    if total > limit:
        raise StageError(
            "atlas_too_large",
            f"the tileset images need {total / 1e6:.1f} megapixels, more than {limit / 1e6:.1f} megapixels "
            f"({ATLAS_FILL:.0%} of the game's {ATLAS_SIDE} x {ATLAS_SIDE} px texture atlas); use fewer or smaller tiles",
        )


def _compile_group(
    tiles: list[dict[str, Any]],
    index: int,
    tile_w: int,
    tile_h: int,
    load_source: Callable[[str], Image.Image],
    out_dir: Path,
) -> CompiledTileset:
    image_name, json_name = tileset_names(index)
    w, h, ax, ay = group_key(tiles[0])
    n = len(tiles)

    # 1. Packed image: rows of ``columns`` w x h sprites.
    columns, rows = grid_size(n, w)
    atlas = Image.new("RGBA", (w * columns, h * rows), (0, 0, 0, 0))
    for local_id, tile in enumerate(tiles):
        r = tile["rect"]
        region = load_source(tile["source"]).crop((r["x"], r["y"], r["x"] + w, r["y"] + h))
        atlas.paste(region, ((local_id % columns) * w, (local_id // columns) * h))
    atlas.save(str(out_dir / image_name))

    # 2. Tile entries.
    tsj_tiles = []
    for local_id, tile in enumerate(tiles):
        entry: dict[str, Any] = {"id": local_id, "properties": _tile_properties(tile)}
        if tile.get("collision_polygon"):
            entry["objectgroup"] = _collision_objectgroup(tile, local_id)
        tsj_tiles.append(entry)

    # 3. The .tsj document. ``tileoffset`` is omitted when it is (0, 0).
    tsj: dict[str, Any] = {
        "columns":      columns,
        "image":        image_name,
        "imageheight":  h * rows,
        "imagewidth":   w * columns,
        "margin":       0,
        "name":         Path(json_name).stem,
        "spacing":      0,
        "tilecount":    n,
        "tiledversion": "1.10.2",
        "tileheight":   h,
        "tilewidth":    w,
    }
    ox, oy = tile_offset(w, h, ax, ay, tile_w, tile_h)
    if (ox, oy) != (0, 0):
        tsj["tileoffset"] = {"x": ox, "y": oy}
    tsj["tiles"] = tsj_tiles
    tsj["type"] = "tileset"
    tsj["version"] = "1.10"

    with open(out_dir / json_name, "w", encoding="utf-8") as f:
        json.dump(tsj, f, indent=2)

    return CompiledTileset(
        tsj=tsj,
        image_name=image_name,
        json_name=json_name,
        catalog_ids=[t["id"] for t in tiles],
    )


def compile_tilesets(
    catalog: dict[str, Any],
    used_ids: Iterable[int],
    out_dir: str,
    source_resolver: Callable[[str], str],
) -> list[CompiledTileset]:
    """
    Build one packed image + ``.tsj`` per tile group used by the level.

    Parameters
    ----------
    catalog : dict
        Parsed asset_catalog.json contents.
    used_ids : iterable of int
        Catalog ids that appear in the level's tile layers.
    out_dir : str
        Directory where the images and ``.tsj`` files are written.
    source_resolver : callable
        Maps a catalog ``source`` (relative to the repository root) to a
        file path.

    Returns
    -------
    list[CompiledTileset]
        In tileset order (``tileset``, ``tileset_1``, ...).
    """
    tile_w: int = catalog["tile_size"]["width"]
    tile_h: int = catalog["tile_size"]["height"]

    groups: dict[GroupKey, list[dict[str, Any]]] = {}
    for tile in sorted(catalog["tiles"], key=lambda t: t["id"]):
        groups.setdefault(group_key(tile), []).append(tile)

    used = set(used_ids)
    used_groups = [tiles for tiles in groups.values() if any(t["id"] in used for t in tiles)]
    used_groups.sort(key=lambda tiles: tiles[0]["id"])
    check_atlas(used_groups)

    sources: dict[str, Image.Image] = {}

    def load_source(source: str) -> Image.Image:
        if source not in sources:
            sources[source] = Image.open(source_resolver(source)).convert("RGBA")
        return sources[source]

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    return [
        _compile_group(tiles, i, tile_w, tile_h, load_source, out_dir_path)
        for i, tiles in enumerate(used_groups)
    ]
