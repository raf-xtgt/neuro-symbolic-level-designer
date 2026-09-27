Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 3.1, 5.1, 5.2 and 6.1 (the catalog schema changed:
`offset` is replaced by `rect` + `anchor`), @neuro-symbolic-level-designer/game-assets/CREDITS.md, and
@neuro-symbolic-level-designer/backend/.

## Goal
Add a second built-in asset pack, `grassland_full`, with walls, obstacles, decorations and water, built from
`game-assets/grassland_tiles.png`. Generated levels then contain obstacles, not only floor tiles. Also add the
deterministic spritesheet slicer of Pipeline 1 and measure it against a known answer key.

All paths are relative to `neuro-symbolic-level-designer/backend/` unless they start with `game-assets/` or
`z_legend_game/`. Game-side collision and depth sorting of tall sprites are NOT part of this task.

## 0. Ground truth
`game-assets/grassland_tiles.flare_v0.15_tilesetdef.txt` is the Flare tileset definition for this exact atlas
(1024 x 1344). Format: `tile=<id>,<x>,<y>,<w>,<h>,<ox>,<oy>` under `# <section>` comment lines.
`(x, y, w, h)` is the sprite rectangle; `(ox, oy)` is the foot point in the sprite = our `anchor`.
It covers all but 18 of 483,174 opaque pixels. 10 of its rectangles are fully transparent: skip them and list them.

## 1. Catalog schema migration (ARCHITECTURE.md 6.1)
- Update `pipeline/schemas/asset_catalog.schema.json` to match ARCHITECTURE.md 6.1: required `source`, `rect`
  `{x, y, w, h}`, `anchor` `{x, y}`; new categories `water`, `hazard`; optional `tags`, `source_ref`. Remove `offset`.
- Migrate `fixtures/starter/asset_catalog.json`: `offset {x, y}` was really the atlas position. It becomes
  `rect {x, y, w: 64, h: 32}` and `anchor {x: 32, y: 16}`.
- Update every reader (`tileset_compiler.py`, tests, asset pack validation).
- **Regression rule:** the starter level output (`level.tmj`, `tileset.tsj`, `tileset.png`) must stay byte-identical,
  and `grassland_starter` jobs must give the same result as before for the same prompt.

## 2. Pack builder (`asset_packs/grassland_full/`)
- `build_pack.py`: parses the Flare definition and writes `asset_catalog.json` + `pack.json`. Deterministic.
  Catalog ids are contiguous from 0; `name` = `<section_slug>_<nn>`; `source_ref` = `flare:tile=<id>`.
- Section mapping (this table is the answer key; apply it exactly):

| Flare section | Include | category | walkable | material | tags |
|---|---|---|---|---|---|
| grass tiles | yes | floor | true | grass | |
| old stonework path | yes | floor | true | stone | |
| cliffs | yes | wall | false | rock | `autotile_required` |
| tents | no (multi-tile assembly) | | | | |
| indicators | no (editor markers) | | | | |
| town objects (e.g. containers) | yes | obstacle | false | wood | `prop` |
| shrubs and grass tufts | yes | decoration | true | plant | `prop` |
| rocks | yes | obstacle | false | rock | `prop` |
| tall town objects | yes | obstacle | false | wood | `prop`, `tall` |
| riverbanks | no (needs autotile rules) | | | | |
| water tiles | yes | water | false | water | `autotile_required` |
| wood bridge/wharf | no (needs autotile rules) | | | | |
| buildings, broken tower, cave tileset entrances, temple entrance | no (multi-tile assembly) | | | | |
| blue trees, dead trees, tall trees, fluffy trees | yes | obstacle | false | plant | `tree`, `tall` |

- `pack.json`: id `grassland_full`, a name and description, spritesheet, catalog, tile size 64 x 32, and a list of
  excluded sections with the reason.
- `contact_sheet.png`: every included tile drawn at its size on a dark background, grouped by category, labeled with
  catalog id and name, with a small dot at its anchor. I use it to check the labels by eye.
- Commit the generated `asset_catalog.json`, `pack.json`, and `contact_sheet.png`. A test checks that running
  `build_pack.py` again gives identical files.

## 3. Tileset compiler: tiles of different sizes (ARCHITECTURE.md 5.2)
- Group catalog tiles used by the level by `(w, h, anchor.x, anchor.y)`. Each group is one Tiled tileset with its own
  packed image: `tileset.png` for the first group, then `tileset_1.png`, `tileset_2.png`, ... in a stable order.
