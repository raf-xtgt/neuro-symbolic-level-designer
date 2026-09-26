"""
FastAPI backend (ARCHITECTURE.md section 8).

Run from ``backend/``:  uv run uvicorn app.main:app --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import UploadFile

from app.asset_packs import BACKEND_DIR, DEFAULT_PACKS_DIR, discover_packs
from app.jobs import BUNDLE_FILES, JobManager, LevelRequest, Upload, parse_job_id
from app.models import (
    AssetPackInfo,
    FieldError,
    Health,
    JobStatus,
    LevelCreated,
    TileSize,
    ValidationErrors,
)
from app.uploads import MAX_FILE_BYTES, check_map, check_png, check_tileset

MAX_PROMPT_CHARS = 2000
FILE_LIMITS = {"spritesheets": 10, "tilesets": 10, "maps": 5}


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not found"}, status_code=404)


def _errors(errors: list[FieldError]) -> JSONResponse:
    return JSONResponse(ValidationErrors(errors=errors).model_dump(), status_code=422)


def create_app(
    data_dir: Path = BACKEND_DIR / "data", packs_dir: Path = DEFAULT_PACKS_DIR
) -> FastAPI:
    app = FastAPI(title="Neuro-Symbolic Level Designer")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    packs = discover_packs(packs_dir)
    jobs = JobManager(data_dir)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _errors(
            [
                FieldError(field=".".join(str(p) for p in e["loc"][1:]), message=e["msg"])
                for e in exc.errors()
            ]
        )

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health()

    @app.get("/api/asset-packs", response_model=list[AssetPackInfo])
    def list_asset_packs() -> list[AssetPackInfo]:
        return [
            AssetPackInfo(
                id=p.id,
                name=p.name,
                description=p.description,
                spritesheets=[s.name for s in p.spritesheets],
                tile_size=TileSize(width=p.tile_width, height=p.tile_height),
            )
            for p in packs.values()
        ]

    @app.post(
        "/api/levels",
        status_code=202,
        response_model=LevelCreated,
        responses={422: {"model": ValidationErrors}},
    )
    async def create_level(request: Request):
        form = await request.form(max_files=sum(FILE_LIMITS.values()) + 20)
        errors: list[FieldError] = []

        def err(field: str, message: str) -> None:
            errors.append(FieldError(field=field, message=message))

        # prompt
        raw_prompt = form.get("prompt")
        prompt = raw_prompt.strip() if isinstance(raw_prompt, str) else ""
        if raw_prompt is None:
            err("prompt", "is required")
        elif not isinstance(raw_prompt, str):
            err("prompt", "must be text")
        elif not prompt:
            err("prompt", "must not be empty")
        elif len(prompt) > MAX_PROMPT_CHARS:
            err("prompt", f"must be at most {MAX_PROMPT_CHARS} characters")

        # files
        uploads: dict[str, list[Upload]] = {}
        for name, limit in FILE_LIMITS.items():
            uploads[name] = []
            items = form.getlist(name)
            # A form with no file chosen sends one empty, unnamed part.
            items = [i for i in items if not (isinstance(i, UploadFile) and not i.filename and not i.size)]
            if len(items) > limit:
                err(name, f"at most {limit} files are allowed, got {len(items)}")
                continue
            for i, item in enumerate(items):
                field = f"{name}[{i}]"
                if not isinstance(item, UploadFile):
                    err(field, "must be a file")
                    continue
                data = await item.read()
                if len(data) > MAX_FILE_BYTES:
                    err(field, f"is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
                    continue
                original = (item.filename or "")[:255]
                ext = Path(original).suffix.lower()
                if name == "spritesheets":
                    problem, ext = check_png(data), ".png"
                elif name == "tilesets":
                    problem = check_tileset(ext, data)
                else:
                    problem = check_map(ext, data)
                if problem:
                    err(field, f"'{original}' {problem}")
                else:
                    uploads[name].append(Upload(original_name=original, ext=ext, data=data))

        # spritesheet source
        pack_id = form.get("asset_pack")
        pack_id = pack_id.strip() if isinstance(pack_id, str) else pack_id
        pack = None
        if pack_id:
            if not isinstance(pack_id, str) or pack_id not in packs:
                err("asset_pack", f"unknown asset pack; available: {', '.join(sorted(packs))}")
            else:
                pack = packs[pack_id]
        sheet_errors = any(e.field.startswith("spritesheets") for e in errors)
        if not uploads["spritesheets"] and not pack_id and not sheet_errors:
            err("spritesheets", "upload at least one spritesheet or choose an asset_pack")

        if errors:
            return _errors(errors)

        warnings = []
        if uploads["spritesheets"] and pack:
            warnings.append(
                f"asset_pack '{pack.id}' was ignored because spritesheets were uploaded"
            )
        job_id = jobs.create(
            LevelRequest(
                prompt=prompt,
                pack_catalog=None if uploads["spritesheets"] else pack.catalog,
                spritesheets=uploads["spritesheets"],
                tilesets=uploads["tilesets"],
                maps=uploads["maps"],
                warnings=warnings,
            )
        )
        return LevelCreated(
            job_id=job_id,
            status_url=f"/api/levels/{job_id}",
            bundle_url=f"/api/levels/{job_id}/bundle/",
        )

    @app.get("/api/levels/{job_id}", response_model=JobStatus, responses={404: {}})
    def job_status(job_id: str):
        canonical = parse_job_id(job_id)
        job = jobs.get(canonical) if canonical else None
        return JobStatus(**job) if job else _not_found()

    @app.get("/api/levels/{job_id}/bundle/{file}", responses={404: {}})
    def bundle_file(job_id: str, file: str):
        canonical = parse_job_id(job_id)
        path = jobs.bundle_file(canonical, file) if canonical else None
        if path is None:
            return _not_found()
        return FileResponse(path, media_type=BUNDLE_FILES[file])

    return app


app = create_app()
