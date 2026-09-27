Read @neuro-symbolic-level-designer/z_legend_game/AGENTS.md, @neuro-symbolic-level-designer/ARCHITECTURE.md
sections 4.1.2, 5.2, 6.1 and 7, and @BUILD_LOG.md Log-25 (open issues).

## Goal
1. In the game, obstacles block movement, and tall sprites (trees, rocks, gravestones) sort in depth with the
   characters, so a character can walk behind a tree.
2. Fix the backend open issues from Log-25: fence pieces and the slicer metric.
3. The planner's path check and the game use the same movement rule.

Paths starting with `lib/` or `test/` are in `z_legend_game/z_legend_game_flutter/`. Paths starting with
`backend/` are in `neuro-symbolic-level-designer/backend/`.

## 1. One movement rule (game and planner)
- A cell is **blocked** if its `Objects` layer tile has the tile property `walkable = false`
  (the tileset compiler already writes `walkable`, `category`, `tags` per tile). Empty cells and walkable tiles
  (decorations) are open. Cells outside the map are blocked.
- 8-direction movement. A diagonal step is allowed only if **both** orthogonal neighbors are open (no corner
  cutting between two obstacles).
- `backend/pipeline/planning/pathing.py`: apply the no-corner-cutting rule in `shortest_path`. Add tests.
  Existing `grassland_starter` plans have no obstacles, so they must not change.

## 2. Game: walkability grid and collision
- `lib/game/level/walkability.dart`: `WalkabilityGrid` built from the loaded map (the `Objects` layer, if present, and
  the tile properties). API: `isOpen(col, row)`, `canStep(col, row, dcol, drow)` (the rule in section 1).
  A map without an `Objects` layer is fully open.
- Player: before each grid step, call `canStep`. If blocked, do not move, but still update the facing direction and
  keep the walk animation off (play idle).
- Zombies: when chasing, move along a BFS path on the `WalkabilityGrid` (recompute each step; the map is small).
  If there is no path, idle. Zombies never enter blocked cells.
- `IsoMath.inBounds` checks stay; the grid covers them.

## 3. Game: depth sorting of tall sprites
The `Objects` tile layer is drawn by flame_tiled as one flat layer, so it cannot interleave with characters.
- After loading, hide the `Objects` layer in the `TiledComponent` (keep `Ground`), and create one
  `SpriteComponent` per non-empty `Objects` cell:
  - Image and source rectangle from the tile's tileset (use the same images cache the loader used).
  - Anchor: the sprite pixel that sits on the tile center. From the tileset `tileoffset` (ARCHITECTURE.md 5.2):
    `anchor = (w - W/2 - tileoffset.x, h - H/2 - tileoffset.y)` with W x H = map tile size. Put the sprite so that
    this pixel is at `IsoMath.gridToWorldCenter(col, row)`. Check it against the flame_tiled placement with a test
    (a tree placed by the component and by flame_tiled must match to the pixel).
- Priority, one formula in `IsoMath` for everything in the world:
  `priority = (col + row) * 100 + bias`, bias: ground layer = far below everything, exit trigger 10,
  decorations (walkable) 20, characters 50, obstacles 50, then `+ col` inside the same bias is not needed; keep it simple
  but deterministic.
  Characters and obstacles never share a cell, so there is no tie at the same cell.
- **Occlusion guard (ARCHITECTURE.md 4.1.2):** when a tall obstacle (tag `tall` or `tree`) has a higher priority than
  the player and its sprite rectangle overlaps the player's sprite rectangle on screen, draw it at 40% opacity.
  Restore full opacity when it no longer overlaps. This keeps the player visible behind trees.
- F1 debug overlay: also outline blocked cells in red.

## 4. Backend: fence pieces (Log-25 open issue)
- `backend/asset_packs/grassland_full/build_pack.py`: add the tag `fence` to the fence pieces
  `town_objects_08` to `town_objects_15` (Flare ids 104 to 111). They are directional connectors.
