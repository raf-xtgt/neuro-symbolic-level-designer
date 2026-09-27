"""
Level generation jobs. One folder per job under ``<data_dir>/jobs/<job_id>/``:
``inputs/``, ``work/``, ``bundle/`` and ``job.json`` (the job state).
Jobs run one at a time on a background thread.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline.errors import StageError
from pipeline.execution.compile import run_compile
from pipeline.execution.verification import job_block, verify_bundle
from pipeline.ingestion.pipeline1 import PIPELINE1_VERSION
from pipeline.ingestion.run import IngestionRequest, LegacyFile, run_ingestion
from pipeline.planning.pathing import path_check
from pipeline.llm.base import LLMProvider
from pipeline.planning.run import DEFAULT_PLANNER, run_planning

log = logging.getLogger(__name__)

STAGES = ("ingesting", "planning", "executing")
# Bundle files that may be served: the map, its preview, the tilesets
# (tileset.png/.tsj, tileset_1.png/.tsj, ...), the agentic planner's
# topology graph and validation report, for uploads the Pipeline 1
# contact sheet and ingestion report, and the Pipeline 3 Flame code and
# verification report. Everything else is 404.
BUNDLE_FILE_RE = re.compile(
    r"level\.tmj|preview_level\.png|tileset(_\d+)?\.(png|tsj)|topology_graph\.json|validation_report\.json"
    r"|contact_sheet\.png|ingestion_report\.json|level_loader\.dart|summary\.json"
)


def bundle_media_type(name: str) -> str | None:
    """Content type of an allowed bundle file name, or None if not allowed."""
    if not BUNDLE_FILE_RE.fullmatch(name):
        return None
    if name.endswith(".png"):
        return "image/png"
    return "text/plain; charset=utf-8" if name.endswith(".dart") else "application/json"


@dataclass
class Upload:
    original_name: str
    ext: str  # lower-case, with dot
    data: bytes


@dataclass
class LevelRequest:
    prompt: str
    pack_catalog: Path | None
    spritesheets: list[Upload] = field(default_factory=list)
    tilesets: list[Upload] = field(default_factory=list)
    maps: list[Upload] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    planner: str = DEFAULT_PLANNER
    source: dict = field(default_factory=dict)  # {"asset_pack": id} or {"spritesheets": [names]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_job_id(job_id: str) -> str | None:
    """Canonical job id, or None when ``job_id`` is not a UUID."""
    try:
        return str(uuid.UUID(job_id))
    except ValueError:
        return None


class JobManager:
    def __init__(self, data_dir: Path, llm_provider: LLMProvider | None = None):
        # llm_provider: for tests (replay); None = configured by LLM_MODE.
        self.llm_provider = llm_provider
        self.jobs_dir = data_dir / "jobs"
        self.cache_dir = data_dir / "ingestion_cache"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="level-job")
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def get(self, job_id: str) -> dict | None:
        path = self._job_dir(job_id) / "job.json"
        with self._lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def _update(self, job_id: str, **changes) -> None:
        path = self._job_dir(job_id) / "job.json"
        with self._lock:
            job = json.loads(path.read_text(encoding="utf-8"))
            job.update(changes)
            job["updated_at"] = _now()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def bundle_file(self, job_id: str, name: str) -> Path | None:
        if bundle_media_type(name) is None:
            return None
        path = self._job_dir(job_id) / "bundle" / name
        return path if path.is_file() else None

    def bundle_zip(self, job_id: str) -> bytes | None:
        """A zip of the allowed bundle files of a ``done`` job, else None."""
        job = self.get(job_id)
        if job is None or job["status"] != "done":
            return None
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((self._job_dir(job_id) / "bundle").iterdir()):
                if path.is_file() and bundle_media_type(path.name) is not None:
                    archive.write(path, path.name)
        return buffer.getvalue()

    # -- create ------------------------------------------------------------

    def create(self, request: LevelRequest) -> str:
        job_id = str(uuid.uuid4())
        job_dir = self._job_dir(job_id)
        for sub in ("inputs", "work", "bundle"):
            (job_dir / sub).mkdir(parents=True)

        # Uploaded names are never used as paths: files get generated names.
        def store(kind: str, uploads: list[Upload]) -> list[LegacyFile]:
            folder = job_dir / "inputs" / kind
            folder.mkdir()
            stored = []
            for i, up in enumerate(uploads):
                path = folder / f"{i}{up.ext}"
                path.write_bytes(up.data)
                stored.append(LegacyFile(path=path, original_name=up.original_name))
            return stored

        ingestion = IngestionRequest(
            pack_catalog=request.pack_catalog,
            spritesheets=store("spritesheets", request.spritesheets),
            tilesets=store("tilesets", request.tilesets),
            maps=store("maps", request.maps),
        )
        (job_dir / "inputs" / "prompt.txt").write_text(request.prompt, encoding="utf-8")

        now = _now()
        job = {
            "job_id": job_id,
            "status": "queued",
            "stages": {s: "pending" for s in STAGES},
            "created_at": now,
            "updated_at": now,
            "warnings": request.warnings,
            "error": None,
            "summary": None,
            "planner": request.planner,
            "source": request.source,
            "ingestion_steps": [],
            "planning_steps": [],
        }
        (job_dir / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        self._executor.submit(self._run, job_id, request.prompt, ingestion, request.planner, request.source)
        return job_id

    # -- run ---------------------------------------------------------------

    def _run(
        self, job_id: str, prompt: str, ingestion: IngestionRequest, planner: str, source: dict | None = None,
    ) -> None:
        job_dir = self._job_dir(job_id)
        work, bundle = job_dir / "work", job_dir / "bundle"
        stages = {s: "pending" for s in STAGES}
        stage = STAGES[0]
        started: dict[str, float] = {}
        timings: dict[str, float] = {}

        def start(name: str) -> None:
            nonlocal stage
            stage = name
            stages[name] = "running"
            started[name] = time.monotonic()
            self._update(job_id, status=name, stages=stages)

        def finish(name: str) -> None:
            stages[name] = "done"
            timings[name] = round(time.monotonic() - started[name], 2)
            self._update(job_id, stages=stages)

        try:
            start("ingesting")
            ingested = run_ingestion(
                ingestion, work, job_dir=job_dir, provider=self.llm_provider,
                on_step=lambda steps: self._update(job_id, ingestion_steps=steps), cache_dir=self.cache_dir,
            )
            if ingested.warnings:
                self._update(job_id, warnings=self.get(job_id)["warnings"] + ingested.warnings)
            for path in ingested.extra_files:
                shutil.copyfile(path, bundle / path.name)
            finish("ingesting")

            start("planning")
            planning = run_planning(
                prompt, ingested.catalog_path, work, planner=planner,
                on_step=lambda steps: self._update(job_id, planning_steps=steps),
                provider=self.llm_provider,
            )
            if planning.warnings:
                self._update(job_id, warnings=self.get(job_id)["warnings"] + planning.warnings)
            finish("planning")

            start("executing")
            try:
                run_compile(
                    str(planning.plan_path), str(ingested.catalog_path), str(bundle), source_root=ingested.source_root,
                    prompt=prompt,
                )
            except StageError:
                raise
            except Exception as exc:
                raise StageError("execution_failed", str(exc)) from exc
            for path in planning.extra_files:
                shutil.copyfile(path, bundle / path.name)

            summary = _summarize(planning.plan_path, ingested.catalog_path, ingested.legacy_files)
            summary.update(planning.summary)
            if ingested.summary is not None:
                summary["ingestion"] = ingested.summary
            verify_start = time.monotonic()
            report = verify_bundle(
                bundle,
                level={"job_id": job_id, "prompt": prompt, "planner": planner, "source": source or {}},
                playability=_playability(summary),
                timings_s={**timings, "executing": round(time.monotonic() - started["executing"], 2)},
                llm_usage={
                    "ingestion": (ingested.summary or {}).get("llm_usage", {}),
                    "planning": planning.summary.get("llm_usage", {}),
                    "mechanics": planning.summary.get("mechanics", {}).get("llm_usage", {}),
                },
                versions={"pipeline1": PIPELINE1_VERSION},
            )
            summary["verification"] = job_block(report)
            summary["verification"]["seconds"] = round(time.monotonic() - verify_start, 2)
            finish("executing")
            summary["warnings"] = self.get(job_id)["warnings"]
            self._update(job_id, status="done", summary=summary)
        except Exception as exc:
            summary = None
            if isinstance(exc, StageError):
                error = {"code": exc.code, "message": exc.message}
                summary = exc.details
                for name in ("topology_graph.json", "validation_report.json", "contact_sheet.png",
                             "ingestion_report.json"):
                    if (work / name).is_file():
                        shutil.copyfile(work / name, bundle / name)
            else:
                log.exception("Job %s crashed in stage %s", job_id, stage)
                error = {"code": "internal_error", "message": str(exc)}
            stages[stage] = "failed"
            self._update(job_id, status="failed", stages=stages, error=error, summary=summary)


def _playability(summary: dict) -> dict:
    validation = summary.get("validation")
    checks = {c["name"]: c["passed"] for c in (validation or {}).get("checks", [])}
    path = summary["path_check"]
    return {
        "validation_passed": validation["passed"] if validation else path["path_found"],
        "validator": "pipeline2" if validation else "path_check",
        "path_found": path["path_found"],
        "path_length": path["path_length"],
        "rooms_reachable": checks.get("rooms_reachable"),
    }


def _summarize(plan_path: Path, catalog_path: Path, legacy_files: list[dict]) -> dict:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in catalog["tiles"]}
    # Every Ground cell, and the non-empty cells of the layers after it.
    placed = [
        by_id[tile_id]
        for index, layer in enumerate(plan["layers"])
        for row in layer["grid"]
        for tile_id in row
        if index == 0 or tile_id != 0
    ]
    props = plan["map_properties"]
    summary = {
        "map_size": {"width": props["width"], "height": props["height"]},
        "tile_count_by_material": dict(Counter(t.get("material", "unknown") for t in placed)),
        "tile_count_by_category": dict(Counter(t["category"] for t in placed)),
        "entity_count_by_type": dict(Counter(o["type"] for o in plan["objects"])),
        "path_check": path_check(plan, catalog),
        "legacy_files": legacy_files,
    }
    planner = plan.get("summary", {})
    if "obstacles_placed" in planner:
        summary["overlay"] = {
            k: planner[k] for k in ("obstacles_placed", "decorations_placed", "obstacles_removed")
        }
    return summary
