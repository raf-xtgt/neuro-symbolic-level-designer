"""
Pipeline 3 completion: entity mechanics agent, Flame code generator,
verification engine (summary.json), bundle download.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from pipeline.execution.codegen import CodegenError, camel_case, render_level_loader
from pipeline.execution.compile import run_compile
from pipeline.execution.mechanics import DEFAULTS, LevelMechanics, RoomMechanics, generate_mechanics
from pipeline.execution.verification import check_dart_analyze, run_checks
from pipeline.llm.base import LLMUnavailableError
from pipeline.llm.fake import FakeProvider
from pipeline.planning.run import run_planning
from tests.test_pipeline2 import TOPOLOGIES

BACKEND_DIR = Path(__file__).parent.parent
FULL_CATALOG = BACKEND_DIR / "asset_packs" / "grassland_full" / "asset_catalog.json"
CATEGORIES = {e["type"]: e["category"] for e in json.loads(FULL_CATALOG.read_text())["entities"]}
ROOMS = [
    {"id": "e", "purpose": "entrance", "description": "gate", "enemy_count": 0},
    {"id": "c", "purpose": "combat", "description": "yard", "enemy_count": 3},
    {"id": "b", "purpose": "boss", "description": "", "enemy_count": 4},
]


def _mech(room_id: str, behavior: str = "patrol_room") -> RoomMechanics:
    return RoomMechanics(room_id=room_id, chase_range_tiles=7, step_interval_ms=300, behavior=behavior, rationale="x")


# ---------------------------------------------------------------------------
# Entity mechanics agent
# ---------------------------------------------------------------------------

def test_mechanics_valid_output():
    provider = FakeProvider([LevelMechanics(rooms=[_mech("c"), _mech("b", "guard_exit")])])
    result = generate_mechanics("graveyard", ROOMS, ["Zombie"], provider, exit_room="b")
    assert result.source == "llm" and not result.warnings and result.usage["calls"] == 1
    assert result.rooms["b"]["behavior"] == "guard_exit" and result.rooms["c"]["chase_range_tiles"] == 7
    call = provider.calls[0]
    assert call.temperature == 0.2 and "- c, combat, 3 enemies, yard" in call.prompt and "exit is in room b" in call.prompt


def test_mechanics_unknown_room_id_is_rejected():
    result = generate_mechanics("x", ROOMS, ["Zombie"], FakeProvider([LevelMechanics(rooms=[_mech("zz")])]))
    assert result.source == "defaults" and "unknown room ids zz" in result.warnings[0]
    assert result.rooms == {rid: {**DEFAULTS, "rationale": "default"} for rid in ("c", "b")}


def test_mechanics_llm_error_falls_back_to_defaults():
    result = generate_mechanics("x", ROOMS, ["Zombie"], FakeProvider([LLMUnavailableError("down")]))
    assert result.source == "defaults" and "down" in result.warnings[0]
    assert result.for_room("c")["behavior"] == "idle_until_near"


def test_mechanics_ranges_are_enforced():
    with pytest.raises(ValueError):
        RoomMechanics(room_id="c", chase_range_tiles=9, step_interval_ms=300, behavior="patrol_room", rationale="")


def test_planner_writes_zombie_properties(tmp_path):
    graph = TOPOLOGIES["three_line"]
    mech = LevelMechanics(rooms=[_mech("c"), _mech("b", "guard_exit")])
    result = run_planning("graveyard", FULL_CATALOG, tmp_path, provider=FakeProvider([graph, mech]))
    plan = json.loads(result.plan_path.read_text())
    zombies = [o for o in plan["objects"] if o["type"] == "Zombie"]
    assert len(zombies) == 7 and not result.warnings
    for z in zombies:
        p = z["properties"]
        assert p["behavior"] == ("guard_exit" if p["room_id"] == "b" else "patrol_room")
        assert (p["chase_range"], p["step_interval_ms"]) == (7, 300)
        assert {"room_col", "room_row", "room_w", "room_h"} <= p.keys()
    assert {r["id"]: r.get("mechanics", {}).get("behavior") for r in result.summary["rooms"]} == {
        "e": None, "c": "patrol_room", "b": "guard_exit"}


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    """A compiled agentic level (grassland_full) with zombies."""
    work = tmp_path_factory.mktemp("level")
    mech = LevelMechanics(rooms=[_mech("c"), _mech("b", "guard_exit")])
    result = run_planning("graveyard", FULL_CATALOG, work, provider=FakeProvider([TOPOLOGIES["three_line"], mech]))
    with contextlib.redirect_stdout(io.StringIO()):
        run_compile(str(result.plan_path), str(FULL_CATALOG), str(work / "bundle"), prompt="graveyard")
    return work / "bundle"


def _tmj(bundle: Path) -> dict:
    return json.loads((bundle / "level.tmj").read_text())


def test_codegen_with_zombies(bundle):
    code = (bundle / "level_loader.dart").read_text()
    assert code.count("  Component? spawn") == 3
    assert "Component? spawnZombie(Vector2 position, ZombieConfig config);" in code
    assert "Component? spawnPlayerSpawn(Vector2 position);" in code
    assert "Component? spawnExitTrigger(Vector2 position);" in code
    assert "factory ZombieConfig.fromProperties(CustomProperties properties)" in code
    assert "stepIntervalMs: _intProperty(properties, 'step_interval_ms', 350)," in code
    assert "behavior: _stringProperty(properties, 'behavior', \"idle_until_near\")," in code
    assert "class GeneratedLevel extends PositionComponent with HasGameReference" in code
    assert "String normalizeForTiled(String contents)" in code


def test_codegen_without_zombies(bundle):
    tmj = _tmj(bundle)
    entities = next(layer for layer in tmj["layers"] if layer["name"] == "Entities")
    entities["objects"] = [o for o in entities["objects"] if o["type"] != "Zombie"]
    code = render_level_loader(tmj, "calm", CATEGORIES)
    assert "Config" not in code and "_intProperty" not in code and "spawnZombie" not in code
    assert code.count("  Component? spawn") == 2


def test_codegen_header_golden(bundle):
    tmj = _tmj(bundle)
    header = render_level_loader(tmj, "a  graveyard\nwith a $cabin", CATEGORIES).split("library;")[0]
    assert header.splitlines()[:11] == [
        "// GENERATED CODE - DO NOT EDIT BY HAND.",
        "//",
        "// Level loader for a generated level (neuro-symbolic level designer,",
        "// Pipeline 3 template-assisted code generator, ARCHITECTURE.md 5.3).",
        "//",
        "// Prompt:            a graveyard with a $cabin",
        "// Generator version: 1",
        f"// Map size:          {tmj['width']} x {tmj['height']} tiles",
        "// Tile size:         64 x 32 px (isometric)",
        "// Entities:          ExitTrigger 1, PlayerSpawn 1, Zombie 7",
        "//",
    ]
    assert 'static const String prompt = "a  graveyard\\nwith a \\$cabin";' in render_level_loader(
        tmj, "a  graveyard\nwith a $cabin", CATEGORIES)


@pytest.mark.parametrize("bad", ["Bad-Type", "class", "9lives", "zombie boss"])
def test_codegen_rejects_bad_entity_types(bundle, bad):
    tmj = _tmj(bundle)
    next(layer for layer in tmj["layers"] if layer["name"] == "Entities")["objects"][0]["type"] = bad
    with pytest.raises(CodegenError):
        render_level_loader(tmj, "x", CATEGORIES)


def test_property_names_are_sanitized():
    assert camel_case("step_interval_ms") == "stepIntervalMs"
    for bad in ("chase-range", "1st", "a b", "if"):
        with pytest.raises(CodegenError):
            camel_case(bad)


# ---------------------------------------------------------------------------
# dart analyze
# ---------------------------------------------------------------------------

needs_dart = pytest.mark.skipif(shutil.which("dart") is None, reason="dart is not on PATH")


@needs_dart
def test_dart_analyze_generated_code(bundle, monkeypatch):
    monkeypatch.setenv("DART_ANALYZE", "on")
    check = check_dart_analyze(bundle / "level_loader.dart")
    if check["skipped"]:
        pytest.skip(check["detail"])
    assert check["passed"], check["detail"]


@needs_dart
def test_dart_analyze_reports_broken_code(bundle, tmp_path, monkeypatch):
    monkeypatch.setenv("DART_ANALYZE", "on")
    broken = tmp_path / "level_loader.dart"
    broken.write_text((bundle / "level_loader.dart").read_text() + "\nint broken = ;\n")
    check = check_dart_analyze(broken)
    if check["skipped"]:
        pytest.skip(check["detail"])
    assert not check["passed"] and "error" in check["detail"] and "level_loader.dart" in check["detail"]


def test_dart_analyze_skips_without_dart(bundle, monkeypatch):
    monkeypatch.setenv("DART_ANALYZE", "on")
    monkeypatch.setattr("pipeline.execution.verification.shutil.which", lambda _: None)
    check = check_dart_analyze(bundle / "level_loader.dart")
    assert check["skipped"] and check["passed"] and "not on PATH" in check["detail"]


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------

def _copy(bundle: Path, tmp_path: Path) -> Path:
    out = tmp_path / "b"
    shutil.copytree(bundle, out)
    return out


def _failing(bundle: Path) -> set[str]:
    return {c["name"] for c in run_checks(bundle)[0] if not c["passed"]}


def test_verification_passes(bundle):
    checks, _ = run_checks(bundle)
    assert [c["name"] for c in checks] == [
        "tmj_parses", "gids_resolve", "images_exist", "atlas_fits", "objects_on_walkable", "dart_analyze"]
    assert all(c["passed"] for c in checks)
    assert "% of the 4096 x 4096 web atlas" in checks[3]["detail"]


def test_verification_gids_resolve(bundle, tmp_path):
    out = _copy(bundle, tmp_path)
    tmj = _tmj(out)
    tmj["layers"][0]["data"][3] = 99999
    (out / "level.tmj").write_text(json.dumps(tmj))
    assert _failing(out) == {"gids_resolve"}


def test_verification_images_exist(bundle, tmp_path):
    out = _copy(bundle, tmp_path)
    Image.new("RGBA", (8, 8)).save(out / "tileset.png")  # wrong size
    assert _failing(out) == {"images_exist"}
    (out / "tileset.png").unlink()
    assert _failing(out) == {"images_exist"}


def test_verification_objects_on_walkable(bundle, tmp_path):
    out = _copy(bundle, tmp_path)
    tmj = _tmj(out)
    objects = next(layer for layer in tmj["layers"] if layer["name"] == "Objects")
    blocking = {
        ts["firstgid"] + t["id"] for ts in tmj["tilesets"] for t in ts.get("tiles", [])
        if any(p["name"] == "walkable" and p["value"] is False for p in t.get("properties", []))
    }
    blocked = next(i for i, gid in enumerate(objects["data"]) if gid in blocking)
    spawn = next(o for layer in tmj["layers"] if layer["type"] == "objectgroup" for o in layer["objects"]
                 if o["type"] == "PlayerSpawn")
    spawn["x"] = (blocked % tmj["width"] + 0.5) * tmj["tileheight"]
    spawn["y"] = (blocked // tmj["width"] + 0.5) * tmj["tileheight"]
    (out / "level.tmj").write_text(json.dumps(tmj))
    failing = _failing(out)
    assert failing == {"objects_on_walkable"}


# ---------------------------------------------------------------------------
# API: summary.json, level_loader.dart, bundle.zip
# ---------------------------------------------------------------------------

def _wait(client: TestClient, url: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(url).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    pytest.fail("job did not finish")


def test_api_bundle_zip_and_new_files(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path / "data"))
    created = client.post("/api/levels", data={"prompt": "meadow", "asset_pack": "grassland_starter",
                                               "planner": "placeholder"}).json()
    job = _wait(client, created["status_url"])
    assert job["status"] == "done", job
    block = job["summary"]["verification"]
    assert block["checks_passed"] == block["checks_total"] == 5 and block["dart_analyze"]["status"] == "skipped"

    summary = client.get(created["bundle_url"] + "summary.json").json()
    assert summary["level"]["source"] == {"asset_pack": "grassland_starter"}
    assert summary["level"]["prompt"] == "meadow" and summary["level"]["planner"] == "placeholder"
    assert summary["playability"]["path_found"] and set(summary["timings_s"]) >= {"ingesting", "planning", "executing"}
    assert {"ingestion", "planning", "mechanics"} == set(summary["llm_usage"])
    dart = client.get(created["bundle_url"] + "level_loader.dart")
    assert dart.status_code == 200 and dart.text.startswith("// GENERATED CODE") and "text/plain" in dart.headers["content-type"]

    resp = client.get(f"/api/levels/{job['job_id']}/bundle.zip")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    names = set(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())
    assert {"level.tmj", "tileset.png", "tileset.tsj", "preview_level.png", "level_loader.dart", "summary.json"} <= names
    files = {f["name"] for f in summary["files"]}
    assert files == names - {"summary.json"}

    assert client.get("/api/levels/not-a-uuid/bundle.zip").status_code == 404
    assert client.get("/api/levels/00000000-0000-0000-0000-000000000000/bundle.zip").status_code == 404
