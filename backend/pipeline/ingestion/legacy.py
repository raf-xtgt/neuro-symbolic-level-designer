"""
Legacy Tiled files (Pipeline 1, ARCHITECTURE.md 3.1): ``.tsj`` / ``.tsx``
tilesets and ``.tmj`` / ``.tmx`` maps.

A tileset whose image name or pixel size matches an uploaded spritesheet is
ground truth: its grid rectangles become the chips of that sheet (no contour
slicing) and its tile properties (``category``, ``walkable``, ``material``,
``type`` / ``class``, ``tags``) win over the agents.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PROPERTY_FIELDS = ("category", "walkable", "material", "family", "tags")


@dataclass
class LegacyTileset:
    file_name: str
    name: str
    tile_width: int
    tile_height: int
    columns: int
    tile_count: int
    margin: int
    spacing: int
    image: str | None  # file name only
    image_size: tuple[int, int] | None
    tiles: dict[int, dict] = field(default_factory=dict)  # local id -> ground truth fields

    def rect(self, local_id: int) -> tuple[int, int, int, int]:
        col, row = local_id % self.columns, local_id // self.columns
        x = self.margin + col * (self.tile_width + self.spacing)
        y = self.margin + row * (self.tile_height + self.spacing)
        return x, y, self.tile_width, self.tile_height

    def summary(self) -> dict:
        return {
            "kind": "tileset", "file_name": self.file_name, "tile_count": self.tile_count,
            "tile_size": [self.tile_width, self.tile_height], "image": self.image,
            "tiles_with_properties": len(self.tiles),
        }


def _truth(props: dict, tile_type: str | None) -> dict:
    """Ground-truth fields from Tiled properties (only the defined ones)."""
    out: dict = {}
    if isinstance(props.get("category"), str):
        out["category"] = props["category"].strip().lower()
    walkable = props.get("walkable")
    if isinstance(walkable, bool):
        out["walkable"] = walkable
    elif isinstance(walkable, str) and walkable.lower() in ("true", "false"):
        out["walkable"] = walkable.lower() == "true"
    if isinstance(props.get("material"), str):
        out["material"] = props["material"].strip().lower()
    if tile_type:
        out["family"] = tile_type.strip()
    if isinstance(props.get("tags"), str) and props["tags"].strip():
        out["tags"] = [t.strip() for t in props["tags"].split(",") if t.strip()]
    return out


def parse_tileset(path: Path, file_name: str) -> LegacyTileset:
    if path.suffix.lower() == ".tsj":
        data = json.loads(path.read_text(encoding="utf-8"))
        tiles = {}
        for tile in data.get("tiles", []):
            props = {p["name"]: p.get("value") for p in tile.get("properties", [])}
            truth = _truth(props, tile.get("type") or tile.get("class"))
            if truth:
                tiles[int(tile["id"])] = truth
        image = data.get("image")
        size = (data["imagewidth"], data["imageheight"]) if "imagewidth" in data and "imageheight" in data else None
        return LegacyTileset(
            file_name=file_name, name=data.get("name", ""), tile_width=int(data["tilewidth"]),
            tile_height=int(data["tileheight"]), columns=int(data.get("columns") or 1),
            tile_count=int(data.get("tilecount", len(data.get("tiles", [])))), margin=int(data.get("margin", 0)),
            spacing=int(data.get("spacing", 0)), image=PurePosixPath(image).name if image else None,
            image_size=size, tiles=tiles,
        )
    root = ET.parse(path).getroot()
    tiles = {}
    for tile in root.findall("tile"):
        props = {}
        for p in tile.findall("properties/property"):
            value: object = p.get("value", p.text)
            if p.get("type") == "bool":
                value = str(value).lower() == "true"
            props[p.get("name")] = value
        truth = _truth(props, tile.get("type") or tile.get("class"))
        if truth:
            tiles[int(tile.get("id"))] = truth
    image = root.find("image")
    return LegacyTileset(
        file_name=file_name, name=root.get("name", ""), tile_width=int(root.get("tilewidth")),
        tile_height=int(root.get("tileheight")), columns=int(root.get("columns") or 1),
        tile_count=int(root.get("tilecount", len(root.findall("tile")))), margin=int(root.get("margin", 0)),
        spacing=int(root.get("spacing", 0)),
        image=PurePosixPath(image.get("source")).name if image is not None and image.get("source") else None,
        image_size=(int(image.get("width")), int(image.get("height")))
        if image is not None and image.get("width") and image.get("height") else None,
        tiles=tiles,
    )


def matches(tileset: LegacyTileset, sheet_name: str, sheet_size: tuple[int, int]) -> bool:
    """The tileset describes this uploaded sheet (same image name or same pixel size)."""
    if tileset.image and tileset.image.lower() == PurePosixPath(sheet_name).name.lower():
        return True
    return tileset.image_size is not None and tuple(tileset.image_size) == tuple(sheet_size)


_TMX_LAYER_TAGS = {"layer", "objectgroup", "imagelayer", "group"}
_FLIP_MASK = 0x1FFFFFFF  # clear Tiled's flip bits


def parse_map(path: Path, file_name: str) -> dict:
    """Size, layer count, and per-GID usage counts of the tile layers."""
    usage: dict[int, int] = {}

    def count(gids) -> None:
        for gid in gids:
            gid = int(gid) & _FLIP_MASK
            if gid:
                usage[gid] = usage.get(gid, 0) + 1

    if path.suffix.lower() == ".tmj":
        data = json.loads(path.read_text(encoding="utf-8"))
        width, height, layers = data.get("width"), data.get("height"), data.get("layers", [])

        def visit(items):
            for layer in items:
                if layer.get("type") == "tilelayer" and isinstance(layer.get("data"), list):
                    count(layer["data"])
                visit(layer.get("layers", []))

        visit(layers)
        layer_count = len(layers)
    else:
        root = ET.parse(path).getroot()
        width, height = root.get("width"), root.get("height")
        layer_count = sum(1 for child in root if child.tag in _TMX_LAYER_TAGS)
        for data in root.iter("data"):
            if data.get("encoding") == "csv" and data.text:
                count(v for v in data.text.replace("\n", "").split(",") if v.strip())
            else:
                count(t.get("gid", 0) for t in data.findall("tile"))
    return {
        "kind": "map", "file_name": file_name,
        "width": int(width) if width is not None else None,
        "height": int(height) if height is not None else None,
        "layer_count": layer_count,
        "gid_usage": {str(k): v for k, v in sorted(usage.items())},
    }
