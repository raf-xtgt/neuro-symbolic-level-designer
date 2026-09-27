"""
Smoke test against the real model.

Run from ``backend/``:
    python -m pipeline.llm.smoke
    python -m pipeline.llm.smoke --topology "graveyard with a cabin and a boss arena" --record

Call 1 asks a tiny ``Ping`` question. Call 2 (``--topology``) generates one
``RoomTopologyGraph``. ``--record`` saves both responses as replay fixtures
in ``tests/llm_fixtures/``. Prints the provider, model, and location only:
never the project id or the credentials path. Exit code 1 on failure.
"""
from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from pipeline.llm.base import LLMError, LLMProvider, LLMResult
from pipeline.llm.config import load_config
from pipeline.llm.factory import get_provider
from pipeline.planning.models import RoomTopologyGraph


class Ping(BaseModel):
    answer: int
    word: str


PING_SYSTEM = "Answer briefly."
PING_PROMPT = "What is 2 + 3? Give one word that describes grass."

TOPOLOGY_SYSTEM = (
    "You are the spatial topology planner of an isometric 2D level generator. "
    "Design the room graph of one level for the user's prompt: 3 to 6 rooms, exactly one room with "
    "purpose 'entrance', unique room ids, and corridors that connect every room, using only room ids "
    "you defined. style_distribution lists 2 to 5 distinct tile groups with weights from 0 to 1 that "
    "sum to 1."
)


def _report(label: str, result: LLMResult) -> None:
    print(f"\n== {label}")
    print(result.value.model_dump_json(indent=2))
    print(
        f"tokens: input {result.input_tokens}, output {result.output_tokens}; "
        f"latency {result.latency_ms} ms; attempts {result.attempts}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM smoke test against the real model")
    parser.add_argument("--topology", metavar="PROMPT", help="also generate a RoomTopologyGraph for PROMPT")
    parser.add_argument("--record", action="store_true", help="save the responses as replay fixtures")
    args = parser.parse_args(argv)

    try:
        config = load_config(mode="record" if args.record else "live")
        print(f"provider: {config.provider}, model: {config.model}, location: {config.location}", flush=True)
        provider: LLMProvider = get_provider(config)

        _report("Ping", provider.generate_structured(Ping, system=PING_SYSTEM, prompt=PING_PROMPT))
        if args.topology:
            _report(
                "RoomTopologyGraph",
                provider.generate_structured(RoomTopologyGraph, system=TOPOLOGY_SYSTEM, prompt=args.topology),
            )
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.record:
        print("\nfixtures saved to tests/llm_fixtures/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
