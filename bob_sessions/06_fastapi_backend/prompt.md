Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 1.2, 1.3, 5, 6, 7 and 8, and @neuro-symbolic-level-designer/backend/.

## Goal
Build the FastAPI backend app (ARCHITECTURE.md section 8). It accepts a level request under the input contract
(section 1.2), runs it as a job through the pipeline stages, and serves the output bundle to the Flutter web app.
Pipelines 1 and 2 are not built yet. Put clean stage interfaces in place, with the temporary behavior listed below.

All paths are relative to `neuro-symbolic-level-designer/backend/`. Python 3.12, managed with `uv`.

## 1. Dependencies
Add to `requirements.txt` (pinned): `fastapi`, `uvicorn[standard]`, `python-multipart`, `httpx` (for tests).

## 2. Built-in asset packs (`asset_packs/`)
- `asset_packs/grassland_starter/pack.json`:
  `{ "id", "name", "description", "spritesheets": ["game-assets/grassland_tiles.png"], "catalog": "fixtures/starter/asset_catalog.json", "tile_size": {"width": 64, "height": 32} }`
  Spritesheet paths are relative to the repository root. The catalog path is relative to `backend/`.
- `app/asset_packs.py`: discover packs by scanning `asset_packs/*/pack.json`. Validate each manifest (files exist,
  catalog passes the 6.1 schema) at startup; skip invalid packs with a logged warning.

## 3. App (`app/`)
- `app/main.py`: FastAPI app, CORS for the Flutter dev server: `allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+"`,
  methods GET and POST.
- Endpoints exactly as in ARCHITECTURE.md section 8. Pydantic models for every response.
- `POST /api/levels` input validation (return `422` with a list of `{field, message}` errors, all errors at once):
  - `prompt`: required, trimmed, 1 to 2000 characters.
  - Spritesheet source: at least one uploaded `spritesheets` file OR a valid `asset_pack` id. Both together are
    allowed (the uploads are used; the pack is ignored and a warning is added to the job).
  - `spritesheets`: 0 to 10 files, each at most 10 MB, PNG signature check, opens with Pillow, mode convertible to RGBA.
  - `tilesets`: 0 to 10 files, extension `.tsx` (well-formed XML with root `tileset`) or `.tsj` (valid JSON object).
  - `maps`: 0 to 5 files, extension `.tmx` (well-formed XML with root `map`) or `.tmj` (valid JSON object with
    `layers`).
  - Never trust uploaded file names: store files under generated names.
- Response `202`: `{ "job_id": "<uuid4>", "status_url": "/api/levels/<id>", "bundle_url": "/api/levels/<id>/bundle/" }`.

## 4. Jobs (`app/jobs.py`)
- One folder per job: `data/jobs/<job_id>/` with `inputs/`, `work/`, `bundle/`, and `job.json` (status, stages,
  timestamps, warnings, error code and message, summary). Add `backend/data/` to `.gitignore`.
- Run the job in a background thread (one worker is enough). Status updates are written to `job.json`.
- Stages, in order. Each stage is a function in `pipeline/` with a clear input and output:
  1. **ingesting** (`pipeline/ingestion/run.py`):
     - Asset pack: copy the pack catalog to `work/asset_catalog.json`. Done.
     - Uploaded spritesheets: Pipeline 1 is not implemented. Fail the job with error code
       `ingestion_not_implemented` and a clear message.
     - Optional tilesets and maps: parse them (JSON or XML) and record in the job summary: file name, tile count,
       map size, layer count. They are not used by later stages yet.
  2. **planning** (`pipeline/planning/run.py`): Pipeline 2 is not implemented. Use a **placeholder planner**
     (`pipeline/planning/placeholder_planner.py`), clearly marked as temporary in its docstring:
     - Move the logic from `generate_level_plan.py` into it, generalized to any catalog: floor tiles by `material`,
       map size 20 x 20, a stone path corner to corner, `PlayerSpawn` at the path start, `ExitTrigger` at the path end,
       3 `Zombie` objects on walkable tiles.
     - Seed = a stable hash of the prompt, so the same prompt gives the same level.
     - Keep `generate_level_plan.py` working (it calls the placeholder planner with seed 42 and writes the fixture);
       the existing fixture must not change.
     - Validate the plan against the 6.3 schema. Write `work/level_plan.json`.
  3. **executing**: call `pipeline.execution.compile.run_compile` with `work/level_plan.json` and
     `work/asset_catalog.json`, output to `bundle/`.
- Summary on success: map size, tile count by material, entity count by type, legacy file info, warnings.

## 5. Bundle serving
- `GET /api/levels/{job_id}/bundle/{file}`: serve only the 4 allowed file names from the job's `bundle/` folder.
  Any other name returns `404`. The job id must be a valid UUID. Correct `Content-Type` for `.tmj`/`.tsj`
  (`application/json`) and `.png`.
- The embedded tileset in `level.tmj` must reference `tileset.png` by a plain relative name, so the Flutter
  `NetworkAssetBundle` with base URL `.../bundle/` resolves it.

## 6. Tests (`tests/test_api.py`, FastAPI `TestClient`)
- Health and asset pack list (contains `grassland_starter`).
- `422` cases: missing prompt, empty prompt, prompt over 2000 characters, no spritesheet and no pack, unknown pack,
  a `.png` upload that is not a PNG, a `.tsj` that is not JSON, a `.tmx` whose root is not `map`, too many files.
- Happy path with `asset_pack=grassland_starter`: poll until `done` (timeout 30 s), download all 4 bundle files,
  parse `level.tmj` (20 x 20, embedded tileset with `image: "tileset.png"`, 5 objects), and check the summary.
- Same prompt twice gives identical `level.tmj`; a different prompt gives a different ground layer.
- Upload a valid PNG spritesheet with no pack: job ends `failed` with `ingestion_not_implemented`.
- Optional files: a valid `.tsj` and `.tmj` (use the starter bundle files) are parsed and appear in the summary.
- Bundle security: unknown file name and `../` paths return `404`; invalid job id returns `404` or `422`.
- Existing tests keep passing.

## Constraints
- Do not change Dart code, `game-assets/`, `tools/`, `.bob/`, or the docs.
- Do not change the output format of `pipeline/execution/`.
- Keep the code small. No authentication, no database, no Serverpod.

## Done when (from `backend/`)
- `uv run pytest` passes.
- `uv run uvicorn app.main:app --port 8000` starts, and these work with `curl`:
  - `curl -s localhost:8000/api/asset-packs`
  - `curl -s -F prompt="graveyard with a cabin" -F asset_pack=grassland_starter localhost:8000/api/levels`
  - then the status URL until `done`, then `curl -o level.tmj <bundle_url>level.tmj`.
- Report the actual output of these commands.
