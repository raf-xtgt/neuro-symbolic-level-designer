"""Pydantic response models."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

JobStatusName = Literal["queued", "ingesting", "planning", "executing", "done", "failed"]
StageStatus = Literal["pending", "running", "done", "failed"]


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class TileSize(BaseModel):
    width: int
    height: int


class AssetPackInfo(BaseModel):
    id: str
    name: str
    description: str
    spritesheets: list[str]
    tile_size: TileSize


class FieldError(BaseModel):
    field: str
    message: str


class ValidationErrors(BaseModel):
    errors: list[FieldError]


class LevelCreated(BaseModel):
    job_id: str
    status_url: str
    bundle_url: str


class JobError(BaseModel):
    code: str
    message: str


class PlanningStep(BaseModel):
    """A planning graph node run, or an execution step (``execution_steps``)."""
    node: str
    status: Literal["running", "done", "failed"]
    attempt: int
    message: str


class IngestionStep(BaseModel):
    node: str
    status: Literal["running", "done", "failed", "cached"]
    message: str
    done: int | None = None
    total: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: JobStatusName
    stages: dict[str, StageStatus]
    created_at: str
    updated_at: str
    warnings: list[str]
    error: JobError | None = None
    summary: dict[str, Any] | None = None
    planner: str | None = None
    ingestion_steps: list[IngestionStep] = []
    planning_steps: list[PlanningStep] = []
    execution_steps: list[PlanningStep] = []
    source: dict[str, Any] = {}  # {"asset_pack": id} or {"spritesheets": [names]}
