Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 3.4 and 4.3, and these files in
`neuro-symbolic-level-designer/backend/`: `pipeline/planning/dressing.py`, `validator.py`, `catalog_digest.py`,
`pipeline/ingestion/harmonizer.py`, `asset_packs/grassland_full/build_pack.py`.

## Working rules (token budget)
- Write the code and small unit tests for the new logic only.
- Run `uv run pytest` once at the end (offline, replay mode). Run `flutter test` only if you change Dart code.
- **No live LLM runs, no evaluation scripts, no report regeneration.** If a replay fixture misses because a prompt
  input changed (for example the catalog digest), re-record only those fixtures with `LLM_MODE=record`, and list them.
- Report briefly: what changed, tests added, fixtures re-recorded. I review and test manually.

## Goal
Levels look designed, not scattered: less rock rubble, stronger themes, and no half buildings.

## 1. Wilderness: a hedge instead of a rubble field (`dressing.py`)
Today every cell outside rooms and corridors is filled, and the camera clearance band in front of playable cells is
6 steps of small rocks (`SHORT_DEPTH = 6`), which dominates the view.
- Build a **hedge**: the blocking ring around the playable area (rooms + corridors), 2 cells thick, 8-connected.
  With the no-corner-cutting rule this fully encloses the playable area.
  - Hedge cells in front of playable cells (the current camera-clearance test) use low blockers only:
    `rock_small`, `logs`, `sack`, `cart`, `stump` families if present, weighted toward the style's obstacle groups.
  - Other hedge cells: trees and rock pillars, weighted toward the style.
