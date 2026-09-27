"""
Evaluate Pipeline 1 (spritesheet ingestion) and write ``eval/pipeline1_report.md``.

Items:
  1. grassland_tiles.png against the Flare answer key (the grassland_full
     catalog plus the excluded sections of its pack.json): chip recall by
     tight-box IoU >= 0.5, category and walkable accuracy, connector
     precision and recall (cliffs, water), anchor error, family agreement,
     confusion matrix. Computed from the cold upload of item 5.
  2. tileset_desert.png: summary and a sample of 20 random chips.
  3. sheet_ground_128x64_shaded.png (grassland_sheets.zip): tile size
     detection must find 128 x 64 and scale to 64 x 32.
  4. A sheet composed from 16 Kenney farm PNGs (tests/fixtures/kenney_farm_sheet.png).
  5. End to end through the API: upload grassland_tiles.png with the AI
     planner, cold and with a cache hit.
  6. Negative case: a character sheet from death_city.zip (git-ignored, local
     only; live, not recorded) must fail with ingestion_no_floor.

The Flare definition is used here as the answer key only; the ingestion
pipeline never reads it.

Run from ``backend/``:
    LLM_MODE=record uv run python tools/evaluate_ingestion.py   # live, records fixtures
    LLM_MODE=replay uv run python tools/evaluate_ingestion.py   # offline (items 1-5)

A live or record run stores its cost and time measurements in
``eval/ingestion/live_run.json``; a replay or update run reuses them (replayed
calls take no time) and the stored item 6 result. After a record or update run,
untracked fixtures that the run did not use are deleted (stale recordings).
"""
from __future__ import annotations

import io
import json
import random
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from pipeline.errors import StageError  # noqa: E402
from pipeline.ingestion.contact_sheet import render  # noqa: E402
from pipeline.ingestion.pipeline1 import Upload, run_pipeline1  # noqa: E402
from pipeline.ingestion.preprocess import ChipInfo  # noqa: E402
from pipeline.ingestion.slicer import iou  # noqa: E402
from pipeline.llm.config import load_config  # noqa: E402
from pipeline.llm.factory import get_provider  # noqa: E402

