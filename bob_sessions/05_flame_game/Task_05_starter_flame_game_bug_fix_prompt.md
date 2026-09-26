
---

## Prompt 2: Review fixes

A review found that the game cannot work in the browser. Fix all items below. All paths are relative to
`z_legend_game/z_legend_game_flutter/` unless they start with `backend/`.

### 1. The map does not load (blocker)
`TiledComponent.load` fails with `XmlParserException: Expected a single root element`. Cause: `level.tmj` references
the external tileset `tileset.tsj`, and flame_tiled 3.1.2 (`FlameTsxProvider.getSource`) parses external tilesets
as XML only.
- In `backend/pipeline/execution/map_compiler.py`, write the tileset **inline** in `level.tmj` (embedded tileset:
  all tileset fields plus `firstgid`, no `source`). Make this the default. Keep writing the standalone
  `tileset.tsj` and `tileset.png` (ARCHITECTURE.md 5.2). The embedded `image` path must resolve from the `.tmj`.
- Update the backend tests and regenerate the starter level. `uv run pytest` (from `backend/`) must pass.
- Add `test/level_loader_test.dart`: load the starter map with `LevelLoader(LevelSource.bundled(...))` and check
  map size 20 x 20, one tile layer, and 5 objects in `Entities`. This test must fail on the old `level.tmj`.

### 2. Keyboard input never reaches the player (blocker)
`ZLegendGame` uses `KeyboardEvents`, so `PlayerComponent` (a `KeyboardHandler`) never receives key events.
- Use `HasKeyboardHandlerComponents` on the game (not both mixins). Handle F1 and R in the game's `onKeyEvent`
  and call `super.onKeyEvent` so the event also reaches the components.
- Add a test with `flame_test` (dev dependency): load the game, send a D key down/up, advance time, and check that
  the player's grid position changed.

### 3. Space attack does nothing
`_playerIsAttacking()` always returns false, so zombies are never killed.
- Expose `isAttacking` on `PlayerComponent`. When an attack starts, kill every zombie within 1 tile, once per attack.
  Remove the dead code.

### 4. Animations use the wrong sidecar data
`_meta ??= meta` keeps only the first sidecar (idle), and `_animMetas` is never filled. Result: player `walk` shows
1 frame instead of 4, player `die` 1 instead of 2, zombie `die` 20 instead of 24.
- Store and use each animation's own `SpriteSheetMeta` (frames, fps). The anchor is the same for all animations of a
  character.
- Add a test: after load, each animation's frame count matches its sidecar JSON.

### 5. Restart (R) is broken
`_restart()` calls `onLoad()` again, which adds a second `World` and `CameraComponent`. Zombies spawn in `onMount()`,
which does not run again, so they do not come back after restart.
- Create the world and camera once. Put level setup in one method (`_loadLevel()`) that clears the world, loads the
  map, and spawns the player first and then the zombies. `onLoad` and restart both call it.
- The player does not remove itself after `die`; it stays on its last frame. Only zombies are removed after `die`.

### 6. Map size and tile size are hard-coded
`IsoMath` uses constants 20 x 20 and 64 x 32. Generated levels will have other sizes.
- Make `IsoMath` an instance created from the loaded map (`map.width`, `map.height`, `map.tileWidth`,
  `map.tileHeight`). flame_tiled shifts X by `map.height * tileWidth / 2`, so use the height for the offset.
- Update the tests, and add a case with a non-square map (for example 30 x 12).

### 7. Simplify
- Replace the hand-written `atan` approximation in `character_component.dart` with `dart:math` `atan2`.

### Done when
- `dart analyze` 0 issues, `dart format --set-exit-if-changed .` passes, `flutter test` passes (including the new
  loader, keyboard, and animation tests), `flutter build web` succeeds.
- Run the app on the web and read the runtime logs. Report the actual result: does the map render, and does the
  player move with WASD? Do not report success without running it.
