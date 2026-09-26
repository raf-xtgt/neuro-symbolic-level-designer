"""
Tileset Compiler
================
Reads the asset_catalog.json and produces:
  - tileset.tsj   – Tiled External Tileset JSON
  - tileset.png   – packed atlas (uniform 64×32 grid, one row per catalog tile row)

The packed atlas contains ONLY the tiles listed in the catalog (in ascending id order),
laid out in a single row so that Tiled can index them by (gid - firstgid).

Usage (via CLI module):
    python -m pipeline.execution.compile --plan ... --catalog ... --out ...

Public API:
    compile_tileset(catalog: dict, source_image_path: str, out_dir: str) -> dict
        Returns the tileset dict (as it will be written to .tsj).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PIL import Image


def compile_tileset(
    catalog: dict[str, Any],
    source_image_path: str,
    out_dir: str,
    tileset_image_name: str = "tileset.png",
    tileset_json_name: str = "tileset.tsj",
) -> dict[str, Any]:
    """
    Build a packed tileset PNG and the matching Tiled .tsj from an asset catalog.

    Parameters
    ----------
    catalog : dict
        Parsed asset_catalog.json contents.
    source_image_path : str
        Absolute or relative path to the source atlas image
        (e.g. ``game-assets/grassland_tiles.png``).
    out_dir : str
        Directory where tileset.png and tileset.tsj are written.
    tileset_image_name : str
        Filename for the packed PNG (default ``tileset.png``).
    tileset_json_name : str
        Filename for the Tiled tileset JSON (default ``tileset.tsj``).

    Returns
    -------
    dict
        The parsed tileset dict (identical to what was written to .tsj).
    """
    tw: int = catalog["tile_size"]["width"]
    th: int = catalog["tile_size"]["height"]
    tiles: list[dict] = sorted(catalog["tiles"], key=lambda t: t["id"])
    n_tiles = len(tiles)

    # -----------------------------------------------------------------
    # 1. Build the packed atlas PNG
    # -----------------------------------------------------------------
    src = Image.open(source_image_path).convert("RGBA")

    # One row, n_tiles columns
    atlas = Image.new("RGBA", (tw * n_tiles, th), (0, 0, 0, 0))

    for packed_idx, tile in enumerate(tiles):
        ox: int = tile["offset"]["x"]
        oy: int = tile["offset"]["y"]
        region = src.crop((ox, oy, ox + tw, oy + th))
        atlas.paste(region, (packed_idx * tw, 0))

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    atlas_path = out_dir_path / tileset_image_name
    atlas.save(str(atlas_path))

    # -----------------------------------------------------------------
    # 2. Build tile property objects for .tsj
    # -----------------------------------------------------------------
    tsj_tiles = []
    for packed_idx, tile in enumerate(tiles):
        tile_entry: dict[str, Any] = {"id": packed_idx}

        props: list[dict] = [
            {"name": "catalog_id", "type": "int",    "value": tile["id"]},
            {"name": "category",   "type": "string", "value": tile["category"]},
            {"name": "walkable",   "type": "bool",   "value": tile["walkable"]},
        ]
        if "material" in tile:
            props.append({"name": "material", "type": "string", "value": tile["material"]})
        if "elevation" in tile:
            props.append({"name": "elevation", "type": "int", "value": tile["elevation"]})

        tile_entry["properties"] = props

        # Collision polygon (diamond shape for floor tiles if not provided)
        if "collision_polygon" in tile and tile["collision_polygon"]:
            tile_entry["objectgroup"] = {
                "draworder": "index",
                "id": packed_idx + 1,
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

        tsj_tiles.append(tile_entry)

    # -----------------------------------------------------------------
    # 3. Build the .tsj document
    # -----------------------------------------------------------------
    tsj: dict[str, Any] = {
        "columns":     n_tiles,
        "image":       tileset_image_name,
        "imageheight": th,
        "imagewidth":  tw * n_tiles,
        "margin":      0,
        "name":        Path(tileset_json_name).stem,
        "spacing":     0,
        "tilecount":   n_tiles,
        "tiledversion": "1.10.2",
        "tileheight":  th,
        "tilewidth":   tw,
        "tiles":       tsj_tiles,
        "type":        "tileset",
        "version":     "1.10",
    }

    tsj_path = out_dir_path / tileset_json_name
    with open(tsj_path, "w", encoding="utf-8") as f:
        json.dump(tsj, f, indent=2)

    return tsj
