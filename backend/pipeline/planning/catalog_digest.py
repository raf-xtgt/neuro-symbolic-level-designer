"""
Catalog digest (Pipeline 2): the tile groups the planner can name.

Deterministic. Works for any catalog:
  * ``floor.<material>`` for floor tiles;
  * ``<category>.<family tag>`` for obstacles and decorations (a family tag is
    any tag other than the generic ones below), with ``<category>.<material>``
    as the fallback;
  * ``structure.<family>`` for whole buildings in one sprite (tag
    ``structure``, footprint from the ``footprint_<n>`` tag): placed at most
    once per room, by name in a room's ``dressing``.
Tiles tagged ``autotile_required``, ``fence`` or ``structure_part`` are left
out of every group: there are no placement rules for them yet (cliffs, water,
fence connectors, slices of multi-tile buildings). Tiles tagged ``void`` or
``floor_outlier`` (Pipeline 1: near-black sprites, dark floor variants) are
left out too; they stay in the catalog for inspection.

The digest is the only catalog information the LLM sees.
"""
from __future__ import annotations

from dataclasses import dataclass

EXCLUDED_TAGS = {"autotile_required", "fence", "structure_part", "void", "floor_outlier"}
GENERIC_TAGS = {"prop", "tall", "tree", "autotile_required", "fence", "structure", "structure_part", "void",
                "floor_outlier"}
GROUPED_CATEGORIES = ("floor", "obstacle", "decoration")
STRUCTURE = "structure"
FOOTPRINT_TAG = "footprint_"
GROUP_ORDER = (*GROUPED_CATEGORIES, STRUCTURE)

# Plural noun phrases for the known families, for the group descriptions.
_FAMILY_NOUNS = {
    "cart": "wooden carts",
    "sack": "grain sacks",
    "logs": "stacks of firewood logs",
    "campfire": "campfire",
    "anvil": "anvil on a stump",
    "rock_small": "small rocks and pebbles",
    "rock_pillar": "tall rock pillars",
    "stump": "tree stumps",
    "signpost": "wooden signposts",
    "gravestone": "gravestones and stone crosses",
    "tree_blue": "blue-green leafy trees",
    "tree_dead": "dead, leafless trees",
    "tree_tall": "tall green pine-like trees",
    "tree_fluffy": "round, bushy green trees",
    "fern": "ferns",
    "weed": "dark weeds",
    "leafy_plant": "leafy green plants",
    "flower": "purple flowers",
    "bush": "small bushes",
    "dry_grass": "dry grass tufts",
}
_MATERIAL_NOUNS = {"grass": "grass ground", "stone": "old stonework path"}


@dataclass(frozen=True)
class TileGroup:
    id: str
    category: str
    walkable: bool
    tall: bool
    tile_ids: tuple[int, ...]
    description: str
    footprint: int = 1  # tiles along the east diagonal (structures)
    sprite_area: int = 64 * 32  # px, the largest sprite of the group

    @property
    def count(self) -> int:
        return len(self.tile_ids)

    @property
    def family(self) -> str:
        return self.id.split(".", 1)[1]

    @property
    def is_floor(self) -> bool:
        return self.category == "floor"

    @property
    def blocks(self) -> bool:
        return not self.walkable

    @property
    def is_structure(self) -> bool:
        return self.category == STRUCTURE


@dataclass(frozen=True)
class CatalogDigest:
    groups: tuple[TileGroup, ...]

    @property
    def by_id(self) -> dict[str, TileGroup]:
        return {g.id: g for g in self.groups}

    def of_category(self, category: str) -> list[TileGroup]:
        return [g for g in self.groups if g.category == category]

    @property
    def floors(self) -> list[TileGroup]:
        return self.of_category("floor")

    @property
    def has_blocking(self) -> bool:
        return any(g.blocks for g in self.groups)

    def as_text(self) -> str:
        """One line per group, for the LLM."""
        return "\n".join(f"- {g.description}" for g in self.groups)

    def as_dict(self) -> list[dict]:
        return [
            {
                "id": g.id, "category": g.category, "walkable": g.walkable, "tall": g.tall,
                "tile_ids": list(g.tile_ids), "count": g.count, "description": g.description,
                **({"footprint": g.footprint} if g.is_structure else {}),
            }
            for g in self.groups
        ]


