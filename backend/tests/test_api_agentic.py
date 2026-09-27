"""
API with the agentic planner (default): recorded LLM responses (replay),
planning steps in the job status, summary additions, bundle files, errors.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from pipeline.llm.base import LLMOutputError, LLMUnavailableError
from pipeline.llm.fake import FakeProvider
from tests.test_api import _create, _error_fields, _wait
from tests.test_pipeline2 import TOPOLOGIES
from tests.test_pipeline2_graph import PROMPTS, replay_provider


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path_factory.mktemp("data"), llm_provider=replay_provider()))


def _agentic(client, prompt: str, pack: str = "grassland_full", **extra):
    resp = _create(client, {"prompt": prompt, "asset_pack": pack, **extra})
    assert resp.status_code == 202, resp.text
    created = resp.json()
    return created, _wait(client, created["status_url"], timeout=60)


@pytest.mark.parametrize("prompt", PROMPTS)
def test_evaluation_prompt_job(client, prompt):
    created, job = _agentic(client, prompt)
    assert job["status"] == "done", job
    assert job["planner"] == "agentic"
    summary = job["summary"]
    assert summary["planner"] == "agentic"
    assert summary["validation"]["passed"]
    assert summary["design_notes"]
    assert {"id", "purpose", "size", "description", "enemy_count"} <= summary["rooms"][0].keys()
    assert summary["attempts"]["topology"] >= 1 and summary["llm_usage"]["calls"] >= 1
    assert summary["entity_count_by_type"]["Zombie"] == sum(r["enemy_count"] for r in summary["rooms"])

    nodes = [s["node"] for s in job["planning_steps"]]
    assert nodes[0] == "topology_agent" and nodes[-1] == "validator"
    assert job["planning_steps"][-1]["status"] == "done"

    for name in ("level.tmj", "preview_level.png", "topology_graph.json", "validation_report.json"):
        assert client.get(created["bundle_url"] + name).status_code == 200, name
    assert client.get(created["bundle_url"] + "validation_report.json").json()["passed"]


def test_bundle_still_rejects_other_json(client):
    created, job = _agentic(client, PROMPTS[0])
    for name in ("level_plan.json", "job.json", "topology_graph.json.bak"):
        assert client.get(created["bundle_url"] + name).status_code == 404


def test_unknown_planner_is_rejected(client):
    resp = _create(client, {"prompt": "x", "asset_pack": "grassland_full", "planner": "magic"})
    assert _error_fields(resp) == ["planner"]


def test_missing_fixture_fails_with_llm_unavailable(client):
    _, job = _agentic(client, "a prompt that was never recorded")
    assert job["status"] == "failed"
    assert job["stages"]["planning"] == "failed"
    assert job["error"]["code"] == "llm_unavailable"
    assert "LLM_MODE=record" in job["error"]["message"]


@pytest.mark.parametrize(
    "error,code", [(LLMUnavailableError("down"), "llm_unavailable"), (LLMOutputError("bad"), "llm_output_invalid")],
)
def test_llm_error_codes(tmp_path, error, code):
    client = TestClient(create_app(data_dir=tmp_path, llm_provider=FakeProvider([error])))
    _, job = _agentic(client, "graveyard")
    assert (job["status"], job["error"]["code"]) == ("failed", code)


def test_validation_failure_reports_in_summary(tmp_path):
    bad = TOPOLOGIES["three_line"].model_copy(deep=True)
    bad.style_distribution[0].tile_group = "floor.lava"
    client = TestClient(create_app(data_dir=tmp_path, llm_provider=FakeProvider([bad] * 3)))
    created, job = _agentic(client, "graveyard")
    assert job["error"]["code"] == "plan_validation_failed"
    assert job["summary"]["validation"]["passed"] is False
    assert [s["status"] for s in job["planning_steps"]] == ["failed"] * 3
    assert client.get(created["bundle_url"] + "validation_report.json").status_code == 200


def test_starter_pack_with_the_agentic_planner(tmp_path):
    starter = TOPOLOGIES["three_line"].model_copy(deep=True)
    starter.style_distribution = [s for s in starter.style_distribution if s.tile_group.startswith("floor.")]
    client = TestClient(create_app(data_dir=tmp_path, llm_provider=FakeProvider([starter])))
    _, job = _agentic(client, "a quiet meadow", pack="grassland_starter")
    assert job["status"] == "done", job
    assert any("no blocking obstacles" in w for w in job["summary"]["warnings"])
