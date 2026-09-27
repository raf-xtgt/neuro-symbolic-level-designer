import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/level/level_loader.dart';

import 'fixture_source.dart';

/// A tileset image wrapped into rows: 82 floor tiles of 64 x 32 in one group
/// (the floor group of the recorded grassland upload) give a 2048 x 96 image,
/// 32 columns x 3 rows. A single 5248 px row failed flame_tiled's 4096 px
/// atlas on the web. Fixture from `backend/tests/test_tileset_rows.py`
/// (`uv run python -m tests.test_tileset_rows`); the plan puts catalog id i
/// on cell i (cols and rows 0 to 9).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late TiledComponent tiled;

  setUpAll(() async {
    tiled = await LevelLoader(fixtureSource('multirow_tileset')).load();
  });

  test('the tileset has 32 columns and 3 rows', () {
    final ts = tiled.tileMap.map.tilesets.single;
    expect(ts.columns, 32);
    expect(ts.tileCount, 82);
    expect(ts.image!.width, 2048);
    expect(ts.image!.height, 96);
  });

  test('tiles draw from the right row of the image', () {
    final map = tiled.tileMap.map;
    final ts = map.tilesets.single;
    final ground = tiled.tileMap.getLayer<TileLayer>('Ground')!;
    // Catalog id 70 sits on cell 70 = (col 0, row 7): local tile 70 is in
    // image row 2, column 6.
    final gid = ground.tileData![7][0].tile;
    final tile = map.tileByGid(gid)!;
    expect(tile.localId, 70);
    final rect = ts.computeDrawRect(tile);
    expect([rect.left, rect.top, rect.width, rect.height], [384, 64, 64, 32]);
  });
}
