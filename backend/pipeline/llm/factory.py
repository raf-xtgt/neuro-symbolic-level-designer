"""``get_provider()``: the configured provider for the configured ``LLM_MODE``."""
from __future__ import annotations

from pipeline.llm.base import LLMProvider
from pipeline.llm.config import LLMConfig, load_config
from pipeline.llm.recording import RecordingProvider


def get_provider(config: LLMConfig | None = None) -> LLMProvider:
    config = config or load_config()
    if config.mode == "replay":
        return RecordingProvider(None, "replay", model=config.model)

    from pipeline.llm.gemini import GeminiProvider  # config.provider is "gemini"

    provider = GeminiProvider(config)
    if config.mode == "record":
        return RecordingProvider(provider, "record")
    return provider
