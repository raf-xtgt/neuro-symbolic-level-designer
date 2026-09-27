"""``UsageTracker``: sums LLM calls and tokens, for a job's summary."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from pipeline.llm.base import LLMResult


@dataclass
class UsageTracker:
    calls: int = 0
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    def add(self, result: LLMResult) -> LLMResult:
        """Adds one call; returns ``result`` so it can wrap a call inline."""
        self.calls += 1
        self.attempts += result.attempts
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.latency_ms += result.latency_ms
        return result

    def as_dict(self) -> dict[str, int]:
        return asdict(self)
