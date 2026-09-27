"""
Pipeline 1 for uploaded spritesheets (ARCHITECTURE.md section 3):

    preprocess -> 4 agents in parallel over contact sheet batches
               -> harmonizer (+ LLM arbitration for conflicts only) -> quality gate

Outputs in ``work_dir``: ``asset_catalog.json``, ``ingestion_report.json``,
``contact_sheet.png``, the normalized atlas ``catalog_atlas.png`` (the
catalog ``source``, relative to the job folder) and scaled sheets.

Cache: results are keyed by the SHA-256 of the sheet bytes, the legacy files
and ``PIPELINE1_VERSION``, and stored in ``<cache_dir>/<key>/``. A hit skips
every LLM call. A sheet that fails the quality gate is cached too (the same
bytes fail the same way), and a hit raises the same error.

LLM cost bound per sheet: 4 agent calls per batch of 32 chips (+ 1 repair
call for an incomplete batch), and arbitration calls only for conflicts.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from pipeline.errors import StageError
from pipeline.ingestion import legacy as legacy_files
from pipeline.ingestion.agents import AGENTS, CLASSIFICATION, AgentSpec, run_agent_batch
from pipeline.ingestion.agents.arbiter import ARBITER
from pipeline.ingestion.contact_sheet import BATCH_SIZE, Batch, make_batches, render
from pipeline.ingestion.harmonizer import (
    ATLAS_NAME, apply_arbitration, arbitration_context, build_catalog, contact_sheet, detect_conflicts, merge,
    quality_gate,
)
from pipeline.ingestion.preprocess import ChipInfo, SheetInfo, build_chips, prepare_sheet
from pipeline.llm.base import LLMProvider
from pipeline.llm.config import setting, vision_thinking_level
from pipeline.llm.usage import UsageTracker

PIPELINE1_VERSION = "1"
DEFAULT_CONCURRENCY = 6
OUTPUT_FILES = ("asset_catalog.json", "ingestion_report.json", "contact_sheet.png", ATLAS_NAME)

StepCallback = Callable[[list[dict]], None]


@dataclass
class Upload:
    path: Path
    name: str  # original file name


@dataclass
class Pipeline1Result:
    catalog_path: Path
    report_path: Path
    contact_sheet_path: Path
    summary: dict
    warnings: list[str] = field(default_factory=list)


class Progress:
    """``ingestion_steps``: one entry per step, updated in place."""

    ORDER = ("preprocess", "boundary_agent", "classification_agent", "collision_agent", "entity_agent",
             "harmonizer", "quality_gate")

    def __init__(self, on_step: StepCallback | None):
        self.on_step = on_step
        self.steps: dict[str, dict] = {}

    def set(self, node: str, status: str, message: str, done: int | None = None, total: int | None = None) -> None:
        step = {"node": node, "status": status, "message": message}
        if total is not None:
            step.update(done=done or 0, total=total)
        self.steps[node] = step
        if self.on_step is not None:
            self.on_step(self.list())

    def list(self) -> list[dict]:
        return [self.steps[n] for n in self.ORDER if n in self.steps]


def cache_key(sheets: list[Upload], tilesets: list[Upload], maps: list[Upload]) -> str:
    digest = hashlib.sha256(f"pipeline1:{PIPELINE1_VERSION}".encode())
    for kind, files in (("sheet", sheets), ("tileset", tilesets), ("map", maps)):
        for f in files:
            # Bytes only: the same sheet under another name is a hit (names are patched in).
            digest.update(f"{kind}:".encode())
            digest.update(hashlib.sha256(f.path.read_bytes()).digest())
    return digest.hexdigest()


def run_pipeline1(
    sheets: list[Upload],
    tilesets: list[Upload],
    maps: list[Upload],
    job_dir: Path,
    work_dir: Path,
    provider: LLMProvider | None,
    on_step: StepCallback | None = None,
    cache_dir: Path | None = None,
) -> Pipeline1Result:
    progress = Progress(on_step)
    key = cache_key(sheets, tilesets, maps)
    cached = cache_dir / key if cache_dir is not None else None
    if cached is not None and (cached / "ingestion_report.json").is_file():
        return _from_cache(cached, work_dir, progress, [s.name for s in sheets])

    started = time.monotonic()
    usage = UsageTracker()
    report: dict = {"version": PIPELINE1_VERSION, "cache_key": key, "cached": False}

    # -- Legacy files ----------------------------------------------------------
    legacy_tilesets = [legacy_files.parse_tileset(t.path, t.name) for t in tilesets]
    report["legacy"] = [t.summary() for t in legacy_tilesets] + [legacy_files.parse_map(m.path, m.name) for m in maps]

    # -- Preprocess ------------------------------------------------------------
    progress.set("preprocess", "running", f"{len(sheets)} sheet(s)")
    sheet_infos: list[SheetInfo] = []
    images: dict[int, Image.Image] = {}
    chips: list[ChipInfo] = []
    warnings: list[str] = []
    for index, upload in enumerate(sheets):
        info, path = prepare_sheet(upload.path, index, upload.name, work_dir, job_dir)
        images[index] = Image.open(path).convert("RGBA")
        match = next((t for t in legacy_tilesets if legacy_files.matches(t, upload.name, info.original_size)), None)
        rects = None
        if match is not None:
            rects = [
                ((round(x * info.scale), round(y * info.scale), round(w * info.scale), round(h * info.scale)),
                 "legacy", {**match.tiles.get(i, {}), "tileset": match.file_name, "tile_id": i})
                for i in range(match.tile_count)
                for x, y, w, h in [match.rect(i)]
            ]
            warnings.append(f"{upload.name}: using the grid and properties of the tileset {match.file_name}")
        chips += build_chips(path, info, len(chips), rects, original_path=upload.path)
        warnings += info.warnings
        sheet_infos.append(info)
    report["sheets"] = [s.as_dict() for s in sheet_infos]
    sizes = ", ".join(f"{s.tile_size[0]} x {s.tile_size[1]}" + (f" scaled x{s.scale:g}" if s.scale != 1 else "")
                      for s in sheet_infos)
    progress.set(
        "preprocess", "done",
        f"{len(chips)} chips (tile size {sizes}; {sum(s.dropped_noise for s in sheet_infos)} noise, "
        f"{sum(s.merged_duplicates for s in sheet_infos)} duplicates merged)",
    )

    # -- Agents ----------------------------------------------------------------
    batches = make_batches(chips, images)
    if provider is None and batches:  # one provider for the agents and the arbiter
        from pipeline.llm.factory import get_provider
        provider = get_provider()
    thinking = vision_thinking_level()
    results, missing = _run_agents(provider, batches, usage, thinking, progress)

    # -- Harmonizer ------------------------------------------------------------
    progress.set("harmonizer", "running", "merging agent outputs")
    records = merge(chips, results)
    conflicting = detect_conflicts(records)
    arbitration_calls = 0
    for start in range(0, len(conflicting), BATCH_SIZE):
        group = conflicting[start:start + BATCH_SIZE]
        batch = Batch(start // BATCH_SIZE, [r.chip for r in group], render([r.chip for r in group], images))
        decided = run_agent_batch(provider, ARBITER, batch, usage, thinking, context=arbitration_context(group))
        arbitration_calls += 2 if decided.repaired else 1
        for rec in group:
            record = decided.records.get(rec.chip.number)
            apply_arbitration(rec, record.model_dump() if record else None)
    names = {s.index: s.name for s in sheet_infos}
    catalog, atlas = build_catalog(records, images, names, (work_dir / ATLAS_NAME).relative_to(job_dir).as_posix())
    exclusions = Counter(r.excluded for r in records if r.excluded)
    progress.set(
        "harmonizer", "done",
        f"{len(catalog['tiles'])} tiles, {sum(exclusions.values())} excluded, {len(conflicting)} conflicts, "
        f"{arbitration_calls} arbitration call(s)",
    )

    # -- Report and files --------------------------------------------------------
    atlas.save(work_dir / ATLAS_NAME)
    (work_dir / "asset_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    contact_sheet(catalog, atlas).save(work_dir / "contact_sheet.png")
    report.update(
        chips=[_chip_report(r, missing) for r in records],
        exclusions=dict(exclusions),
        conflicts=[
            {"chip": r.chip.number, "rules": r.conflicts, **(r.resolution or {})} for r in conflicting
        ],
        arbitration_calls=arbitration_calls,
        usage=usage.as_dict(),
        seconds=round(time.monotonic() - started, 1),
        thinking_level=thinking,
        warnings=warnings,
    )
    summary = _summary(report, catalog)
    report["summary"] = summary

    # -- Quality gate ------------------------------------------------------------
    try:
        gate = quality_gate(catalog, records)
    except StageError as exc:
        report["quality_gate"] = {"passed": False, "code": exc.code, "detail": exc.message}
        _write_report(report, work_dir)
        if cached is not None:
            _store_cache(cached, work_dir, sheet_infos)
        progress.set("quality_gate", "failed", exc.message)
        exc.details = {"ingestion": summary}
        raise
    report["quality_gate"] = gate
    progress.set(
        "quality_gate", "done",
        "floor families: " + ", ".join(f"{f} ({n})" for f, n in gate["floor_families"].items()),
    )
    report_path = _write_report(report, work_dir)
    if cached is not None:
        _store_cache(cached, work_dir, sheet_infos)
    return Pipeline1Result(work_dir / "asset_catalog.json", report_path, work_dir / "contact_sheet.png",
                           summary, warnings)


# ---------------------------------------------------------------------------
# Agents in parallel
# ---------------------------------------------------------------------------

def _needed(spec: AgentSpec, batch: Batch) -> bool:
    """False when a legacy tileset already defines the agent's fields for every chip."""
    if spec is not CLASSIFICATION:
        return True
    required = {"category", "walkable", "material", "family"}
    return not all(required <= chip.legacy.keys() for chip in batch.chips)


