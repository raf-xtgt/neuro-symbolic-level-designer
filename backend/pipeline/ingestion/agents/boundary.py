"""
Tile Boundary Agent (ARCHITECTURE.md 3.2.1), hybrid. The rectangle, the
anchor estimate and the footprint are deterministic (``preprocess.py``); the
agent says what kind of chip it is and whether the marked anchor is plausible.
If not, its ``anchor_hint`` is converted deterministically by the harmonizer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pipeline.ingestion.agents.base import STANDARD, AgentSpec

ChipKind = Literal["floor_tile", "single_object", "multi_tile_part", "fragment", "noise"]
AnchorHint = Literal["keep", "bottom_center", "diamond_center", "left_edge", "right_edge"]


class BoundaryRecord(BaseModel):
    chip: int
    kind: ChipKind
    anchor_ok: bool = Field(description="Is the magenta dot a plausible foot point?")
    anchor_hint: AnchorHint = Field(description="Where the anchor should be if anchor_ok is false; else keep")


class BoundaryBatch(BaseModel):
    records: list[BoundaryRecord]


SYSTEM = f"""You are the Tile Boundary Agent of a spritesheet ingestion pipeline.
{STANDARD}

For every chip decide:
- kind:
  floor_tile: a flat ground tile (a diamond, possibly with a thin side), for example grass, stone, water.
  single_object: one complete sprite that stands on one base (tree, rock, crate, wall piece, cliff piece).
  multi_tile_part: a piece of a larger assembly that only makes sense with other pieces (part of a
    building, a tent, a big structure split into several chips).
  fragment: a cut-off or incomplete part of a sprite (half a tree, a stray corner).
  noise: specks, lines, text, or nothing recognizable.
- anchor_ok: true if the magenta dot is where the sprite touches the ground (the center of its base).
- anchor_hint: "keep" if anchor_ok is true. Otherwise where the foot point is: bottom_center (the base
  is centered at the bottom of the sprite), diamond_center (the whole chip is one flat diamond),
  left_edge or right_edge (the base is at the bottom left or right of the chip).

Examples:
- a 64 x 32 grass diamond with the dot in its middle: floor_tile, anchor_ok true, keep.
- a 128 x 224 tree with the dot at the trunk bottom: single_object, anchor_ok true, keep.
- the left third of a house with windows cut at the chip edge: multi_tile_part, anchor_ok false,
  bottom_center."""

BOUNDARY = AgentSpec(
    name="boundary_agent",
    batch_model=BoundaryBatch,
    system=SYSTEM,
    instruction="Classify the kind of every chip and check its anchor dot.",
    fields=("kind", "anchor_ok", "anchor_hint"),
)