ASSETS = REPO_ROOT / "game-assets"
GRASSLAND = ASSETS / "grassland_tiles.png"
DESERT = ASSETS / "tileset_desert.png"
FLARE_DEF = ASSETS / "grassland_tiles.flare_v0.15_tilesetdef.txt"
PACK_DIR = BACKEND_DIR / "asset_packs" / "grassland_full"
KENNEY_SHEET = BACKEND_DIR / "tests" / "fixtures" / "kenney_farm_sheet.png"
EVAL_DIR = BACKEND_DIR / "eval"
OUT_DIR = EVAL_DIR / "ingestion"
MANUAL_NOTES = OUT_DIR / "manual_notes.md"
LIVE_RUN = OUT_DIR / "live_run.json"
GRASSLAND_REPORT = OUT_DIR / "grassland_ingestion_report.json"
E2E_PROMPT = "graveyard with a cabin and a boss arena"
KENNEY_FILES = [
    "dirt_E", "dirtFarmland_E", "planks_E", "planksOld_E", "hay_E", "hayBales_E", "sack_E", "sacksCrate_E",
    "corn_E", "cornYoung_E", "fenceLow_E", "fenceHigh_E", "woodWall_E", "woodWallWindow_E", "chimneyBase_E",
    "ladderStand_E",
]
# Families that name the same thing (manual review of the answer key's family tags; floors and
# water are named by their material there).
EQUIVALENT_FAMILIES = {
    "grass": {"grass", "dry_grass"}, "stone_path": {"stone"}, "stone_floor": {"stone"},
    "old_stone_path": {"stone"}, "cobblestone": {"stone"}, "tree_cypress": {"tree_tall"},
    "tree_blue_green": {"tree_blue"}, "tree_teal": {"tree_blue"}, "tree_bushy": {"tree_fluffy"},
    "tree_broadleaf": {"tree_fluffy"}, "tree_conifer": {"tree_tall"}, "tree_oak": {"tree_fluffy"},
    "tree_pine": {"tree_tall"}, "tree_leafy": {"tree_fluffy"}, "tree_blue": {"tree_blue"},
    "tree_dead": {"tree_dead"}, "tree_stump": {"stump"}, "stump": {"stump"}, "firewood": {"logs"},
    "log": {"logs"}, "rock_pillar": {"rock_pillar"}, "obelisk": {"rock_pillar"}, "rock_small": {"rock_small"},
    "gravestone": {"gravestone"}, "signpost": {"signpost"}, "fence": {"fence"}, "cliff": {"cliff"},
    "water": {"water"}, "dark_water": {"water"}, "bush": {"bush"}, "shrub": {"leafy_plant", "fern", "bush"},
    "fern": {"fern"}, "flower": {"flower"}, "reed": {"weed"}, "weed": {"weed"}, "crate": {"sack", "cart"},
    "sack": {"sack"}, "cart": {"cart"}, "campfire": {"campfire"}, "anvil": {"anvil"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_sheet(path: Path, name: str, provider, work: Path) -> tuple[dict | None, dict | None, str | None, float]:
    """(report, summary, error, seconds) of Pipeline 1 on one sheet."""
    job = work / name.replace(".", "_")
    (job / "work").mkdir(parents=True, exist_ok=True)
    (job / "inputs").mkdir(exist_ok=True)
    sheet = job / "inputs" / "0.png"
    sheet.write_bytes(path.read_bytes())
    started = time.monotonic()
    try:
        result = run_pipeline1([Upload(sheet, name)], [], [], job, job / "work", provider)
        report = json.loads(result.report_path.read_text())
        return report, result.summary, None, time.monotonic() - started
    except StageError as exc:
        report_path = job / "work" / "ingestion_report.json"
        report = json.loads(report_path.read_text()) if report_path.is_file() else None
        return report, (exc.details or {}).get("ingestion"), f"{exc.code}: {exc.message}", time.monotonic() - started


def chip_infos(report: dict) -> list[ChipInfo]:
    return [
        ChipInfo(number=c["number"], sheet=c["sheet"], rect=tuple(c["rect"]), strategy=c["strategy"],
                 anchor=tuple(c["anchor_final"]), is_diamond=c["is_diamond"], footprint=c["footprint"],
                 collision_polygon=[], opaque_pixels=c["opaque_pixels"], pixel_hash="")
        for c in report["chips"]
    ]


def save_crops(report: dict, sheet_path: Path, numbers: list[int], name: str) -> str | None:
    """Contact sheet of the given chips (no anchor dots are recomputed: final anchors are shown)."""
    if not numbers:
        return None
    by_number = {c.number: c for c in chip_infos(report)}
    image = Image.open(sheet_path).convert("RGBA")
    png = render([by_number[n] for n in numbers[:32]], {0: image})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_bytes(png)
    return f"ingestion/{name}"


def usage_line(summary: dict | None) -> str:
    if not summary:
        return "-"
    u = summary["llm_usage"]
    return (f"{u['calls']} calls, {u['input_tokens']:,} input + {u['output_tokens']:,} output tokens, "
            f"{u['latency_ms'] / 1000:.0f} s model time")


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + [
        "| " + " | ".join(str(v) for v in row) + " |" for row in rows
    ]


# ---------------------------------------------------------------------------
# 1. Flare answer key
# ---------------------------------------------------------------------------

def answer_key() -> list[dict]:
    """Every non-empty Flare rectangle, tight box, with the expected fields."""
    from pipeline.ingestion.flare import parse_flare_definition

    alpha = np.array(Image.open(GRASSLAND).convert("RGBA"))[:, :, 3]
    catalog = json.loads((PACK_DIR / "asset_catalog.json").read_text())
    pack = json.loads((PACK_DIR / "pack.json").read_text())
    by_ref = {t["source_ref"]: t for t in catalog["tiles"]}
    excluded = {e["section"]: e["reason"] for e in pack["excluded_sections"]}
    truth = []
    for t in parse_flare_definition(FLARE_DEF):
        ys, xs = np.nonzero(alpha[t.y:t.y + t.h, t.x:t.x + t.w] > 0)
        if len(xs) == 0:
            continue
        tight = (t.x + int(xs.min()), t.y + int(ys.min()), int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1)
        tile = by_ref.get(f"flare:tile={t.flare_id}")
        entry = {"flare_id": t.flare_id, "section": t.section, "rect": tight,
                 "anchor_sheet": (t.x + t.anchor_x, t.y + t.anchor_y)}
        if tile is not None:
            tags = tile.get("tags", [])
            # Floors and water have no family tag in the answer key: their material names them.
            family = next((g for g in tags if g not in ("prop", "tall", "tree", "autotile_required")),
                          tile.get("material") if tile["category"] in ("floor", "water") else t.section)
            entry.update(category=tile["category"], walkable=tile["walkable"], family=family,
                         connector="autotile_required" in tags or "fence" in tags)
        else:
            entry.update(category=None, excluded_reason=excluded.get(t.section, "excluded"))
        truth.append(entry)
    return truth


def match(chips: list[dict], truth: list[dict]) -> list[tuple[dict, dict, float]]:
    pairs = sorted(((iou(tuple(c["rect"]), t["rect"]), ci, ti) for ci, c in enumerate(chips)
                    for ti, t in enumerate(truth)), reverse=True)
    used_c, used_t, out = set(), set(), []
    for score, ci, ti in pairs:
        if score < 0.5:
            break
        if ci in used_c or ti in used_t:
            continue
        used_c.add(ci)
        used_t.add(ti)
        out.append((chips[ci], truth[ti], score))
    return out


def evaluate_flare(report: dict) -> tuple[list[str], dict]:
    truth = answer_key()
    chips = report["chips"]
    matches = match(chips, truth)
    matched_truth = {id(t) for _, t, _ in matches}
    in_catalog = [(c, t) for c, t, _ in matches if t["category"] is not None]
    kept = [(c, t) for c, t in in_catalog if not c["excluded"]]

    def pct(n: int, d: int) -> str:
        return f"{n / d:.1%} ({n}/{d})" if d else "-"

    cat_ok = sum(1 for c, t in kept if c["final"]["category"] == t["category"])
    walk_ok = sum(1 for c, t in kept if c["final"]["walkable"] == t["walkable"])
    conn = [(c["final"]["connector"], t["connector"]) for c, t in in_catalog if c["agents"]["classification"]]
    tp = sum(1 for p, a in conn if p and a)
    fp = sum(1 for p, a in conn if p and not a)
    fn = sum(1 for p, a in conn if not p and a)
    errors = [float(np.hypot(c["anchor_sheet"][0] - t["anchor_sheet"][0], c["anchor_sheet"][1] - t["anchor_sheet"][1]))
              for c, t in kept]
    floor_err = [e for e, (c, t) in zip(errors, kept) if t["category"] in ("floor", "water")]
    obj_err = [e for e, (c, t) in zip(errors, kept) if t["category"] not in ("floor", "water")]

    def p(values: list[float], q: float) -> str:
        return f"{np.percentile(values, q):.1f}" if values else "-"

    metrics = {
        "chips": len(chips), "truth": len(truth), "matched": len(matches),
        "chip_recall": len(matches) / len(truth), "chip_precision": len(matches) / len(chips),
        "category_accuracy": cat_ok / len(kept) if kept else 0, "walkable_accuracy": walk_ok / len(kept) if kept else 0,
        "connector_precision": tp / (tp + fp) if tp + fp else 0, "connector_recall": tp / (tp + fn) if tp + fn else 0,
        "anchor_median": float(np.median(errors)) if errors else 0, "anchor_p90": float(np.percentile(errors, 90)) if errors else 0,
    }
    lines = [
        "### Totals", "",
        *table(["Measure", "Value"], [
            ["Answer key rectangles (non-empty)", len(truth)],
            ["Chips after clean-up", len(chips)],
            ["**Chip recall** (tight-box IoU >= 0.5)", f"**{pct(len(matches), len(truth))}**"],
            ["Chip precision", pct(len(matches), len(chips))],
            ["Matched chips of catalog sections / kept by the harmonizer", f"{len(in_catalog)} / {len(kept)}"],
            ["**Category accuracy** (kept, matched)", f"**{pct(cat_ok, len(kept))}**"],
            ["**Walkable accuracy** (kept, matched)", f"**{pct(walk_ok, len(kept))}**"],
            ["**Connector precision** (vs cliffs, water, fences)", f"**{pct(tp, tp + fp)}**"],
            ["**Connector recall**", f"**{pct(tp, tp + fn)}**"],
            ["**Anchor error** median / 90th percentile, px", f"**{p(errors, 50)} / {p(errors, 90)}**"],
            ["Anchor error, floors and water: median / p90", f"{p(floor_err, 50)} / {p(floor_err, 90)}"],
            ["Anchor error, objects: median / p90", f"{p(obj_err, 50)} / {p(obj_err, 90)}"],
        ]), "",
        "Accuracy is measured on matched chips of the answer key's catalog sections that the harmonizer kept;",
        "the answer key's own anchors for water tiles sit one tile lower (Flare art choice), which shows as",
        "about 32 px in the floor and water anchor error.",
        "",
    ]

    # Per section
    rows = []
    for section in dict.fromkeys(t["section"] for t in truth):
        ts = [t for t in truth if t["section"] == section]
        ms = [(c, t) for c, t, _ in matches if t["section"] == section]
        kept_s = [(c, t) for c, t in ms if not c["excluded"]]
        cat_s = sum(1 for c, t in kept_s if t["category"] and c["final"]["category"] == t["category"])
        expected = ts[0]["category"] or f"excluded ({ts[0]['excluded_reason']})"
        predicted = Counter(c["final"]["category"] if not c["excluded"] else f"excl:{c['excluded']}" for c, _ in ms)
        rows.append([section, expected, len(ts), len(ms), f"{len(ms) / len(ts):.2f}",
                     f"{cat_s}/{len(kept_s)}" if ts[0]["category"] else "-",
                     ", ".join(f"{k} {v}" for k, v in predicted.most_common(3)) or "-"])
    lines += ["### Per section", "",
              *table(["Section", "Expected", "Rects", "Matched", "Recall", "Category ok (kept)", "Predicted (top 3)"],
                     rows), ""]

    # Confusion matrix
    columns = ["floor", "wall", "obstacle", "decoration", "water", "hazard", "excl:fragment",
               "excl:multi_tile_part", "excl:noise", "excl:other"]
    matrix: dict[str, Counter] = defaultdict(Counter)
    for c, t, _ in matches:
        row = t["category"] or "excluded section"
        col = c["final"]["category"] if not c["excluded"] else f"excl:{c['excluded']}"
        matrix[row][col if col in columns else "excl:other"] += 1
    rows = [[row] + [matrix[row][col] or "" for col in columns] for row in
            ["floor", "wall", "obstacle", "decoration", "water", "excluded section"] if matrix[row]]
    lines += ["### Confusion matrix (matched chips; rows: answer key, columns: Pipeline 1)", "",
              *table(["answer key \\ predicted"] + columns, rows), ""]

    # Families
    ours = Counter(c["final"]["family"] for c, t in kept)
    rows = []
    for family, n in ours.most_common(10):
        truth_families = Counter(t["family"] for c, t in kept if c["final"]["family"] == family)
        top, top_n = truth_families.most_common(1)[0]
        agree = top in EQUIVALENT_FAMILIES.get(family, {family})
        rows.append([family, n, ", ".join(f"{k} {v}" for k, v in truth_families.most_common(3)),
                     "yes" if agree else "no", f"{top_n}/{n}"])
    lines += ["### Family agreement (10 most common Pipeline 1 families, matched and kept)", "",
              "Agreement uses a manual list of equivalent names (`EQUIVALENT_FAMILIES` in the tool, for example",
              "`tree_pine` = `tree_tall`, `firewood` = `logs`).", "",
              *table(["Pipeline 1 family", "Chips", "Answer key families", "Same thing", "Majority"], rows), ""]

    # Failure patterns
    unmatched_truth = [t for t in truth if id(t) not in matched_truth]
    wrong_cat = [c for c, t in kept if c["final"]["category"] != t["category"]]
    big_anchor = [c for (c, t), e in zip(kept, errors) if e > 16 and t["category"] not in ("water",)]
    excluded_real = [c for c, t in in_catalog if c["excluded"]]
    patterns = [
        ("Answer key sprites with no matching chip", Counter(t["section"] for t in unmatched_truth), [], None),
        ("Kept with the wrong category", Counter(c["final"]["category"] for c in wrong_cat), wrong_cat,
         "flare_wrong_category.png"),
        ("Anchor error > 16 px (excluding water)", Counter(c["final"]["category"] for c in big_anchor), big_anchor,
         "flare_anchor_error.png"),
        ("Catalog-section sprites excluded by the harmonizer", Counter(c["excluded"] for c in excluded_real),
         excluded_real, "flare_excluded.png"),
    ]
    lines += ["### Failure patterns", ""]
    for title, counts, examples, crop in patterns:
        lines.append(f"* **{title}:** {sum(counts.values())} ({', '.join(f'{k} {v}' for k, v in counts.most_common(5))})")
        if examples:
            numbers = [c["number"] for c in examples]
            detail = "; ".join(
                f"#{c['number']} {c['final']['category']}/{c['final']['family']}: {c['final']['description'][:60]}"
                for c in examples[:5])
            link = save_crops(report, GRASSLAND, numbers, crop)
            lines.append(f"  Examples: {detail}. Crops: [{crop}]({link}).")
    lines.append("")
    return lines, metrics


# ---------------------------------------------------------------------------
# Other sheets
# ---------------------------------------------------------------------------

def compose_kenney() -> Path | None:
    """16 Kenney farm PNGs, tight crops, 4 x 4 cells with transparent 8 px gutters."""
    archive = ASSETS / "kenney_isometric-miniature-farm.zip"
    if KENNEY_SHEET.is_file():
        return KENNEY_SHEET
    if not archive.is_file():
        return None
    with zipfile.ZipFile(archive) as z:
        sprites = []
        for name in KENNEY_FILES:
            image = Image.open(io.BytesIO(z.read(f"Isometric/{name}.png"))).convert("RGBA")
            sprites.append(image.crop(image.getbbox()))
    gutter = 8
    cell_w, cell_h = max(s.width for s in sprites), max(s.height for s in sprites)
    sheet = Image.new("RGBA", (4 * cell_w + 5 * gutter, 4 * cell_h + 5 * gutter), (0, 0, 0, 0))
    for i, sprite in enumerate(sprites):
        x = gutter + (i % 4) * (cell_w + gutter) + (cell_w - sprite.width) // 2
        y = gutter + (i // 4) * (cell_h + gutter) + (cell_h - sprite.height)
        sheet.alpha_composite(sprite, (x, y))
    KENNEY_SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(KENNEY_SHEET)
    return KENNEY_SHEET


def sheet_section(title: str, report: dict | None, summary: dict | None, error: str | None, seconds: float,
                  expect_scale: float | None = None, live: dict | None = None) -> list[str]:
    """``live``: stored live measurements ({llm, seconds}) that replace replayed ones."""
    lines = [f"## {title}", ""]
    if report is None:
        return lines + [f"Not run: {error}", ""]
    sheet = report["sheets"][0]
    rows = [
        ["Sheet size", f"{sheet['original_size'][0]} x {sheet['original_size'][1]}"],
        ["Detected base tile", f"{sheet['tile_size'][0]} x {sheet['tile_size'][1]} ({sheet['diamonds']} diamonds)"],
        ["Scale to 64 x 32", f"{sheet['scale']:g}" + (
            f" ({'as expected' if abs(sheet['scale'] - expect_scale) < 1e-9 else 'EXPECTED ' + str(expect_scale)})"
            if expect_scale is not None else "")],
        ["Chips (noise dropped, duplicates merged)",
         f"{len(report['chips'])} ({sheet['dropped_noise']}, {sheet['merged_duplicates']})"],
        ["Slicing", ", ".join(f"{k} {v}" for k, v in Counter(c["strategy"] for c in report["chips"]).items())],
    ]
    if summary:
        rows += [
            ["Catalog tiles", summary["tiles"]],
            ["By category", ", ".join(f"{k} {v}" for k, v in summary["tile_count_by_category"].items()) or "-"],
            ["Top families", ", ".join(f"{k} {v}" for k, v in list(summary["tile_count_by_family"].items())[:10]) or "-"],
            ["Exclusions", ", ".join(f"{k} {v}" for k, v in summary["exclusions"].items()) or "-"],
            ["Conflicts / arbitration calls", f"{summary['conflicts']} / {summary['arbitration_calls']}"],
            ["LLM", live["llm"] if live else usage_line(summary)],
        ]
    wall = live["seconds"] if live else seconds
    rows += [["Result", error or "catalog built, quality gate passed"], ["Wall time", f"{wall:.0f} s"]]
    return lines + table(["Measure", "Value"], rows) + [""]


def sample_table(report: dict, sheet: Path, name: str, n: int = 20) -> list[str]:
    rng = random.Random(12)
    chips = rng.sample(report["chips"], min(n, len(report["chips"])))
    chips.sort(key=lambda c: c["number"])
    link = save_crops(report, sheet, [c["number"] for c in chips], name)
    rows = [[f"#{c['number']}", f"{c['rect'][2]} x {c['rect'][3]}",
             f"excluded: {c['excluded']}" if c["excluded"] else c["final"]["category"],
             c["final"]["family"], c["final"]["description"][:70]] for c in chips]
    return [f"Sample of {len(chips)} random chips (seed 12), crops: [{name}]({link}).", "",
            *table(["Chip", "Size", "Category", "Family", "Description"], rows), ""]


# ---------------------------------------------------------------------------
# 5. End to end through the API
# ---------------------------------------------------------------------------

def run_e2e(provider, work: Path) -> dict:
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app(data_dir=work / "data", llm_provider=provider))
    runs = []
    for attempt in ("cold", "cache hit"):
        started = time.monotonic()
        resp = client.post(
            "/api/levels",
            data={"prompt": E2E_PROMPT, "planner": "agentic"},
            files=[("spritesheets", ("grassland_tiles.png", GRASSLAND.read_bytes(), "image/png"))],
        )
        created = resp.json()
        while True:
            job = client.get(created["status_url"]).json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        runs.append({"attempt": attempt, "seconds": time.monotonic() - started, "job": job, "created": created})
    # The bundle of the LAST run: both runs send the same planner prompt, so the
    # recorded planner answer (one fixture per key) is the last run's.
    bundle = {}
    last = runs[-1]
    if last["job"]["status"] == "done":
        for name in ("ingestion_report.json", "level.tmj", "contact_sheet.png", "preview_level.png"):
            bundle[name] = client.get(last["created"]["bundle_url"] + name).content
        tmj = json.loads(bundle["level.tmj"])
        for ts in tmj["tilesets"]:
            bundle[ts["image"]] = client.get(last["created"]["bundle_url"] + ts["image"]).content
    return {"runs": runs, "bundle": bundle}


def e2e_section(e2e: dict, live: dict | None = None) -> list[str]:
    rows = []
    for i, run in enumerate(e2e["runs"]):
        if live:
            run = {**run, "seconds": live["e2e_seconds"][i]}
        job = run["job"]
        s = job.get("summary") or {}
        ing = s.get("ingestion", {})
        rows.append([
            run["attempt"], job["status"], f"{run['seconds']:.0f} s",
            "yes" if ing.get("cached") else "no",
            (s.get("validation") or {}).get("passed", "-"),
            (live["e2e_llm"][i] if live else usage_line(ing)) if ing else "-",
            f"{(s.get('llm_usage') or {}).get('calls', 0)} planner call(s)",
            (job.get("error") or {}).get("message", ""),
        ])
    lines = ["## 5. End to end: upload through the API with the AI planner", "",
             f"`POST /api/levels` with `grassland_tiles.png` and the prompt \"{E2E_PROMPT}\" (in-process API,",
             "same code path as the Level Designer). The same upload is sent twice; the second hits the",
             "ingestion cache.", "",
             *table(["Run", "Status", "Total time", "Ingestion cached", "Validation passed", "Ingestion LLM",
                     "Planner LLM", "Error"], rows), ""]
    last = e2e["runs"][-1]["job"]
    if last["status"] == "done":
        s = last["summary"]
        lines += [f"Level (second run; its planner answer is the recorded one): "
                  f"{s['map_size']['width']} x {s['map_size']['height']}, "
                  f"{len(s.get('rooms', []))} rooms, entities {s['entity_count_by_type']}, "
                  f"tiles by category {s['tile_count_by_category']}.",
                  "Preview: ![upload preview](ingestion/e2e_preview.png)", ""]
    return lines


def prune_fixtures(provider) -> None:
    """Deletes untracked fixtures that this run did not read or write."""
    import subprocess

    from pipeline.llm.recording import FIXTURE_DIR

    listed = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", str(FIXTURE_DIR)],
                            capture_output=True, text=True, cwd=BACKEND_DIR).stdout.split()
    stale = [BACKEND_DIR / f for f in listed if Path(f).stem not in provider.used]
    for path in stale:
        path.unlink()
    print(f"pruned {len(stale)} stale fixture(s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    config = load_config()
    provider = get_provider(config)
    live = getattr(provider, "inner", None) or provider  # item 6 is never recorded
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    replay = config.mode in ("replay", "update")
    stored = json.loads(LIVE_RUN.read_text()) if replay and LIVE_RUN.is_file() else None
    measured: dict = {"sheets": {}, "e2e_seconds": [], "e2e_llm": [], "negative": None}

    def cost_row(name: str, chips: int, tiles: int, summary: dict | None, seconds: float) -> list:
        if stored and name in stored["sheets"]:
            entry = stored["sheets"][name]
        else:
            entry = {"llm": usage_line(summary), "seconds": seconds}
        measured["sheets"][name] = entry
        return [name, chips, tiles, entry["llm"], f"{entry['seconds']:.0f} s"]
    lines = [
        "# Pipeline 1 evaluation (spritesheet ingestion)",
        "",
        "Generated by `tools/evaluate_ingestion.py`. The Flare definition is the answer key only; the",
        f"ingestion pipeline never reads it. Model `{config.model}`, LLM mode `{config.mode}`.",
        "",
    ]
    cost_rows = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        print("[5] end to end (cold + cache hit) ...", flush=True)
        e2e = run_e2e(provider, work)
        cold = e2e["runs"][0]["job"]
        report = json.loads(e2e["bundle"]["ingestion_report.json"]) if "ingestion_report.json" in e2e["bundle"] else None
        if "preview_level.png" in e2e["bundle"]:
            (OUT_DIR / "e2e_preview.png").write_bytes(e2e["bundle"]["preview_level.png"])
            (OUT_DIR / "e2e_contact_sheet.png").write_bytes(e2e["bundle"]["contact_sheet.png"])
            flutter = REPO_ROOT / "z_legend_game" / "z_legend_game_flutter" / "test" / "fixtures" / "upload_grassland"
            flutter.mkdir(parents=True, exist_ok=True)
            for old in flutter.glob("*"):
                old.unlink()
            for name, data in e2e["bundle"].items():
                if name == "level.tmj" or name.startswith("tileset"):
                    (flutter / name).write_bytes(data)

        print("[1] Flare answer key ...", flush=True)
        lines += ["## 1. `grassland_tiles.png` against the Flare answer key", ""]
        metrics = {}
        if report is not None:
            section, metrics = evaluate_flare(report)
            lines += section
            GRASSLAND_REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")
            s = report["summary"]
            cost_rows.append(cost_row("grassland_tiles.png (cold, via the API)", s["chips"], s["tiles"], s,
                                      report["seconds"]))
        else:
            lines += [f"Not available: {(cold.get('error') or {}).get('message')}", ""]

        print("[2] desert ...", flush=True)
        rep, summ, err, secs = run_sheet(DESERT, "tileset_desert.png", provider, work)
        if rep:
            cost_rows.append(cost_row("tileset_desert.png", len(rep["chips"]), summ["tiles"] if summ else 0, summ, secs))
        lines += sheet_section("2. `tileset_desert.png` (new theme, same grid)", rep, summ, err, secs,
                               live=measured["sheets"].get("tileset_desert.png") if stored else None)
        if rep:
            lines += sample_table(rep, DESERT, "desert_sample.png")

        print("[3] 128 x 64 ground sheet ...", flush=True)
        with zipfile.ZipFile(ASSETS / "grassland_sheets.zip") as z:
            ground = work / "sheet_ground_128x64_shaded.png"
            ground.write_bytes(z.read("sheet_ground_128x64_shaded.png"))
        rep, summ, err, secs = run_sheet(ground, ground.name, provider, work)
        if rep:
            cost_rows.append(cost_row(ground.name, len(rep["chips"]), summ["tiles"] if summ else 0, summ, secs))
        lines += sheet_section("3. `sheet_ground_128x64_shaded.png` (128 x 64 base tiles)", rep, summ, err, secs,
                               expect_scale=0.5, live=measured["sheets"].get(ground.name) if stored else None)

        print("[4] Kenney composed sheet ...", flush=True)
        kenney = compose_kenney()
        if kenney is None:
            lines += ["## 4. Kenney farm (composed sheet)", "", "Not run: the Kenney zip is missing.", ""]
        else:
            rep, summ, err, secs = run_sheet(kenney, kenney.name, provider, work)
            if rep:
                cost_rows.append(cost_row(kenney.name, len(rep["chips"]), summ["tiles"] if summ else 0, summ, secs))
            lines += sheet_section("4. Kenney farm, 16 PNGs composed into `tests/fixtures/kenney_farm_sheet.png`",
                                   rep, summ, err, secs, expect_scale=0.25,
                                   live=measured["sheets"].get(kenney.name) if stored else None)
            if rep:
                lines += sample_table(rep, KENNEY_SHEET, "kenney_chips.png", n=16)

        for run in e2e["runs"]:
            ing = (run["job"].get("summary") or {}).get("ingestion")
            measured["e2e_seconds"].append(run["seconds"])
            measured["e2e_llm"].append(usage_line(ing) if ing else "-")
        if stored:
            measured["e2e_seconds"], measured["e2e_llm"] = stored["e2e_seconds"], stored["e2e_llm"]
        lines += e2e_section(e2e, stored)

        print("[6] negative case ...", flush=True)
        lines += ["## 6. Negative case: a character sheet", ""]
        archive = ASSETS / "death_city.zip"
        if stored and stored.get("negative"):
            negative = stored["negative"]
            lines += negative["lines"]
            cost_rows.append(negative["cost_row"])
            measured["negative"] = negative
        elif not archive.is_file():
            lines += ["Skipped: `game-assets/death_city.zip` is missing (git-ignored, local only).", ""]
        else:
            with zipfile.ZipFile(archive) as z:
                survivor = work / "survivor.png"
                survivor.write_bytes(z.read("death_city/assets/survivor.png"))
            rep, summ, err, secs = run_sheet(survivor, "survivor.png", live, work)
            characters = sum(1 for c in (rep or {}).get("chips", []) if c["excluded"] == "character")
            ok = err is not None and err.startswith("ingestion_no_floor")
            negative_lines = table(["Measure", "Value"], [
                ["Result", f"{'as expected' if ok else 'UNEXPECTED'}: {err or 'catalog built'}"],
                ["Chips flagged as characters", f"{characters} of {len((rep or {}).get('chips', []))}"],
                ["LLM", usage_line(summ)], ["Wall time", f"{secs:.0f} s"],
            ]) + ["", "Run live and not recorded: the sheet is licensed for local use only.", ""]
            lines += negative_lines
            row = ["survivor.png (negative)", len((rep or {}).get("chips", [])), 0, usage_line(summ), f"{secs:.0f} s"]
            cost_rows.append(row)
            measured["negative"] = {"lines": negative_lines, "cost_row": row}

    lines[5:5] = ["## Cost and time per sheet", "",
                  *table(["Sheet", "Chips", "Catalog tiles", "LLM", "Pipeline 1 time"], cost_rows), ""]
    if MANUAL_NOTES.is_file():
        lines += ["## Manual review", "", MANUAL_NOTES.read_text(encoding="utf-8").strip(), ""]
    (EVAL_DIR / "pipeline1_report.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    if not replay:
        LIVE_RUN.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    if config.mode in ("record", "update"):
        prune_fixtures(provider)
    print(json.dumps(metrics, indent=1))
    print(f"-> {EVAL_DIR / 'pipeline1_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