def _run_agents(
    provider: LLMProvider | None, batches: list[Batch], usage: UsageTracker, thinking: str | None, progress: Progress,
) -> tuple[dict[str, dict[int, object]], dict[str, list[int]]]:
    results: dict[str, dict[int, object]] = {spec.name: {} for spec in AGENTS}
    missing: dict[str, list[int]] = {spec.name: [] for spec in AGENTS}
    work = [(spec, batch) for spec in AGENTS for batch in batches if _needed(spec, batch)]
    totals = Counter(spec.name for spec, _ in work)
    done: Counter = Counter()
    for spec in AGENTS:
        progress.set(spec.name, "running" if totals[spec.name] else "done",
                     f"0 of {totals[spec.name]} batches" if totals[spec.name] else "not needed (tileset)",
                     0, totals[spec.name])
    if not work:
        return results, missing

    workers = int(setting("INGESTION_MAX_CONCURRENCY", str(DEFAULT_CONCURRENCY)) or DEFAULT_CONCURRENCY)
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="agent") as pool:
        futures = {pool.submit(run_agent_batch, provider, spec, batch, usage, thinking): (spec, batch)
                   for spec, batch in work}
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                spec, _ = futures[future]
                if future.exception() is not None:
                    for other in pending:
                        other.cancel()
                    progress.set(spec.name, "failed", str(future.exception()), done[spec.name], totals[spec.name])
                    raise future.exception()
                outcome = future.result()
                results[spec.name].update(outcome.records)
                missing[spec.name] += outcome.missing
                done[spec.name] += 1
                status = "done" if done[spec.name] == totals[spec.name] else "running"
                message = f"{done[spec.name]} of {totals[spec.name]} batches"
                if missing[spec.name]:
                    message += f", {len(missing[spec.name])} chips without a record"
                progress.set(spec.name, status, message, done[spec.name], totals[spec.name])
    return results, missing


