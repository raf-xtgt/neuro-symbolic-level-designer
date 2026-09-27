"""
``RecordingProvider``: record and replay LLM calls, so tests run offline,
free, and deterministic.

* ``live``: pass-through to the inner provider.
* ``record``: calls the inner provider and writes ``<fixture_dir>/<key>.json``.
* ``replay``: reads the fixture; no inner provider or network is needed.
* ``update``: replays when the fixture exists, else calls the inner provider
  and records (keeps existing recordings stable when a few prompts change).

The key is the SHA-256 of the model, the schema name and JSON schema, the
system instruction, the prompt, the image hashes, and the temperature, so a
changed prompt or schema needs a new recording. Fixtures hold the schema
name, the prompts, the response text and token counts: no credentials.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.llm.base import LLMProvider, LLMResult, LLMUnavailableError, T, log_call

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "llm_fixtures"
MODES = ("live", "record", "replay", "update")


def fixture_key(
    model: str, schema_name: str, schema_json: dict, system: str, prompt: str,
    images: list[bytes] | None, temperature: float,
) -> str:
    payload = {
        "model": model,
        "schema": schema_name,
        "schema_json": schema_json,
        "system": system,
        "prompt": prompt,
        "images": [hashlib.sha256(img).hexdigest() for img in images or []],
        "temperature": temperature,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class RecordingProvider:
    def __init__(
        self,
        inner: LLMProvider | None,
        mode: str,
        model: str | None = None,
        fixture_dir: Path = FIXTURE_DIR,
    ):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.used: set[str] = set()  # fixture keys read or written (for pruning stale fixtures)
        if inner is None and mode != "replay":
            raise ValueError(f"mode {mode} needs an inner provider")
        self.inner = inner
        self.mode = mode
        self.model = model or inner.model
        self.name = inner.name if inner is not None else "replay"
        self.fixture_dir = fixture_dir

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
        kwargs = dict(
            system=system, prompt=prompt, images=images, temperature=temperature,
            max_output_tokens=max_output_tokens, timeout_s=timeout_s,
            thinking_level=thinking_level, thinking_budget=thinking_budget,
        )
        if self.mode == "live":
            return self.inner.generate_structured(schema, **kwargs)

        key = fixture_key(
            self.model, schema.__name__, schema.model_json_schema(), system, prompt, images, temperature,
        )
        path = self.fixture_dir / f"{key}.json"
        self.used.add(key)

        if self.mode == "record" or (self.mode == "update" and not path.is_file()):
            result = self.inner.generate_structured(schema, **kwargs)
            self.fixture_dir.mkdir(parents=True, exist_ok=True)
            fixture = {
                "key": key,
                "model": self.model,
                "schema": schema.__name__,
                "system": system,
                "prompt": prompt,
                "image_count": len(images or []),
                "temperature": temperature,
                "response_text": result.raw_text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
            path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
            return result

        if not path.is_file():
            raise LLMUnavailableError(
                f"no recorded LLM response for {schema.__name__} with prompt {prompt[:80]!r} "
                f"(model {self.model}, key {key[:12]}). Record it with LLM_MODE=record against the live model."
            )
        fixture = json.loads(path.read_text(encoding="utf-8"))
        result = LLMResult(
            value=schema.model_validate_json(fixture["response_text"]),
            raw_text=fixture["response_text"],
            model=self.model,
            input_tokens=fixture["input_tokens"],
            output_tokens=fixture["output_tokens"],
            latency_ms=0,
            attempts=0,
        )
        log_call("replay", schema, result, prompt)
        return result
