"""
Pipeline 2 LangGraph loop with ``FakeProvider`` (retry routing, error
payloads, failures), planner selection, and the end-to-end replay of the 5
evaluation prompts from recorded fixtures.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

from pipeline.errors import StageError
from pipeline.execution.compile import run_compile
from pipeline.llm.base import LLMConfigError, LLMOutputError, LLMUnavailableError
from pipeline.llm.fake import FakeProvider
from pipeline.llm.recording import FIXTURE_DIR, RecordingProvider
from pipeline.planning import graph as graph_module
from pipeline.planning.graph import MAX_TOPOLOGY_ATTEMPTS, PlanningFailed, plan_with_llm
from pipeline.planning.run import run_planning
from tests.test_pipeline2 import FULL, TOPOLOGIES, topology

BACKEND_DIR = Path(__file__).parent.parent
FULL_CATALOG = BACKEND_DIR / "asset_packs" / "grassland_full" / "asset_catalog.json"
sys.path.insert(0, str(BACKEND_DIR / "tools"))
from evaluate_planner import PROMPTS  # noqa: E402

GOOD = TOPOLOGIES["three_line"]
BAD_GROUP = topology(
    [("e", "entrance", "south", "small"), ("c", "combat", "center", "medium", 2), ("b", "boss", "north", "large", 3)],
    [("e", "c", "straight"), ("c", "b", "straight")],
    style=[{"tile_group": "floor.grass", "weight": 1}, {"tile_group": "gravestones", "weight": 0.5}],
)


def _nodes(outcome_or_steps) -> list[tuple[str, str, int]]:
    steps = outcome_or_steps if isinstance(outcome_or_steps, list) else outcome_or_steps.steps
    return [(s["node"], s["status"], s["attempt"]) for s in steps]


class _FailValidator:
    """Replaces ``validate_plan``: fails ``times`` times with ``check``, then validates for real."""

    def __init__(self, check: str, times: int):
        self.check, self.times, self.calls = check, times, 0
        self.real = graph_module.validate_plan

    def __call__(self, plan, catalog, rooms):
        self.calls += 1
        report = self.real(plan, catalog, rooms)
        if self.calls <= self.times:
            report = {**report, "passed": False,
                      "checks": [{"name": self.check, "passed": False, "detail": f"{self.check} (crafted)"}]}
        return report


def test_happy_path_steps_and_usage():
    seen: list[list[dict]] = []
    outcome = plan_with_llm("graveyard", FULL, 7, FakeProvider([GOOD]), on_step=seen.append)
    assert outcome.passed and outcome.attempts == {"topology": 1, "layout": 1}
    assert [n for n, _, _ in _nodes(outcome)] == [
        "topology_agent", "layout_builder", "stacking", "spawner", "dressing", "validator",
    ]
    assert [len(s) for s in seen] == [1, 2, 3, 4, 5, 6]  # one callback per node
    assert outcome.steps[0]["message"] == "3 rooms, 7 enemies"
    assert outcome.usage["calls"] == 1


def test_llm_call_settings():
    fake = FakeProvider([GOOD])
    plan_with_llm("graveyard", FULL, 7, fake)
    call = fake.calls[0]
    assert call.temperature == 0.4
    assert "obstacle.gravestone: 4 gravestones" in call.system  # the digest
    assert "Design prompt: graveyard" == call.prompt


def test_invalid_topology_error_reaches_the_next_call():
    fake = FakeProvider([BAD_GROUP, GOOD])
    outcome = plan_with_llm("graveyard", FULL, 7, fake)
    assert outcome.passed and outcome.attempts["topology"] == 2
    second = fake.calls[1].prompt
    assert "tile_group_exists" in second and "'gravestones'" in second
    assert '"tile_group":"gravestones"' in second  # the previous graph, to correct
    assert _nodes(outcome)[:2] == [("topology_agent", "failed", 1), ("topology_agent", "done", 2)]


def test_layout_only_failure_retries_layout_without_llm(monkeypatch):
    fail = _FailValidator("rooms_reachable", times=1)
    monkeypatch.setattr(graph_module, "validate_plan", fail)
    fake = FakeProvider([GOOD])
    outcome = plan_with_llm("graveyard", FULL, 7, fake)
    assert outcome.passed and len(fake.calls) == 1
    assert outcome.attempts == {"topology": 1, "layout": 2}
    assert ("validator", "failed", 1) in _nodes(outcome) and ("layout_builder", "done", 2) in _nodes(outcome)


def test_layout_retries_used_up_go_back_to_the_topology_agent(monkeypatch):
    monkeypatch.setattr(graph_module, "validate_plan", _FailValidator("rooms_reachable", times=3))
    fake = FakeProvider([GOOD, GOOD])
    outcome = plan_with_llm("graveyard", FULL, 7, fake)
    assert outcome.passed and len(fake.calls) == 2
    assert outcome.attempts == {"topology": 2, "layout": 4}  # 3 layouts, then 1 for the new topology
    assert "rooms_reachable: rooms_reachable (crafted)" in fake.calls[1].prompt


def test_other_failures_go_straight_to_the_topology_agent(monkeypatch):
    monkeypatch.setattr(graph_module, "validate_plan", _FailValidator("ids_exist", times=1))
    fake = FakeProvider([GOOD, GOOD])
    outcome = plan_with_llm("graveyard", FULL, 7, fake)
    assert outcome.passed and len(fake.calls) == 2
    assert outcome.attempts == {"topology": 2, "layout": 2}


def test_layout_error_map_size_asks_for_a_new_topology():
    rooms = [("e", "entrance", "south", "large")] + [(f"n{i}", "combat", "north", "large") for i in range(6)]
    huge = topology(rooms, [("e", "n0", "straight")] + [(f"n{i}", f"n{i + 1}", "straight") for i in range(5)])
    fake = FakeProvider([huge, GOOD])
    outcome = plan_with_llm("graveyard", FULL, 7, fake)
    assert outcome.passed and ("layout_builder", "failed", 1) in _nodes(outcome)
    assert "map_size" in fake.calls[1].prompt


def test_all_attempts_fail(monkeypatch):
    monkeypatch.setattr(graph_module, "validate_plan", _FailValidator("ids_exist", times=99))
    fake = FakeProvider([GOOD] * MAX_TOPOLOGY_ATTEMPTS)
    with pytest.raises(PlanningFailed) as info:
        plan_with_llm("graveyard", FULL, 7, fake)
    outcome = info.value.outcome
    assert len(fake.calls) == MAX_TOPOLOGY_ATTEMPTS
    assert not outcome.passed and outcome.plan is None
    assert outcome.report["checks"][0]["name"] == "ids_exist"
    assert "failed validation after 3 topology" in str(info.value)


def test_all_topologies_invalid():
    with pytest.raises(PlanningFailed) as info:
        plan_with_llm("graveyard", FULL, 7, FakeProvider([BAD_GROUP] * 3))
    assert info.value.outcome.attempts["topology"] == 3
    assert info.value.outcome.report["checks"][0]["name"] == "tile_group_exists"


# ---------------------------------------------------------------------------
# run_planning: planners, files, error codes
# ---------------------------------------------------------------------------

def test_run_planning_agentic_writes_reports(tmp_path):
    result = run_planning("graveyard", FULL_CATALOG, tmp_path, provider=FakeProvider([GOOD]))
    assert result.planner == "agentic"
    assert {p.name for p in result.extra_files} == {"topology_graph.json", "validation_report.json"}
    assert json.loads((tmp_path / "validation_report.json").read_text())["passed"]
    assert json.loads((tmp_path / "topology_graph.json").read_text())["rooms"][0]["id"] == "e"
    summary = result.summary
    assert summary["planner"] == "agentic" and summary["attempts"] == {"topology": 1, "layout": 1}
    assert [r["id"] for r in summary["rooms"]] == ["e", "c", "b"] and summary["llm_usage"]["calls"] == 1
    assert summary["validation"]["passed"]


def test_run_planning_placeholder_unchanged(tmp_path):
    from pipeline.planning.placeholder_planner import plan_level, seed_from_prompt

    result = run_planning("a quiet meadow", FULL_CATALOG, tmp_path, planner="placeholder")
    assert result.summary == {"planner": "placeholder", "mechanics": {"source": "defaults", "rooms": {}, "llm_usage": {}}}
    # Unchanged except for the default enemy properties.
    expected = plan_level(FULL, seed_from_prompt("a quiet meadow"))
    for obj in expected["objects"]:
        if obj["type"] == "Zombie":
            obj["properties"] = {"chase_range": 5, "step_interval_ms": 350, "behavior": "idle_until_near"}
    assert json.loads(result.plan_path.read_text()) == expected


def test_run_planning_failure_has_details(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_module, "validate_plan", _FailValidator("ids_exist", times=99))
    with pytest.raises(StageError) as info:
        run_planning("graveyard", FULL_CATALOG, tmp_path, provider=FakeProvider([GOOD] * 3))
    assert info.value.code == "plan_validation_failed"
    assert info.value.details["validation"]["passed"] is False
    assert (tmp_path / "validation_report.json").is_file()


@pytest.mark.parametrize(
    "error,code",
    [
        (LLMUnavailableError("down"), "llm_unavailable"),
        (LLMOutputError("bad json"), "llm_output_invalid"),
        (LLMConfigError("GOOGLE_GENAI_MODEL is not set"), "llm_config"),
    ],
)
def test_llm_errors_map_to_codes(tmp_path, error, code):
    with pytest.raises(StageError) as info:
        run_planning("graveyard", FULL_CATALOG, tmp_path, provider=FakeProvider([error]))
    assert (info.value.code, info.value.message) == (code, str(error))


def test_unknown_planner(tmp_path):
    with pytest.raises(StageError, match="unknown planner"):
        run_planning("graveyard", FULL_CATALOG, tmp_path, planner="magic")


# ---------------------------------------------------------------------------
# End to end: the 5 evaluation prompts, replayed from recorded fixtures
# ---------------------------------------------------------------------------

def replay_provider() -> RecordingProvider:
    models = {json.loads(p.read_text())["model"] for p in FIXTURE_DIR.glob("*.json")}
    assert len(models) == 1, models
    return RecordingProvider(None, "replay", model=models.pop())


@pytest.mark.parametrize("prompt", PROMPTS)
def test_evaluation_prompt_replays_to_a_valid_compiled_level(tmp_path, prompt):
    result = run_planning(prompt, FULL_CATALOG, tmp_path, provider=replay_provider())
    assert result.summary["validation"]["passed"]
    assert 3 <= len(result.summary["rooms"]) <= 7
    with contextlib.redirect_stdout(io.StringIO()):
        out = run_compile(str(result.plan_path), str(FULL_CATALOG), str(tmp_path / "bundle"))
    layers = [layer["name"] for layer in out["tmj"]["layers"]]
    assert layers == ["Ground", "Objects", "Entities"]
    assert (tmp_path / "bundle" / "preview_level.png").is_file()
