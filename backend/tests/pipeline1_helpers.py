"""
Test helpers for Pipeline 1: synthetic spritesheets and a scripted vision
provider. The agents run in parallel threads, so a queue-based fake would be
racy; ``ScriptedProvider`` answers every chip number in the prompt with
records from per-schema rules instead.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import BaseModel

from pipeline.ingestion.agents.arbiter import ArbitrationBatch, ArbitrationRecord
from pipeline.ingestion.agents.boundary import BoundaryBatch, BoundaryRecord
from pipeline.ingestion.agents.classification import ClassificationBatch, ClassificationRecord
from pipeline.ingestion.agents.collision import CollisionBatch, CollisionRecord
from pipeline.ingestion.agents.entity import EntityBatch, EntityRecord
from pipeline.ingestion.preprocess import diamond_template
from pipeline.llm.base import LLMResult

CHIP_LINE = re.compile(r"^chip (\d+): (\d+) x (\d+) px(.*)$", re.MULTILINE)


class Chip:
    """What a rule sees about one chip (from the prompt's chip list)."""

    def __init__(self, number: int, w: int, h: int, rest: str):
        self.number, self.w, self.h = number, w, h
        self.diamond = "base diamond" in rest


def default_rules(characters: bool = False) -> dict[type, Callable[[Chip], BaseModel]]:
    """Floors for diamonds, obstacles (trees) for everything else; or all characters."""
    return {
        BoundaryBatch: lambda c: BoundaryRecord(
            chip=c.number, kind="floor_tile" if c.diamond else "single_object", anchor_ok=True, anchor_hint="keep"),
        ClassificationBatch: lambda c: ClassificationRecord(
            chip=c.number, category="floor" if c.diamond else "obstacle", walkable=c.diamond,
            material="grass" if c.diamond else "plant", family="grass" if c.diamond else "tree_pine",
            connector=False, description="grass floor" if c.diamond else "a pine tree"),
        CollisionBatch: lambda c: CollisionRecord(
            chip=c.number, blocks_movement=not c.diamond, blocks_projectiles=not c.diamond,
            height_class="flat" if c.diamond else "tall"),
        EntityBatch: lambda c: EntityRecord(
            chip=c.number, is_character=characters, is_interactive=False, is_editor_marker=False),
        ArbitrationBatch: lambda c: ArbitrationRecord(
            chip=c.number, category="obstacle", walkable=False, blocks_movement=True, height_class="tall",
            kind="single_object", reason="scripted"),
    }


class ScriptedProvider:
    name = "scripted"
    model = "scripted-model"

    def __init__(self, rules: dict[type, Callable[[Chip], BaseModel]] | None = None,
                 drop_first: dict[type, set[int]] | None = None):
        """``drop_first``: chip numbers left out of the first answer per schema (repair path)."""
        self.rules = rules or default_rules()
        self.drop_first = {k: set(v) for k, v in (drop_first or {}).items()}
        self.calls: list[tuple[type, str]] = []
        self._lock = threading.Lock()

    def generate_structured(self, schema, *, system, prompt, images=None, temperature=0.2,
                            max_output_tokens=None, timeout_s=60, thinking_level=None, thinking_budget=None):
        with self._lock:
            self.calls.append((schema, prompt))
            drop = self.drop_first.pop(schema, set())
        listed = prompt.split("\n\n")[1] if "\n\n" in prompt else prompt
        chips = [Chip(int(n), int(w), int(h), rest) for n, w, h, rest in CHIP_LINE.findall(listed)]
        records = [self.rules[schema](c) for c in chips if c.number not in drop]
        value = schema(records=records)
        return LLMResult(value, value.model_dump_json(), self.model, 100, 50, 1, 1)

    def calls_for(self, schema) -> list[str]:
        return [p for s, p in self.calls if s is schema]


class FailingProvider:
    """Any call is a test failure (cache hits and legacy skips must not call the model)."""

    name = model = "failing"

    def generate_structured(self, *args, **kwargs):
        raise AssertionError("the LLM must not be called")


# ---------------------------------------------------------------------------
# Synthetic sheets
# ---------------------------------------------------------------------------

def diamond(w: int, h: int, color=(60, 140, 60, 255)) -> np.ndarray:
    tile = np.zeros((h, w, 4), dtype=np.uint8)
    tile[diamond_template(w, h)] = color
    return tile


def tree(w: int = 48, h: int = 96) -> np.ndarray:
    """A crown on a 6 px trunk; the trunk bottom is centered."""
    sprite = np.zeros((h, w, 4), dtype=np.uint8)
    sprite[: h - 30, 2: w - 2] = (30, 110, 40, 255)
    sprite[h - 30:, w // 2 - 3: w // 2 + 3] = (90, 60, 30, 255)
    return sprite


def paste(sheet: np.ndarray, sprite: np.ndarray, x: int, y: int) -> None:
    h, w = sprite.shape[:2]
    sheet[y:y + h, x:x + w] = sprite


def floor_sheet(path: Path, base: int = 64, with_tree: bool = True) -> Path:
    """4 diamonds (one repeated), a tree, and an 8 x 4 speck of noise, 16 px gutters."""
    h = base // 2
    sheet = np.zeros((h + 16 + 120, 6 * (base + 16), 4), dtype=np.uint8)
    colors = [(60, 140, 60, 255), (70, 150, 60, 255), (80, 160, 70, 255), (60, 140, 60, 255)]
    for i, color in enumerate(colors):  # the 4th repeats the 1st: a duplicate
        paste(sheet, diamond(base, h, color), 8 + i * (base + 16), 8)
    if with_tree:
        paste(sheet, tree(), 8, h + 16)
    sheet[h + 20: h + 24, 300:308] = (255, 255, 255, 255)  # 8 x 4 px: passes the slicer, then noise
    Image.fromarray(sheet, "RGBA").save(path)
    return path


def character_sheet(path: Path) -> Path:
    """8 small figures (not diamonds)."""
    sheet = np.zeros((80, 8 * 40, 4), dtype=np.uint8)
    for i in range(8):
        sheet[10:70, i * 40 + 12: i * 40 + 28] = (200, 150, 100 + i * 10, 255)
        sheet[10:22, i * 40 + 14: i * 40 + 26] = (240, 200, 160, 255)
    Image.fromarray(sheet, "RGBA").save(path)
    return path