# ---------------------------------------------------------------------------
# Report, summary, cache
# ---------------------------------------------------------------------------

def _chip_report(rec, missing: dict[str, list[int]]) -> dict:
    x, y, _, _ = rec.chip.rect
    return {
        **rec.chip.as_dict(),
        "anchor_final": list(rec.anchor),
        "anchor_sheet": [x + rec.anchor[0], y + rec.anchor[1]],
        "anchor_source": rec.anchor_source,
        "agents": {"boundary": rec.boundary, "classification": rec.classification,
                   "collision": rec.collision, "entity": rec.entity},
        "missing_from": [name for name, chips in missing.items() if rec.chip.number in chips],
        "final": {
            "kind": rec.kind, "category": rec.category, "walkable": rec.walkable, "material": rec.material,
            "family": rec.family, "connector": rec.connector, "blocks_movement": rec.blocks_movement,
            "height_class": rec.height_class, "interactive": rec.interactive, "description": rec.description,
        },
        "fields_from_tileset": rec.fields_from_tileset,
        "excluded": rec.excluded,
        "conflicts": rec.conflicts,
        "resolution": rec.resolution,
        "catalog_id": rec.catalog_id,
    }


def _summary(report: dict, catalog: dict) -> dict:
    tiles = catalog["tiles"]
    families = Counter(t["tags"][0] for t in tiles)
    return {
        "cached": report.get("cached", False),
        "sheets": [
            {"name": s["name"], "tile_size": s["tile_size"], "scale": s["scale"], "size": s["size"]}
            for s in report["sheets"]
        ],
        "chips": len(report["chips"]),
        "tiles": len(tiles),
        "tile_count_by_category": dict(Counter(t["category"] for t in tiles)),
        "tile_count_by_family": dict(families.most_common()),
        "exclusions": report["exclusions"],
        "conflicts": len(report["conflicts"]),
        "resolutions": dict(Counter(c.get("resolved_by", "none") for c in report["conflicts"])),
        "arbitration_calls": report["arbitration_calls"],
        "llm_usage": report["usage"],
        "seconds": report["seconds"],
    }


