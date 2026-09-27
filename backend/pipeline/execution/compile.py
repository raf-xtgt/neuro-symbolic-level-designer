"""
Compile CLI
===========
Entry point for the Execution Pipeline first slice.

Run from ``backend/``:
    python -m pipeline.execution.compile \\
        --plan  fixtures/starter/level_plan.json \\
        --catalog fixtures/starter/asset_catalog.json \\
        --out   ../z_legend_game/z_legend_game_flutter/assets/tiles/starter

Outputs:
    <out>/tileset.tsj, <out>/tileset.png        (first tile group)
    <out>/tileset_1.tsj, <out>/tileset_1.png    (further groups, if any)
    <out>/level.tmj
    <out>/preview_level.png
    <out>/level_loader.dart                     (Flame integration code, codegen.py)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import jsonschema

from pipeline.execution.codegen import write_level_loader
from pipeline.execution.tileset_compiler import compile_tilesets
from pipeline.execution.map_compiler import compile_map
from pipeline.execution.preview_renderer import render_preview


# compile.py is at backend/pipeline/execution/compile.py → 4 levels up is repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _schema_path(name: str) -> Path:
    here = Path(__file__).parent.parent  # pipeline/
    return here / "schemas" / name


def _validate(instance: dict, schema_name: str) -> None:
    schema = _load_json(str(_schema_path(schema_name)))
    jsonschema.validate(instance=instance, schema=schema)


def _resolve_source(source: str, root: Path = _REPO_ROOT) -> str:
    """
    Resolve a catalog tile ``source``. Values are relative to ``root``: the
    repository root (``neuro-symbolic-level-designer/``) for asset packs, the
    job folder for uploaded spritesheets. Absolute paths are used as-is.
    """
    p = Path(source)
    resolved = p if p.is_absolute() else root / p
    if not resolved.exists():
        raise FileNotFoundError(
            f"Cannot find source image '{source}'. Resolved to: {resolved}"
        )
    return str(resolved)


def _used_catalog_ids(level_plan: dict) -> set[int]:
    """Catalog ids in the plan's tile layers (0 is empty in overlay layers)."""
    used: set[int] = set()
    for index, layer in enumerate(level_plan["layers"]):
        for row in layer["grid"]:
            used.update(c for c in row if index == 0 or c != 0)
    return used


# -------------------------------------------------------------------------
# Main compile function (also called from tests)
# -------------------------------------------------------------------------

def run_compile(
    plan_path: str, catalog_path: str, out_dir: str, source_root: str | Path | None = None, prompt: str = "",
) -> dict:
    """
    Full compile pipeline.  Returns a dict with the parsed tmj, the tileset dicts, and the out dir.
    ``source_root``: the folder catalog sources are relative to (default: the repository root).
    ``prompt``: the design prompt, for the header of the generated ``level_loader.dart``.
    """
    root = Path(source_root) if source_root is not None else _REPO_ROOT
    catalog = _load_json(catalog_path)
    level_plan = _load_json(plan_path)

    # Validate fixtures against schemas
    print("Validating asset_catalog.json …", end=" ")
    _validate(catalog, "asset_catalog.schema.json")
    print("OK")

    print("Validating level_plan.json …", end=" ")
    _validate(level_plan, "level_plan.schema.json")
    print("OK")

    # 1. Tilesets (one per tile group used by the level)
    print("Compiling tilesets …", end=" ")
    tilesets = compile_tilesets(
        catalog=catalog,
        used_ids=_used_catalog_ids(level_plan),
        out_dir=out_dir,
        source_resolver=lambda source: _resolve_source(source, root),
    )
    print(f"OK ({len(tilesets)})")

    # 2. Map
    print("Compiling map …", end=" ")
    tmj = compile_map(level_plan=level_plan, tilesets=tilesets, out_dir=out_dir)
    print("OK")

    # 3. Preview
    preview_path = os.path.join(out_dir, "preview_level.png")
    print("Rendering preview …", end=" ")
    render_preview(tmj=tmj, bundle_dir=out_dir, out_path=preview_path)
    print("OK")

    # 4. Flame integration code
    print("Generating level_loader.dart …", end=" ")
    categories = {e["type"]: e["category"] for e in catalog.get("entities", [])}
    write_level_loader(tmj, prompt, categories, out_dir)
    print("OK")

    print(f"\nOutput written to: {os.path.abspath(out_dir)}")
    return {"tmj": tmj, "tilesets": [ts.tsj for ts in tilesets], "out_dir": out_dir}


# -------------------------------------------------------------------------
# CLI entry point
# -------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic Map & Tileset Compiler (Pipeline 3 slice 1)"
    )
    parser.add_argument("--plan",    required=True, help="Path to level_plan.json")
    parser.add_argument("--catalog", required=True, help="Path to asset_catalog.json")
    parser.add_argument("--out",     required=True, help="Output directory")
    parser.add_argument("--prompt",  default="", help="Design prompt, for the generated code header")
    args = parser.parse_args(argv)

    try:
        run_compile(args.plan, args.catalog, args.out, prompt=args.prompt)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
