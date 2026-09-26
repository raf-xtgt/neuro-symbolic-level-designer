Read @neuro-symbolic-level-designer/ARCHITECTURE.md (sections 5.1, 5.2, 6.1, 6.3) and @game-assets/ASSET_SPEC.md.

## Goal
Build the first slice of Pipeline 3 (Execution): the Deterministic Map Compiler and Tileset Compiler.
Drive it with hand-written fixtures. No Tiled editor, no manual map drawing.

All Python code goes under `neuro-symbolic-level-designer/backend/`. A FastAPI app will be added
to this folder later, so structure `pipeline/` as an importable Python package.

## 1. Fixtures (`backend/fixtures/starter/`)
- `asset_catalog.json` (schema: ARCHITECTURE.md 6.1). Source image `game-assets/grassland_tiles.png`.
  - Only the top 2 atlas rows, both a clean 64x32 grid:
    - Row 0 (y=0..32): 16 grass tiles, category `floor`, walkable true, material grass.
    - Row 1 (y=32..64): 16 stone path tiles, category `floor`, walkable true, material stone.
  - Entities: `PlayerSpawn` (player), `Zombie` (enemy), `ExitTrigger` (trigger).
- `level_plan.json` (schema: ARCHITECTURE.md 6.3). 20x20 isometric, 64x32.
  - Ground layer: random grass variants (fixed seed) with a stone path from one corner to the opposite corner.
  - Objects: 1 PlayerSpawn at the path start, 1 ExitTrigger at the path end, 3 Zombies on grass.
- Add JSON Schema files for 6.1 and 6.3 (`backend/pipeline/schemas/`) and validate both fixtures against them.

## 2. Compilers (`backend/pipeline/execution/`)
Python 3 + Pillow, deterministic, no LLM calls.
- `tileset_compiler.py`: catalog -> `tileset.tsj` + a packed `tileset.png` that contains only the catalog tiles
  (uniform 64x32 grid, so Tiled/flame_tiled can index it with `columns`).
- `map_compiler.py`: level plan + catalog -> `level.tmj` (orientation `isometric`, renderorder `right-down`,
  uncompressed CSV/array tile data, correct `firstgid`). Objects go in an object layer named `Entities`,
  object `type` = entity name.
- CLI, run from `backend/`: `python -m pipeline.execution.compile --plan <path> --catalog <path> --out <dir>`.
- Add `backend/requirements.txt` (pinned versions).

## 3. Output
Write to `neuro-symbolic-level-designer/z_legend_game/z_legend_game_flutter/assets/tiles/starter/`
(`level.tmj`, `tileset.tsj`, `tileset.png`). Tileset image paths in the .tsj/.tmj must be relative and
must resolve from the .tmj location.

## 4. Tests (`backend/tests/`, pytest)
- Every GID in `level.tmj` exists in the tileset.
- Map width x height = data length.
- Every object is on a walkable tile.
- Round trip: parse the generated .tmj/.tsj back and compare to level_plan.json.

## 5. Preview
Render `preview_level.png` (next to the output files): the map drawn in isometric projection from the .tmj,
with object markers. I use this to check the map without Tiled.

## Constraints
- Do not modify ASSET_SPEC.md, CREDITS.md, or the character assets.
- Do not change Dart code or pubspec.yaml in this task.
- Do not use Serverpod. The backend is Python + FastAPI (see BUILD_LOG.md Log-8).

## Done when
- `pytest` (run from `backend/`) passes.
- preview_level.png shows a 20x20 diamond-shaped map with a stone path and 5 markers.

---

## Prompt 2: Isometric object coordinate fix

Object coordinates in `level.tmj` use the wrong convention (x = col * tile_width, y = row * tile_height).
For isometric maps, Tiled and flame_tiled expect both x and y in tile-height units on the unprojected grid:
x = col * tile_height, y = row * tile_height. Example: the exit at col 19, row 19 is now (1216, 608),
which flame_tiled places outside the 20x20 map.

1. In `level_plan.json`, store object positions as tile coordinates (`col`, `row`), not pixels.
   Update `level_plan.schema.json` and `generate_level_plan.py` to match.
2. In `map_compiler.py`, convert tile coordinates to Tiled isometric object coordinates at the tile center:
   x = (col + 0.5) * tile_height, y = (row + 0.5) * tile_height.
3. Update `preview_renderer.py` to project objects from Tiled isometric object coordinates
   (screen_x = (x - y) * tile_width / (2 * tile_height), screen_y = (x + y) / 2), so the preview
   uses the same convention flame_tiled uses.
4. Add a test: every object in `level.tmj` satisfies 0 <= x < width * tile_height and 0 <= y < height * tile_height,
   and maps back to the same (col, row) as in level_plan.json.
5. Add `.pytest_cache/` to `.gitignore`. Regenerate the output files and the preview.