def _write_report(report: dict, work_dir: Path) -> Path:
    path = work_dir / "ingestion_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _store_cache(cached: Path, work_dir: Path, sheets: list[SheetInfo]) -> None:
    tmp = cached.with_name(cached.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name in OUTPUT_FILES:
        shutil.copyfile(work_dir / name, tmp / name)
    for sheet in sheets:
        if sheet.scale != 1:
            name = Path(sheet.source).name
            shutil.copyfile(work_dir / name, tmp / name)
    shutil.rmtree(cached, ignore_errors=True)
    tmp.rename(cached)


def _from_cache(cached: Path, work_dir: Path, progress: Progress, names: list[str]) -> Pipeline1Result:
    for path in cached.iterdir():
        shutil.copyfile(path, work_dir / path.name)
    report = json.loads((work_dir / "ingestion_report.json").read_text(encoding="utf-8"))
    # The cache is keyed by bytes: use this upload's file names.
    old = {s["index"]: s["name"] for s in report["sheets"]}
    catalog_path = work_dir / "asset_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    for tile in catalog["tiles"]:
        for index, name in old.items():
            prefix = f"upload:{name}#"
            if index < len(names) and tile.get("source_ref", "").startswith(prefix):
                tile["source_ref"] = f"upload:{names[index]}#" + tile["source_ref"][len(prefix):]
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    for sheet in report["sheets"]:
        if sheet["index"] < len(names):
            sheet["name"] = names[sheet["index"]]
    report["cached"] = True
    (work_dir / "ingestion_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {**report["summary"], "cached": True,
               "llm_usage": {"calls": 0, "attempts": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
               "cold_llm_usage": report["summary"]["llm_usage"]}
    for node in Progress.ORDER:
        progress.set(node, "cached", "from the ingestion cache")
    gate = report.get("quality_gate", {})
    if not gate.get("passed", False):
        raise StageError(gate.get("code", "ingestion_no_floor"), gate.get("detail", "ingestion failed"),
                         details={"ingestion": summary})
    return Pipeline1Result(work_dir / "asset_catalog.json", work_dir / "ingestion_report.json",
                           work_dir / "contact_sheet.png", summary, report.get("warnings", []))
