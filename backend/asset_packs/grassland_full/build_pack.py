"""
Build the ``grassland_full`` asset pack from the Flare tileset definition.

Inputs (repository root relative):
    game-assets/grassland_tiles.png
    game-assets/grassland_tiles.flare_v0.15_tilesetdef.txt

Outputs (this folder, or ``--out``):
    asset_catalog.json   catalog (ARCHITECTURE.md 6.1), ids contiguous from 0
    pack.json            pack manifest, including the excluded sections
    contact_sheet.png    every included tile, grouped by category, labeled
                         with id and name, with a dot at its anchor

The Flare definition is the ground truth: ``tile=<id>,<x>,<y>,<w>,<h>,<ox>,<oy>``
gives the sprite rectangle and its foot point (our ``anchor``). The section
table below is the answer key for categories. Deterministic: running it again
gives identical files.

Run from ``backend/``:  python asset_packs/grassland_full/build_pack.py

License: the Flare art and definition are CC-BY-SA 3.0 (Clint Bellanger and
Flare contributors), so the generated catalog and contact sheet are too.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PACK_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACK_DIR.parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from pipeline.ingestion.flare import parse_flare_definition  # noqa: E402
SPRITESHEET = "game-assets/grassland_tiles.png"
DEFINITION = "game-assets/grassland_tiles.flare_v0.15_tilesetdef.txt"

# Section slug -> (category, walkable, material, tags). Answer key.
INCLUDED: dict[str, tuple[str, bool, str, list[str]]] = {
    "grass_tiles":        ("floor",      True,  "grass", []),
    "old_stonework_path": ("floor",      True,  "stone", []),
    "cliffs":             ("wall",       False, "rock",  ["autotile_required"]),
    "town_objects":       ("obstacle",   False, "wood",  ["prop"]),
    "shrubs_and_grass_tufts": ("decoration", True, "plant", ["prop"]),
    "rocks":              ("obstacle",   False, "rock",  ["prop"]),
    "tall_town_objects":  ("obstacle",   False, "wood",  ["prop", "tall"]),
    "water_tiles":        ("water",      False, "water", ["autotile_required"]),
    "blue_trees":         ("obstacle",   False, "plant", ["tree", "tall"]),
    "dead_trees":         ("obstacle",   False, "plant", ["tree", "tall"]),
    "tall_trees":         ("obstacle",   False, "plant", ["tree", "tall"]),
    "fluffy_trees":       ("obstacle",   False, "plant", ["tree", "tall"]),
}

# Section slug -> reason it is left out.
EXCLUDED: dict[str, str] = {
    "tents": "multi-tile assembly",
    "indicators": "editor markers",
    "riverbanks": "needs autotile rules",
    "wood_bridge_wharf": "needs autotile rules",
    "buildings": "multi-tile assembly",
    "broken_tower": "multi-tile assembly",
    "cave_tileset_entrances": "multi-tile assembly",
    "temple_entrance": "multi-tile assembly",
}

ENTITIES = [
    {"type": "PlayerSpawn", "name": "Player Spawn", "category": "player", "width": 64, "height": 32},
    {"type": "Zombie", "name": "Zombie", "category": "enemy", "width": 64, "height": 64},
    {"type": "ExitTrigger", "name": "Exit Trigger", "category": "trigger", "width": 64, "height": 32},
]

CATEGORY_ORDER = ["floor", "wall", "water", "obstacle", "decoration"]

def build(out_dir: Path) -> None:
    flare = parse_flare_definition(REPO_ROOT / DEFINITION)
    sheet = Image.open(REPO_ROOT / SPRITESHEET).convert("RGBA")
    alpha = np.array(sheet)[:, :, 3]

    unknown = {t.section for t in flare} - INCLUDED.keys() - EXCLUDED.keys()
    if unknown:
        raise ValueError(f"sections missing from the answer key: {sorted(unknown)}")

    tiles, empty, per_section = [], [], {}
    for t in flare:
        if not alpha[t.y : t.y + t.h, t.x : t.x + t.w].any():
            empty.append({"flare_id": t.flare_id, "section": t.section})
            continue
        if t.section not in INCLUDED:
            continue
        category, walkable, material, tags = INCLUDED[t.section]
        nn = per_section.get(t.section, 0)
        per_section[t.section] = nn + 1
        tile = {
            "id": len(tiles),
            "name": f"{t.section}_{nn:02d}",
            "source": SPRITESHEET,
            "category": category,
            "walkable": walkable,
            "material": material,
            "elevation": 0,
            "rect": {"x": t.x, "y": t.y, "w": t.w, "h": t.h},
            "anchor": {"x": t.anchor_x, "y": t.anchor_y},
        }
        if tags:
            tile["tags"] = list(tags)
        tile["source_ref"] = f"flare:tile={t.flare_id}"
        tiles.append(tile)

    catalog = {"tile_size": {"width": 64, "height": 32}, "tiles": tiles, "entities": ENTITIES}

    excluded_counts: dict[str, int] = {}
    for t in flare:
        if t.section in EXCLUDED:
            excluded_counts[t.section] = excluded_counts.get(t.section, 0) + 1
    pack = {
        "id": "grassland_full",
        "name": "Grassland Full",
        "description": (
            f"{len(tiles)} tiles from the Flare grassland tileset: grass and stone floors, "
            "cliffs, water, rocks, town objects, shrubs and trees."
        ),
        "spritesheets": [SPRITESHEET],
        "catalog": "asset_packs/grassland_full/asset_catalog.json",
        "tile_size": {"width": 64, "height": 32},
        "license": "CC-BY-SA 3.0",
        "credits": "Grassland tileset and Flare tileset definition by Clint Bellanger and Flare contributors.",
        "excluded_sections": [
            {"section": s, "reason": EXCLUDED[s], "tile_count": excluded_counts.get(s, 0)}
            for s in EXCLUDED
        ],
        "empty_rects": empty,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "asset_catalog.json").write_text(_catalog_json(catalog), encoding="utf-8")
    (out_dir / "pack.json").write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    _contact_sheet(tiles, sheet).save(out_dir / "contact_sheet.png")
    print(f"{len(tiles)} tiles, {len(empty)} empty rects skipped -> {out_dir}")


def _catalog_json(catalog: dict) -> str:
    """One tile per line, like the starter catalog, so diffs stay readable."""
    tile_lines = ",\n".join("    " + json.dumps(t) for t in catalog["tiles"])
    entity_lines = ",\n".join("    " + json.dumps(e) for e in catalog["entities"])
    return (
        "{\n"
        f'  "tile_size": {json.dumps(catalog["tile_size"])},\n'
        f'  "tiles": [\n{tile_lines}\n  ],\n'
        f'  "entities": [\n{entity_lines}\n  ]\n'
        "}\n"
    )


def _contact_sheet(tiles: list[dict], sheet: Image.Image) -> Image.Image:
    """Tiles grouped by category, at their size, with id/name labels and anchor dots."""
    font = ImageFont.load_default()
    pad, label_h, max_w = 8, 24, 1400
    rows: list[tuple[str, list[dict]]] = []
    for category in CATEGORY_ORDER:
        group = [t for t in tiles if t["category"] == category]
        if group:
            rows.append((category, group))

    # Lay out: a heading per category, then tiles left to right, wrapping.
    placements, headings, y = [], [], pad
    for category, group in rows:
        headings.append((category, y))
        y += 22
        x, row_h = pad, 0
        for t in group:
            label_w = int(font.getlength(f'{t["id"]} {t["name"]}'))
            cell_w = max(t["rect"]["w"], label_w) + pad
            if x + cell_w > max_w:
                x, y = pad, y + row_h + label_h + pad
                row_h = 0
            placements.append((t, x, y))
            x += cell_w
            row_h = max(row_h, t["rect"]["h"])
        y += row_h + label_h + 2 * pad

    image = Image.new("RGBA", (max_w, y), (30, 32, 38, 255))
    draw = ImageDraw.Draw(image)
    for category, hy in headings:
        draw.text((pad, hy), category.upper(), fill=(255, 210, 90, 255), font=font)
    for t, x, y0 in placements:
        r = t["rect"]
        sprite = sheet.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))
        draw.rectangle((x - 1, y0 - 1, x + r["w"], y0 + r["h"]), outline=(70, 74, 84, 255))
        image.alpha_composite(sprite, (x, y0))
        ax, ay = x + t["anchor"]["x"], y0 + t["anchor"]["y"]
        draw.ellipse((ax - 2, ay - 2, ax + 2, ay + 2), fill=(255, 40, 200, 255))
        draw.text((x, y0 + r["h"] + 2), f'{t["id"]} {t["name"]}', fill=(220, 220, 220, 255), font=font)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", type=Path, default=PACK_DIR, help="output folder")
    build(parser.parse_args().out)


if __name__ == "__main__":
    main()
