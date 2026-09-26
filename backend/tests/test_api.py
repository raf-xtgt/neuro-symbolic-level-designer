"""
API tests for the FastAPI backend (ARCHITECTURE.md section 8).

Each test module gets its own data folder, so jobs never touch backend/data/.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app

BACKEND_DIR = Path(__file__).parent.parent
STARTER_BUNDLE = (
    BACKEND_DIR.parent / "z_legend_game" / "z_legend_game_flutter" / "assets" / "tiles" / "starter"
)
BUNDLE_FILES = ["level.tmj", "tileset.tsj", "tileset.png", "preview_level.png"]
PACK = {"asset_pack": "grassland_starter"}


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path_factory.mktemp("data")))


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 32), (0, 128, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _create(client: TestClient, data: dict, files=None):
    return client.post("/api/levels", data=data, files=files or [])


def _wait(client: TestClient, status_url: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(status_url).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    pytest.fail(f"job did not finish in {timeout}s: {job}")


def _run(client: TestClient, prompt: str, files=None) -> tuple[dict, dict]:
    resp = _create(client, {"prompt": prompt, **PACK}, files)
    assert resp.status_code == 202, resp.text
    created = resp.json()
    return created, _wait(client, created["status_url"])


def _error_fields(resp) -> list[str]:
    assert resp.status_code == 422, resp.text
    return [e["field"] for e in resp.json()["errors"]]


# ---------------------------------------------------------------------------
# Health and asset packs
# ---------------------------------------------------------------------------

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_asset_packs(client):
    packs = {p["id"]: p for p in client.get("/api/asset-packs").json()}
    assert "grassland_starter" in packs
    pack = packs["grassland_starter"]
    assert pack["spritesheets"] == ["grassland_tiles.png"]
    assert pack["tile_size"] == {"width": 64, "height": 32}


def test_invalid_pack_is_skipped(tmp_path):
    bad = tmp_path / "packs" / "broken"
    bad.mkdir(parents=True)
    (bad / "pack.json").write_text(json.dumps({"id": "broken", "catalog": "missing.json"}))
    app = create_app(data_dir=tmp_path / "data", packs_dir=tmp_path / "packs")
    assert TestClient(app).get("/api/asset-packs").json() == []


# ---------------------------------------------------------------------------
# 422 validation
# ---------------------------------------------------------------------------

def test_missing_prompt(client):
    assert "prompt" in _error_fields(_create(client, PACK))


def test_empty_prompt(client):
    assert "prompt" in _error_fields(_create(client, {"prompt": "   ", **PACK}))


def test_prompt_too_long(client):
    assert "prompt" in _error_fields(_create(client, {"prompt": "x" * 2001, **PACK}))


def test_no_spritesheet_source(client):
    assert _error_fields(_create(client, {"prompt": "a level"})) == ["spritesheets"]


def test_unknown_pack(client):
    resp = _create(client, {"prompt": "a level", "asset_pack": "nope"})
    assert _error_fields(resp) == ["asset_pack"]


def test_all_errors_reported_at_once(client):
    fields = _error_fields(_create(client, {"asset_pack": "nope"}))
    assert set(fields) == {"prompt", "asset_pack"}


def test_png_that_is_not_png(client):
    files = [("spritesheets", ("sheet.png", b"not a png", "image/png"))]
    assert _error_fields(_create(client, {"prompt": "a level"}, files)) == ["spritesheets[0]"]


def test_tsj_that_is_not_json(client):
    files = [("tilesets", ("t.tsj", b"{not json", "application/json"))]
    assert _error_fields(_create(client, {"prompt": "a level", **PACK}, files)) == ["tilesets[0]"]


def test_tmx_with_wrong_root(client):
    files = [("maps", ("m.tmx", b"<tileset/>", "application/xml"))]
    assert _error_fields(_create(client, {"prompt": "a level", **PACK}, files)) == ["maps[0]"]


def test_too_many_files(client):
    files = [("maps", (f"m{i}.tmj", b'{"layers": []}', "application/json")) for i in range(6)]
    assert _error_fields(_create(client, {"prompt": "a level", **PACK}, files)) == ["maps"]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def test_happy_path(client):
    created, job = _run(client, "graveyard with a cabin")
    assert job["status"] == "done", job
    assert job["stages"] == {"ingesting": "done", "planning": "done", "executing": "done"}
    assert created["bundle_url"] == f"/api/levels/{created['job_id']}/bundle/"

    bodies = {}
    for name in BUNDLE_FILES:
        resp = client.get(created["bundle_url"] + name)
        assert resp.status_code == 200, name
        expected = "image/png" if name.endswith(".png") else "application/json"
        assert resp.headers["content-type"].startswith(expected)
        bodies[name] = resp.content

    tmj = json.loads(bodies["level.tmj"])
    assert (tmj["width"], tmj["height"]) == (20, 20)
    (tileset,) = tmj["tilesets"]
    assert "source" not in tileset
    assert tileset["image"] == "tileset.png"
    (entities,) = [l for l in tmj["layers"] if l["type"] == "objectgroup"]
    assert len(entities["objects"]) == 5

    summary = job["summary"]
    assert summary["map_size"] == {"width": 20, "height": 20}
    assert sum(summary["tile_count_by_material"].values()) == 400
    assert summary["tile_count_by_material"]["stone"] == 20
    assert summary["entity_count_by_type"] == {"PlayerSpawn": 1, "ExitTrigger": 1, "Zombie": 3}
    assert summary["legacy_files"] == []
    assert summary["warnings"] == []


def _ground(client, created) -> list[int]:
    tmj = client.get(created["bundle_url"] + "level.tmj").json()
    return next(l for l in tmj["layers"] if l["type"] == "tilelayer")["data"]


def test_same_prompt_same_level(client):
    a, job_a = _run(client, "a quiet meadow")
    b, job_b = _run(client, "a quiet meadow")
    c, job_c = _run(client, "a haunted swamp")
    assert job_a["status"] == job_b["status"] == job_c["status"] == "done"
    level_a = client.get(a["bundle_url"] + "level.tmj").content
    level_b = client.get(b["bundle_url"] + "level.tmj").content
    assert level_a == level_b
    assert _ground(client, a) != _ground(client, c)


def test_uploaded_spritesheet_not_implemented(client):
    files = [("spritesheets", ("sheet.png", _png_bytes(), "image/png"))]
    resp = _create(client, {"prompt": "a level"}, files)
    assert resp.status_code == 202, resp.text
    job = _wait(client, resp.json()["status_url"])
    assert job["status"] == "failed"
    assert job["stages"]["ingesting"] == "failed"
    assert job["error"]["code"] == "ingestion_not_implemented"


def test_upload_and_pack_warns(client):
    files = [("spritesheets", ("sheet.png", _png_bytes(), "image/png"))]
    resp = _create(client, {"prompt": "a level", **PACK}, files)
    assert resp.status_code == 202, resp.text
    job = _wait(client, resp.json()["status_url"])
    assert job["error"]["code"] == "ingestion_not_implemented"
    assert any("grassland_starter" in w for w in job["warnings"])


def test_optional_files_in_summary(client):
    files = [
        ("tilesets", ("tileset.tsj", (STARTER_BUNDLE / "tileset.tsj").read_bytes(), "application/json")),
        ("maps", ("level.tmj", (STARTER_BUNDLE / "level.tmj").read_bytes(), "application/json")),
    ]
    _, job = _run(client, "with legacy files", files)
    assert job["status"] == "done", job
    assert job["summary"]["legacy_files"] == [
        {"kind": "tileset", "file_name": "tileset.tsj", "tile_count": 32},
        {"kind": "map", "file_name": "level.tmj", "width": 20, "height": 20, "layer_count": 2},
    ]


def test_uploaded_names_are_not_used_as_paths(client):
    files = [("maps", ("../../evil.tmj", b'{"layers": []}', "application/json"))]
    _, job = _run(client, "path names", files)
    assert job["status"] == "done", job
    assert job["summary"]["legacy_files"][0]["file_name"] == "../../evil.tmj"


# ---------------------------------------------------------------------------
# Bundle security
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def done_job(client) -> dict:
    created, job = _run(client, "security checks")
    assert job["status"] == "done"
    return created


@pytest.mark.parametrize(
    "file",
    ["job.json", "level_plan.json", "..%2Fjob.json", "..%2F..%2Fwork%2Flevel_plan.json"],
)
def test_bundle_rejects_unknown_files(client, done_job, file):
    assert client.get(done_job["bundle_url"] + file).status_code == 404


def test_bundle_rejects_dot_dot_path(client, done_job):
    url = f"/api/levels/{done_job['job_id']}/bundle/../job.json"
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("job_id", ["not-a-uuid", "..", "00000000-0000-0000-0000-000000000000"])
def test_invalid_or_unknown_job_id(client, job_id):
    assert client.get(f"/api/levels/{job_id}").status_code in (404, 422)
    assert client.get(f"/api/levels/{job_id}/bundle/level.tmj").status_code in (404, 422)
