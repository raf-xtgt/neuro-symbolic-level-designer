Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 1.2, 1.3, 3, 4.3, 5.2, 6.1, 8 and 9,
@BUILD_LOG.md Log-24 to Log-35, and @neuro-symbolic-level-designer/backend/ (especially `pipeline/ingestion/`,
`pipeline/llm/`, `asset_packs/grassland_full/`, `app/jobs.py`).

## Goal
Implement Pipeline 1 (Data Ingestion, ARCHITECTURE.md section 3) so that **uploaded spritesheets work end to end**:
upload PNG -> slice -> parallel analysis agents (Gemini vision) -> harmonizer -> `asset_catalog.json` -> the existing
Pipeline 2 and 3 -> playable level. Remove the `ingestion_not_implemented` path. Measure the result against the Flare
answer key. Aim for production quality: deterministic where possible, bounded LLM cost, caching, clear progress,
and honest error messages.

Paths starting with `lib/` or `test/` are in `z_legend_game/z_legend_game_flutter/`; all other paths are relative to
`neuro-symbolic-level-designer/backend/`. Use the LLM only through `pipeline/llm/` (`generate_structured`, which
already accepts `images`).

## Secrets
Same rules as tasks 10 and 11: never print, log, commit, or copy values from `.env` or `creds.json`.

## 1. Pre-processor (deterministic, ARCHITECTURE.md 3.1)
Build on `pipeline/ingestion/slicer.py` (contour + grid fallback).
- **Base tile size detection:** find the isometric base diamond size from the floor-like chips (2:1 diamonds with a
  full opaque diamond mask): 64 x 32, 128 x 64, or 32 x 16. If it is not 64 x 32, scale the whole sheet to the
  64 x 32 standard (`game-assets/ASSET_SPEC.md`) before slicing chips (LANCZOS), and record the scale factor.
  If no diamond is found, assume 64 x 32 and add a warning.
- **Chip clean-up:** drop chips smaller than 6 x 6 px or with fewer than 40 opaque pixels (noise); merge exact
  duplicates (same pixel hash) and record the duplicate count.
- **Deterministic geometry per chip:** tight alpha box, `rect`, and an anchor estimate: for a full base diamond,
  its center; otherwise the horizontal center of the lowest opaque rows and a foot point `H/2` above the bottom
  (H = base tile height). Also a footprint estimate in tiles from the width of the lowest opaque rows.
- **Contact sheets for the agents:** batches of at most 32 chips. Each chip drawn in a cell on a neutral checkerboard,
  scaled to fit (never upscaled beyond 2x), labeled with its chip number. The text part of the prompt lists each
  chip number with its pixel size and the deterministic estimates.

## 2. Analysis agents (ARCHITECTURE.md 3.2), Pydantic output per chip
Run in parallel over the batches (thread pool, `INGESTION_MAX_CONCURRENCY`, default 6). Each agent returns a list
with exactly one record per chip number in the batch (validate that: missing or extra chip numbers trigger the
repair path). Temperature 0.1; thinking level from configuration (`LLM_THINKING_LEVEL_VISION`, default `low`).
- **Tile Boundary Agent (3.2.1)**, hybrid: `kind` = `floor_tile` | `single_object` | `multi_tile_part` |
  `fragment` | `noise`, and `anchor_ok: bool` (is the marked foot point plausible). The deterministic anchor is kept
  unless the agent says it is wrong; then use the agent's `anchor_hint` (`bottom_center` | `diamond_center` |
  `left_edge` | `right_edge`), converted deterministically.
- **Tile Classification Agent (3.2.2):** `category` (floor, wall, obstacle, decoration, water, hazard), `walkable`,
  `material`, `family` (short snake_case name, for example `gravestone`, `tree_dead`, `barrel`), `connector: bool`
  (an edge, corner, or transition piece that only makes sense next to matching tiles: cliffs, riverbanks, fences,
  water edges), and `description` (max 80 characters).
