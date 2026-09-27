import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:z_legend_game_flutter/game/level/level_source.dart';

/// A [LevelSource] that serves the bundle in `test/fixtures/<name>/` over
/// mock HTTP, the same path as "Try Out".
///
/// Fixtures (backend output, regenerate with `pipeline.execution.compile`
/// from `backend/`):
/// * `grassland_full`: the placeholder planner's level for the prompt
///   "graveyard with a cabin" with the `grassland_full` pack.
/// * `collision`: a 12 x 12 map compiled from its `level_plan.json`
///   (`--catalog asset_packs/grassland_full/asset_catalog.json`). Spawn on
///   (2, 5) with a rock on (3, 4) (one D step away), a tall tree on (6, 6),
///   a zombie on (11, 2), and a rock wall on (9, 1) to (9, 3). (col, row)
LevelSource fixtureSource(String name, {List<String>? requested}) {
  final client = MockClient((request) async {
    final file = request.url.pathSegments.last;
    requested?.add(file);
    final f = File('test/fixtures/$name/$file');
    if (!f.existsSync()) return http.Response('not found', 404);
    return http.Response.bytes(f.readAsBytesSync(), 200);
  });
  return LevelSource.network(
    Uri.parse('http://test/api/levels/$name/bundle/'),
    client: client,
  );
}