- Tileset `tileoffset` = `(w - W/2 - anchor.x, h - H/2 - anchor.y)` with W x H = 64 x 32. This is derived from the
  flame_tiled 3.1.2 isometric renderer, which draws sprite pixel `(w - W/2, h - H/2)` on the tile center. Put this
  derivation in a comment and cover it with a unit test (floor tile -> offset (0, 0)).
- The map compiler embeds all tilesets with consecutive `firstgid` values and maps catalog ids to GIDs.
- Keep a standalone `.tsj` per tileset (`tileset.tsj`, `tileset_1.tsj`, ...).
- The starter pack has one group, so its output stays byte-identical (regression rule).

## 4. Placeholder planner: obstacles
- If the catalog has tiles with category `obstacle` or `decoration` and without the tag `autotile_required`, add a
  second layer `Objects` (elevation 0) above `Ground`. Value 0 = empty cell.
- Place obstacles on about 8% and decorations on about 5% of the cells (seeded by the prompt, as now). Never on the
  path cells, the entity tiles, or the 8 neighbors of the spawn and the exit.
- Never use tiles tagged `autotile_required` (cliffs, water) in the placeholder planner.
- Walkability check: a cell is walkable if its `Objects` tile is empty or walkable. Run a BFS from `PlayerSpawn` to
  `ExitTrigger` (8 directions, same as the game). If no path exists, remove obstacles along a straight line until
  one exists. Zombies stay on walkable cells. Record `path_found: true` and the path length in the plan's summary
  data so the job summary can show it.
- `grassland_starter` has no obstacle tiles, so its plans are unchanged.

## 5. Preview renderer
- Draw the `Objects` layer after `Ground`, with each sprite placed by its anchor, in depth order (row + col, then
  col). Entity markers on top.

## 6. API
- Register `grassland_full` (automatic discovery). The pack list shows it.
- Bundle serving: allow `level.tmj`, `preview_level.png`, and `tileset(_\d+)?\.(png|tsj)`. Everything else stays 404.
- Job summary: add tile counts by category and the path check result.

## 7. Pipeline 1 slicer, measured against the answer key (`pipeline/ingestion/slicer.py`)
- Add `opencv-python-headless` and `numpy` (pinned).
- `slice_spritesheet(path) -> list[Chip]` with `Chip(rect, strategy)`:
  1. Contour slicing: alpha threshold, connected components (`cv2.findContours` or `connectedComponentsWithStats`),
     bounding boxes.
  2. Grid fallback: when components touch across a large area (for example the top floor rows, where diamonds share
     edges), split that region on a 64 x 32 grid.
- `tools/evaluate_slicer.py` (in `backend/`): runs the slicer on `grassland_tiles.png` and compares the chips with the
  Flare rectangles: matches at IoU >= 0.5, precision, recall, and a per-section table. Write the report to
  `asset_packs/grassland_full/slicer_report.md`.
- No pass threshold yet: report the real numbers. A test checks only that the floor rows (grass and stone path)
  are found by the grid fallback (32 chips, IoU >= 0.9).
- The slicer is not used to build the pack (the Flare definition is the ground truth). It is the first real part of
  Pipeline 1.

## 8. Flutter check (no Dart code changes expected)
- Add `test/full_pack_level_test.dart`: generate a `grassland_full` level with the backend CLI or a checked-in
  fixture bundle in `test/fixtures/grassland_full/`, then load it with `LevelLoader`: more than one tileset, all
  tileset images loaded, 2 tile layers, 5 entities. If `_normalizeForTiled` or the loader needs a change for multiple
  tilesets, make it and say so.

## Constraints
- Do not change `game-assets/`, `tools/prepare_characters.py`, `.bob/`, or the docs.
- Keep `grassland_starter` behavior and output identical.

## Done when
- From `backend/`: `uv run pytest` passes; `python asset_packs/grassland_full/build_pack.py` gives no diff;
  `python tools/evaluate_slicer.py` writes the report.
- From `z_legend_game_flutter/`: `dart analyze` 0 issues, `flutter test` passes.
- Live: start the API, create a `grassland_full` job with `curl`, download `preview_level.png` and every tileset
  file listed in `level.tmj`. Report the numbers: tiles by category, obstacles placed, path length, and the slicer
  precision and recall.
