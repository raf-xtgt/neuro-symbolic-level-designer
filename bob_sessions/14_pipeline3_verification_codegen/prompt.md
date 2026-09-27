Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 5 (5.3 and 5.4), 7 and 9, and these files:
`backend/pipeline/execution/` (all), `backend/pipeline/planning/run.py`, `backend/app/jobs.py`, `backend/app/main.py`,
`z_legend_game/z_legend_game_flutter/lib/game/level/level_loader.dart`,
`z_legend_game/z_legend_game_flutter/lib/game/characters/zombie_component.dart`,
`z_legend_game/z_legend_game_flutter/lib/designer/level_designer_screen.dart`.

## Working rules (token budget)
- Write the code and small unit tests for the new logic only. Run `uv run pytest` and `flutter test` once at the end.
- No evaluation scripts or report regeneration. LLM fixtures: record only the new calls that the tests need
  (`LLM_MODE=record`), and list them.
- Report briefly. I review and test manually.

## Goal
Finish Pipeline 3 (ARCHITECTURE.md section 5): every level bundle gets a **verification report** (`summary.json`) and
**Flame integration code** (`level_loader.dart`) that a developer can drop into their own Flame project. Add a
**bundle download** so the output is portable. Also wire the entity behavior into our game so the generated
configuration has a visible effect.

All backend paths are relative to `neuro-symbolic-level-designer/backend/`; `lib/` and `test/` are in
`z_legend_game/z_legend_game_flutter/`.

## 1. Entity mechanics agent (LLM, ARCHITECTURE.md 5.3, structured output only)
- `pipeline/execution/mechanics.py`: one `generate_structured` call per level (skip it for the placeholder planner:
  use defaults). Input: the prompt, the room list (id, purpose, description, enemy count), entity types present.
  Output (Pydantic): per room with enemies: `chase_range_tiles` (3 to 8), `step_interval_ms` (250 to 600, lower =
  faster), `behavior` (`idle_until_near` | `patrol_room` | `guard_exit`), and a one-line `rationale`.
  Temperature 0.2, small thinking level. Validate room ids against the plan.
- The planner writes these values as **Tiled object properties** on each `Zombie` object
  (`chase_range`, `step_interval_ms`, `behavior`, `room_id`). The level plan stays in the 6.3 format (object
  `properties`).
- The LLM never writes Dart code. Code comes only from templates (section 2).
- Errors: `LLMError` subclasses fall back to defaults (chase 5, step 350 ms, `idle_until_near`) with a warning in the
  summary; this call must never fail a level.

## 2. Template-assisted Flame code generator (Jinja2, ARCHITECTURE.md 5.3)
- Add `jinja2` (pinned). Template `pipeline/execution/templates/level_loader.dart.j2`, renderer
  `pipeline/execution/codegen.py`, output `level_loader.dart` in the bundle.
- The generated file is **self-contained** (depends only on `flame`, `flame_tiled`, `flutter`) and contains:
  - A doc header: prompt, generator version, map size, tile size, entity counts, and "generated, do not edit".
  - `const` level metadata (map file name, map size, tile size).
  - The TMJ loading helper for flame_tiled 3.1.2 (the same normalization as our `LevelLoader._normalizeForTiled`,
    rendered from the template), so `.tmj` files with embedded tilesets load.
  - One `ZombieConfig`-style typed config class per enemy entity type, with `fromProperties(...)`.
  - An abstract `LevelEntityFactory` with one typed method per entity type present in this level
    (`spawnPlayerSpawn(Vector2 position)`, `spawnZombie(Vector2 position, ZombieConfig config)`,
    `spawnExitTrigger(Vector2 position)`), generated from the level's object types.
  - A `GeneratedLevel extends PositionComponent with HasGameReference` that loads the map, converts isometric object
    coordinates to grid cells (tile-height units, ARCHITECTURE.md 6.3) and to world positions, calls the factory,
    and adds a diamond `PolygonHitbox` for every blocked cell of the `Objects` layer (blocked = tile property
    `walkable == false`).
- Names in the template come from sanitized entity types (valid Dart identifiers; reject anything else).

## 3. Verification engine (ARCHITECTURE.md 5.4) -> `summary.json`
Written at the end of the execution stage into the bundle. Contents:
- Level: job id, prompt, planner, source (asset pack id or uploaded sheet names), map size, tile size.
- Counts: tiles by category and material, entities by type, zombies by behavior.
- Playability: validation passed, path length spawn -> exit, rooms reachable.
- **Checks** (each `{name, passed, detail}`): `tmj_parses`, `gids_resolve` (every GID maps to a tileset tile),
  `images_exist` (every tileset image referenced by `level.tmj` is in the bundle with the declared size),
  `atlas_fits` (area use of the 4096 x 4096 web atlas, in %), `objects_on_walkable`, `dart_analyze` (see below).
- `dart_analyze`: run `dart analyze` on the generated file inside a small scratch package
  `codegen_check/` (committed `pubspec.yaml` with `flame`, `flame_tiled`, `flutter` versions matching the game;
  resolved once with `flutter pub get --offline` if possible). Copy the file in, analyze, remove it. If `dart` is not
  on `PATH` or the package cannot resolve, the check is `skipped` with the reason (never fails the job). Timeout 60 s.
- Timings per stage, LLM usage per pipeline (ingestion, planning, mechanics), files in the bundle with size and
  SHA-256, generator versions.
- The job summary includes a short verification block (checks passed / total, `dart_analyze` result).

## 4. API
- Bundle: allow `level_loader.dart` and `summary.json`.
- `GET /api/levels/{job_id}/bundle.zip`: a zip of every bundle file (only the allowed names), for `done` jobs.

## 5. Game and UI (Flutter)
- `ZombieComponent`: read `chase_range`, `step_interval_ms`, and `behavior` from its Tiled object properties when
  present; defaults otherwise. `patrol_room`: when the player is out of range, walk to random open cells inside its
  room (use the `room_id` cells: the planner also writes each room's rectangle as properties on a `Rooms` object layer,
  or pass the rectangle on the zombie object; choose the smaller change and say which). `guard_exit`: stay within
  3 tiles of the exit unless the player is in range.
- Level Designer result: a "Verification" section (checks with pass / fail / skipped, atlas use, `dart_analyze`
  result) and a **"Download bundle (.zip)"** button (browser download of `bundle.zip`). Show the zombie behaviors
  per room in the room list.

## 6. Tests
- Mechanics agent with `FakeProvider`: valid output, unknown room id rejected, LLM error -> defaults + warning.
- Codegen: rendering for a level with and without zombies; identifiers sanitized; the output contains one factory
  method per entity type; golden check of the doc header fields.
- `dart_analyze` check: an integration test marked to skip when `dart` is missing; a broken template output is
  reported as failed.
- Verification checks: one failing case each for `gids_resolve`, `images_exist`, `objects_on_walkable`.
- API: `bundle.zip` contents; `summary.json` and `level_loader.dart` served.
- Flutter: zombie reads properties (and defaults); `patrol_room` keeps the zombie inside its room; widget test for
  the verification section and the download button with a fake API.
- Existing tests pass; asset pack outputs change only by the new files and the new zombie properties.

## Done when
`uv run pytest` and `flutter test` pass, `dart analyze` on the game is clean, and the report lists new fixtures and
where the room rectangle for `patrol_room` comes from.
