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


class JobStatus(BaseModel):
    job_id: str
    status: JobStatusName
    stages: dict[str, StageStatus]
    created_at: str
    updated_at: str
    warnings: list[str]
    error: JobError | None = None
    summary: dict[str, Any] | None = None
