"""
``FakeProvider`` for agent unit tests: returns queued Pydantic objects or
raises queued errors, in order, and records every call.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from pipeline.llm.base import LLMError, LLMResult, T, log_call


@dataclass(frozen=True)
class FakeCall:
    schema: type[BaseModel]
    system: str
    prompt: str
    images: list[bytes] | None
    temperature: float


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[BaseModel | Exception] | None = None, model: str = "fake-model"):
        self.model = model
        self._queue: list[BaseModel | Exception] = list(responses or [])
        self.calls: list[FakeCall] = []

    def queue(self, *responses: BaseModel | Exception) -> None:
        self._queue.extend(responses)

    def generate_structured(
        self,
        schema: type[T],
        *,
        system: str,
        prompt: str,
        images: list[bytes] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_s: float = 60,
        thinking_level: str | None = None,
        thinking_budget: int | None = None,
    ) -> LLMResult[T]:
        self.calls.append(FakeCall(schema, system, prompt, images, temperature))
        if not self._queue:
            raise LLMError(f"FakeProvider: no response queued for {schema.__name__}")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, schema):
            raise TypeError(f"FakeProvider: queued {type(item).__name__}, but {schema.__name__} was requested")
        text = item.model_dump_json()
        result = LLMResult(item, text, self.model, len(prompt) // 4, len(text) // 4, 0, 1)
        log_call(self.name, schema, result, prompt)
        return result
