"""
API with uploaded spritesheets (Pipeline 1): scripted vision provider for the
fast cases, and the recorded live run of grassland_tiles.png (replay).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from pipeline.llm.base import LLMOutputError, LLMUnavailableError
from pipeline.llm.fake import FakeProvider
from tests.pipeline1_helpers import FailingProvider, ScriptedProvider, character_sheet, default_rules, floor_sheet
from tests.test_api import _wait

BACKEND_DIR = Path(__file__).parent.parent
GRASSLAND = BACKEND_DIR.parent / "game-assets" / "grassland_tiles.png"
E2E_PROMPT = "graveyard with a cabin and a boss arena"


def _upload(client, sheet: bytes, name: str = "sheet.png", planner: str = "placeholder", prompt: str = "a level"):
    resp = client.post("/api/levels", data={"prompt": prompt, "planner": planner},
                       files=[("spritesheets", (name, sheet, "image/png"))])
    assert resp.status_code == 202, resp.text
    created = resp.json()
    return created, _wait(client, created["status_url"], timeout=120)


@pytest.fixture
def floor_png(tmp_path) -> bytes:
    return floor_sheet(tmp_path / "floor.png").read_bytes()


def test_upload_runs_pipeline1_end_to_end(tmp_path, floor_png):
    client = TestClient(create_app(data_dir=tmp_path / "data", llm_provider=ScriptedProvider()))
    created, job = _upload(client, floor_png)
    assert job["status"] == "done", job
    ingestion = job["summary"]["ingestion"]
    assert ingestion["tile_count_by_category"] == {"floor": 3, "obstacle": 1}
    assert ingestion["cached"] is False and ingestion["llm_usage"]["calls"] == 4
    assert ingestion["sheets"][0]["tile_size"] == [64, 32]
    steps = job["ingestion_steps"]
    assert [s["node"] for s in steps][0] == "preprocess" and steps[-1]["node"] == "quality_gate"
    assert all(s["status"] == "done" for s in steps)
    assert steps[1]["done"] == steps[1]["total"] == 1
    for name in ("contact_sheet.png", "ingestion_report.json", "level.tmj", "preview_level.png"):
        assert client.get(created["bundle_url"] + name).status_code == 200, name
    report = client.get(created["bundle_url"] + "ingestion_report.json").json()
    assert report["quality_gate"]["passed"]


def test_second_upload_hits_the_cache(tmp_path, floor_png):
    data = tmp_path / "data"
    _, first = _upload(TestClient(create_app(data_dir=data, llm_provider=ScriptedProvider())), floor_png)
    assert first["status"] == "done"
    _, second = _upload(TestClient(create_app(data_dir=data, llm_provider=FailingProvider())), floor_png, "other.png")
    assert second["status"] == "done", second
    assert second["summary"]["ingestion"]["cached"] is True
    assert {s["status"] for s in second["ingestion_steps"]} == {"cached"}


def test_upload_without_floor_fails_with_ingestion_no_floor(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path / "data",
                                   llm_provider=ScriptedProvider(default_rules(characters=True))))
    created, job = _upload(client, character_sheet(tmp_path / "c.png").read_bytes())
    assert (job["status"], job["error"]["code"]) == ("failed", "ingestion_no_floor")
    assert "character sprites" in job["error"]["message"]
    assert job["summary"]["ingestion"]["exclusions"] == {"character": 8}
    last = job["ingestion_steps"][-1]
    assert (last["node"], last["status"], last["message"]) == ("quality_gate", "failed", job["error"]["message"])
    assert client.get(created["bundle_url"] + "ingestion_report.json").status_code == 200


@pytest.mark.parametrize(
    "error,code", [(LLMUnavailableError("down"), "llm_unavailable"), (LLMOutputError("bad"), "llm_output_invalid")],
)
def test_ingestion_llm_errors(tmp_path, floor_png, error, code):
    client = TestClient(create_app(data_dir=tmp_path / "data", llm_provider=FakeProvider([error] * 8)))
    _, job = _upload(client, floor_png)
    assert (job["status"], job["stages"]["ingesting"], job["error"]["code"]) == ("failed", "failed", code)


def test_asset_pack_jobs_do_not_run_pipeline1(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path / "data", llm_provider=FailingProvider()))
    resp = client.post("/api/levels", data={"prompt": "x", "asset_pack": "grassland_starter", "planner": "placeholder"})
    job = _wait(client, resp.json()["status_url"])
    assert job["status"] == "done" and "ingestion" not in job["summary"] and job["ingestion_steps"] == []
    assert client.get(resp.json()["bundle_url"] + "contact_sheet.png").status_code == 404


def test_recorded_grassland_upload_with_the_ai_planner(tmp_path):
    """The live run of tools/evaluate_ingestion.py (item 5), replayed."""
    from tests.test_pipeline2_graph import replay_provider

    client = TestClient(create_app(data_dir=tmp_path / "data", llm_provider=replay_provider()))
    created, job = _upload(client, GRASSLAND.read_bytes(), "grassland_tiles.png", "agentic", E2E_PROMPT)
    assert job["status"] == "done", job.get("error")
    summary = job["summary"]
    assert summary["validation"]["passed"]
    assert summary["ingestion"]["tiles"] > 100 and summary["ingestion"]["llm_usage"]["calls"] >= 40
    # The entity mechanics agent's recorded answer is on the zombies.
    assert summary["mechanics"]["source"] == "llm" and not any("entity mechanics" in w for w in summary["warnings"])
    assert summary["verification"]["checks_passed"] == summary["verification"]["checks_total"]
    report = client.get(created["bundle_url"] + "summary.json").json()
    assert report["counts"]["zombies_by_behavior"] and "none" not in report["counts"]["zombies_by_behavior"]
    assert report["level"]["source"] == {"spritesheets": ["grassland_tiles.png"]}
    tmj = client.get(created["bundle_url"] + "level.tmj").json()
    for tileset in tmj["tilesets"]:
        assert client.get(created["bundle_url"] + tileset["image"]).status_code == 200
    report = client.get(created["bundle_url"] + "ingestion_report.json").json()
    assert report["quality_gate"]["passed"] and len(report["chips"]) > 250
