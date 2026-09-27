Read @neuro-symbolic-level-designer/z_legend_game/AGENTS.md and these files:
`lib/game/z_legend_game.dart`, `lib/game/characters/player_component.dart`, `lib/game/characters/zombie_component.dart`,
`lib/designer/level_designer_screen.dart`, `lib/designer/api/models.dart`, and in `backend/`:
`pipeline/planning/dressing.py`, `pipeline/planning/catalog_digest.py`, `app/main.py`.

## Working rules (token budget)
- Code plus small unit or widget tests for the new logic only. Run `uv run pytest` and `flutter test` once at the end.
- No live LLM runs, no evaluation scripts. I test the uploads in the browser myself.
- Report briefly.

Paths starting with `lib/` or `test/` are in `z_legend_game/z_legend_game_flutter/`.

## 1. Player health (game)
- The player has **6 health points**. The death overlay appears only at 0.
- A zombie **attacks** when it is on a cell next to the player (Chebyshev distance 1) or on the same cell: it stops
  moving, faces the player, plays its `attack` animation, and deals 1 damage. Each zombie has an attack cooldown of
  1.0 s. After a hit, the player is invulnerable for 0.6 s and flashes (opacity blink). Zombies do not step onto the
  player's cell.
- **Health bar HUD** in the camera viewport, top left: 6 segments (filled red / empty dark), with a small "HP" label.
  It updates on every hit and resets on restart (R).
- Space attack stays as it is.
- Tests: 6 hits kill the player, not 5; cooldown and invulnerability timing; the HUD shows the right number of filled
  segments.

## 2. More spritesheets for variety (tool + robustness)
- `tools/compose_kenney_sheet.py` (repository root `tools/`, Python + Pillow): reads a Kenney isometric miniature zip,
  takes every file in `Isometric/` that ends with `_S.png` (one facing per object), and packs them into one sheet with
  8 px transparent gutters, in sorted order, rows at most 2048 px wide. Write
  `game-assets/kenney_farm_sheet.png` (from `kenney_isometric-miniature-farm.zip`) and
  `game-assets/kenney_library_sheet.png` (from `kenney_isometric-miniature-library.zip`). Commit both (CC0). This is
  the only allowed change in `game-assets/`.
- The desert sheet (`game-assets/tileset_desert.png`) is uploaded as is.
- Robustness of Pipeline 2 for small or unusual catalogs (these sheets have no trees; the library is an indoor set):
  - Wilderness and hedge fall back to any blocking obstacle group that is not a `structure` or `structure_part` when
    there are no tree, pillar, or low-blocker families (for example hay bales or crates on the farm, bookcases in the
    library).
  - If the catalog has only one floor family, corridors use it too (no `floor.stone` required).
  - Tests with `FakeProvider` and two small synthetic catalogs (a farm-like one: 2 floor families, crates, hay, sacks,
    no trees; a library-like one: 1 floor family, bookcases, tables): the planner produces a valid level, the hedge
    encloses the playable area, and no `structure_part` is placed.

## 3. Hide the planner choice; friendlier progress text (UI)
- Remove the "Planner" dropdown. Always send `planner=agentic` (keep the API field as it is).
- Progress sub-rows: show a friendly label per step while it runs, for example:
  - Ingestion: `preprocess` "Slicing the spritesheet...", `boundary_agent` "AI-powered tile boundary analysis is
    running...", `classification_agent` "AI-powered tile classification is running...", `collision_agent`
    "AI-powered collision analysis is running...", `entity_agent` "AI-powered entity detection is running...",
    `harmonizer` "Building the asset catalog...", `quality_gate` "Checking for floor tiles...".
  - Planning: `topology_agent` "AI-powered level layout planning is running...", `layout_builder` "Placing rooms and
    corridors...", `stacking` "Setting elevation...", `spawner` "Placing the player, zombies, and exit...",
    `dressing` "Dressing the level...", `validator` "Validating playability...".
  - Execution: "AI-powered enemy behavior design is running..." for the mechanics step, then "Generating Flame code..."
    and "Verifying the bundle...". If the execution stage has no sub-steps yet, add them to the job status the same way
    as planning (`execution_steps`).
  - When a step is done, show its current detail message (as now) instead of the running label.
- Keep the batch counters (for example "3 of 10 batches") on the AI ingestion steps.

## 4. Spritesheet source: default grassland, uploads only (UI)
- Remove the "Built-in asset pack" radio and dropdown. Show only the spritesheet upload area, with the text:
  "Upload your isometric spritesheets (PNG). If you do not upload any, the default grassland spritesheet is used."
- On submit: with no uploads, send `asset_pack=grassland_full`; with uploads, send the files and no asset pack.
- The result shows which source was used ("Default grassland spritesheet" or the uploaded file names).
- Widget tests: submit without files sends `asset_pack=grassland_full`; with a file sends it and no pack.

## Done when
`uv run pytest` and `flutter test` pass, `dart analyze` is clean, and `tools/compose_kenney_sheet.py` produced both
sheets. Report the sheet sizes and object counts.