def _family(tile: dict) -> str | None:
    families = [t for t in tile.get("tags", []) if t not in GENERIC_TAGS and not t.startswith(FOOTPRINT_TAG)]
    return families[0] if families else None


def group_id(tile: dict) -> str | None:
    """The group of ``tile``, or None when it is not placeable by the planner."""
    tags = set(tile.get("tags", []))
    if EXCLUDED_TAGS & tags:
        return None
    if STRUCTURE in tags:
        return f"{STRUCTURE}.{_family(tile) or tile.get('material', 'default')}"
    if tile["category"] not in GROUPED_CATEGORIES:
        return None
    if tile["category"] == "floor":
        return f"floor.{tile.get('material', 'default')}"
    return f"{tile['category']}.{_family(tile) or tile.get('material', 'default')}"


def build_digest(catalog: dict) -> CatalogDigest:
    members: dict[str, list[dict]] = {}
    for tile in catalog["tiles"]:
        gid = group_id(tile)
        if gid is not None:
            members.setdefault(gid, []).append(tile)

    order = {c: i for i, c in enumerate(GROUP_ORDER)}
    groups = []
    for gid in sorted(members, key=lambda g: (order[g.split(".")[0]], g)):
        tiles = members[gid]
        category = STRUCTURE if gid.startswith(f"{STRUCTURE}.") else tiles[0]["category"]
        footprint = max(_footprint(t) for t in tiles) if category == STRUCTURE else 1
        walkable = all(t["walkable"] for t in tiles)
        tall = any("tall" in t.get("tags", []) for t in tiles)
        example = next((t["description"] for t in tiles if t.get("description")), None)
        groups.append(TileGroup(
            id=gid,
            category=category,
            walkable=walkable,
            tall=tall,
            tile_ids=tuple(t["id"] for t in tiles),
            description=_describe(gid, category, len(tiles), walkable, tall, example, footprint),
            footprint=footprint,
            sprite_area=max(t.get("rect", {}).get("w", 64) * t.get("rect", {}).get("h", 32) for t in tiles),
        ))
    return CatalogDigest(tuple(groups))


def _footprint(tile: dict) -> int:
    """Footprint in tiles: the ``footprint_<n>`` tag, else the sprite width in base tiles."""
    for tag in tile.get("tags", []):
        if tag.startswith(FOOTPRINT_TAG) and tag[len(FOOTPRINT_TAG):].isdigit():
            return max(1, int(tag[len(FOOTPRINT_TAG):]))
    return max(1, tile.get("rect", {}).get("w", 64) // 64)


def _describe(
    gid: str, category: str, count: int, walkable: bool, tall: bool, example: str | None = None,
    footprint: int = 1,
) -> str:
    """``example``: a tile description from Pipeline 1, used for families not listed above."""
    family = gid.split(".", 1)[1]
    if category == "floor":
        noun = _MATERIAL_NOUNS.get(family, f"{family.replace('_', ' ')} floor")
        text = f"{gid}: {count} {noun} floor variants, walkable"
        return text if family in _MATERIAL_NOUNS or not example else f"{text} (for example: {example})"
    if category == STRUCTURE:
        text = (f"{gid}: {count} whole {family.replace('_', ' ')} building(s), blocks movement, "
                f"{footprint} tiles wide, placed at most once per room (name it in a room's dressing)")
        return f"{text}, for example: {example}" if example else text
    noun = _FAMILY_NOUNS.get(family, f"{family.replace('_', ' ')} {category}s")
    parts = [f"{gid}: {count} {noun}", "walkable" if walkable else "blocks movement"]
    if example and family not in _FAMILY_NOUNS:
        parts.append(f"for example: {example}")
    if tall:
        parts.append("tall")
    return ", ".join(parts)
