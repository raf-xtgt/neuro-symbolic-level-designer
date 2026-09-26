
---

## Prompt 3: Finish the review fixes (Bob ran out of credits during Prompt 2)

### 1. Load `.tmj` as JSON (blocker, corrected root cause)
`TiledComponent.load` -> `RenderableTiledMap.fromString` -> `TiledMap.fromString` parses the map as **XML (TMX)
only** in flame_tiled 3.1.2 / tiled 0.11.1. A `.tmj` (JSON) map always fails with `XmlParserException`, even with
the tileset embedded. The embedded tileset from Prompt 2 is still required (the JSON parser has no external
tileset support).
- In `lib/game/level/level_loader.dart`, do not call `TiledComponent.load`. Instead:
  1. `final contents = await source.bundle.loadString('${source.prefix}level.tmj');`
  2. `final map = TileMapParser.parseJson(contents);` (from `package:tiled`)
  3. `final renderable = await RenderableTiledMap.fromTiledMap(map, destTileSize, images: Images(prefix: source.prefix, bundle: source.bundle), bundle: source.bundle);`
  4. `return TiledComponent(renderable);`
- Add `tiled` to `pubspec.yaml` with the version that flame_tiled 3.1.2 uses.

### 2. Clean up
- Fix the analyzer error in `test/input_direction_test.dart` (missing `isoMath` argument) and the 4 unused imports.
- Run `dart format .`.
- `test/game_keyboard_test.dart`: the test returns early (passes) when the player is null. Make it fail instead.

### Done when
- `dart analyze` 0 issues, `dart format --set-exit-if-changed .` passes, `flutter test` passes
  (`level_loader_test.dart` and `game_keyboard_test.dart` must run, not skip), `flutter build web` succeeds.
- Run the app on the web and report the actual result.
