"""
Preview Renderer
================
Renders the compiled .tmj map as an isometric preview PNG.

Tile layers are drawn in map order. The first layer (Ground) is flat; the
layers after it (Objects) are drawn in depth order (row + col, then col), so
nearer sprites cover farther ones. Every sprite is placed so that its anchor
sits on the tile center; the anchor is recovered from the tileset's
``tileoffset`` (see ``tileset_compiler.tile_offset``). Object markers are
drawn on top as coloured diamonds. The canvas is sized to fit every sprite,
including tall ones that reach above the map.

Public API:
    render_preview(tmj, bundle_dir, out_path) -> None
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
_BACKGROUND = (40, 44, 52, 255)
_MARGIN = 8


def _tile_center(col: int, row: int, tw: int, th: int) -> tuple[int, int]:
    """Center of tile (col, row), with the map's top vertex at x = 0, y = 0."""
    return (col - row) * (tw // 2), (col + row) * (th // 2) + th // 2


def _tiled_iso_to_screen(x: float, y: float, tw: int, th: int) -> tuple[float, float]:
    """
    Tiled isometric object coordinates (both axes in tile-height units on the
    unprojected grid) to the same screen space as ``_tile_center``.
    """
    return (x - y) * tw / (2 * th), (x + y) / 2


class _Sprites:
    """GID -> (sprite image, anchor), loaded from the bundle's tileset images."""

    def __init__(self, tmj: dict[str, Any], bundle_dir: Path):
        tw, th = tmj["tilewidth"], tmj["tileheight"]
        self._tilesets = []
        for ts in tmj["tilesets"]:
            w, h = ts["tilewidth"], ts["tileheight"]
            off = ts.get("tileoffset", {"x": 0, "y": 0})
            anchor = (w - tw // 2 - off["x"], h - th // 2 - off["y"])
            image = Image.open(bundle_dir / ts["image"]).convert("RGBA")
            self._tilesets.append((ts["firstgid"], ts["tilecount"], w, h, anchor, image))

    def get(self, gid: int) -> tuple[Image.Image, tuple[int, int]]:
        for firstgid, count, w, h, anchor, image in self._tilesets:
            if firstgid <= gid < firstgid + count:
                x = (gid - firstgid) * w
                return image.crop((x, 0, x + w, h)), anchor
        raise KeyError(f"GID {gid} is in no tileset")


def render_preview(tmj: dict[str, Any], bundle_dir: str, out_path: str) -> None:
    """
    Draw the isometric map with tile sprites and object markers.

    Parameters
    ----------
    tmj : dict
        Parsed level.tmj.
    bundle_dir : str
        Folder that holds the tileset images named in ``tmj``.
    out_path : str
        Where to write preview_level.png.
    """
    width: int  = tmj["width"]
    height: int = tmj["height"]
    tw: int     = tmj["tilewidth"]
    th: int     = tmj["tileheight"]
    sprites = _Sprites(tmj, Path(bundle_dir))

    # 1. Collect sprite placements (top-left in map space) in draw order.
    placements: list[tuple[Image.Image, int, int]] = []
    tile_layers = [l for l in tmj["layers"] if l["type"] == "tilelayer"]
    for layer_index, layer in enumerate(tile_layers):
        cells = [(row, col) for row in range(height) for col in range(width)]
        if layer_index > 0:
            cells.sort(key=lambda rc: (rc[0] + rc[1], rc[1]))
        for row, col in cells:
            gid = layer["data"][row * width + col]
            if gid == 0:
                continue
            image, (ax, ay) = sprites.get(gid)
            cx, cy = _tile_center(col, row, tw, th)
            placements.append((image, cx - ax, cy - ay))

    # 2. Object markers.
    markers: list[tuple[list[tuple[float, float]], tuple[int, int, int, int]]] = []
    r, rh = tw // 4, th // 4
    for layer in tmj["layers"]:
        if layer["type"] != "objectgroup":
            continue
        for obj in layer["objects"]:
            cx, cy = _tiled_iso_to_screen(obj["x"], obj["y"], tw, th)
            diamond = [(cx, cy - rh), (cx + r, cy), (cx, cy + rh), (cx - r, cy)]
            markers.append((diamond, _MARKER_COLORS.get(obj.get("type", ""), _DEFAULT_MARKER_COLOR)))

    # 3. Canvas that fits the whole map diamond and every sprite.
    left, top = -height * (tw // 2), 0
    right, bottom = width * (tw // 2), (width + height) * (th // 2)
    for image, x, y in placements:
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x + image.width), max(bottom, y + image.height)
    shift_x, shift_y = _MARGIN - left, _MARGIN - top
    canvas = Image.new(
        "RGBA",
        (right - left + 2 * _MARGIN, bottom - top + 2 * _MARGIN),
        _BACKGROUND,
    )

    for image, x, y in placements:
        canvas.alpha_composite(image, (x + shift_x, y + shift_y))

    draw = ImageDraw.Draw(canvas)
    for diamond, color in markers:
        draw.polygon([(x + shift_x, y + shift_y) for x, y in diamond], fill=color)

    canvas.save(out_path)
