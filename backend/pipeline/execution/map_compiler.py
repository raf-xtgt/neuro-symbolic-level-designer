"""
Map Compiler
============
Reads level_plan.json + asset_catalog.json and produces level.tmj.

Tiled JSON map format (orientation=isometric, renderorder=right-down).
Tile data is stored as uncompressed CSV integers (Tiled "csv" encoding).
GID = firstgid + packed_index_in_tileset.

The tileset is **embedded inline** in level.tmj by default so that
flame_tiled can load it without a separate file-system lookup.
The standalone tileset.tsj and tileset.png are still written by the
tileset_compiler (ARCHITECTURE.md 5.2) and are kept for tooling use.

Public API:
    compile_map(level_plan, catalog, tileset_tsj, out_dir,
                firstgid=1,
                tileset_image_name="tileset.png",
                map_json_name="level.tmj") -> dict
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def compile_map(
    level_plan: dict[str, Any],
    catalog: dict[str, Any],
    tileset_tsj: dict[str, Any],
    out_dir: str,
    firstgid: int = 1,
    tileset_image_name: str = "tileset.png",
    map_json_name: str = "level.tmj",
    # Legacy parameter kept for callers that still pass it; ignored.
    tileset_json_name: str = "tileset.tsj",
) -> dict[str, Any]:
    """
    Compile a level_plan + catalog into a Tiled .tmj file.

    The tileset is embedded inline (all fields from tileset_tsj plus
    ``firstgid``).  The ``image`` path is set to ``tileset_image_name``
    so that it resolves relative to the .tmj directory.

    Parameters
    ----------
    level_plan : dict
        Parsed level_plan.json.
    catalog : dict
        Parsed asset_catalog.json.
    tileset_tsj : dict
        Parsed tileset.tsj (output of tileset_compiler).
    out_dir : str
        Directory where level.tmj is written.
    firstgid : int
        GID offset for this tileset (default 1, Tiled convention).
    tileset_image_name : str
        Filename of the tileset PNG relative to the .tmj (default
        ``tileset.png``).
    map_json_name : str
        Filename for the output map file (default ``level.tmj``).
    tileset_json_name : str
        Ignored – kept for backwards compatibility with callers.

    Returns
    -------
    dict
        Parsed map dict (identical to what was written to .tmj).
    """
    props = level_plan["map_properties"]
    width: int  = props["width"]
    height: int = props["height"]
    tw: int     = props["tile_width"]
    th: int     = props["tile_height"]

    # Build lookup: catalog_id -> packed_index (0-based position in tileset atlas)
    catalog_tiles = sorted(catalog["tiles"], key=lambda t: t["id"])
    catalog_id_to_packed = {tile["id"]: idx for idx, tile in enumerate(catalog_tiles)}

    # Build lookup: packed_index -> walkable
    packed_walkable = {idx: tile["walkable"] for idx, tile in enumerate(catalog_tiles)}

    # -----------------------------------------------------------------
    # 1. Tile layers → Tiled layer objects
    # -----------------------------------------------------------------
    tiled_layers: list[dict[str, Any]] = []
    layer_id_counter = 1

    for layer in level_plan["layers"]:
        grid = layer["grid"]
        flat_data: list[int] = []
        for row in grid:
            for catalog_id in row:
                packed = catalog_id_to_packed[catalog_id]
                flat_data.append(firstgid + packed)

        tiled_layer: dict[str, Any] = {
            "data":       flat_data,
            "encoding":   "csv",
            "height":     height,
            "id":         layer_id_counter,
            "name":       layer["name"],
            "opacity":    1,
            "type":       "tilelayer",
            "visible":    True,
            "width":      width,
            "x":          0,
            "y":          0,
        }
        if layer.get("elevation", 0) != 0:
            tiled_layer["properties"] = [
                {"name": "elevation", "type": "int", "value": layer["elevation"]}
            ]
        tiled_layers.append(tiled_layer)
        layer_id_counter += 1

    # -----------------------------------------------------------------
    # 2. Objects layer
    #
    # Tiled isometric object coordinates use the unprojected grid units where
    # both axes are in tile-height units:
    #   x = (col + 0.5) * tile_height   (right edge of Tiled's rhombus grid)
    #   y = (row + 0.5) * tile_height
    # This matches what flame_tiled expects when loading an isometric map.
    # -----------------------------------------------------------------
    obj_id_counter = 1
    tiled_objects: list[dict[str, Any]] = []

    for obj in level_plan["objects"]:
        col: int = obj["col"]
        row: int = obj["row"]
        iso_x: float = (col + 0.5) * th
        iso_y: float = (row + 0.5) * th
        tiled_obj: dict[str, Any] = {
            "id":      obj_id_counter,
            "name":    obj["name"],
            "type":    obj["type"],
            "x":       iso_x,
            "y":       iso_y,
            "width":   0.0,
            "height":  0.0,
            "rotation": 0,
            "visible": True,
        }
        if "properties" in obj and obj["properties"]:
            tiled_obj["properties"] = [
                {"name": k, "type": "string", "value": str(v)}
                for k, v in obj["properties"].items()
            ]
        tiled_objects.append(tiled_obj)
        obj_id_counter += 1

    entities_layer: dict[str, Any] = {
        "draworder": "topdown",
        "id":        layer_id_counter,
        "name":      "Entities",
        "objects":   tiled_objects,
        "opacity":   1,
        "type":      "objectgroup",
        "visible":   True,
        "x":         0,
        "y":         0,
    }
    tiled_layers.append(entities_layer)

    # -----------------------------------------------------------------
    # 3. Build the embedded tileset entry.
    #    Copy all fields from tileset_tsj and override "image" to the
    #    local filename, then add "firstgid".
    # -----------------------------------------------------------------
    embedded_tileset: dict[str, Any] = {
        k: v for k, v in tileset_tsj.items()
        if k not in ("type", "version", "tiledversion")
    }
    embedded_tileset["firstgid"] = firstgid
    embedded_tileset["image"]    = tileset_image_name

    # -----------------------------------------------------------------
    # 4. Build the .tmj document
    # -----------------------------------------------------------------
    tmj: dict[str, Any] = {
        "compressionlevel": -1,
        "height":           height,
        "infinite":         False,
        "layers":           tiled_layers,
        "nextlayerid":      layer_id_counter + 1,
        "nextobjectid":     obj_id_counter + 1,
        "orientation":      "isometric",
        "renderorder":      "right-down",
        "tiledversion":     "1.10.2",
        "tileheight":       th,
        "tilesets":         [embedded_tileset],
        "tilewidth":        tw,
        "type":             "map",
        "version":          "1.10",
        "width":            width,
    }

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    map_path = out_dir_path / map_json_name
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(tmj, f, indent=2)

    return tmj