- Placeholder planner: never scatter tiles tagged `fence`. Rebuild the pack (`asset_catalog.json`,
  `contact_sheet.png`) and regenerate any test fixture bundle that depends on it.

## 5. Backend: slicer metric (Log-25 open issue)
- `backend/tools/evaluate_slicer.py`: add a second answer key where each Flare rectangle is shrunk to the bounding box
  of its opaque pixels (alpha > 0). Report both: "padded cells" (current) and "tight boxes" (new), with totals and the
  per-section table for each. Do not change the slicer in this task. Regenerate `slicer_report.md`.

## 6. Tests
- `test/walkability_test.dart`: open and blocked cells from a map with obstacles, `canStep` with corner cutting
  blocked, out of bounds blocked, a map without `Objects` is open.
- `test/object_sprites_test.dart`: load the `grassland_full` fixture bundle; one sprite component per non-empty
  `Objects` cell; the `Objects` layer is hidden; the anchor math matches flame_tiled for a 64 x 32, a 64 x 96, and a
  128 x 224 tile.
- Priority tests: a character one row "in front of" a tree has a higher priority than the tree; one row behind has a
  lower priority; a decoration on the character's cell is below the character.
- Game test (flame_test): with a fixture map where the cell east of the player is blocked, pressing D does not move
  the player; a zombie with a wall between it and the player walks around it.
- Occlusion test: the tree's opacity is 0.4 when the player stands behind it, 1.0 otherwise.
- Backend: pathing no-corner-cutting tests, fence tiles never scattered, pack rebuild is still deterministic,
  `grassland_starter` output unchanged.

## Constraints
- Do not change `game-assets/`, `tools/prepare_characters.py`, `.bob/`, or the docs.
- Do not change the level file format, except the rebuilt `grassland_full` catalog (new `fence` tag).
- Web only, no `dart:io`.

## Done when
- Backend: `uv run pytest` passes, `build_pack.py` gives no diff after the rebuild, `slicer_report.md` has both metrics.
- Flutter: `dart analyze` 0 issues, `dart format --set-exit-if-changed .` passes, `flutter test` passes,
  `flutter build web` succeeds.
- Report the new slicer numbers (padded and tight), and list the manual browser checks for me: walk into a tree
  (blocked), walk behind a tree (player drawn behind it, tree faded), walk in front of a tree (player in front),
  zombie goes around obstacles, F1 shows blocked cells.

---

## Prompt 2: Ground layer drawn on top in the browser

**Symptom (browser only):** after "Try Out" with `grassland_full`, the ground tiles cover the player, zombies, and all
object sprites. Only the parts of tall sprites that stick out past the map edge are visible. All tests pass.

**Cause (verified):** `lib/game/iso/iso_math.dart` has `static const int groundPriority = -1 << 30;`.
On the Dart VM (tests) this is `-1073741824`. On the web (dart2js), bitwise shift results are unsigned 32-bit, so it
compiles to `3221225472`, a large positive number. The ground `TiledComponent` then gets the highest priority and is
drawn last, on top of everything. (Checked with `dart compile js`: the constant is emitted as `3221225472`.)

**Fix:**
1. `groundPriority`: use a plain negative literal, for example `static const int groundPriority = -1000000000;`
   (still below every `depthPriority`, which is at least 0). Do not use bitwise operators to build it.
2. Search `lib/` for other bitwise operators (`<<`, `>>`, `>>>`, `&`, `|`, `^`, `~`) on `int` values that can be
   negative or larger than 32 bits, and replace them with arithmetic. Report what you found.
3. Test `test/iso_math_test.dart`: `groundPriority` is negative and below `depthPriority(0, 0, DepthLayer.exitTrigger)`.
   (This passes on the VM either way. It documents the rule; the rule itself is in `z_legend_game/AGENTS.md`.)

**Done when:** `dart analyze` 0 issues, `flutter test` passes, `flutter build web` succeeds, and
`grep -rn "<<" lib/` finds no shift used for a priority or other signed value. Then I re-run the browser check.
