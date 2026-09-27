import 'dart:io';

import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/level_source.dart';

/// Loads a grassland_full level (several tilesets of different sprite sizes,
/// Ground + Objects layers) through the same network path as "Try Out".
///
/// The fixture in test/fixtures/grassland_full/ is backend output for the
/// prompt "graveyard with a cabin" (level.tmj and the tileset images).
/// Regenerate it with the backend CLI (pipeline.execution.compile).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const fixtureDir = 'test/fixtures/grassland_full';
  final requested = <String>[];
  final client = MockClient((request) async {
    final name = request.url.pathSegments.last;
    requested.add(name);
    final file = File('$fixtureDir/$name');
    if (!file.existsSync()) return http.Response('not found', 404);
    return http.Response.bytes(file.readAsBytesSync(), 200);
  });

  late TiledComponent tiled;

  setUpAll(() async {
    final source = LevelSource.network(
      Uri.parse('http://test/api/levels/abc/bundle/'),
      client: client,
    );
    tiled = await LevelLoader(source).load();
  });

  test('has more than one tileset, and every tileset image is loaded', () {
    final tilesets = tiled.tileMap.map.tilesets;
    expect(tilesets.length, greaterThan(1));
    final images = [for (final ts in tilesets) ts.image!.source!];
    expect(images.first, 'tileset.png');
    expect(requested, containsAll(images));
  });

  test('tall tilesets keep their tileoffset', () {
    final trees = tiled.tileMap.map.tilesets.where((ts) => ts.tileWidth == 128);
    expect(trees, isNotEmpty);
    for (final ts in trees) {
      expect((ts.tileOffset?.x, ts.tileOffset?.y), (32, 0));
    }
  });

  test('has 2 tile layers: Ground and Objects', () {
    final layers = tiled.tileMap.map.layers.whereType<TileLayer>().toList();
    expect([for (final l in layers) l.name], ['Ground', 'Objects']);
    expect(tiled.tileMap.renderableLayers.length, greaterThanOrEqualTo(2));
  });

  test('Entities layer has 5 objects', () {
    expect(tiled.tileMap.getLayer<ObjectGroup>('Entities')?.objects.length, 5);
  });
}
