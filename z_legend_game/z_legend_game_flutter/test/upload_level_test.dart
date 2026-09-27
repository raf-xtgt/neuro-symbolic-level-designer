import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/iso/iso_math.dart';
import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/object_sprites.dart';
import 'package:z_legend_game_flutter/game/level/walkability.dart';

import 'fixture_source.dart';

/// A level generated from an UPLOADED spritesheet: Pipeline 1 ingested
/// `grassland_tiles.png` (tiles from the normalized atlas), the AI planner
/// planned the level, Pipeline 3 compiled it. Recorded by
/// `backend/tools/evaluate_ingestion.py` (item 5) into
/// `test/fixtures/upload_grassland/`. Loaded through the "Try Out" path.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final requested = <String>[];
  late LevelLoader loader;
  late TiledComponent tiled;

  setUpAll(() async {
    loader = LevelLoader(
      fixtureSource('upload_grassland', requested: requested),
    );
    tiled = await loader.load();
  });

  test('every tileset image of the upload bundle loads', () {
    final images = [
      for (final ts in tiled.tileMap.map.tilesets) ts.image!.source!,
    ];
    expect(images.length, greaterThan(1));
    expect(requested, containsAll(images));
  });

  test('tilesets use the normalized cell sizes (width x 64, height x 32)', () {
    for (final ts in tiled.tileMap.map.tilesets) {
      expect(ts.tileWidth! % 64, 0, reason: ts.name);
      expect(ts.tileHeight! % 32, 0, reason: ts.name);
    }
  });

  test('Ground, Objects and Entities; the spawn is walkable', () {
    final map = tiled.tileMap.map;
    expect(
      [for (final l in map.layers) l.name],
      ['Ground', 'Objects', 'Entities'],
    );
    final entities = tiled.tileMap.getLayer<ObjectGroup>('Entities')!.objects;
    expect(entities.where((o) => o.type == 'PlayerSpawn'), hasLength(1));
    expect(entities.where((o) => o.type == 'ExitTrigger'), hasLength(1));

    final iso = IsoMath(
      tileWidth: map.tileWidth.toDouble(),
      tileHeight: map.tileHeight.toDouble(),
      mapCols: map.width,
      mapRows: map.height,
    );
    final grid = WalkabilityGrid.fromMap(map);
    expect(grid.blockedCells, isNotEmpty);
    for (final o in entities) {
      final (col, row) = iso.objectToGrid(o.x, o.y);
      expect(
        grid.isOpen(col, row),
        isTrue,
        reason: '${o.type} at ($col, $row)',
      );
    }
    final spawn = entities.firstWhere((o) => o.type == 'PlayerSpawn');
    final exit = entities.firstWhere((o) => o.type == 'ExitTrigger');
    expect(
      grid.findPath(
        iso.objectToGrid(spawn.x, spawn.y),
        iso.objectToGrid(exit.x, exit.y),
      ),
      isNotNull,
    );
  });

  test('object sprites are cut from the upload tilesets', () async {
    final map = tiled.tileMap.map;
    final iso = IsoMath(
      tileWidth: map.tileWidth.toDouble(),
      tileHeight: map.tileHeight.toDouble(),
      mapCols: map.width,
      mapRows: map.height,
    );
    final sprites = await extractObjectSprites(tiled, iso, loader.images);
    expect(sprites, isNotEmpty);
    expect(sprites.where((s) => s.isTall), isNotEmpty);
  });
}
