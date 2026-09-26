"""
Ingestion stage (Pipeline 1, ARCHITECTURE.md section 3).

Input:  an IngestionRequest (asset pack catalog and/or uploaded files).
Output: ``<work_dir>/asset_catalog.json`` plus a summary of the optional
        tilesets and maps.

Pipeline 1 is not implemented: uploaded spritesheets fail the stage with
``ingestion_not_implemented``. An asset pack supplies a pre-built catalog.
"""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.errors import StageError


@dataclass
class LegacyFile:
    path: Path
    original_name: str


@dataclass
class IngestionRequest:
    pack_catalog: Path | None = None
    spritesheets: list[Path] = field(default_factory=list)
    tilesets: list[LegacyFile] = field(default_factory=list)
    maps: list[LegacyFile] = field(default_factory=list)


@dataclass
class IngestionResult:
    catalog_path: Path
    legacy_files: list[dict]


def _describe_tileset(path: Path) -> dict:
    if path.suffix == ".tsj":
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"tile_count": data.get("tilecount", len(data.get("tiles", [])))}
    root = ET.parse(path).getroot()
    return {"tile_count": int(root.get("tilecount", len(root.findall("tile"))))}


_TMX_LAYER_TAGS = {"layer", "objectgroup", "imagelayer", "group"}


def _describe_map(path: Path) -> dict:
    if path.suffix == ".tmj":
        data = json.loads(path.read_text(encoding="utf-8"))
        width, height, layers = data.get("width"), data.get("height"), len(data["layers"])
    else:
        root = ET.parse(path).getroot()
        width, height = root.get("width"), root.get("height")
        layers = sum(1 for child in root if child.tag in _TMX_LAYER_TAGS)
    return {
        "width": int(width) if width is not None else None,
        "height": int(height) if height is not None else None,
        "layer_count": layers,
    }


def describe_legacy_files(request: IngestionRequest) -> list[dict]:
    """Parses the optional tilesets and maps. Later stages do not use them yet."""
    info = [
        {"kind": "tileset", "file_name": f.original_name, **_describe_tileset(f.path)}
        for f in request.tilesets
    ]
    info += [
        {"kind": "map", "file_name": f.original_name, **_describe_map(f.path)}
        for f in request.maps
    ]
    return info


def run_ingestion(request: IngestionRequest, work_dir: Path) -> IngestionResult:
    legacy = describe_legacy_files(request)
    if request.spritesheets:
        raise StageError(
            "ingestion_not_implemented",
            "Pipeline 1 (spritesheet ingestion) is not implemented yet. "
            "Use a built-in asset pack instead of uploading spritesheets.",
        )
    if request.pack_catalog is None:
        raise StageError("no_spritesheet_source", "No spritesheet source was given.")

    catalog_path = work_dir / "asset_catalog.json"
    shutil.copyfile(request.pack_catalog, catalog_path)
    return IngestionResult(catalog_path=catalog_path, legacy_files=legacy)
