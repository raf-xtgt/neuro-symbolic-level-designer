"""
Tests for the LLM client (pipeline/llm/). Offline: the Gemini client is
mocked, and recorded responses are replayed from tests/llm_fixtures/.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from pipeline.llm import config as llm_config
from pipeline.llm.base import LLMConfigError, LLMError, LLMOutputError, LLMUnavailableError
from pipeline.llm.config import LLMConfig, load_config
from pipeline.llm.factory import get_provider
from pipeline.llm.fake import FakeProvider
from pipeline.llm.gemini import GeminiProvider
from pipeline.llm.recording import FIXTURE_DIR, RecordingProvider, fixture_key
from pipeline.llm.smoke import PING_PROMPT, PING_SYSTEM, TOPOLOGY_SYSTEM, Ping
from pipeline.llm.usage import UsageTracker
from pipeline.planning.models import RoomTopologyGraph

REPO_ROOT = Path(__file__).resolve().parents[2]
DUMMY_PROJECT = "dummy-project-4711"
DUMMY_KEY_NAME = "dummy-key-0815.json"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_file(tmp_path: Path, **values: str) -> Path:
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def _full_env(credentials: str) -> dict[str, str]:
    return {
        "GOOGLE_CLOUD_PROJECT": DUMMY_PROJECT,
        "GOOGLE_CLOUD_LOCATION": "us-central1",
        "GOOGLE_GENAI_USE_VERTEXAI": "True",
        "GOOGLE_APPLICATION_CREDENTIALS": credentials,
        "GOOGLE_GENAI_MODEL": "gemini-test",
    }


def test_config_relative_credentials_resolve_from_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_config, "REPO_ROOT", tmp_path)
    (tmp_path / DUMMY_KEY_NAME).write_text("{}", encoding="utf-8")
    config = load_config(_env_file(tmp_path, **_full_env(DUMMY_KEY_NAME)), environ={}, mode="live")
    assert config.credentials_path == tmp_path / DUMMY_KEY_NAME
    assert (config.provider, config.mode, config.model, config.location) == (
        "gemini", "live", "gemini-test", "us-central1",
    )
    assert config.project == DUMMY_PROJECT


def test_config_absolute_credentials(tmp_path):
    key = tmp_path / "keys" / DUMMY_KEY_NAME
    key.parent.mkdir()
    key.write_text("{}", encoding="utf-8")
    config = load_config(_env_file(tmp_path, **_full_env(str(key))), environ={}, mode="live")
    assert config.credentials_path == key


def test_config_environment_wins_over_file(tmp_path):
    key = tmp_path / DUMMY_KEY_NAME
    key.write_text("{}", encoding="utf-8")
    env_file = _env_file(tmp_path, **_full_env(str(key)))
    config = load_config(env_file, environ={"GOOGLE_CLOUD_LOCATION": "global"}, mode="live")
    assert config.location == "global"


def test_config_repr_hides_project_and_credentials(tmp_path):
    key = tmp_path / DUMMY_KEY_NAME
    key.write_text("{}", encoding="utf-8")
    config = load_config(_env_file(tmp_path, **_full_env(str(key))), environ={}, mode="live")
    assert DUMMY_PROJECT not in repr(config)
    assert DUMMY_KEY_NAME not in repr(config)


@pytest.mark.parametrize(
    "missing",
    ["GOOGLE_GENAI_MODEL", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS"],
)
def test_config_missing_variable_is_named_without_values(tmp_path, missing):
    key = tmp_path / DUMMY_KEY_NAME
    key.write_text("{}", encoding="utf-8")
    values = _full_env(str(key))
    del values[missing]
    with pytest.raises(LLMConfigError) as info:
        load_config(_env_file(tmp_path, **values), environ={}, mode="live")
    message = str(info.value)
    assert missing in message
    for value in values.values():
        if value not in ("True",):
            assert value not in message


def test_config_errors_never_contain_values(tmp_path):
    values = _full_env(DUMMY_KEY_NAME)  # relative, and the file does not exist
    with pytest.raises(LLMConfigError) as info:
        load_config(_env_file(tmp_path, **values), environ={}, mode="live")
    assert "GOOGLE_APPLICATION_CREDENTIALS" in str(info.value)
    assert DUMMY_KEY_NAME not in str(info.value)
    assert DUMMY_PROJECT not in str(info.value)

    with pytest.raises(LLMConfigError) as info:
        load_config(_env_file(tmp_path, **values, LLM_MODE="secret-mode-99"), environ={})
    assert "LLM_MODE" in str(info.value) and "secret-mode-99" not in str(info.value)

    with pytest.raises(LLMConfigError, match="LLM_PROVIDER"):
        load_config(_env_file(tmp_path, **values, LLM_PROVIDER="watsonx"), environ={})

    with pytest.raises(LLMConfigError, match="GOOGLE_GENAI_USE_VERTEXAI"):
        load_config(_env_file(tmp_path, **{**values, "GOOGLE_GENAI_USE_VERTEXAI": "false"}), environ={}, mode="live")


def test_config_replay_needs_only_the_model(tmp_path):
    config = load_config(_env_file(tmp_path, GOOGLE_GENAI_MODEL="gemini-test"), environ={}, mode="replay")
    assert (config.mode, config.model) == ("replay", "gemini-test")
    assert isinstance(get_provider(config), RecordingProvider)


def test_default_mode_is_live_and_tests_replay(tmp_path):
    config = load_config(_env_file(tmp_path, GOOGLE_GENAI_MODEL="m"), environ={"LLM_MODE": "replay"})
    assert config.mode == "replay"
    key = tmp_path / DUMMY_KEY_NAME
    key.write_text("{}", encoding="utf-8")
    assert load_config(_env_file(tmp_path, **_full_env(str(key))), environ={}).mode == "live"


# ---------------------------------------------------------------------------
# GeminiProvider with a mocked client
# ---------------------------------------------------------------------------

class _Models:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(text: str, prompt_tokens: int = 10, output_tokens: int = 5, thoughts: int = 2):
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens, candidates_token_count=output_tokens, thoughts_token_count=thoughts,
    )
    return SimpleNamespace(text=text, usage_metadata=usage)


def _api_error(code: int, status: str, message: str = "details") -> errors.APIError:
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "status": status, "message": message}})


def _provider(*outcomes):
    models = _Models(outcomes)
    sleeps: list[float] = []
    config = LLMConfig(
        "gemini", "live", "gemini-test", "us-central1",
        project=DUMMY_PROJECT, credentials_path=Path("/nowhere") / DUMMY_KEY_NAME,
    )
    provider = GeminiProvider(config, client=SimpleNamespace(models=models), sleep=sleeps.append)
    return provider, models, sleeps


def _ping(provider, **kwargs):
    return provider.generate_structured(Ping, system="sys", prompt="What is 2 + 3?", **kwargs)


def test_gemini_valid_json():
    provider, models, sleeps = _provider(_response('{"answer": 5, "word": "green"}'))
    result = _ping(provider, temperature=0.5, max_output_tokens=100)
    assert result.value == Ping(answer=5, word="green")
    assert (result.attempts, result.input_tokens, result.output_tokens) == (1, 10, 7)
    assert result.model == "gemini-test" and result.raw_text == '{"answer": 5, "word": "green"}'
    config = models.calls[0]["config"]
    assert config.response_schema is Ping
    assert config.response_mime_type == "application/json"
    assert config.system_instruction == "sys"
    assert (config.temperature, config.max_output_tokens) == (0.5, 100)
    assert config.http_options.timeout == 60_000
    assert sleeps == []


def test_gemini_sends_images_before_the_prompt():
    provider, models, _ = _provider(_response('{"answer": 1, "word": "a"}'))
    _ping(provider, images=[b"\x89PNG fake"])
    parts = models.calls[0]["contents"][0].parts
    assert parts[0].inline_data.data == b"\x89PNG fake"
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[1].text == "What is 2 + 3?"


def test_gemini_repair_after_invalid_output():
    provider, models, _ = _provider(
        _response('{"answer": "five", "word": "green"}'),
        _response('{"answer": 5, "word": "green"}'),
    )
    result = _ping(provider)
    assert result.value.answer == 5
    assert result.attempts == 2
    assert (result.input_tokens, result.output_tokens) == (20, 14)
    repair = models.calls[1]["contents"]
    assert [c.role for c in repair] == ["user", "model", "user"]
    assert repair[1].parts[0].text == '{"answer": "five", "word": "green"}'
    assert "answer" in repair[2].parts[0].text
    assert "five" not in repair[2].parts[0].text  # errors without the input values


def test_gemini_invalid_twice_raises_output_error():
    provider, models, _ = _provider(_response('{"answer": "five"}'), _response("not json"))
    with pytest.raises(LLMOutputError, match="Ping") as info:
        _ping(provider)
    assert len(models.calls) == 2
    assert DUMMY_PROJECT not in str(info.value)


def test_gemini_empty_response_is_repaired():
    provider, _, _ = _provider(_response(None), _response('{"answer": 5, "word": "green"}'))
    assert _ping(provider).value.word == "green"


def test_gemini_retries_429_with_backoff():
    provider, models, sleeps = _provider(
        _api_error(429, "RESOURCE_EXHAUSTED"), _response('{"answer": 5, "word": "green"}'),
    )
    result = _ping(provider)
    assert result.attempts == 2 and len(models.calls) == 2
    assert len(sleeps) == 1 and 1.0 <= sleeps[0] <= 1.5


def test_gemini_backoff_grows_and_gives_up_after_3_attempts():
    provider, models, sleeps = _provider(
        _api_error(503, "UNAVAILABLE"), httpx.ReadTimeout("slow"), _api_error(500, "INTERNAL"),
    )
    with pytest.raises(LLMUnavailableError, match="after 3 attempts"):
        _ping(provider)
    assert len(models.calls) == 3
    assert len(sleeps) == 2 and 1.0 <= sleeps[0] <= 1.5 and 2.0 <= sleeps[1] <= 3.0


@pytest.mark.parametrize("code,status", [(401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED")])
def test_gemini_auth_error_is_not_retried(code, status):
    provider, models, sleeps = _provider(
        _api_error(code, status, f"Permission denied on resource project {DUMMY_PROJECT}."),
    )
    with pytest.raises(LLMUnavailableError, match="GOOGLE_APPLICATION_CREDENTIALS") as info:
        _ping(provider)
    assert len(models.calls) == 1 and sleeps == []
    assert DUMMY_PROJECT not in str(info.value)


def test_gemini_model_not_found_has_a_hint():
    provider, models, _ = _provider(
        _api_error(404, "NOT_FOUND", f"projects/{DUMMY_PROJECT}/locations/us-central1/models/gemini-test"),
    )
    with pytest.raises(LLMUnavailableError) as info:
        _ping(provider)
    message = str(info.value)
    assert "GOOGLE_GENAI_MODEL" in message and "GOOGLE_CLOUD_LOCATION" in message
    assert DUMMY_PROJECT not in message
    assert len(models.calls) == 1


def test_gemini_bad_request_message_is_redacted():
    provider, _, _ = _provider(
        _api_error(400, "INVALID_ARGUMENT", f"schema field not supported in projects/{DUMMY_PROJECT}"),
    )
    with pytest.raises(LLMError) as info:
        _ping(provider)
    assert "schema field not supported" in str(info.value)
    assert DUMMY_PROJECT not in str(info.value)


# ---------------------------------------------------------------------------
# FakeProvider, RecordingProvider, UsageTracker
# ---------------------------------------------------------------------------

def test_fake_provider_returns_queued_values_and_errors():
    fake = FakeProvider([Ping(answer=5, word="green"), LLMUnavailableError("down")])
    assert fake.generate_structured(Ping, system="s", prompt="p").value.answer == 5
    with pytest.raises(LLMUnavailableError):
        fake.generate_structured(Ping, system="s", prompt="p")
    with pytest.raises(LLMError, match="no response queued"):
        fake.generate_structured(Ping, system="s", prompt="p")
    assert [c.prompt for c in fake.calls] == ["p", "p", "p"]


def test_record_then_replay_gives_the_same_object(tmp_path):
    ping = Ping(answer=5, word="green")
    recorder = RecordingProvider(FakeProvider([ping], model="m1"), "record", fixture_dir=tmp_path)
    recorded = recorder.generate_structured(Ping, system="s", prompt="p", images=[b"img"])
    (fixture,) = tmp_path.glob("*.json")
    assert json.loads(fixture.read_text())["schema"] == "Ping"

    replayer = RecordingProvider(None, "replay", model="m1", fixture_dir=tmp_path)
    replayed = replayer.generate_structured(Ping, system="s", prompt="p", images=[b"img"])
    assert replayed.value == recorded.value == ping
    assert replayed.attempts == 0


def test_replay_missing_fixture_names_the_prompt(tmp_path):
    replayer = RecordingProvider(None, "replay", model="m1", fixture_dir=tmp_path)
    with pytest.raises(LLMUnavailableError) as info:
        replayer.generate_structured(Ping, system="s", prompt="What is 2 + 3?")
    assert "What is 2 + 3?" in str(info.value) and "LLM_MODE=record" in str(info.value)


def test_update_mode_replays_or_records(tmp_path):
    first = RecordingProvider(FakeProvider([Ping(answer=1, word="a")], model="m1"), "update", fixture_dir=tmp_path)
    assert first.generate_structured(Ping, system="s", prompt="p").value.answer == 1  # recorded
    again = RecordingProvider(FakeProvider([], model="m1"), "update", fixture_dir=tmp_path)
    assert again.generate_structured(Ping, system="s", prompt="p").attempts == 0  # replayed, no call
    assert len(again.used) == 1


def test_live_mode_passes_through(tmp_path):
    fake = FakeProvider([Ping(answer=1, word="w")])
    assert RecordingProvider(fake, "live", fixture_dir=tmp_path).generate_structured(
        Ping, system="s", prompt="p",
    ).value.answer == 1
    assert not list(tmp_path.iterdir())


def test_fixture_key_covers_every_input():
    base = dict(model="m", schema_name="Ping", schema_json=Ping.model_json_schema(), system="s",
                prompt="p", images=None, temperature=0.2)
    key = fixture_key(**base)
    for change in (
        {"model": "m2"}, {"schema_name": "Pong"}, {"schema_json": {}}, {"system": "s2"},
        {"prompt": "p2"}, {"images": [b"x"]}, {"temperature": 0.3},
    ):
        assert fixture_key(**{**base, **change}) != key, change


def test_usage_tracker_sums_calls():
    tracker = UsageTracker()
    fake = FakeProvider([Ping(answer=1, word="w"), Ping(answer=2, word="x")])
    for _ in range(2):
        tracker.add(fake.generate_structured(Ping, system="s", prompt="12345678"))
    assert tracker.as_dict()["calls"] == 2
    assert tracker.input_tokens == 4 and tracker.attempts == 2


# ---------------------------------------------------------------------------
# Committed fixtures from the live smoke run (--record)
# ---------------------------------------------------------------------------

def _recorded_model() -> str:
    models = {json.loads(p.read_text())["model"] for p in FIXTURE_DIR.glob("*.json")}
    assert len(models) == 1, models
    return models.pop()


def test_replay_committed_smoke_fixtures():
    provider = RecordingProvider(None, "replay", model=_recorded_model())
    ping = provider.generate_structured(Ping, system=PING_SYSTEM, prompt=PING_PROMPT).value
    assert ping.answer == 5 and ping.word

    graph = provider.generate_structured(
        RoomTopologyGraph, system=TOPOLOGY_SYSTEM, prompt="graveyard with a cabin and a boss arena",
    ).value
    assert 3 <= len(graph.rooms) <= 6
    assert sum(1 for r in graph.rooms if r.purpose == "entrance") == 1
    assert graph.style_map()


# ---------------------------------------------------------------------------
# Secret guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [".env", "creds.json"])
def test_secret_files_are_git_ignored(name):
    result = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO_ROOT)
    assert result.returncode == 0, f"{name} is not git-ignored"


def test_fixtures_contain_no_key_material():
    files = list(FIXTURE_DIR.glob("*"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for marker in ("private_key", "BEGIN PRIVATE KEY", "client_email"):
            assert marker not in text, (path.name, marker)


# ---------------------------------------------------------------------------
# Live (network): LLM_MODE=live uv run pytest -m live
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_ping():
    provider = get_provider(load_config(mode="live"))
    result = provider.generate_structured(Ping, system=PING_SYSTEM, prompt=PING_PROMPT)
    assert result.value.answer == 5 and result.attempts >= 1
