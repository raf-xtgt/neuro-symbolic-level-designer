import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:z_legend_game_flutter/designer/api/level_api.dart';
import 'package:z_legend_game_flutter/designer/api/models.dart';

final _base = Uri.parse('http://api.test:8000');

http.Response _json(Object body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json'},
);

const _job = {
  'job_id': 'abc',
  'status': 'done',
  'stages': {'ingesting': 'done', 'planning': 'done', 'executing': 'done'},
  'created_at': '2026-09-26T18:38:44+00:00',
  'updated_at': '2026-09-26T18:38:44+00:00',
  'warnings': ['a warning'],
  'error': null,
  'summary': {
    'map_size': {'width': 20, 'height': 20},
    'tile_count_by_material': {'stone': 20, 'grass': 380},
    'entity_count_by_type': {'PlayerSpawn': 1, 'ExitTrigger': 1, 'Zombie': 3},
    'legacy_files': [
      {'kind': 'tileset', 'file_name': 't.tsj', 'tile_count': 32},
    ],
    'warnings': ['a warning'],
  },
};

void main() {
  test('bundleUrl', () {
    expect(
      LevelApi(_base).bundleUrl('abc').toString(),
      'http://api.test:8000/api/levels/abc/bundle/',
    );
  });

  test('listAssetPacks parses packs', () async {
    final api = LevelApi(
      _base,
      client: MockClient((request) async {
        expect(request.url.toString(), 'http://api.test:8000/api/asset-packs');
        return _json([
          {
            'id': 'grassland_starter',
            'name': 'Grassland Starter',
            'description': 'Grass and stone.',
            'spritesheets': ['grassland_tiles.png'],
            'tile_size': {'width': 64, 'height': 32},
          },
        ]);
      }),
    );
    final packs = await api.listAssetPacks();
    expect(packs.single.id, 'grassland_starter');
    expect(packs.single.name, 'Grassland Starter');
    expect(packs.single.spritesheets, ['grassland_tiles.png']);
    expect((packs.single.tileWidth, packs.single.tileHeight), (64, 32));
  });

  test('createLevel sends multipart fields and files', () async {
    late http.Request sent;
    final api = LevelApi(
      _base,
      client: MockClient((request) async {
        sent = request;
        return _json({
          'job_id': 'abc',
          'status_url': '/api/levels/abc',
          'bundle_url': '/api/levels/abc/bundle/',
        }, 202);
      }),
    );
    final result = await api.createLevel(
      LevelRequest(
        prompt: 'graveyard with a cabin',
        assetPack: 'grassland_starter',
        spritesheets: [
          LevelFile(name: 'sheet.png', bytes: Uint8List.fromList([1, 2])),
        ],
        tilesets: [
          LevelFile(
            name: 't.tsj',
            bytes: Uint8List.fromList(utf8.encode('{}')),
          ),
        ],
        maps: [
          LevelFile(
            name: 'm.tmx',
            bytes: Uint8List.fromList(utf8.encode('<map/>')),
          ),
        ],
      ),
    );

    expect(result.jobId, 'abc');
    expect(result.bundleUrl, '/api/levels/abc/bundle/');
    expect(sent.method, 'POST');
    expect(sent.url.toString(), 'http://api.test:8000/api/levels');
    expect(sent.headers['content-type'], startsWith('multipart/form-data'));
    final body = latin1.decode(sent.bodyBytes);
    expect(body, contains('name="prompt"\r\n\r\ngraveyard with a cabin'));
    expect(body, contains('name="asset_pack"\r\n\r\ngrassland_starter'));
    expect(body, contains('name="spritesheets"; filename="sheet.png"'));
    expect(body, contains('name="tilesets"; filename="t.tsj"'));
    expect(body, contains('name="maps"; filename="m.tmx"'));
  });

  test('422 throws ApiValidationException with field errors', () async {
    final api = LevelApi(
      _base,
      client: MockClient(
        (_) async => _json({
          'errors': [
            {'field': 'prompt', 'message': 'is required'},
            {'field': 'spritesheets[0]', 'message': 'is not a PNG file'},
          ],
        }, 422),
      ),
    );
    await expectLater(
      api.createLevel(const LevelRequest(prompt: '')),
      throwsA(
        isA<ApiValidationException>().having(
          (e) => [for (final f in e.errors) (f.field, f.input, f.message)],
          'errors',
          [
            ('prompt', 'prompt', 'is required'),
            ('spritesheets[0]', 'spritesheets', 'is not a PNG file'),
          ],
        ),
      ),
    );
  });

  test('getJob parses status, stages, warnings and summary', () async {
    final api = LevelApi(
      _base,
      client: MockClient((request) async {
        expect(request.url.path, '/api/levels/abc');
        return _json(_job);
      }),
    );
    final job = await api.getJob('abc');
    expect(job.isDone, isTrue);
    expect(job.stages, {
      'ingesting': StageState.done,
      'planning': StageState.done,
      'executing': StageState.done,
    });
    expect(job.warnings, ['a warning']);
    expect(job.errorCode, isNull);
    final summary = job.summary!;
    expect((summary.mapWidth, summary.mapHeight), (20, 20));
    expect(summary.tilesByMaterial, {'stone': 20, 'grass': 380});
    expect(summary.entitiesByType['Zombie'], 3);
    expect(summary.legacyFiles.single['tile_count'], 32);
  });

  test('getJob parses a failed job', () async {
    final api = LevelApi(
      _base,
      client: MockClient(
        (_) async => _json({
          ..._job,
          'status': 'failed',
          'stages': {
            'ingesting': 'failed',
            'planning': 'pending',
            'executing': 'pending',
          },
          'error': {'code': 'ingestion_not_implemented', 'message': 'nope'},
          'summary': null,
        }),
      ),
    );
    final job = await api.getJob('abc');
    expect(job.isFailed, isTrue);
    expect(job.stages['ingesting'], StageState.failed);
    expect(job.errorCode, 'ingestion_not_implemented');
    expect(job.errorMessage, 'nope');
    expect(job.summary, isNull);
  });

  test(
    'network error throws ApiUnavailableException with the base URL',
    () async {
      final api = LevelApi(
        _base,
        client: MockClient(
          (request) async =>
              throw http.ClientException('Connection refused', request.url),
        ),
      );
      await expectLater(
        api.listAssetPacks(),
        throwsA(
          isA<ApiUnavailableException>().having(
            (e) => e.baseUrl,
            'baseUrl',
            _base,
          ),
        ),
      );
    },
  );
}
