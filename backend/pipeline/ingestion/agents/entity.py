"""
Entity and Prop Extractor Agent (ARCHITECTURE.md 3.2.4). Characters and
editor markers are excluded from the terrain catalog (1.3); interactive
props are tagged.
"""
from __future__ import annotations

from pydantic import BaseModel

from pipeline.ingestion.agents.base import STANDARD, AgentSpec


class EntityRecord(BaseModel):
    chip: int
    is_character: bool
    is_interactive: bool
    is_editor_marker: bool


class EntityBatch(BaseModel):
    records: list[EntityRecord]


SYSTEM = f"""You are the Entity and Prop Extractor Agent of a spritesheet ingestion pipeline.
{STANDARD}

For every chip return:
- is_character: a person, animal, creature, monster or enemy sprite (any pose or animation frame).
  Characters are not level terrain and are removed from the catalog.
- is_interactive: something a player would use: chest, door, gate, lever, switch, sign to read.
- is_editor_marker: an editor or debug graphic, not part of the game world: arrows, grid markers,
  selection outlines, text labels, colored test shapes.

Examples:
- a tree or a floor tile: false, false, false.
- a soldier walking to the left: true, false, false.
- a treasure chest: false, true, false.
- a small blue arrow: false, false, true."""

ENTITY = AgentSpec(
    name="entity_agent",
    batch_model=EntityBatch,
    system=SYSTEM,
    instruction="Flag characters, interactive props and editor markers.",
    fields=("is_character", "is_interactive", "is_editor_marker"),
)
