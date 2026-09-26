"""
Preview Renderer
================
Renders the compiled .tmj map as an isometric preview PNG.
Object markers are drawn as coloured diamonds.

Public API:
    render_preview(tmj, tsj, tileset_png_path, out_path) -> None
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


# Marker colours by object type
_MARKER_COLORS: dict[str, tuple[int, int, int, int]] = {
    "PlayerSpawn": (0, 200, 0, 220),
    "ExitTrigger": (200, 200, 0, 220),
    "Zombie":      (200, 0, 0, 220),
}
_DEFAULT_MARKER_COLOR = (100, 100, 255, 220)


def _iso_to_screen(col: int, row: int, tw: int, th: int, origin_x: int, origin_y: int):
    """Convert isometric tile coordinates to screen pixel coordinates (tile top-center)."""
    sx = origin_x + (col - row) * (tw // 2)
    sy = origin_y + (col + row) * (th // 2)
    return sx, sy


def _tiled_iso_to_screen(
    x: float, y: float, tw: int, th: int, origin_x: int, origin_y: int
) -> tuple[float, float]:
    """
    Convert Tiled isometric object coordinates to canvas screen coordinates.

    Tiled stores object positions on the unprojected rhombus grid where both
    axes are in tile-height units.  The projection to screen is:
        screen_x = (x - y) * tile_width / (2 * tile_height)
        screen_y = (x + y) / 2

    ``origin_x`` / ``origin_y`` shift to match the canvas origin used for tiles.
    """
    sx = origin_x + (x - y) * tw / (2 * th)
    sy = origin_y + (x + y) / 2
    return sx, sy


def render_preview(
    tmj: dict[str, Any],
    tsj: dict[str, Any],
    tileset_png_path: str,
    out_path: str,
) -> None:
    """
    Draw the isometric map with tile sprites and object markers.

    Parameters
    ----------
    tmj : dict
        Parsed level.tmj.
    tsj : dict
        Parsed tileset.tsj.
    tileset_png_path : str
        Path to the packed tileset.png.
    out_path : str
        Where to write preview_level.png.
    """
    width: int  = tmj["width"]
    height: int = tmj["height"]
    tw: int     = tmj["tilewidth"]
    th: int     = tmj["tileheight"]

    firstgid: int = tmj["tilesets"][0]["firstgid"]

    # Load the packed tileset
    tileset_img = Image.open(tileset_png_path).convert("RGBA")

    # Canvas size: the diamond-shaped map fits in a rhombus
    # Leftmost point: row=max, col=0 → x = origin_x - max*(tw/2)
    # Rightmost point: col=max, row=0 → x = origin_x + max*(tw/2)
    # So canvas_width = (width + height) * tw/2
    # canvas_height = (width + height) * th/2  + th (for the bottom of the last tile)
    canvas_w = (width + height) * (tw // 2)
    canvas_h = (width + height) * (th // 2) + th

    # Origin: top vertex of the diamond
    origin_x = height * (tw // 2)
    origin_y = 0

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (40, 44, 52, 255))

    # Find the first tile layer
    tile_layers = [l for l in tmj["layers"] if l["type"] == "tilelayer"]
    object_layers = [l for l in tmj["layers"] if l["type"] == "objectgroup"]

    for layer in tile_layers:
        data = layer["data"]
        for row in range(height):
            for col in range(width):
                gid = data[row * width + col]
                if gid == 0:
                    continue
                packed_idx = gid - firstgid
                # Crop tile from packed atlas
                sx_tile = packed_idx * tw
                tile_crop = tileset_img.crop((sx_tile, 0, sx_tile + tw, th))
                # Screen position: top-left of the tile diamond
                sx, sy = _iso_to_screen(col, row, tw, th, origin_x, origin_y)
                canvas.paste(tile_crop, (sx, sy), tile_crop)

    # Draw object markers
    draw = ImageDraw.Draw(canvas)
    for layer in object_layers:
        for obj in layer["objects"]:
            obj_type = obj.get("type", "")
            color = _MARKER_COLORS.get(obj_type, _DEFAULT_MARKER_COLOR)
            # Project from Tiled isometric object coordinates to canvas pixels.
            # obj["x"] and obj["y"] are in tile-height units on the unprojected grid.
            sx, sy = _tiled_iso_to_screen(
                obj["x"], obj["y"], tw, th, origin_x, origin_y
            )
            # Draw a filled diamond marker centred on the tile
            cx = int(sx + tw // 2)
            cy = int(sy + th // 2)
            r = tw // 4  # marker half-width
            rh = th // 4
            diamond = [
                (cx,      cy - rh),
                (cx + r,  cy),
                (cx,      cy + rh),
                (cx - r,  cy),
            ]
            draw.polygon(diamond, fill=color)

    canvas.save(out_path)