- **Beyond the hedge:**
  - Back and side zones (not in front of playable cells): dense trees and pillars as now.
  - Front zone (inside the camera-clearance band): the main floor with sparse decorations (about 15%, from the
    style's decoration groups), no blockers. This area is unreachable, so it may stay walkable.
  - Reduce the band to `SHORT_DEPTH = 3` and `PILLAR_DEPTH = 8`.
- Style weight: at least 80% of trees in the hedge and back zones come from the style's tree groups when the style
  names any (for example `obstacle.tree_dead`).

## 2. Validator: boundary integrity by reachability (`validator.py`)
Change `boundary_integrity` to: no cell **reachable from the spawn** (movement rule) lies on the outer ring of the
map. Unreachable walkable cells (the front zone) are allowed. Keep the "no blocking tiles" skip.

## 3. Themed props inside rooms (`dressing.py`)
- New densities: entrance 4%, combat 8%, puzzle 12%, treasure 10%, boss 6% (boss center 3 x 3 still clear).
- Place props in **clusters** of 2 to 4 cells of the same group (seeded), not one by one, with at least 1 open cell
  between clusters.
- Each room with its own `dressing` gets at least 2 clusters from its non-floor dressing groups (for example the
  graveyard room gets gravestone clusters).
- Keep the existing guarantees (spawn and exit neighborhoods clear, corridors clear) and run the existing
  `ensure_path` logic if a cluster blocks the path.

## 4. Multi-tile parts and structures
Pieces of multi-tile assemblies (house or tent slices, tower parts) must never be placed alone.
- First, check how the cabin in the recorded upload job was formed (`eval/ingestion/grassland_ingestion_report.json`
  and its catalog): were the kept building chips whole buildings (one wide chip) or slices? Report it in 2 lines.
- **Harmonizer:** tag a tile `structure_part` when the Boundary Agent says `multi_tile_part`, or when its family is a
  building family (`house`, `cabin`, `building`, `hut`, `tent`, `tower`, `roof`, and `*_wall` pieces narrower than
  the object they belong to). Tag a tile `structure` when it is a whole building in one chip (footprint wider than
  1 tile).
- **Grassland full pack:** tents and buildings stay excluded (no change).
- **Catalog digest:** exclude `structure_part` like `fence`. Put `structure` tiles in groups
  `structure.<family>` with a description that says they are placed at most once per room.
- **Dressing:** a `structure.*` group named in a room's `dressing` is placed once in that room, on free cells that
  cover its footprint (cells along the east diagonal `(col + i, row - i)` for footprint width `i`), all footprint
  cells blocked, not blocking the room's connectivity (`ensure_path`). Never placed in corridors or the hedge.
- Game: no change expected; the sprite is anchored on its first footprint cell. Say so if you find otherwise.

## Done when
`uv run pytest` passes (with only the fixtures listed as re-recorded), and the report above is short.

---

## Prompt 2: Front hedge looks like a junkyard

Same working rules as above (code + small unit tests, `uv run pytest` once, no live LLM runs).

**Review finding (replay previews of "graveyard with a cabin and a boss arena" and "a winding path through dead
trees to a boss clearing in the north"):** the themes now read well (dead trees, gravestone and campfire clusters,
open grass in front). But the front hedge is 2 rows of carts, sacks, logs, and stumps along every room edge in front,
so each room looks walled by junk. Carts and sacks are camp props, not a natural boundary.

**Fix in `pipeline/planning/dressing.py`:**
1. `LOW_FAMILIES`: use only natural low blockers, in this order of weight: `rock_small` 0.5, `stump` 0.3,
   `logs` 0.2 (only the families present in the catalog; renormalize). Remove `cart` and `sack` (they stay available
   as room props through the style).
2. Hedge thickness in front of playable cells (cells within `SHORT_DEPTH`): **1 cell**. Elsewhere keep 2 cells.
   The ring must still enclose the playable area (8-connected, no corner cutting); add a test for a room whose front
   edge is diagonal.
3. In front hedge cells, vary the tile variant inside a family (no two identical variants side by side along the
   hedge, where the family has more than one variant).

**Done when:** `uv run pytest` passes; report which fixtures (if any) were re-recorded.

---

## Prompt 3: "Try Out" crashes for uploaded spritesheets (RectangleBinPacker)

Same working rules (code + small tests, run the suites once, no live LLM runs).

**Symptom (browser):** upload `grassland_tiles.png` + AI planner -> generation, preview, and validation succeed, but
"Try Out" shows: `Assertion failed: flame_tiled-3.1.2/lib/src/rectangle_bin_packer.dart:35 ... RectangleBinPacker
failed to pack an image. Consider using a bigger atlas`.

**Cause (verified on the failing job's bundle):** the tileset compiler writes every tileset image as a single row.
The upload catalog has 82 floor tiles of 64 x 32 in one group, so `tileset.png` is **5248 x 32** px. flame_tiled packs
all tileset images into one atlas with a maximum of **4096 x 4096 on the web** (`tile_atlas.dart`), so an image wider
than 4096 px can never be placed. The total area is small (14 tilesets, about 1.2 megapixels), so it fits once the
images are not single rows. Asset packs never hit this because their widest group is 32 tiles x 64 px = 2048 px.

**Fix (`backend/pipeline/execution/tileset_compiler.py`):**
1. Wrap each tileset image into rows: `columns = min(tilecount, max(1, 2048 // tilewidth))`,
   `rows = ceil(tilecount / columns)`; image size `columns * tilewidth` x `rows * tileheight`. Write `columns`,
   `imagewidth`, `imageheight` accordingly (map compiler's embedded copy too). Tile index -> (index % columns,
   index // columns).
2. Guard: if the sum of all tileset image areas exceeds 80% of 4096 x 4096, or any image side exceeds 4096, fail the
   execution stage with error code `atlas_too_large` and a clear message (do not produce a level that crashes the game).
3. Regression rule: asset pack outputs stay byte-identical (their groups have at most 2048 px per row, so
   `columns` does not change). Verify with the existing starter test.

**Tests:**
- Backend: a synthetic catalog with 82 floor tiles -> `tileset.png` is at most 2048 px wide, `columns` = 32,
  rows = 3, and the GIDs still map to the right tile images (compare a few tiles pixel by pixel with the source).
- Backend: the `atlas_too_large` guard.
- Flutter: a fixture bundle with a multi-row tileset (copy the output of the synthetic backend case) loads through
  `LevelLoader` and the tiles render from the right rows (check `computeDrawRect` of a tile in row 2).

**Done when:** `uv run pytest` and `flutter test` pass. Report briefly.
