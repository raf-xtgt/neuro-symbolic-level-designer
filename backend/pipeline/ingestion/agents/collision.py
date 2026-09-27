"""
Collision and Physics Agent (ARCHITECTURE.md 3.2.3), hybrid. The collision
polygon is deterministic (OpenCV contour of the opaque base,
``preprocess.collision_polygon``); the agent returns the blocking flags and
the height class.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pipeline.ingestion.agents.base import STANDARD, AgentSpec

HeightClass = Literal["flat", "low", "tall"]


class CollisionRecord(BaseModel):
    chip: int
    blocks_movement: bool
    blocks_projectiles: bool
    height_class: HeightClass


class CollisionBatch(BaseModel):
    records: list[CollisionRecord]


SYSTEM = f"""You are the Collision and Physics Agent of a spritesheet ingestion pipeline.
{STANDARD}

For every chip return:
- blocks_movement: would a character be stopped by this object in its grid cell?
- blocks_projectiles: would it stop an arrow or a bullet (high and solid enough)?
- height_class: flat (lies on the ground: floor tiles, water, flat decorations), low (below knee to
  waist height: small rocks, bushes, crates, stumps), tall (taller than a person: trees, walls,
  cliffs, pillars, tall gravestones, signposts).

Examples:
- a grass floor diamond: false, false, flat.
- a small rock: true, false, low.
- a tall pine tree: true, true, tall."""

COLLISION = AgentSpec(
    name="collision_agent",
    batch_model=CollisionBatch,
    system=SYSTEM,
    instruction="Decide the blocking flags and the height class of every chip.",
    fields=("blocks_movement", "blocks_projectiles", "height_class"),
)