- **Collision and Physics Agent (3.2.3)**, hybrid: the collision polygon is deterministic (OpenCV contour of the
  sprite's opaque base: the lowest `H` px band, simplified to at most 8 points, in sprite pixels). The agent returns
  `blocks_movement`, `blocks_projectiles`, `height_class` (`flat` | `low` | `tall`).
- **Entity and Prop Extractor Agent (3.2.4):** `is_character` (a person, creature, or enemy sprite; excluded from the
  catalog, ARCHITECTURE.md 1.3), `is_interactive` (chest, door, lever, sign), `is_editor_marker` (arrows, grid
  markers, text). Flagged chips are excluded from the catalog and listed in the report.

System instructions describe the isometric 64 x 32 standard, what each field means, and give 2 or 3 short examples.
Keep each agent's prompt and schema in its own module under `pipeline/ingestion/agents/`.

## 3. Legacy tilesets (optional input, ARCHITECTURE.md 3.1)
- Parse uploaded `.tsj` and `.tsx`: tile size, columns, margin, spacing, image name, image size, per-tile properties
  (`category`, `walkable`, `material`, `type`/`class`, `tags`).
- If a legacy tileset's image name or pixel size matches an uploaded spritesheet, use its grid rectangles as the chips
  for that sheet (skip contour slicing) and its properties as ground truth: agents only fill the fields the tileset
  does not define. Record which fields came from the tileset.
- Legacy maps stay parsed and summarized (as now); additionally record per-GID usage counts in the ingestion report.

## 4. Asset Harmonizer (ARCHITECTURE.md 3.3)
- **Deterministic merge** into one record per chip -> catalog tiles in the 6.1 schema: contiguous ids, `name` =
  `<family>_<nn>`, `source`, `rect`, `anchor`, `category`, `walkable`, `material`, `tags` (family, `tall` for
  `height_class = tall`, `prop` for single objects, `autotile_required` for connectors, `interactive`),
  `collision_polygon`, `source_ref` = `upload:<sheet>#<chip>`.
- **Exclusions:** `noise`, `fragment`, characters, editor markers, and `multi_tile_part` (no multi-tile assembly yet).
  All listed in the report with the reason.
- **Conflict rules** (deterministic detection): `wall` or `obstacle` with `walkable = true`; `floor` with
  `blocks_movement = true`; `floor` whose `kind` is not `floor_tile`; `decoration` with `height_class = tall` and
  `blocks_movement = false`. Only conflicting chips go to **LLM arbitration** (one batched call per up to 32
  conflicts, with the chip images and all agent outputs); the arbiter returns the final fields and a one-line reason.
- **Family normalization:** families with one member stay; similar names are merged deterministically (lowercase,
  singular, strip digits; for example `gravestones` -> `gravestone`).
- **Quality gate:** the catalog needs at least one walkable floor family with 2 or more tiles. Otherwise fail with
  error code `ingestion_no_floor` and a clear message (for example "no isometric floor tiles found; the sheet looks
  like character sprites").

## 5. Integration
- `pipeline/ingestion/run.py`: uploads run Pipeline 1; asset packs work as now. Uploaded sheets and legacy files are
  combined into one catalog.
- **Source paths:** catalog `source` for uploads is relative to the job folder (for example `inputs/sheet_0.png`).
  Extend `run_compile` with a `source_root` argument (default: repository root, so asset packs are unchanged) and pass
  the job folder for uploads. The scaled sheet (section 1) is stored in `work/` and referenced from there.
- **Cache:** results keyed by SHA-256 of the sheet bytes + legacy files + a `PIPELINE1_VERSION` constant, stored in
  `data/ingestion_cache/<key>/` (catalog, report, contact sheet, scaled sheet). A cache hit skips all LLM calls and is
  reported as `cached`.
- **Progress:** `ingestion_steps` in the job status, like `planning_steps`:
  `preprocess` (chips, tile size, scale), `boundary_agent`, `classification_agent`, `collision_agent`,
  `entity_agent` (each with batches done / total), `harmonizer` (tiles, exclusions, conflicts, arbitration calls),
  `quality_gate`. Update `job.json` as batches finish.
- **Job summary:** ingestion block with tile counts by category and family, exclusions by reason, conflicts and
  resolutions, cache hit, LLM usage for ingestion (calls, tokens, time), and the detected tile size and scale.
- **Bundle:** also serve `contact_sheet.png` and `ingestion_report.json` for upload jobs.
- **Error codes:** `ingestion_no_floor`, plus the LLM codes from task 11 (`llm_unavailable`, `llm_output_invalid`,
  `llm_config`).

## 6. Level Designer UI (Flutter)
- Remove the "Custom spritesheet ingestion is not available yet" note.
- Under "1. Data Ingestion", show `ingestion_steps` as sub-rows (with batch progress), like planning.
- Result: for upload jobs, show the contact sheet image and an ingestion summary (tiles by category, top families,
  exclusions, conflicts resolved, cache hit, LLM usage).
- Friendly message for `ingestion_no_floor`.
- Widget tests with a fake API for the ingestion sub-rows and the summary.

## 7. Evaluation (`tools/evaluate_ingestion.py` -> `eval/pipeline1_report.md`)
Run live and record fixtures (`LLM_MODE=record`):
1. **`game-assets/grassland_tiles.png` against the Flare answer key** (`asset_packs/grassland_full/asset_catalog.json`
   plus the excluded sections in `pack.json`): chip matching by tight-box IoU >= 0.5; for matched chips: category
   accuracy, walkable accuracy, `autotile_required` (connector) precision and recall against the cliffs and water
   sections, anchor error in px (median, 90th percentile), family agreement (manual table of the 10 most common
   families). Confusion matrix of categories.
2. **`game-assets/tileset_desert.png`** (new theme, same grid): summary and a qualitative review of 20 random chips.
3. **`sheet_ground_128x64_shaded.png`** from `game-assets/grassland_sheets.zip` (extract to a temp folder): tile size
   detection must find 128 x 64 and scale to 64 x 32.
4. **Kenney** (`game-assets/kenney_isometric-miniature-farm.zip` has single PNGs, no sheet): compose a test sheet from
   16 files of its `Isometric/` folder (transparent 8 px gutters, deterministic order) under
   `tests/fixtures/kenney_farm_sheet.png`; report slicing, the detected scale, and classification.
5. **End to end:** upload `grassland_tiles.png` with the AI planner through the API; the job finishes, validation
   passes, the level loads (compile + the Flutter loader test with a recorded bundle). Report the total time cold and
   with a cache hit.
6. **Negative case (local only; `death_city.zip` is git-ignored):** a Game Gland character sheet (for example
   `death_city/assets/survivor.png`, extracted to a temp folder) must fail with `ingestion_no_floor` and list the
   chips as characters. Skip with a clear message if the zip is missing.

The report has totals, per-section tables, the confusion matrix, cost (calls, tokens) and time per sheet, and a
short list of failure patterns with examples (chip numbers and contact sheet crops saved under `eval/ingestion/`).

## 8. Tests (offline)
- Tile size detection and scaling (synthetic 64 x 32 and 128 x 64 diamonds), noise and duplicate filtering, anchor
  and footprint estimates, contact sheet batching (32 per batch, labels), collision polygon extraction.
- Each agent with `FakeProvider`: batch completeness validation (missing chip -> repair path), field parsing.
- Harmonizer: merge, exclusions by reason, every conflict rule, arbitration call only for conflicts, family
  normalization, quality gate.
- Legacy `.tsj` and `.tsx` parsing and the "tileset wins" rule.
- Cache: second run with the same bytes makes no LLM call.
- API end to end in replay mode: upload `grassland_tiles.png` -> `done`, bundle has `contact_sheet.png` and
  `ingestion_report.json`; upload without a floor -> `ingestion_no_floor`.
- Asset pack jobs and `grassland_starter` output unchanged. All existing tests pass.

## Constraints
- Do not change `game-assets/`, `tools/prepare_characters.py`, `.bob/`, or the docs (I update ARCHITECTURE.md from
  your report).
- Keep the Flare definition as the answer key only; it must not be used by the ingestion pipeline itself.
- LLM cost bound: at most 2 vision agents with an LLM call per batch plus 2 hybrid agents that call the LLM per batch
  only for the fields listed above; arbitration only for conflicts. Report calls and tokens per sheet.

## Done when
- Backend `uv run pytest` passes offline; Flutter `dart analyze` 0 issues, `flutter test` passes, `flutter build web`
  succeeds.
- `eval/pipeline1_report.md` exists with real numbers for all 6 evaluation items.
- A live upload of `grassland_tiles.png` through the Level Designer flow (API) produces a playable, validated level.
- Report: the main numbers (chip recall, category and walkable accuracy, connector precision and recall, anchor
  error), cost and time per sheet (cold and cached), schema changes, and known weaknesses. No secret values.
