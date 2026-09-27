"""
Provider interface for the pipeline agents: structured output as validated
Pydantic objects, never raw text.

Error messages are safe to show in a job status: they name settings and the
model, never setting values, credentials, or the project id.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

log = logging.getLogger("pipeline.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class. The message is safe to show to the user."""


class LLMConfigError(LLMError):
    """A setting is missing or invalid. Names the variable, never its value."""


class LLMOutputError(LLMError):
    """The model output does not match the schema, even after a repair attempt."""


class LLMUnavailableError(LLMError):
    """The model cannot be reached: network, auth, quota, or model not found."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int  # billed output: response plus thinking tokens
    latency_ms: int
    attempts: int  # API calls made (retries and the repair included); 0 = replayed


class LLMProvider(Protocol):
    name: str
    model: str

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
        """
        Returns a validated ``schema`` instance, or raises an ``LLMError``.

        ``thinking_level`` (minimal, low, medium, high) or ``thinking_budget``
        (tokens) override the provider's configured thinking setting.
        """
        ...


def log_call(provider: str, schema: type[BaseModel], result: LLMResult, prompt: str) -> None:
    """One INFO line per call; the prompt only at DEBUG, truncated."""
    log.info(
        "llm call provider=%s model=%s schema=%s attempts=%d input_tokens=%d output_tokens=%d latency_ms=%d",
        provider, result.model, schema.__name__, result.attempts,
        result.input_tokens, result.output_tokens, result.latency_ms,
    )
    log.debug("llm prompt schema=%s prompt=%r", schema.__name__, prompt[:200])
