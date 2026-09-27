"""
Asset Harmonizer (Pipeline 1, ARCHITECTURE.md 3.3): code first, LLM only for
conflicts.

1. Deterministic merge of the deterministic chip geometry and the 4 agent
   records into one record per chip. Legacy tileset properties win over the
   agents (``fields_from_tileset``).
2. Exclusions (with reasons): noise, fragment, multi_tile_part (no multi-tile
   assembly yet), character, editor_marker, analysis_incomplete, and
   not_a_floor_diamond: a chip classified as floor that is not a full base
   diamond (ASSET_SPEC: the diamond fills a floor sprite) is a piece of a
   larger structure (a wharf, stairs) and would show as a broken tile.
3. Conflict rules (deterministic detection): wall/obstacle that is walkable;
   floor that blocks movement; floor whose kind is not floor_tile; tall
   decoration that does not block movement. Only these chips go to the LLM
   arbiter (one call per up to 32 chips). Whatever the arbiter leaves
   inconsistent is fixed by the rule itself (``resolved_by: rule``).
4. Family normalization (lowercase snake_case, no digits, singular).
   Structure tags (``structure_role``): ``structure_part`` for slices of a
   multi-tile assembly (the Boundary Agent says ``multi_tile_part``, a
   building family one tile wide, or a ``*_wall`` piece one tile wide);
   ``structure`` plus ``footprint_<n>`` for a whole building in one chip
   (building family, footprint wider than 1 tile). Pipeline 2 never places a
   ``structure_part`` and places a ``structure`` at most once per room.
5. Catalog tiles (ARCHITECTURE.md 6.1) in a normalized atlas: every kept chip
   is copied into a cell whose width is a multiple of 64 px and height a
   multiple of 32 px, with the anchor at the bottom center of the base
   diamond (``game-assets/ASSET_SPEC.md``). Tiles of the same cell size share
   one tileset in Pipeline 3, and no neighbor pixels bleed in.
6. Dark outliers (deterministic, from the pixels): a chip where more than
   ``VOID_SHARE`` of the opaque pixels are near black (luminance below
   ``VOID_LUMINANCE``) is excluded as ``void`` (holes, pits, dark cave
   pieces). Inside each floor family, a tile whose median opaque luminance is
   more than ``FLOOR_OUTLIER_DROP`` below the family median is tagged
   ``floor_outlier`` (kept in the catalog, left out of the Pipeline 2 digest).
7. Quality gate: at least one walkable floor family with 2 or more tiles,
   else ``ingestion_no_floor``.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from pipeline.errors import StageError
from pipeline.ingestion.preprocess import BASE_H, BASE_W, ChipInfo

EXCLUDED_KINDS = ("noise", "fragment", "multi_tile_part")
CATEGORIES = ("floor", "wall", "ramp", "obstacle", "decoration", "water", "hazard")
# Tags the Pipeline 2 digest treats as generic; a family must not be one of them.
_GENERIC_FAMILY_RENAMES = {"tree": "tree_plain", "prop": "prop_item", "tall": "tall_object"}
# Words of a family (or description) that name a building or part of one.
BUILDING_WORDS = {"house", "cabin", "building", "hut", "shack", "tent", "tower", "roof"}
ATLAS_WIDTH = 2048
ATLAS_NAME = "catalog_atlas.png"
# Packs draw opaque black shadows: trees and tall grass reach 48% of pixels
# below 16 (the grassland sheet), black void pieces 65% and more.
VOID_LUMINANCE = 16  # 0..255
VOID_SHARE = 0.6  # of the opaque pixels
FLOOR_OUTLIER_DROP = 0.35  # darker than the family median by more than this share
OPAQUE_ALPHA = 128


@dataclass
class ChipRecord:
    chip: ChipInfo
    boundary: dict | None
    classification: dict | None
    collision: dict | None
    entity: dict | None
    fields_from_tileset: list[str] = field(default_factory=list)
    # Final values
    kind: str = ""
    category: str = ""
    walkable: bool = False
    material: str = ""
    family: str = ""
    connector: bool = False
    description: str = ""
    blocks_movement: bool = False
    blocks_projectiles: bool = False
    height_class: str = "flat"
    interactive: bool = False
    anchor: tuple[int, int] = (0, 0)
    anchor_source: str = "estimate"
    excluded: str | None = None
    conflicts: list[str] = field(default_factory=list)
    resolution: dict | None = None
    catalog_id: int | None = None
    floor_outlier: bool = False


def normalize_family(name: str, fallback: str = "tile") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", name.lower())
    text = re.sub(r"\d+", "", text)
    words = [w for w in text.split("_") if w]
    if not words:
        return fallback
    last = words[-1]
    if len(last) > 3 and last.endswith("ies"):
        last = last[:-3] + "y"
    elif len(last) > 3 and last.endswith(("ches", "shes", "sses", "xes")):
        last = last[:-2]
    elif len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
        last = last[:-1]
    words[-1] = last
    family = "_".join(words)
    return _GENERIC_FAMILY_RENAMES.get(family, family)


def anchor_from_hint(hint: str, w: int, h: int) -> tuple[int, int]:
    """Deterministic anchor for the boundary agent's hint (chip pixels)."""
    return {
        "bottom_center": (w // 2, h - BASE_H // 2),
        "diamond_center": (w // 2, h // 2),
        "left_edge": (min(BASE_W // 2, w // 2), h - BASE_H // 2),
        "right_edge": (max(w - BASE_W // 2, w // 2), h - BASE_H // 2),
    }.get(hint, (w // 2, h - BASE_H // 2))


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _dump(record: BaseModel | None) -> dict | None:
    return None if record is None else record.model_dump(exclude={"chip"})


def merge(chips: list[ChipInfo], results: dict[str, dict[int, BaseModel]]) -> list[ChipRecord]:
    """``results``: agent name -> chip number -> record."""
    records = []
    for chip in chips:
        rec = ChipRecord(
            chip=chip,
            boundary=_dump(results.get("boundary_agent", {}).get(chip.number)),
            classification=_dump(results.get("classification_agent", {}).get(chip.number)),
            collision=_dump(results.get("collision_agent", {}).get(chip.number)),
            entity=_dump(results.get("entity_agent", {}).get(chip.number)),
        )
        _apply(rec)
        records.append(rec)
    return records


def _apply(rec: ChipRecord) -> None:
    b, c, k, e = rec.boundary, rec.classification, rec.collision, rec.entity
    truth = rec.chip.legacy
    rec.fields_from_tileset = sorted(f for f in ("category", "walkable", "material", "family", "tags") if f in truth)

    if c is None and not {"category", "walkable"} <= truth.keys():
        rec.excluded = "analysis_incomplete"
        return
    c = c or {}
    rec.category = truth.get("category") or c.get("category", "obstacle")
    if rec.category not in CATEGORIES:
        rec.category = c.get("category", "obstacle")
    rec.walkable = truth["walkable"] if "walkable" in truth else bool(c.get("walkable", False))
    rec.material = truth.get("material") or c.get("material") or "unknown"
    rec.description = c.get("description", "")
    tags = truth.get("tags", [])
    rec.connector = ("autotile_required" in tags) if "tags" in truth else bool(c.get("connector", False))
    rec.family = normalize_family(truth.get("family") or c.get("family") or rec.material, rec.category)

    if k is not None:
        rec.blocks_movement, rec.blocks_projectiles = k["blocks_movement"], k["blocks_projectiles"]
        rec.height_class = k["height_class"]
    else:
        rec.blocks_movement = not rec.walkable
        rec.height_class = "tall" if rec.chip.rect[3] > 2 * BASE_H else "flat"
    rec.interactive = bool(e and e["is_interactive"])

    legacy = bool(truth) or rec.chip.strategy == "legacy"
    if b is not None:
        rec.kind = b["kind"]
        if not b["anchor_ok"] and b["anchor_hint"] != "keep":
            rec.anchor = anchor_from_hint(b["anchor_hint"], rec.chip.rect[2], rec.chip.rect[3])
            rec.anchor_source = f"agent_hint:{b['anchor_hint']}"
    else:
        rec.kind = "floor_tile" if rec.chip.is_diamond else "single_object"
    if rec.anchor_source == "estimate":
        rec.anchor = rec.chip.anchor
    if legacy and rec.kind in EXCLUDED_KINDS:
        rec.kind = "floor_tile" if rec.category == "floor" else "single_object"

    if e and e["is_character"]:
        rec.excluded = "character"
    elif e and e["is_editor_marker"]:
        rec.excluded = "editor_marker"
    elif b is None and not legacy:
        rec.excluded = "analysis_incomplete"
    elif rec.kind in EXCLUDED_KINDS:
        rec.excluded = rec.kind
    elif rec.category == "floor" and not rec.chip.is_diamond and not legacy:
        rec.excluded = "not_a_floor_diamond"


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------

def conflicts_of(rec: ChipRecord) -> list[str]:
    """Deterministic conflict rules. Fields fixed by a legacy tileset never conflict."""
    rules = []
    from_tileset = set(rec.fields_from_tileset)
    if rec.category in ("wall", "obstacle") and rec.walkable and not {"category", "walkable"} <= from_tileset:
        rules.append("blocking_category_walkable")
    if rec.category == "floor" and rec.blocks_movement and "category" not in from_tileset:
        rules.append("floor_blocks_movement")
    if rec.category == "floor" and rec.kind != "floor_tile" and "category" not in from_tileset:
        rules.append("floor_not_floor_tile")
    if rec.category == "decoration" and rec.height_class == "tall" and not rec.blocks_movement:
        rules.append("tall_decoration_not_blocking")
    return rules


def detect_conflicts(records: list[ChipRecord]) -> list[ChipRecord]:
    found = []
    for rec in records:
        if rec.excluded:
            continue
        rec.conflicts = conflicts_of(rec)
        if rec.conflicts:
            found.append(rec)
    return found


def arbitration_context(conflicting: list[ChipRecord]) -> str:
    lines = ["Agent outputs and the rules each chip breaks:"]
    for rec in conflicting:
        lines.append(
            f"chip {rec.chip.number}: breaks {', '.join(rec.conflicts)}; boundary {rec.boundary}; "
            f"classification {rec.classification}; collision {rec.collision}"
        )
    return "\n".join(lines)


def apply_arbitration(rec: ChipRecord, decision: dict | None) -> None:
    """Final values from the arbiter (tileset fields stay), then the rules as the last word."""
    from_tileset = set(rec.fields_from_tileset)
    if decision is not None:
        if "category" not in from_tileset:
            rec.category = decision["category"]
        if "walkable" not in from_tileset:
            rec.walkable = decision["walkable"]
        rec.blocks_movement = decision["blocks_movement"]
        rec.height_class = decision["height_class"]
        rec.kind = decision["kind"]
        rec.resolution = {"resolved_by": "arbiter", "reason": decision.get("reason", "")}
        if rec.kind in EXCLUDED_KINDS:
            rec.excluded = rec.kind
            return
    remaining = conflicts_of(rec)
    if remaining:
        _enforce_rules(rec)
        by = "arbiter+rule" if decision is not None else "rule"
        rec.resolution = {"resolved_by": by, "reason": f"rules enforced: {', '.join(remaining)}"}
    elif rec.resolution is None:
        rec.resolution = {"resolved_by": "rule", "reason": "no conflict left"}


def _enforce_rules(rec: ChipRecord) -> None:
    if rec.category in ("wall", "obstacle"):
        rec.walkable = False
        rec.blocks_movement = True
    if rec.category == "floor":
        rec.blocks_movement = False
        rec.kind = "floor_tile"
    if rec.category == "decoration" and rec.height_class == "tall" and not rec.blocks_movement:
        rec.height_class = "low"


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

def structure_role(rec: ChipRecord) -> str | None:
    """``structure`` (a whole building), ``structure_part`` (a slice of one), or None."""
    if rec.category in ("floor", "water", "ramp"):
        return None
    if rec.boundary and rec.boundary.get("kind") == "multi_tile_part":
        return "structure_part"
    words = set(rec.family.split("_")) | set(re.findall(r"[a-z]+", rec.description.lower()))
    if BUILDING_WORDS & words:
        return "structure" if rec.chip.footprint > 1 else "structure_part"
    if rec.family.endswith("_wall") and rec.chip.footprint <= 1:
        return "structure_part"
    return None


# ---------------------------------------------------------------------------
# Dark outliers
# ---------------------------------------------------------------------------

def _luminance(sprite: Image.Image) -> np.ndarray:
    """Luminance (0..255) of the opaque pixels of ``sprite``."""
    rgba = np.asarray(sprite.convert("RGBA"), dtype=np.float32)
    opaque = rgba[..., 3] >= OPAQUE_ALPHA
    return (rgba[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32))[opaque]


def mark_dark(records: list[ChipRecord], sheets: dict[int, Image.Image]) -> None:
    """Excludes near-black sprites as ``void``; flags dark floor variants as ``floor_outlier``."""
    floor_luma: dict[str, list[tuple[ChipRecord, float]]] = {}
    for rec in records:
        if rec.excluded:
            continue
        luma = _luminance(rec.chip.image(sheets[rec.chip.sheet]))
        if not luma.size:
            continue
        if float(np.mean(luma < VOID_LUMINANCE)) > VOID_SHARE:
            rec.excluded = "void"
        elif rec.category == "floor":
            floor_luma.setdefault(rec.family, []).append((rec, float(np.median(luma))))
    for members in floor_luma.values():
        median = statistics.median(v for _, v in members)
        for rec, value in members:
            rec.floor_outlier = value < (1 - FLOOR_OUTLIER_DROP) * median


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def _cell(rec: ChipRecord) -> tuple[int, int, int, int]:
    """Normalized cell (width, height, anchor x, anchor y) for a chip."""
    _, _, w, h = rec.chip.rect
    ax, ay = rec.anchor
    if rec.chip.is_diamond and (w, h) == (BASE_W, BASE_H) and (ax, ay) == (BASE_W // 2, BASE_H // 2):
        return BASE_W, BASE_H, BASE_W // 2, BASE_H // 2
    half = max(ax, w - ax, 1)
    cw = max(BASE_W, math.ceil(2 * half / BASE_W) * BASE_W)
    below = max(BASE_H // 2, math.ceil(max(h - ay, 0) / (BASE_H // 2)) * (BASE_H // 2))
    ch = max(BASE_H, math.ceil((max(ay, 0) + below) / BASE_H) * BASE_H)
    return cw, ch, cw // 2, ch - below


def build_catalog(
    records: list[ChipRecord], sheets: dict[int, Image.Image], sheet_names: dict[int, str], atlas_source: str,
) -> tuple[dict, Image.Image]:
    """Catalog dict (6.1) and the normalized atlas image."""
    mark_dark(records, sheets)
    kept = [r for r in records if not r.excluded]
    order = {c: i for i, c in enumerate(("floor", "water", "wall", "obstacle", "decoration", "hazard", "ramp"))}
    kept.sort(key=lambda r: (order.get(r.category, 9), r.family, r.chip.number))

    cells = [_cell(r) for r in kept]
    # Shelf packing, cells of one size together.
    placements, x, y, shelf = [], 0, 0, 0
    for rec, (cw, ch, ax, ay) in sorted(zip(kept, cells), key=lambda rc: (rc[1][1], rc[1][0])):
        if x + cw > ATLAS_WIDTH:
            x, y, shelf = 0, y + shelf, 0
        placements.append((rec, (cw, ch, ax, ay), (x, y)))
        x += cw
        shelf = max(shelf, ch)
    atlas = Image.new("RGBA", (ATLAS_WIDTH, max(1, y + shelf)), (0, 0, 0, 0))
    position = {id(rec): (cell, pos) for rec, cell, pos in placements}

    per_family: Counter = Counter()
    tiles = []
    for tile_id, rec in enumerate(kept):
        (cw, ch, cax, cay), (px, py) = position[id(rec)]
        ox, oy = cax - rec.anchor[0], cay - rec.anchor[1]
        sprite = rec.chip.image(sheets[rec.chip.sheet])
        atlas.alpha_composite(sprite, (px + max(ox, 0), py + max(oy, 0)), (max(-ox, 0), max(-oy, 0)))
        nn = per_family[rec.family]
        per_family[rec.family] += 1
        tags = [rec.family]
        if rec.height_class == "tall":
            tags.append("tall")
        if rec.kind == "single_object":
            tags.append("prop")
        if rec.connector:
            tags.append("autotile_required")
        if rec.interactive:
            tags.append("interactive")
        role = structure_role(rec)
        if role:
            tags.append(role)
        if role == "structure":
            tags.append(f"footprint_{rec.chip.footprint}")
        if rec.floor_outlier:
            tags.append("floor_outlier")
        tile = {
            "id": tile_id,
            "name": f"{rec.family}_{nn:02d}",
            "source": atlas_source,
            "category": rec.category,
            "walkable": rec.walkable,
            "material": rec.material,
            "elevation": 0,
            "rect": {"x": px, "y": py, "w": cw, "h": ch},
            "anchor": {"x": cax, "y": cay},
            "tags": tags,
            "source_ref": f"upload:{sheet_names[rec.chip.sheet]}#{rec.chip.number}",
        }
        if rec.description:
            tile["description"] = rec.description
        if rec.blocks_movement and rec.chip.collision_polygon:
            tile["collision_polygon"] = [{"x": px_ + ox, "y": py_ + oy} for px_, py_ in rec.chip.collision_polygon]
        rec.catalog_id = tile_id
        tiles.append(tile)

    entities = [
        {"type": "PlayerSpawn", "name": "Player Spawn", "category": "player", "width": 64, "height": 32},
        {"type": "Zombie", "name": "Zombie", "category": "enemy", "width": 64, "height": 64},
        {"type": "ExitTrigger", "name": "Exit Trigger", "category": "trigger", "width": 64, "height": 32},
    ]
    return {"tile_size": {"width": BASE_W, "height": BASE_H}, "tiles": tiles, "entities": entities}, atlas


def quality_gate(catalog: dict, records: list[ChipRecord]) -> dict:
    floors = Counter(
        next(iter(t["tags"]), "") for t in catalog["tiles"] if t["category"] == "floor" and t["walkable"]
    )
    good = {f: n for f, n in floors.items() if n >= 2}
    if good:
        return {"passed": True, "floor_families": good}
    characters = sum(1 for r in records if r.excluded == "character")
    detail = "no isometric floor tiles found (need at least 2 walkable floor tiles of one family)"
    if records and characters >= len(records) / 2:
        detail = (
            f"no isometric floor tiles found; the sheet looks like character sprites "
            f"({characters} of {len(records)} chips are characters)"
        )
    raise StageError("ingestion_no_floor", detail)


def contact_sheet(catalog: dict, atlas: Image.Image) -> Image.Image:
    """Every catalog tile grouped by category, labeled with id and name, anchor dot."""
    font = ImageFont.load_default()
    pad, label_h, max_w = 8, 14, 1400
    placements, headings, y = [], [], pad
    for category in CATEGORIES:
        group = [t for t in catalog["tiles"] if t["category"] == category]
        if not group:
            continue
        headings.append((category, y))
        y += 18
        x, row_h = pad, 0
        for t in group:
            label = f'{t["id"]} {t["name"]}'
            cw = max(t["rect"]["w"], int(font.getlength(label))) + pad
            if x + cw > max_w:
                x, y, row_h = pad, y + row_h + label_h + pad, 0
            placements.append((t, x, y))
            x += cw
            row_h = max(row_h, t["rect"]["h"])
        y += row_h + label_h + 2 * pad
    image = Image.new("RGBA", (max_w, max(y, 40)), (30, 32, 38, 255))
    draw = ImageDraw.Draw(image)
    for category, hy in headings:
        draw.text((pad, hy), category.upper(), fill=(255, 210, 90, 255), font=font)
    for t, x, y0 in placements:
        r = t["rect"]
        image.alpha_composite(atlas.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])), (x, y0))
        ax, ay = x + t["anchor"]["x"], y0 + t["anchor"]["y"]
        draw.ellipse((ax - 2, ay - 2, ax + 2, ay + 2), fill=(255, 40, 200, 255))
        draw.text((x, y0 + r["h"] + 1), f'{t["id"]} {t["name"]}', fill=(220, 220, 220, 255), font=font)
    return image
