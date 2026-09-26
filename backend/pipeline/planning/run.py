"""
Planning stage (Pipeline 2, ARCHITECTURE.md section 4).

Input:  the design prompt and ``asset_catalog.json``.
Output: ``<work_dir>/level_plan.json``, validated against the 6.3 schema.

Pipeline 2 is not implemented: the temporary placeholder planner builds the
plan, seeded by a stable hash of the prompt.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from pipeline.errors import StageError
from pipeline.planning.placeholder_planner import plan_level, seed_from_prompt

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "level_plan.schema.json"


def run_planning(prompt: str, catalog_path: Path, work_dir: Path) -> Path:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    try:
        plan = plan_level(catalog, seed_from_prompt(prompt))
    except ValueError as exc:
        raise StageError("planning_failed", str(exc)) from exc

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=plan, schema=schema)
    except jsonschema.ValidationError as exc:
        raise StageError("plan_invalid", exc.message) from exc

    plan_path = work_dir / "level_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan_path
