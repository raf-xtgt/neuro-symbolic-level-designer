Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 2, 3.2, 4.1.1, 6.2 and 8, @BUILD_LOG.md Log-30, and
@neuro-symbolic-level-designer/backend/.

## Goal
Build the LLM client foundation for the pipeline agents (Pipeline 2 next, Pipeline 1 later). No agent logic in this
task, and no change to how levels are generated today.
- Provider: Gemini on Vertex AI through the `google-genai` SDK. The model and project come from
  `neuro-symbolic-level-designer/.env`; the service account key is `neuro-symbolic-level-designer/creds.json`.
- Structured output: Pydantic models as the response schema. Every agent gets a validated Pydantic object or a clear
  error, never raw text.

All paths are relative to `neuro-symbolic-level-designer/backend/`.

## Secrets (strict)
- `.env` and `creds.json` are git-ignored. Never print, log, commit, or copy their values: not in code, tests, test
  fixtures, error messages, reports, or your final summary. Only the model name and the location may be shown.
- Do not modify `.env` or `creds.json`. Do not read `creds.json` yourself; the Google SDK reads it through
  `GOOGLE_APPLICATION_CREDENTIALS`.

## 1. Dependencies
Add pinned: `google-genai`, `python-dotenv`. (`pydantic` comes with FastAPI.) Add `langgraph` pinned too; it is
used in the next task, and pinning it now confirms it resolves with the other packages.

## 2. Configuration (`pipeline/llm/config.py`)
- Load `neuro-symbolic-level-designer/.env` (path from the module location, not the working directory). Existing
  environment variables win over the file.
- Variables: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI`,
  `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_GENAI_MODEL`, plus new optional `LLM_PROVIDER` (default `gemini`) and
  `LLM_MODE` (`live`, `record`, `replay`; default `live` for the app, `replay` in tests).
- A relative `GOOGLE_APPLICATION_CREDENTIALS` resolves from the repository root (`neuro-symbolic-level-designer/`).
  The current value is absolute; both must work.
- Missing or invalid settings raise `LLMConfigError` naming the variable, never its value.

## 3. Provider interface (`pipeline/llm/`)
- `base.py`:
  - `LLMProvider` protocol with
    `generate_structured(schema: type[T], *, system: str, prompt: str, images: list[bytes] | None = None,
    temperature: float = 0.2, max_output_tokens: int | None = None, timeout_s: float = 60) -> LLMResult[T]`.
    `images` is for the Pipeline 1 vision agents later (PNG bytes).
  - `LLMResult[T]`: `value: T`, `raw_text`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `attempts`.
  - Errors: `LLMError` (base), `LLMConfigError`, `LLMOutputError` (the output does not match the schema after
    retries), `LLMUnavailableError` (network, auth, quota, model not found). Messages are safe to show in the job
    status.
- `gemini.py`, `GeminiProvider`:
  - `genai.Client(vertexai=True, project=..., location=...)`.
  - `GenerateContentConfig` with `system_instruction`, `response_mime_type="application/json"`,
    `response_schema=<Pydantic model>`, temperature, max output tokens.
  - Parse with `schema.model_validate_json(response.text)`; do not trust `response.parsed` alone.
  - Schema mismatch: one repair attempt that sends the validation errors back to the model; then `LLMOutputError`.
  - Transient errors (429, 5xx, timeouts): up to 3 attempts with exponential backoff and jitter.
    Auth errors and "model not found": no retry, `LLMUnavailableError` with a hint (check `GOOGLE_GENAI_MODEL` and
    `GOOGLE_CLOUD_LOCATION`).
- `fake.py`, `FakeProvider`: returns queued Pydantic objects or raises queued errors. For unit tests of agents.
- `recording.py`, `RecordingProvider` (wraps another provider):
  - Key: SHA-256 of model, schema name, the schema's JSON, system, prompt, image hashes, temperature.
  - `record`: calls the inner provider and writes `tests/llm_fixtures/<key>.json` (schema name, prompt, response
    text, token counts; no secrets, no credentials).
  - `replay`: reads the fixture; a missing fixture raises `LLMUnavailableError` saying which prompt to record.
  - `live`: pass-through.
- `factory.py`: `get_provider()` from the configuration and `LLM_MODE`.
- Logging: one INFO line per call: provider, model, schema name, attempts, input and output tokens, latency. The
  prompt only at DEBUG, truncated to 200 characters.
- `usage.py`: `UsageTracker` that sums calls and tokens, so a job can report LLM usage in its summary later.

## 4. Topology schema check (`pipeline/planning/models.py`)
- Pydantic models for ARCHITECTURE.md 6.2 (`RoomTopologyGraph`, `Room`, `Corridor`) with the same enums.
- Gemini structured output supports only a subset of JSON Schema. `style_distribution` is a free-form map
  (`additionalProperties`), which may not be supported. If a construct is rejected or ignored, change the model shape
  (for example `style_distribution: list[StyleWeight]` with `tile_group: str`, `weight: float`), keep the meaning,
  and report exactly what changed and why. I update ARCHITECTURE.md 6.2 from your report.
- Add Pydantic validators for the rules the schema cannot express: room ids unique, corridor endpoints exist,
  exactly one `entrance` room, weights between 0 and 1.

## 5. Smoke test (`python -m pipeline.llm.smoke`)
- Prints the provider, model, and location only (no project id, no credential path).
- Call 1: a tiny schema (`Ping { answer: int, word: str }`, prompt "What is 2 + 3? Give one word that describes grass.").
- Call 2 (`--topology "<prompt>"`): generate one `RoomTopologyGraph` for the given prompt with a short system
  instruction (3 to 6 rooms, one entrance). Print the validated JSON.
- Print tokens and latency for each call. Exit code 1 with the safe error message on failure.
- `--record`: run through `RecordingProvider` in `record` mode and save fixtures for both calls.

## 6. Tests (offline; no network in `uv run pytest`)
- Config: relative and absolute credential paths; missing variable -> `LLMConfigError` naming the variable; error
  text never contains the values from `.env` (use a temporary `.env` with dummy values in the test).
- `GeminiProvider` with a mocked `genai` client: valid JSON; invalid then valid (repair works); invalid twice ->
  `LLMOutputError`; 429 then success (backoff with a patched sleep); auth error -> `LLMUnavailableError`, no retry.
- `RecordingProvider`: record then replay gives the same object; a missing fixture gives a clear error.
- Topology validators (duplicate ids, unknown corridor endpoint, zero or two entrances).
- Replay test with the committed fixtures from the live smoke run (`--record`).
- Secret guard: `git check-ignore` matches `.env` and `creds.json`; no file under `tests/llm_fixtures/` contains
  `private_key`, `BEGIN PRIVATE KEY`, or `client_email`.
- Mark any test that needs the network with `@pytest.mark.live`; skip it unless `LLM_MODE=live`.

## Constraints
- Do not change the placeholder planner, the API behavior, the level format, Dart code, `game-assets/`, `.bob/`, or
  the docs.
- Keep it small: no LangChain wrappers around the SDK, no Instructor.

## Done when
- `uv run pytest` passes with the network disabled (all existing tests too).
- `uv run python -m pipeline.llm.smoke` and `uv run python -m pipeline.llm.smoke --topology "graveyard with a cabin and
  a boss arena" --record` succeed against the real model. Report: model, location, both parsed results, tokens,
  latency, and every schema adaptation you made. Do not include any secret value in the report.
