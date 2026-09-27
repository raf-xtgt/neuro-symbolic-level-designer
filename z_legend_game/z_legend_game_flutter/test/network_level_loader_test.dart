import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/level_source.dart';

/// Proves the "Try Out" loading path without a browser: the starter bundle is
/// served over (mock) HTTP and loaded through [LevelSource.network].
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const bundlePath = '/api/levels/abc/bundle/';
  final requested = <String>[];

  final client = MockClient((request) async {
    final path = request.url.path;
    requested.add(path);
    if (request.url.host != 'test' || !path.startsWith(bundlePath)) {
      return http.Response('not found', 404);
    }
    final name = path.substring(bundlePath.length);
    try {
      final data = await rootBundle.load('assets/tiles/starter/$name');
      return http.Response.bytes(data.buffer.asUint8List(), 200);
    } on FlutterError {
      return http.Response('not found', 404);
    }
  });

  late TiledComponent tiled;

  setUpAll(() async {
    final source = LevelSource.network(
      Uri.parse('http://test$bundlePath'),
      client: client,
    );
    tiled = await LevelLoader(source).load();
  });

  test('map is 20 x 20', () {
    expect(tiled.tileMap.map.width, 20);
    expect(tiled.tileMap.map.height, 20);
  });

  test('embedded tileset image is loaded over HTTP', () {
    expect(tiled.tileMap.map.tilesets.single.image?.source, 'tileset.png');
    expect(
      requested,
      containsAll(['${bundlePath}level.tmj', '${bundlePath}tileset.png']),
    );
    expect(tiled.tileMap.renderableLayers, isNotEmpty);
  });

  test('Entities layer has 5 objects', () {
    final entities = tiled.tileMap.getLayer<ObjectGroup>('Entities');
    expect(entities?.objects.length, 5);
  });
}
