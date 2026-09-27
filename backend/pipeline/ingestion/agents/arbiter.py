"""
Conflict arbiter (Asset Harmonizer, ARCHITECTURE.md 3.3). Called only for
chips whose merged agent outputs contradict each other (deterministic rules in
``harmonizer.py``): one batched call per up to 32 conflicting chips, with their
contact sheet and all agent outputs. Returns the final fields and a reason.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from pipeline.ingestion.agents.base import STANDARD, AgentSpec
from pipeline.ingestion.agents.boundary import ChipKind
from pipeline.ingestion.agents.classification import Category
from pipeline.ingestion.agents.collision import HeightClass

REASON_CHARS = 120


class ArbitrationRecord(BaseModel):
    chip: int
    category: Category
    walkable: bool
    blocks_movement: bool
    height_class: HeightClass
    kind: ChipKind
    reason: str = Field(max_length=REASON_CHARS, description="One line: why these final values")

    @field_validator("reason", mode="before")
    @classmethod
    def _cut(cls, value: object) -> object:
        return value[:REASON_CHARS] if isinstance(value, str) else value


class ArbitrationBatch(BaseModel):
    records: list[ArbitrationRecord]


SYSTEM = f"""You are the conflict arbiter of a spritesheet ingestion pipeline. Several agents analyzed
each chip; their answers contradict each other for the chips listed. Look at the chip and decide the
final values.
{STANDARD}

Rules the final values must follow:
- wall and obstacle are never walkable.
- a floor does not block movement, and its kind is floor_tile.
- a tall sprite that does not block movement is not a decoration (use obstacle, or change the height).
Categories: floor, wall, obstacle, decoration, water, hazard. Kinds: floor_tile, single_object,
multi_tile_part, fragment, noise. Height classes: flat, low, tall.

Example: a chip classified as wall but walkable, which shows a tall cliff -> wall, walkable false,
blocks_movement true, tall, single_object, "a cliff face blocks movement"."""

ARBITER = AgentSpec(
    name="arbiter",
    batch_model=ArbitrationBatch,
    system=SYSTEM,
    instruction="Resolve the conflicts of every chip listed. The agent outputs of each chip follow.",
    fields=("category", "walkable", "blocks_movement", "height_class", "kind"),
)
