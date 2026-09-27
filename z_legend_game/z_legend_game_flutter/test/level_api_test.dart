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
    expect(body, contains('name="planner"\r\n\r\nagentic'));
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

  test('getJob parses the agentic planner fields', () async {
    final api = LevelApi(
      _base,
      client: MockClient(
        (_) async => _json({
          ..._job,
          'planner': 'agentic',
          'planning_steps': [
            {
              'node': 'topology_agent',
              'status': 'failed',
              'attempt': 1,
              'message': 'tile_group_exists: unknown group',
            },
            {
              'node': 'topology_agent',
              'status': 'done',
              'attempt': 2,
              'message': '4 rooms, 9 enemies',
            },
          ],
          'summary': {
            ...(_job['summary'] as Map<String, dynamic>),
            'planner': 'agentic',
            'design_notes': 'Graves around a cabin.',
            'rooms': [
              {
                'id': 'r1',
                'purpose': 'entrance',
                'size': 'small',
                'relative_position': 'south',
                'description': 'The gate.',
                'enemy_count': 0,
              },
            ],
            'validation': {
              'passed': true,
              'checks': [
                {'name': 'path_spawn_exit', 'passed': true, 'detail': 'ok'},
              ],
              'warnings': [],
            },
            'llm_usage': {
              'calls': 2,
              'attempts': 2,
              'input_tokens': 3600,
              'output_tokens': 5000,
              'latency_ms': 24000,
            },
            'attempts': {'topology': 2, 'layout': 1},
          },
        }),
      ),
    );
    final job = await api.getJob('abc');
    expect(
      [for (final s in job.planningSteps) (s.node, s.failed)],
      [
        ('topology_agent', true),
        ('topology_agent', false),
      ],
    );
    final summary = job.summary!;
    expect(summary.planner, 'agentic');
    expect(summary.designNotes, 'Graves around a cabin.');
    expect(summary.rooms.single.description, 'The gate.');
    expect(summary.validation!.passed, isTrue);
    expect(summary.validation!.failed, isEmpty);
    expect(summary.llmUsage!.outputTokens, 5000);
  });

  test('getJob parses a failed planning run with only planner facts', () async {
    final api = LevelApi(
      _base,
      client: MockClient(
        (_) async => _json({
          ..._job,
          'status': 'failed',
          'error': {'code': 'plan_validation_failed', 'message': 'x'},
          'summary': {
            'planner': 'agentic',
            'validation': {
              'passed': false,
              'checks': [
                {
                  'name': 'rooms_reachable',
                  'passed': false,
                  'detail': 'room r4 unreachable',
                },
              ],
            },
          },
        }),
      ),
    );
    final job = await api.getJob('abc');
    expect(job.summary!.mapWidth, 0);
    expect(job.summary!.validation!.failed.single.name, 'rooms_reachable');
  });

  test('getJob parses ingestion steps and the ingestion summary', () async {
    final api = LevelApi(
      _base,
      client: MockClient(
        (_) async => _json({
          ..._job,
          'ingestion_steps': [
            {'node': 'preprocess', 'status': 'done', 'message': '12 chips'},
            {
              'node': 'entity_agent',
              'status': 'cached',
              'message': 'from the ingestion cache',
              'done': null,
              'total': null,
            },
            {
              'node': 'boundary_agent',
              'status': 'running',
              'message': '1 of 2 batches',
              'done': 1,
              'total': 2,
            },
          ],
          'summary': {
            ...(_job['summary'] as Map<String, dynamic>),
            'ingestion': {
              'cached': true,
              'sheets': [
                {
                  'name': 'big.png',
                  'tile_size': [128, 64],
                  'scale': 0.5,
                  'size': [512, 448],
                },
              ],
              'chips': 12,
              'tiles': 10,
              'tile_count_by_category': {'floor': 8, 'decoration': 2},
              'tile_count_by_family': {'grass': 8, 'fern': 2},
              'exclusions': {'noise': 2},
              'conflicts': 1,
              'llm_usage': {
                'calls': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'latency_ms': 0,
              },
            },
          },
        }),
      ),
    );
    final job = await api.getJob('abc');
    expect(
      [for (final s in job.ingestionSteps) (s.node, s.done, s.total)],
      [
        ('preprocess', null, null),
        ('entity_agent', null, null),
        ('boundary_agent', 1, 2),
      ],
    );
    final ingestion = job.summary!.ingestion!;
    expect(ingestion.cached, isTrue);
    expect(ingestion.tileSizes, ['big.png: 128 x 64, scaled x0.5']);
    expect(ingestion.tilesByFamily.keys.first, 'grass');
    expect(ingestion.exclusions, {'noise': 2});
    expect(ingestion.llmUsage!.calls, 0);
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
          'error': {'code': 'ingestion_no_floor', 'message': 'nope'},
          'summary': null,
        }),
      ),
    );
    final job = await api.getJob('abc');
    expect(job.isFailed, isTrue);
    expect(job.stages['ingesting'], StageState.failed);
    expect(job.errorCode, 'ingestion_no_floor');
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
