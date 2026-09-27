"""
Planning stage (Pipeline 2, ARCHITECTURE.md section 4).

Input:  the design prompt and ``asset_catalog.json``.
Output: ``<work_dir>/level_plan.json``, validated against the 6.3 schema.

Planners:
  * ``agentic`` (default): the LangGraph pipeline in ``graph.py`` (LLM
    topology agent + deterministic layout, spawner, dressing, validator).
    Also writes ``topology_graph.json`` and ``validation_report.json``.
  * ``placeholder``: the temporary seeded planner (``placeholder_planner.py``).

Both are seeded by a stable hash of the prompt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from pipeline.errors import StageError
from pipeline.llm.base import LLMConfigError, LLMError, LLMOutputError, LLMProvider, LLMUnavailableError
from pipeline.planning.graph import PlanningFailed, PlanningOutcome, StepCallback, plan_with_llm
from pipeline.planning.placeholder_planner import plan_level, seed_from_prompt

PLANNERS = ("agentic", "placeholder")
DEFAULT_PLANNER = "agentic"
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "level_plan.schema.json"


@dataclass
class PlanningResult:
    plan_path: Path
    planner: str
    summary: dict = field(default_factory=dict)  # planner facts for the job summary
    warnings: list[str] = field(default_factory=list)
    extra_files: list[Path] = field(default_factory=list)  # to serve with the bundle


def run_planning(
    prompt: str,
    catalog_path: Path,
    work_dir: Path,
    planner: str = DEFAULT_PLANNER,
    on_step: StepCallback | None = None,
    provider: LLMProvider | None = None,
) -> PlanningResult:
    if planner not in PLANNERS:
        raise StageError("planning_failed", f"unknown planner {planner!r}; use one of {', '.join(PLANNERS)}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    seed = seed_from_prompt(prompt)

    if planner == "placeholder":
        try:
            plan = plan_level(catalog, seed)
        except ValueError as exc:
            raise StageError("planning_failed", str(exc)) from exc
        return PlanningResult(_write_plan(plan, work_dir), planner, {"planner": planner})

    try:
        if provider is None:
            from pipeline.llm.factory import get_provider
            provider = get_provider()
        outcome = plan_with_llm(prompt, catalog, seed, provider, on_step)
    except PlanningFailed as exc:
        files = _write_reports(exc.outcome, work_dir)
        raise StageError(
            "plan_validation_failed", str(exc), details=_summary(planner, exc.outcome, files),
        ) from None
    except LLMConfigError as exc:
        raise StageError("llm_config", str(exc)) from None
    except LLMOutputError as exc:
        raise StageError("llm_output_invalid", str(exc)) from None
    except (LLMUnavailableError, LLMError) as exc:
        raise StageError("llm_unavailable", str(exc)) from None

    files = _write_reports(outcome, work_dir)
    return PlanningResult(
        _write_plan(outcome.plan, work_dir), planner, _summary(planner, outcome, files), outcome.warnings, files,
    )


def _write_plan(plan: dict, work_dir: Path) -> Path:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=plan, schema=schema)
    except jsonschema.ValidationError as exc:
        raise StageError("plan_invalid", exc.message) from exc
    plan_path = work_dir / "level_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan_path


def _write_reports(outcome: PlanningOutcome, work_dir: Path) -> list[Path]:
    files = []
    if outcome.topology is not None:
        path = work_dir / "topology_graph.json"
        path.write_text(outcome.topology.model_dump_json(indent=2), encoding="utf-8")
        files.append(path)
    if outcome.report is not None:
        path = work_dir / "validation_report.json"
        path.write_text(json.dumps(outcome.report, indent=2), encoding="utf-8")
        files.append(path)
    return files


def _summary(planner: str, outcome: PlanningOutcome, files: list[Path]) -> dict:
    topology = outcome.topology
    summary: dict = {
        "planner": planner,
        "attempts": outcome.attempts,
        "llm_usage": outcome.usage,
        "validation": outcome.report,
    }
    if topology is not None:
        summary["theme"] = topology.theme
        summary["design_notes"] = topology.design_notes
        summary["rooms"] = [
            {
                "id": r.id, "purpose": r.purpose, "size": r.size, "relative_position": r.relative_position,
                "description": r.description, "enemy_count": r.enemy_count,
            }
            for r in topology.rooms
        ]
    return summary
