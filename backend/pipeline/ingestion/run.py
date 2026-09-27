"""
Ingestion stage (Pipeline 1, ARCHITECTURE.md section 3).

Input:  an IngestionRequest (asset pack catalog and/or uploaded files).
Output: ``<work_dir>/asset_catalog.json`` plus a summary of the optional
        tilesets and maps.

* Asset pack: the pack's pre-built catalog (sources relative to the
  repository root).
* Uploaded spritesheets: Pipeline 1 (``pipeline1.py``): pre-processor,
  analysis agents, harmonizer. Uploaded sheets and legacy tilesets and maps
  are combined into one catalog, with sources relative to the job folder
  (``source_root``).
"""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.errors import StageError
from pipeline.ingestion.pipeline1 import StepCallback, Upload, run_pipeline1
from pipeline.llm.base import LLMConfigError, LLMError, LLMOutputError, LLMProvider


@dataclass
class LegacyFile:
    path: Path
    original_name: str


@dataclass
class IngestionRequest:
    pack_catalog: Path | None = None
    spritesheets: list[LegacyFile] = field(default_factory=list)
    tilesets: list[LegacyFile] = field(default_factory=list)
    maps: list[LegacyFile] = field(default_factory=list)


@dataclass
class IngestionResult:
    catalog_path: Path
    legacy_files: list[dict]
    source_root: Path | None = None  # None: catalog sources are relative to the repository root
    summary: dict | None = None  # Pipeline 1 summary (uploads only)
    extra_files: list[Path] = field(default_factory=list)  # to serve with the bundle
    warnings: list[str] = field(default_factory=list)


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
    """Short summary of the optional tilesets and maps (the job summary)."""
    info = [
        {"kind": "tileset", "file_name": f.original_name, **_describe_tileset(f.path)}
        for f in request.tilesets
    ]
    info += [
        {"kind": "map", "file_name": f.original_name, **_describe_map(f.path)}
        for f in request.maps
    ]
    return info


def run_ingestion(
    request: IngestionRequest,
    work_dir: Path,
    job_dir: Path | None = None,
    provider: LLMProvider | None = None,
    on_step: StepCallback | None = None,
    cache_dir: Path | None = None,
) -> IngestionResult:
    legacy = describe_legacy_files(request)
    if request.spritesheets:
        job_dir = job_dir or work_dir.parent

        def upload(f: LegacyFile) -> Upload:
            return Upload(f.path, f.original_name)

        try:
            result = run_pipeline1(
                [upload(f) for f in request.spritesheets], [upload(f) for f in request.tilesets],
                [upload(f) for f in request.maps], job_dir, work_dir, provider, on_step, cache_dir,
            )
        except LLMConfigError as exc:
            raise StageError("llm_config", str(exc)) from None
        except LLMOutputError as exc:
            raise StageError("llm_output_invalid", str(exc)) from None
        except LLMError as exc:
            raise StageError("llm_unavailable", str(exc)) from None
        return IngestionResult(
            catalog_path=result.catalog_path,
            legacy_files=legacy,
            source_root=job_dir,
            summary=result.summary,
            extra_files=[result.contact_sheet_path, result.report_path],
            warnings=result.warnings,
        )
    if request.pack_catalog is None:
        raise StageError("no_spritesheet_source", "No spritesheet source was given.")

    catalog_path = work_dir / "asset_catalog.json"
    shutil.copyfile(request.pack_catalog, catalog_path)
    return IngestionResult(catalog_path=catalog_path, legacy_files=legacy)
