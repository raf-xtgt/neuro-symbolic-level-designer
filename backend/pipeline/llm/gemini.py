"""
Gemini on Vertex AI through the ``google-genai`` SDK.

* Structured output: the Pydantic model is the ``response_schema``; the text
  is parsed with ``schema.model_validate_json`` (``response.parsed`` is not
  trusted alone).
* Schema mismatch: one repair attempt that sends the validation errors back
  to the model, then ``LLMOutputError``.
* Transient errors (429, 5xx, timeouts, network): up to ``max_attempts``
  calls with exponential backoff and jitter. Auth errors and "model not
  found" fail at once with a hint.

Google error messages can contain the project id, so only the status code
and name are passed on (plus a redacted message for 400 errors, which
explain rejected schemas).
"""
from __future__ import annotations

import os
import random
import time
from collections.abc import Callable

import httpx
from google import genai
from google.auth import exceptions as auth_exceptions
from google.genai import errors, types
from pydantic import ValidationError

from pipeline.llm.base import (
    LLMError, LLMOutputError, LLMResult, LLMUnavailableError, T, log_call,
)
from pipeline.llm.config import LLMConfig

_MODEL_HINT = (
    "check GOOGLE_GENAI_MODEL and GOOGLE_CLOUD_LOCATION "
    "(some Gemini models are served only from the location 'global')"
)
_AUTH_HINT = (
    "check GOOGLE_APPLICATION_CREDENTIALS and that the service account may use "
    "Vertex AI in GOOGLE_CLOUD_PROJECT"
)
_REPAIR_PROMPT = (
    "Your previous answer did not match the required JSON schema.\n"
    "Validation errors:\n{errors}\n"
    "Answer again with the complete corrected JSON object only."
)


class _Transient(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        config: LLMConfig,
        client: object | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
    ):
        self.model = config.model
        self.location = config.location
        self._project = config.project
        self._credentials = str(config.credentials_path) if config.credentials_path else None
        self.thinking_level = config.thinking_level
        self.thinking_budget = config.thinking_budget
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        if client is None:
            # The Google auth library reads the key file from this variable.
            # Without a key file it must be unset, so Application Default
            # Credentials (the Cloud Run service account) are used.
            if self._credentials:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials
            elif not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            try:
                client = genai.Client(vertexai=True, project=config.project, location=config.location)
            except auth_exceptions.GoogleAuthError:
                raise LLMUnavailableError(f"{self.model}: authentication failed; {_AUTH_HINT}") from None
        self._client = client

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
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=self._thinking(thinking_level, thinking_budget),
        )
        parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images or []]
        parts.append(types.Part.from_text(text=prompt))
        contents = [types.Content(role="user", parts=parts)]

        usage = {"attempts": 0, "input": 0, "output": 0}
        start = time.monotonic()
        text = self._generate(contents, config, usage)
        try:
            value = schema.model_validate_json(text)
        except ValidationError as first:
            contents += [
                types.Content(role="model", parts=[types.Part.from_text(text=text)]),
                types.Content(role="user", parts=[types.Part.from_text(
                    text=_REPAIR_PROMPT.format(errors=_describe(first)),
                )]),
            ]
            text = self._generate(contents, config, usage)
            try:
                value = schema.model_validate_json(text)
            except ValidationError as second:
                raise LLMOutputError(
                    f"{self.model} returned output that does not match {schema.__name__} "
                    f"after a repair attempt: {_describe(second, limit=3)}"
                ) from None

        result = LLMResult(
            value=value,
            raw_text=text,
            model=self.model,
            input_tokens=usage["input"],
            output_tokens=usage["output"],
            latency_ms=round((time.monotonic() - start) * 1000),
            attempts=usage["attempts"],
        )
        log_call(self.name, schema, result, prompt)
        return result

    def _thinking(self, level: str | None, budget: int | None) -> types.ThinkingConfig | None:
        """The call's thinking setting, else the configured one. A budget wins over a level."""
        if level is None and budget is None:
            level, budget = self.thinking_level, self.thinking_budget
        if budget is not None:
            return types.ThinkingConfig(thinking_budget=budget)
        if level is not None:
            return types.ThinkingConfig(thinking_level=level.upper())
        return None

    def _generate(self, contents: list, config: types.GenerateContentConfig, usage: dict) -> str:
        """One logical call: retries transient errors, returns the response text."""
        for attempt in range(1, self._max_attempts + 1):
            usage["attempts"] += 1
            try:
                response = self._call(contents, config)
            except _Transient as exc:
                if attempt == self._max_attempts:
                    raise LLMUnavailableError(
                        f"{self.model} is unavailable ({exc.reason}) after {attempt} attempts; try again later"
                    ) from None
                delay = self._base_delay_s * 2 ** (attempt - 1)
                self._sleep(delay + random.uniform(0, delay / 2))
                continue
            meta = getattr(response, "usage_metadata", None)
            if meta is not None:
                usage["input"] += meta.prompt_token_count or 0
                usage["output"] += (meta.candidates_token_count or 0) + (
                    getattr(meta, "thoughts_token_count", None) or 0
                )
            return response.text or ""
        raise AssertionError("unreachable")

    def _call(self, contents: list, config: types.GenerateContentConfig):
        """Maps SDK and transport errors to ``_Transient`` or an ``LLMError``."""
        try:
            return self._client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.APIError as exc:
            code, status = exc.code, exc.status or ""
            label = f"{code} {status}".strip()
            if code == 429 or (isinstance(code, int) and code >= 500) or code == 408:
                raise _Transient(label) from None
            if code in (401, 403):
                raise LLMUnavailableError(f"{self.model}: access denied ({label}); {_AUTH_HINT}") from None
            if code == 404:
                raise LLMUnavailableError(
                    f"model {self.model} not found in location {self.location} ({label}); {_MODEL_HINT}"
                ) from None
            raise LLMError(f"{self.model} rejected the request ({label}): {self._redact(exc.message)}") from None
        except (httpx.TimeoutException, TimeoutError):
            raise _Transient("timeout") from None
        except (httpx.TransportError, auth_exceptions.TransportError) as exc:
            raise _Transient(f"network error: {type(exc).__name__}") from None
        except auth_exceptions.GoogleAuthError:
            raise LLMUnavailableError(f"{self.model}: authentication failed; {_AUTH_HINT}") from None

    def _redact(self, message: str | None) -> str:
        text = (message or "").replace("\n", " ")[:300]
        for secret in (self._project, self._credentials):
            if secret:
                text = text.replace(secret, "<redacted>")
        return text


def _describe(error: ValidationError, limit: int = 20) -> str:
    """Validation errors without the offending input values."""
    lines = [
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in error.errors(include_input=False, include_url=False)[:limit]
    ]
    return "\n".join(lines)
