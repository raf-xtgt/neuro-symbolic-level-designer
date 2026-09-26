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
    <out>/tileset.tsj
    <out>/tileset.png
    <out>/level.tmj
    <out>/preview_level.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import jsonschema

from pipeline.execution.tileset_compiler import compile_tileset
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


def _resolve_source_image(catalog: dict) -> str:
    """
    Resolve the source image path from the first tile's ``source`` field.
    ``source`` values are relative to the repository root
    (``neuro-symbolic-level-designer/``).  Absolute paths are used as-is.
    """
    first_source = catalog["tiles"][0]["source"]
    p = Path(first_source)
    resolved = p if p.is_absolute() else _REPO_ROOT / p
    if not resolved.exists():
        raise FileNotFoundError(
            f"Cannot find source image '{first_source}'. "
            f"Resolved to: {resolved}"
        )
    return str(resolved)


# -------------------------------------------------------------------------
# Main compile function (also called from tests)
# -------------------------------------------------------------------------

def run_compile(plan_path: str, catalog_path: str, out_dir: str) -> dict:
    """
    Full compile pipeline.  Returns a dict with the parsed tmj, tsj, and paths.
    """
    catalog = _load_json(catalog_path)
    level_plan = _load_json(plan_path)

    # Validate fixtures against schemas
    print("Validating asset_catalog.json …", end=" ")
    _validate(catalog, "asset_catalog.schema.json")
    print("OK")

    print("Validating level_plan.json …", end=" ")
    _validate(level_plan, "level_plan.schema.json")
    print("OK")

    # Resolve source atlas
    source_image = _resolve_source_image(catalog)
    print(f"Source atlas: {source_image}")

    # 1. Tileset
    print("Compiling tileset …", end=" ")
    tsj = compile_tileset(
        catalog=catalog,
        source_image_path=source_image,
        out_dir=out_dir,
    )
    print("OK")

    # 2. Map
    print("Compiling map …", end=" ")
    tmj = compile_map(
        level_plan=level_plan,
        catalog=catalog,
        tileset_tsj=tsj,
        out_dir=out_dir,
    )
    print("OK")

    # 3. Preview
    preview_path = os.path.join(out_dir, "preview_level.png")
    print("Rendering preview …", end=" ")
    render_preview(
        tmj=tmj,
        tsj=tsj,
        tileset_png_path=os.path.join(out_dir, "tileset.png"),
        out_path=preview_path,
    )
    print("OK")

    print(f"\nOutput written to: {os.path.abspath(out_dir)}")
    return {"tmj": tmj, "tsj": tsj, "out_dir": out_dir}


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
    args = parser.parse_args(argv)

    try:
        run_compile(args.plan, args.catalog, args.out)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
