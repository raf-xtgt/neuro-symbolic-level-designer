"""
Shared runner for the batch agents: one vision call per contact sheet batch,
and a completeness check. The answer must hold exactly one record per chip
number of the batch; missing, extra or repeated numbers trigger one repair
call that lists the problems. Chips still missing after the repair are
returned as ``missing`` (the harmonizer excludes them with a reason).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from pydantic import BaseModel

from pipeline.ingestion.contact_sheet import Batch
from pipeline.llm.base import LLMProvider
from pipeline.llm.usage import UsageTracker

TEMPERATURE = 0.1
MAX_OUTPUT_TOKENS = 16384
TIMEOUT_S = 180

STANDARD = """The sprites come from isometric 2D game spritesheets. The standard projection is 2:1 isometric
with a 64 x 32 px base diamond: a floor tile is a 64 x 32 diamond; taller sprites (walls, trees,
props) stand on a base diamond at the bottom of the sprite. The anchor (foot point) of a sprite is
the point that sits on the center of the grid cell it stands on.

The image is a contact sheet: every chip is drawn in its own cell on a grey checkerboard (the
checkerboard is transparency, not part of the sprite), labeled "#<number>" at the top left. A
magenta dot marks the anchor estimated by a deterministic algorithm. Small chips are enlarged at
most 2x, large chips are shrunk to fit."""

_lock = threading.Lock()


@dataclass(frozen=True)
class AgentSpec:
    name: str  # boundary_agent, classification_agent, ...
    batch_model: type[BaseModel]  # has ``records: list[<record with chip: int>]``
    system: str
    instruction: str
    fields: tuple[str, ...]  # the fields this agent provides


@dataclass
class AgentResult:
    records: dict[int, BaseModel]
    missing: list[int]
    repaired: bool


def _check(records: list, expected: list[int]) -> tuple[dict[int, BaseModel], list[int], list[int], list[int]]:
    by_chip: dict[int, BaseModel] = {}
    repeated, extra = [], []
    for record in records:
        if record.chip not in expected:
            extra.append(record.chip)
        elif record.chip in by_chip:
            repeated.append(record.chip)
        else:
            by_chip[record.chip] = record
    missing = [n for n in expected if n not in by_chip]
    return by_chip, missing, sorted(set(extra)), sorted(set(repeated))


def run_agent_batch(
    provider: LLMProvider,
    spec: AgentSpec,
    batch: Batch,
    usage: UsageTracker,
    thinking_level: str | None = None,
    context: str = "",
) -> AgentResult:
    """``context``: extra text after the chip list (the arbiter's agent outputs)."""
    expected = batch.numbers
    prompt = (
        f"{spec.instruction}\n\nThe contact sheet shows {len(expected)} chips. Return exactly one record for "
        f"each of these chip numbers, and no others:\n{batch.chip_list()}"
    )
    if context:
        prompt += f"\n\n{context}"

    def call(text: str):
        result = provider.generate_structured(
            spec.batch_model, system=spec.system, prompt=text, images=[batch.image],
            temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS, timeout_s=TIMEOUT_S,
            thinking_level=thinking_level,
        )
        with _lock:
            usage.add(result)
        return result.value.records

    by_chip, missing, extra, repeated = _check(call(prompt), expected)
    if not (missing or extra or repeated):
        return AgentResult(by_chip, [], False)

    problems = []
    if missing:
        problems.append(f"missing chips: {', '.join(map(str, missing))}")
    if extra:
        problems.append(f"chips that are not in this contact sheet: {', '.join(map(str, extra))}")
    if repeated:
        problems.append(f"chips with more than one record: {', '.join(map(str, repeated))}")
    repair = (
        f"{prompt}\n\nYour previous answer was incomplete ({'; '.join(problems)}). Answer again with exactly one "
        f"record for every chip number listed above."
    )
    again, still_missing, _, _ = _check(call(repair), expected)
    merged = {**by_chip, **again}
    return AgentResult(merged, [n for n in expected if n not in merged], True)
