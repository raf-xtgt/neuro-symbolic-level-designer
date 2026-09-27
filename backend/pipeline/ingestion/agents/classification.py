"""Tile Classification Agent (ARCHITECTURE.md 3.2.2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from pipeline.ingestion.agents.base import STANDARD, AgentSpec

Category = Literal["floor", "wall", "obstacle", "decoration", "water", "hazard"]
DESCRIPTION_CHARS = 80


class ClassificationRecord(BaseModel):
    chip: int
    category: Category
    walkable: bool
    material: str = Field(description="One word, for example grass, stone, dirt, sand, wood, rock, plant, water")
    family: str = Field(description="Short snake_case name of the kind of thing, for example gravestone, tree_dead")
    connector: bool = Field(description="Edge, corner or transition piece that only works next to matching tiles")
    description: str = Field(max_length=DESCRIPTION_CHARS)

    @field_validator("description", mode="before")
    @classmethod
    def _cut(cls, value: object) -> object:
        return value[:DESCRIPTION_CHARS] if isinstance(value, str) else value


class ClassificationBatch(BaseModel):
    records: list[ClassificationRecord]


SYSTEM = f"""You are the Tile Classification Agent of a spritesheet ingestion pipeline.
{STANDARD}

For every chip return:
- category: floor (flat ground a character walks on), wall (cliffs, building and stone walls),
  obstacle (an object that blocks movement: tree, rock, crate, gravestone, stump, fence piece),
  decoration (small flat things a character walks over: grass tufts, flowers, small plants),
  water (water surfaces), hazard (lava, spikes, poison).
- walkable: can a character stand on or walk through this cell? Floors and decorations: usually true.
  Walls, obstacles, water: false.
- material: one lowercase word.
- family: a short snake_case name shared by all chips of the same kind of thing, singular, without
  numbers: for example grass, stone_path, cliff, water, tree_dead, tree_pine, rock_small, rock_pillar,
  gravestone, fence, bush, flower, barrel, crate, cactus. Use the same family for variants.
- connector: true for pieces that only make sense next to matching pieces: cliff edges and corners,
  riverbanks, water edges, fence segments, wall corners. A connector has an edge that must line up
  with a neighbor (a cliff lip, a shoreline, a fence end). Repeatable floor and water tiles are
  false, even when they show worn edges, patches or mixed materials (for example a stone path tile
  with grass between the stones); single objects are false.
- description: up to 80 characters, what the chip shows.

Examples:
- a 64 x 32 grass diamond: floor, walkable true, grass, family grass, connector false.
- a tall dead tree: obstacle, walkable false, plant, family tree_dead, connector false.
- a cliff corner piece: wall, walkable false, rock, family cliff, connector true."""

CLASSIFICATION = AgentSpec(
    name="classification_agent",
    batch_model=ClassificationBatch,
    system=SYSTEM,
    instruction="Classify every chip.",
    fields=("category", "walkable", "material", "family", "connector", "description"),
)
