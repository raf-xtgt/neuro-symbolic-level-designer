import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/level_source.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('LevelLoader – starter level', () {
    late TiledComponent tiledMap;

    setUpAll(() async {
      final source = LevelSource.bundled('assets/tiles/starter/');
      final loader = LevelLoader(source);
      tiledMap = await loader.load();
    });

    test('map is 20 columns wide', () {
      expect(tiledMap.tileMap.map.width, 20);
    });

    test('map is 20 rows tall', () {
      expect(tiledMap.tileMap.map.height, 20);
    });

    test('has exactly one tile layer', () {
      final tileLayers = tiledMap.tileMap.map.layers
          .where((l) => l.type == LayerType.tileLayer)
          .toList();
      expect(tileLayers.length, 1);
    });

    test('embedded tileset is parsed with its image', () {
      final tilesets = tiledMap.tileMap.map.tilesets;
      expect(tilesets.length, 1);
      expect(tilesets.first.image?.source, 'tileset.png');
      expect(tilesets.first.tiles.length, 32);
    });

    test('ground layer has 400 tile gids', () {
      final ground = tiledMap.tileMap.getLayer<TileLayer>('Ground');
      expect(ground?.data?.length, 400);
    });

    test('Entities layer has exactly 5 objects', () {
      final objectGroup = tiledMap.tileMap.getLayer<ObjectGroup>('Entities');
      expect(objectGroup, isNotNull);
      expect(objectGroup!.objects.length, 5);
    });
  });
}
