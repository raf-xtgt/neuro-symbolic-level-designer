import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:z_legend_game_flutter/game/level/http_asset_bundle.dart';

void main() {
  final requested = <Uri>[];
  final client = MockClient((request) async {
    requested.add(request.url);
    return switch (request.url.path) {
      '/api/levels/abc/bundle/level.tmj' => http.Response('{"a": 1}', 200),
      '/api/levels/abc/bundle/tileset.png' => http.Response.bytes([
        1,
        2,
        3,
      ], 200),
      _ => http.Response('not found', 404),
    };
  });

  setUp(requested.clear);

  test('loads bytes', () async {
    final bundle = HttpAssetBundle(
      Uri.parse('http://test/api/levels/abc/bundle/'),
      client: client,
    );
    final data = await bundle.load('tileset.png');
    expect(data.buffer.asUint8List(), [1, 2, 3]);
  });

  test('loads strings', () async {
    final bundle = HttpAssetBundle(
      Uri.parse('http://test/api/levels/abc/bundle/'),
      client: client,
    );
    expect(jsonDecode(await bundle.loadString('level.tmj')), {'a': 1});
  });

  test('resolves keys against the base URL, with or without a slash', () async {
    for (final base in [
      'http://test/api/levels/abc/bundle/',
      'http://test/api/levels/abc/bundle',
    ]) {
      await HttpAssetBundle(
        Uri.parse(base),
        client: client,
      ).load('tileset.png');
    }
    expect(requested, [
      Uri.parse('http://test/api/levels/abc/bundle/tileset.png'),
      Uri.parse('http://test/api/levels/abc/bundle/tileset.png'),
    ]);
  });

  test('non-200 throws a FlutterError with the URL and status', () async {
    final bundle = HttpAssetBundle(
      Uri.parse('http://test/api/levels/abc/bundle/'),
      client: client,
    );
    await expectLater(
      bundle.load('missing.png'),
      throwsA(
        isA<FlutterError>().having(
          (e) => e.message,
          'message',
          allOf(
            contains('http://test/api/levels/abc/bundle/missing.png'),
            contains('404'),
          ),
        ),
      ),
    );
  });
}
