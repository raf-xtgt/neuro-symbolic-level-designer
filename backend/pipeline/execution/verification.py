"""
Verification engine (Pipeline 3, ARCHITECTURE.md 5.4) -> ``summary.json``.

Checks a finished bundle (each ``{name, passed, skipped, detail}``):
  * ``tmj_parses``           level.tmj is JSON with the map fields
  * ``gids_resolve``         every GID of a tile layer maps to a tileset tile
  * ``images_exist``         every tileset image is in the bundle, with its declared size
  * ``atlas_fits``           the tileset images fit the 4096 x 4096 web atlas of flame_tiled
                             (at most ``ATLAS_FILL`` of its area); detail: area use in %
  * ``objects_on_walkable``  every entity is in the map on an empty or walkable Objects cell
  * ``dart_analyze``         ``dart analyze`` on the generated ``level_loader.dart`` inside
                             the scratch package ``backend/codegen_check/``; skipped (never
                             failed) when ``dart`` is missing, the package cannot resolve,
                             it times out (``DART_TIMEOUT_S`` seconds, default 120),
                             or ``DART_ANALYZE=off``

The summary also holds the level facts, counts, playability, timings, LLM
usage per pipeline, the bundle files (size, SHA-256) and generator versions.
The checks report; they do not fail the job.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from collections import Counter
from pathlib import Path

from PIL import Image

from pipeline.execution.codegen import CODEGEN_VERSION, OUTPUT_NAME
from pipeline.execution.mechanics import MECHANICS_VERSION
from pipeline.execution.tileset_compiler import ATLAS_FILL, ATLAS_SIDE

VERIFICATION_VERSION = "1"
SUMMARY_NAME = "summary.json"
MAP_NAME = "level.tmj"
CODEGEN_CHECK_DIR = Path(__file__).resolve().parents[2] / "codegen_check"
DEFAULT_DART_TIMEOUT_S = 120  # a cold first `dart analyze` on Cloud Run is slower than locally
_GID_MASK = 0x1FFFFFFF  # without Tiled's flip flags
_MAP_KEYS = ("width", "height", "tilewidth", "tileheight", "layers", "tilesets")


def _check(name: str, problems: list[str], ok: str) -> dict:
    shown = "; ".join(problems[:5]) + (f"; and {len(problems) - 5} more" if len(problems) > 5 else "")
    return {"name": name, "passed": not problems, "skipped": False, "detail": shown if problems else ok}


def _skipped(name: str, reason: str) -> dict:
    return {"name": name, "passed": True, "skipped": True, "detail": f"skipped: {reason}"}


# ---------------------------------------------------------------------------
# Map checks
# ---------------------------------------------------------------------------

def _tile_properties(tmj: dict) -> dict[int, dict]:
    """GID -> tile properties ({name: value})."""
    out: dict[int, dict] = {}
    for ts in tmj["tilesets"]:
        for tile in ts.get("tiles", []):
            out[ts["firstgid"] + tile["id"]] = {p["name"]: p["value"] for p in tile.get("properties", [])}
    return out


def _tile_layers(tmj: dict) -> list[dict]:
    return [layer for layer in tmj["layers"] if layer.get("type") == "tilelayer"]


def _entities(tmj: dict) -> list[dict]:
    return [o for layer in tmj["layers"] if layer.get("type") == "objectgroup" for o in layer.get("objects", [])]


def check_gids(tmj: dict) -> dict:
    ranges = [(ts["firstgid"], ts["firstgid"] + ts["tilecount"]) for ts in tmj["tilesets"]]
    problems = []
    for layer in _tile_layers(tmj):
        for i, raw in enumerate(layer["data"]):
            gid = raw & _GID_MASK
            if gid and not any(a <= gid < b for a, b in ranges):
                problems.append(f"GID {gid} at ({i % tmj['width']}, {i // tmj['width']}) in {layer['name']}")
    return _check("gids_resolve", problems, "every GID maps to a tileset tile")


def check_images(tmj: dict, bundle: Path) -> dict:
    problems = []
    for ts in tmj["tilesets"]:
        path = bundle / ts["image"]
        if not path.is_file():
            problems.append(f"{ts['image']} is missing")
            continue
        with Image.open(path) as image:
            size = image.size
        if size != (ts["imagewidth"], ts["imageheight"]):
            problems.append(f"{ts['image']} is {size[0]} x {size[1]}, declared {ts['imagewidth']} x {ts['imageheight']}")
    return _check("images_exist", problems, f"{len(tmj['tilesets'])} tileset images with their declared sizes")


def atlas_use_percent(tmj: dict) -> float:
    area = sum(ts["imagewidth"] * ts["imageheight"] for ts in tmj["tilesets"])
    return round(100 * area / (ATLAS_SIDE * ATLAS_SIDE), 1)


def check_atlas(tmj: dict) -> dict:
    percent = atlas_use_percent(tmj)
    problems = [
        f"{ts['image']} is {ts['imagewidth']} x {ts['imageheight']}, over {ATLAS_SIDE} px"
        for ts in tmj["tilesets"] if max(ts["imagewidth"], ts["imageheight"]) > ATLAS_SIDE
    ]
    if percent > 100 * ATLAS_FILL:
        problems.append(f"{percent}% of the {ATLAS_SIDE} x {ATLAS_SIDE} web atlas, over {ATLAS_FILL:.0%}")
    return _check("atlas_fits", problems, f"{percent}% of the {ATLAS_SIDE} x {ATLAS_SIDE} web atlas")


def check_objects(tmj: dict) -> dict:
    width, height, th = tmj["width"], tmj["height"], tmj["tileheight"]
    props = _tile_properties(tmj)
    overlay = next((layer for layer in _tile_layers(tmj) if layer["name"] == "Objects"), None)
    problems = []
    entities = _entities(tmj)
    for obj in entities:
        col, row = int(obj["x"] // th), int(obj["y"] // th)
        if not (0 <= col < width and 0 <= row < height):
            problems.append(f"{obj['name']} at ({col}, {row}) is outside the map")
            continue
        gid = overlay["data"][row * width + col] & _GID_MASK if overlay else 0
        if gid and not props.get(gid, {}).get("walkable", True):
            problems.append(f"{obj['name']} at ({col}, {row}) is on a blocking tile")
    return _check("objects_on_walkable", problems, f"{len(entities)} entities on walkable cells")


# ---------------------------------------------------------------------------
# dart analyze
# ---------------------------------------------------------------------------

def dart_timeout_s() -> int:
    """``DART_TIMEOUT_S`` from the environment (seconds), default 120."""
    try:
        value = int(os.environ.get("DART_TIMEOUT_S", "").strip() or DEFAULT_DART_TIMEOUT_S)
    except ValueError:
        return DEFAULT_DART_TIMEOUT_S
    return value if value > 0 else DEFAULT_DART_TIMEOUT_S


def _resolve_package(package: Path, timeout_s: int) -> str | None:
    """None when the scratch package is resolved, else the reason it is not."""
    if (package / ".dart_tool" / "package_config.json").is_file():
        return None
    flutter = shutil.which("flutter")
    if flutter is None:
        return "the codegen_check package is not resolved and flutter is not on PATH"
    try:
        done = subprocess.run(
            [flutter, "pub", "get", "--offline"], cwd=package, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return "flutter pub get --offline timed out"
    if done.returncode != 0:
        return "flutter pub get --offline failed (packages not in the pub cache)"
    return None


def check_dart_analyze(dart_file: Path, package: Path = CODEGEN_CHECK_DIR, timeout_s: int | None = None) -> dict:
    """``timeout_s``: None = ``DART_TIMEOUT_S`` (read at call time)."""
    name = "dart_analyze"
    timeout_s = timeout_s or dart_timeout_s()
    if os.environ.get("DART_ANALYZE", "on").lower() == "off":
        return _skipped(name, "disabled (DART_ANALYZE=off)")
    if not dart_file.is_file():
        return _check(name, [f"{dart_file.name} is missing"], "")
    dart = shutil.which("dart")
    if dart is None:
        return _skipped(name, "dart is not on PATH")
    if not (package / "pubspec.yaml").is_file():
        return _skipped(name, f"no scratch package at {package}")
    reason = _resolve_package(package, timeout_s)
    if reason:
        return _skipped(name, reason)
    target = package / "lib" / f"check_{uuid.uuid4().hex}.dart"
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(dart_file, target)
    try:
        done = subprocess.run(
            [dart, "analyze", str(target.relative_to(package))], cwd=package, capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _skipped(name, f"dart analyze timed out after {timeout_s} s")
    finally:
        target.unlink(missing_ok=True)
    if done.returncode == 0:
        return _check(name, [], "no issues")
    issues = [
        line.strip().replace(target.name, dart_file.name) for line in done.stdout.splitlines()
        if line.strip().startswith(("error", "warning", "info"))
    ]
    return _check(name, issues or [done.stdout.strip()[-300:] or f"exit code {done.returncode}"], "")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _counts(tmj: dict) -> dict:
    props = _tile_properties(tmj)
    placed = [
        props.get(raw & _GID_MASK, {})
        for index, layer in enumerate(_tile_layers(tmj)) for raw in layer["data"]
        if index == 0 or raw & _GID_MASK
    ]
    entities = _entities(tmj)
    behaviors = Counter(
        next((p["value"] for p in o.get("properties", []) if p["name"] == "behavior"), "none")
        for o in entities if o["type"] == "Zombie"
    )
    return {
        "tiles_by_category": dict(Counter(p.get("category", "unknown") for p in placed)),
        "tiles_by_material": dict(Counter(p.get("material", "unknown") for p in placed)),
        "entities_by_type": dict(Counter(o["type"] for o in entities)),
        "zombies_by_behavior": dict(behaviors),
    }


def _files(bundle: Path) -> list[dict]:
    return [
        {"name": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(bundle.iterdir()) if p.is_file() and p.name != SUMMARY_NAME
    ]


def run_checks(bundle: Path) -> tuple[list[dict], dict | None]:
    """The checks, and the parsed map (None if it does not parse)."""
    try:
        tmj = json.loads((bundle / MAP_NAME).read_text(encoding="utf-8"))
        missing = [k for k in _MAP_KEYS if k not in tmj]
        parse = _check("tmj_parses", [f"missing keys: {', '.join(missing)}"] if missing else [], "level.tmj parses")
    except (OSError, ValueError) as exc:
        tmj, parse = None, _check("tmj_parses", [f"level.tmj: {exc}"], "")
    checks = [parse]
    if parse["passed"]:
        checks += [check_gids(tmj), check_images(tmj, bundle), check_atlas(tmj), check_objects(tmj)]
    else:
        checks += [_check(n, ["level.tmj does not parse"], "")
                   for n in ("gids_resolve", "images_exist", "atlas_fits", "objects_on_walkable")]
    checks.append(check_dart_analyze(bundle / OUTPUT_NAME))
    return checks, tmj if parse["passed"] else None


def verify_bundle(
    bundle: Path,
    level: dict,
    playability: dict,
    timings_s: dict | None = None,
    llm_usage: dict | None = None,
    versions: dict | None = None,
) -> dict:
    """Runs the checks, writes ``summary.json`` into ``bundle`` and returns it."""
    checks, tmj = run_checks(bundle)
    if tmj is not None:
        level = {
            **level,
            "map_size": {"width": tmj["width"], "height": tmj["height"]},
            "tile_size": {"width": tmj["tilewidth"], "height": tmj["tileheight"]},
        }
    summary = {
        "verification_version": VERIFICATION_VERSION,
        "level": level,
        "counts": _counts(tmj) if tmj is not None else {},
        "playability": playability,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "atlas_use_percent": atlas_use_percent(tmj) if tmj is not None else None,
        "timings_s": timings_s or {},
        "llm_usage": llm_usage or {},
        "files": _files(bundle),
        "versions": {
            "codegen": CODEGEN_VERSION, "mechanics": MECHANICS_VERSION, "verification": VERIFICATION_VERSION,
            **(versions or {}),
        },
    }
    (bundle / SUMMARY_NAME).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def job_block(summary: dict) -> dict:
    """The short verification block of the job summary."""
    checks = summary["checks"]
    dart = next(c for c in checks if c["name"] == "dart_analyze")
    ran = [c for c in checks if not c["skipped"]]
    return {
        "passed": summary["passed"],
        "checks_passed": sum(c["passed"] for c in ran),
        "checks_total": len(ran),
        "checks_skipped": len(checks) - len(ran),
        "atlas_use_percent": summary["atlas_use_percent"],
        "dart_analyze": {"status": "skipped" if dart["skipped"] else "passed" if dart["passed"] else "failed",
                         "detail": dart["detail"]},
        "checks": [
            {"name": c["name"], "status": "skipped" if c["skipped"] else "passed" if c["passed"] else "failed",
             "detail": c["detail"]}
            for c in checks
        ],
    }
