"""
Map Compiler
============
Reads level_plan.json + asset_catalog.json and produces level.tmj.

Tiled JSON map format (orientation=isometric, renderorder=right-down).
Tile data is stored as uncompressed CSV integers (Tiled "csv" encoding).
GID = firstgid of the tile's tileset + its local index in that tileset.
Tilesets get consecutive ``firstgid`` values starting at 1.

Plan grids hold catalog ids. The first layer (Ground) fills every cell; in
the layers after it (for example Objects) the value 0 means an empty cell
(GID 0). Catalog id 0 is a floor tile, which never appears in those layers.

All tilesets are **embedded inline** in level.tmj so that flame_tiled can
load them without a separate file-system lookup. The standalone .tsj and
.png files are still written by the tileset_compiler (ARCHITECTURE.md 5.2)
and are kept for tooling use.

Public API:
    compile_map(level_plan, tilesets, out_dir, map_json_name="level.tmj") -> dict
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.execution.tileset_compiler import CompiledTileset


def compile_map(
    level_plan: dict[str, Any],
    tilesets: list[CompiledTileset],
    out_dir: str,
    map_json_name: str = "level.tmj",
) -> dict[str, Any]:
    """
    Compile a level_plan + compiled tilesets into a Tiled .tmj file.

    Each tileset is embedded inline (all fields from its .tsj plus
    ``firstgid``), with ``image`` set to its file name so that it resolves
    relative to the .tmj directory.

    Parameters
    ----------
    level_plan : dict
        Parsed level_plan.json.
    tilesets : list[CompiledTileset]
        Output of ``tileset_compiler.compile_tilesets``, in tileset order.
    out_dir : str
        Directory where level.tmj is written.
    map_json_name : str
        Filename for the output map file (default ``level.tmj``).

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

    # catalog_id -> GID, with consecutive firstgid values per tileset.
    firstgids: list[int] = []
    catalog_id_to_gid: dict[int, int] = {}
    next_gid = 1
    for ts in tilesets:
        firstgids.append(next_gid)
        for local_id, catalog_id in enumerate(ts.catalog_ids):
            catalog_id_to_gid[catalog_id] = next_gid + local_id
        next_gid += ts.tilecount

    # -----------------------------------------------------------------
    # 1. Tile layers → Tiled layer objects
    # -----------------------------------------------------------------
    tiled_layers: list[dict[str, Any]] = []
    layer_id_counter = 1

    for layer_index, layer in enumerate(level_plan["layers"]):
        overlay = layer_index > 0
        flat_data: list[int] = []
        for row in layer["grid"]:
            for catalog_id in row:
                if overlay and catalog_id == 0:
                    flat_data.append(0)
                else:
                    flat_data.append(catalog_id_to_gid[catalog_id])

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
    # 3. Build the embedded tileset entries.
    #    Copy all fields from each .tsj and override "image" to the
    #    local filename, then add "firstgid".
    # -----------------------------------------------------------------
    embedded_tilesets: list[dict[str, Any]] = []
    for ts, firstgid in zip(tilesets, firstgids):
        embedded: dict[str, Any] = {
            k: v for k, v in ts.tsj.items()
            if k not in ("type", "version", "tiledversion")
        }
        embedded["firstgid"] = firstgid
        embedded["image"]    = ts.image_name
        embedded_tilesets.append(embedded)

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
        "tilesets":         embedded_tilesets,
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
