"""
LLM configuration from ``neuro-symbolic-level-designer/.env`` and the
environment (existing environment variables win over the file).

Variables:
    GOOGLE_CLOUD_PROJECT            Vertex AI project
    GOOGLE_CLOUD_LOCATION           Vertex AI location, for example us-central1
    GOOGLE_GENAI_USE_VERTEXAI       must be true (the default) if set
    GOOGLE_APPLICATION_CREDENTIALS  service account key file; a relative path
                                    resolves from the repository root
    GOOGLE_GENAI_MODEL              model name, for example gemini-3.5-flash
    LLM_PROVIDER                    optional, only ``gemini`` (default)
    LLM_MODE                        optional: live (default), record, replay,
                                    update (replay if recorded, else record)
    LLM_THINKING_LEVEL              optional: minimal, low, medium (default),
                                    high, or off (let the model decide)
    LLM_THINKING_BUDGET             optional thinking budget in tokens; wins
                                    over the level (-1 = automatic, 0 = off)
    LLM_THINKING_LEVEL_VISION       optional, Pipeline 1 vision agents: minimal,
                                    low (default), medium, high, or off
    INGESTION_MAX_CONCURRENCY       optional, parallel agent calls (default 6)

Errors name the variable, never its value. ``LLMConfig`` hides the project
and the credentials path from its repr, so it can be logged.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from pipeline.llm.base import LLMConfigError

# backend/pipeline/llm/config.py -> neuro-symbolic-level-designer/
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

PROVIDERS = ("gemini",)
MODES = ("live", "record", "replay", "update")
THINKING_LEVELS = ("minimal", "low", "medium", "high")
DEFAULT_THINKING_LEVEL = "medium"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    mode: str
    model: str
    location: str | None
    project: str | None = field(default=None, repr=False)
    credentials_path: Path | None = field(default=None, repr=False)
    thinking_level: str | None = DEFAULT_THINKING_LEVEL
    thinking_budget: int | None = None


def load_config(
    env_file: Path | None = ENV_FILE,
    environ: Mapping[str, str] | None = None,
    mode: str | None = None,
) -> LLMConfig:
    """
    Reads and checks the settings. ``mode`` overrides ``LLM_MODE``.

    Replay needs only the model name (it is part of the fixture key); live
    and record need everything to reach Vertex AI.
    """
    values: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    values.update(os.environ if environ is None else environ)

    def get(name: str) -> str | None:
        value = values.get(name, "").strip()
        return value or None

    def require(name: str) -> str:
        value = get(name)
        if value is None:
            raise LLMConfigError(f"{name} is not set (in the environment or neuro-symbolic-level-designer/.env)")
        return value

    provider = (get("LLM_PROVIDER") or "gemini").lower()
    if provider not in PROVIDERS:
        raise LLMConfigError(f"LLM_PROVIDER must be one of: {', '.join(PROVIDERS)}")
    mode = (mode or get("LLM_MODE") or "live").lower()
    if mode not in MODES:
        raise LLMConfigError(f"LLM_MODE must be one of: {', '.join(MODES)}")

    model = require("GOOGLE_GENAI_MODEL")
    thinking_level, thinking_budget = _thinking(get("LLM_THINKING_LEVEL"), get("LLM_THINKING_BUDGET"))
    if mode == "replay":
        return LLMConfig(
            provider, mode, model, get("GOOGLE_CLOUD_LOCATION"),
            thinking_level=thinking_level, thinking_budget=thinking_budget,
        )

    use_vertex = (get("GOOGLE_GENAI_USE_VERTEXAI") or "true").lower()
    if use_vertex in _FALSE:
        raise LLMConfigError("GOOGLE_GENAI_USE_VERTEXAI must be true: only Vertex AI is supported")
    if use_vertex not in _TRUE:
        raise LLMConfigError("GOOGLE_GENAI_USE_VERTEXAI must be true or false")

    credentials = Path(require("GOOGLE_APPLICATION_CREDENTIALS")).expanduser()
    if not credentials.is_absolute():
        credentials = REPO_ROOT / credentials
    if not credentials.is_file():
        raise LLMConfigError("GOOGLE_APPLICATION_CREDENTIALS does not point to an existing file")

    return LLMConfig(
        provider=provider,
        mode=mode,
        model=model,
        location=require("GOOGLE_CLOUD_LOCATION"),
        project=require("GOOGLE_CLOUD_PROJECT"),
        credentials_path=credentials,
        thinking_level=thinking_level,
        thinking_budget=thinking_budget,
    )


def setting(name: str, default: str | None = None, env_file: Path | None = ENV_FILE,
            environ: Mapping[str, str] | None = None) -> str | None:
    """One optional setting (environment first, then ``.env``), without the model checks."""
    env = os.environ if environ is None else environ
    if env.get(name, "").strip():
        return env[name].strip()
    if env_file is not None and env_file.is_file():
        value = dotenv_values(env_file).get(name)
        if value and value.strip():
            return value.strip()
    return default


def vision_thinking_level(env_file: Path | None = ENV_FILE, environ: Mapping[str, str] | None = None) -> str | None:
    """``LLM_THINKING_LEVEL_VISION`` for the Pipeline 1 vision agents (default ``low``; ``off`` = model default)."""
    level = (setting("LLM_THINKING_LEVEL_VISION", "low", env_file, environ) or "low").lower()
    if level == "off":
        return None
    if level not in THINKING_LEVELS:
        raise LLMConfigError(f"LLM_THINKING_LEVEL_VISION must be one of: {', '.join(THINKING_LEVELS)}, off")
    return level


def _thinking(level: str | None, budget: str | None) -> tuple[str | None, int | None]:
    if budget is not None:
        try:
            value = int(budget)
        except ValueError:
            raise LLMConfigError("LLM_THINKING_BUDGET must be an integer") from None
        if value < -1:
            raise LLMConfigError("LLM_THINKING_BUDGET must be -1 or more")
        return None, value
    level = (level or DEFAULT_THINKING_LEVEL).lower()
    if level == "off":
        return None, None
    if level not in THINKING_LEVELS:
        raise LLMConfigError(f"LLM_THINKING_LEVEL must be one of: {', '.join(THINKING_LEVELS)}, off")
    return level, None
