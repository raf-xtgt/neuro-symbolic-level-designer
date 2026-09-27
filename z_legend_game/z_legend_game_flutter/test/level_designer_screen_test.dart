import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/designer/api/level_api.dart';
import 'package:z_legend_game_flutter/designer/api/models.dart';
import 'package:z_legend_game_flutter/designer/level_designer_screen.dart';

/// 1 x 1 transparent PNG.
final _png = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
);

const _pack = AssetPack(
  id: 'grassland_starter',
  name: 'Grassland Starter',
  description: 'Grass and stone.',
  spritesheets: ['grassland_tiles.png'],
  tileWidth: 64,
  tileHeight: 32,
);

JobStatus _job(
  String status,
  List<StageState> stages, {
  String? errorCode,
  JobSummary? summary,
  List<PlanningStep> steps = const [],
  List<PlanningStep> executionSteps = const [],
  Map<String, dynamic> source = const {},
}) => JobStatus(
  jobId: 'abc',
  status: status,
  stages: {for (final (i, s) in jobStages.indexed) s: stages[i]},
  warnings: const [],
  errorCode: errorCode,
  errorMessage: errorCode == null ? null : 'server message',
  summary: summary,
  planningSteps: steps,
  executionSteps: executionSteps,
  source: source,
);

const _steps = [
  PlanningStep(
    node: 'topology_agent',
    status: 'failed',
    attempt: 1,
    message: 'tile_group_exists: unknown tile group gravestones',
  ),
  PlanningStep(
    node: 'topology_agent',
    status: 'done',
    attempt: 2,
    message: '4 rooms, 9 enemies',
  ),
  PlanningStep(
    node: 'validator',
    status: 'done',
    attempt: 1,
    message: 'all checks passed',
  ),
];

const _agenticSummary = JobSummary(
  mapWidth: 30,
  mapHeight: 32,
  tilesByMaterial: {'grass': 900},
  entitiesByType: {'Zombie': 9},
  planner: 'agentic',
  designNotes: 'A graveyard around a cabin, the boss waits in the north.',
  rooms: [
    RoomSummary(
      id: 'r1',
      purpose: 'entrance',
      size: 'small',
      description: 'The cemetery gate.',
      enemyCount: 0,
    ),
  ],
  validation: ValidationReport(passed: true, checks: []),
  llmUsage: LlmUsage(
    calls: 2,
    inputTokens: 3600,
    outputTokens: 5000,
    latencyMs: 24000,
  ),
);

const _summary = JobSummary(
  mapWidth: 20,
  mapHeight: 20,
  tilesByMaterial: {'grass': 380, 'stone': 20},
  entitiesByType: {'PlayerSpawn': 1, 'ExitTrigger': 1, 'Zombie': 3},
  legacyFiles: [],
);

class _FakeApi implements LevelApi {
  _FakeApi({this.offline = false, this.jobs = const []});

  bool offline;

  /// Returned by successive [getJob] calls; the last one repeats.
  final List<JobStatus> jobs;
  int _polls = 0;
  LevelRequest? lastRequest;

  @override
  final Uri baseUrl = Uri.parse('http://localhost:8000');

  @override
  Uri bundleUrl(String jobId) => baseUrl.resolve('/api/levels/$jobId/bundle/');

  @override
  Uri bundleZipUrl(String jobId) =>
      baseUrl.resolve('/api/levels/$jobId/bundle.zip');

  @override
  Future<List<AssetPack>> listAssetPacks() async {
    if (offline) throw ApiUnavailableException(baseUrl);
    return const [_pack];
  }

  @override
  Future<CreateJobResult> createLevel(LevelRequest request) async {
    lastRequest = request;
    return const CreateJobResult(
      jobId: 'abc',
      statusUrl: '/api/levels/abc',
      bundleUrl: '/api/levels/abc/bundle/',
    );
  }

  @override
  Future<JobStatus> getJob(String jobId) async =>
      jobs[_polls < jobs.length ? _polls++ : jobs.length - 1];

  @override
  Future<Uint8List> getBundleFile(String jobId, String name) async => _png;
}

Future<void> _pump(
  WidgetTester tester,
  LevelApi api, {
  PickFiles? pick,
  DownloadUrl? download,
}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData.dark(),
      home: LevelDesignerScreen(api: api, pickFiles: pick, download: download),
    ),
  );
  await tester.pump();
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pump();
}

String _stateOf(WidgetTester tester, String label) {
  final row = find.ancestor(of: find.text(label), matching: find.byType(Row));
  final texts = tester
      .widgetList<Text>(
        find.descendant(of: row.first, matching: find.byType(Text)),
      )
      .map((t) => t.data)
      .toList();
  return texts.last!;
}

void main() {
  testWidgets('empty prompt shows an error and sends nothing', (tester) async {
    final api = _FakeApi();
    await _pump(tester, api);

    await _tap(tester, find.text('Generate level'));

    expect(find.text('Enter a prompt.'), findsOneWidget);
    expect(api.lastRequest, isNull);
  });

  testWidgets('happy path goes through the 3 stages and shows Try Out', (
    tester,
  ) async {
    final api = _FakeApi(
      jobs: [
        _job('ingesting', [
          StageState.running,
          StageState.pending,
          StageState.pending,
        ]),
        _job(
          'planning',
          [StageState.done, StageState.running, StageState.pending],
          steps: const [
            PlanningStep(
              node: 'topology_agent',
              status: 'done',
              attempt: 1,
              message: '3 rooms, 7 enemies',
            ),
            PlanningStep(
              node: 'layout_builder',
              status: 'running',
              attempt: 1,
              message: '',
            ),
          ],
        ),
        _job(
          'executing',
          [StageState.done, StageState.done, StageState.running],
          executionSteps: const [
            PlanningStep(
              node: 'mechanics_agent',
              status: 'done',
              attempt: 1,
              message: '2 rooms: patrol_room 2',
            ),
            PlanningStep(
              node: 'codegen',
              status: 'running',
              attempt: 1,
              message: '',
            ),
          ],
        ),
        _job(
          'done',
          [StageState.done, StageState.done, StageState.done],
          summary: _summary,
          source: const {'asset_pack': 'grassland_full'},
        ),
      ],
    );
    await _pump(tester, api);
    expect(find.byKey(const Key('asset_pack')), findsNothing);
    expect(find.byKey(const Key('planner')), findsNothing);
    expect(find.text('Optional'), findsNothing);
    expect(find.text('Existing tilesets (.tsx, .tsj)'), findsNothing);
    expect(find.text('Existing maps (.tmx, .tmj)'), findsNothing);
    expect(find.text('Add files'), findsOneWidget, reason: 'spritesheets only');
    expect(
      find.text(
        'Upload your isometric spritesheets (PNG). If you do not upload '
        'any, the default grassland spritesheet is used.',
      ),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.prompt, 'graveyard');
    expect(api.lastRequest?.assetPack, 'grassland_full');
    expect(api.lastRequest?.spritesheets, isEmpty);
    expect(api.lastRequest?.planner, Planner.agentic);
    expect(api.lastRequest?.tilesets, isEmpty);
    expect(api.lastRequest?.maps, isEmpty);
    expect(_stateOf(tester, '1. Data Ingestion'), 'running');
    expect(find.text('Try Out'), findsNothing);

    await tester.pump(const Duration(milliseconds: 500));
    expect(_stateOf(tester, '1. Data Ingestion'), 'done');
    expect(_stateOf(tester, '2. Level Planning'), 'running');
    expect(
      find.text('Topology agent (AI) (attempt 1): 3 rooms, 7 enemies'),
      findsOneWidget,
    );
    expect(find.text('Placing rooms and corridors...'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 500));
    expect(_stateOf(tester, '3. Execution'), 'running');
    expect(
      find.text('Enemy behavior agent (AI): 2 rooms: patrol_room 2'),
      findsOneWidget,
    );
    expect(find.text('Generating Flame code...'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump();
    for (final label in _stageLabelsInOrder) {
      expect(_stateOf(tester, label), 'done');
    }
    expect(find.text('20 x 20 tiles'), findsOneWidget);
    expect(find.text('Default grassland spritesheet'), findsOneWidget);
    expect(find.text('grass: 380, stone: 20'), findsOneWidget);
    expect(find.text('Try Out'), findsOneWidget);
    expect(find.byType(Image), findsOneWidget);

    // Polling stopped: no timers left.
    await tester.pump(const Duration(seconds: 2));
  });

  testWidgets('upload shows ingestion sub-steps, contact sheet and summary', (
    tester,
  ) async {
    const steps = [
      IngestionStep(
        node: 'preprocess',
        status: 'done',
        message: '307 chips (tile size 64 x 32)',
      ),
      IngestionStep(
        node: 'classification_agent',
        status: 'running',
        message: '3 of 10 batches',
        done: 3,
        total: 10,
      ),
    ];
    const done = [
      IngestionStep(
        node: 'preprocess',
        status: 'done',
        message: '307 chips (tile size 64 x 32)',
      ),
      IngestionStep(
        node: 'classification_agent',
        status: 'done',
        message: '10 of 10 batches',
        done: 10,
        total: 10,
      ),
      IngestionStep(
        node: 'quality_gate',
        status: 'done',
        message: 'floor families: grass (16)',
      ),
    ];
    const ingestion = IngestionSummary(
      cached: false,
      chips: 307,
      tiles: 175,
      tilesByCategory: {'floor': 61, 'obstacle': 60},
      tilesByFamily: {'grass': 20, 'stone_path': 16},
      exclusions: {'fragment': 50},
      conflicts: 3,
      tileSizes: ['sheet.png: 64 x 32'],
      llmUsage: LlmUsage(
        calls: 41,
        inputTokens: 110000,
        outputTokens: 62000,
        latencyMs: 357000,
      ),
    );
    final api = _FakeApi(
      jobs: [
        JobStatus(
          jobId: 'abc',
          status: 'ingesting',
          stages: const {
            'ingesting': StageState.running,
            'planning': StageState.pending,
            'executing': StageState.pending,
          },
          warnings: const [],
          ingestionSteps: steps,
        ),
        JobStatus(
          jobId: 'abc',
          status: 'done',
          stages: const {
            'ingesting': StageState.done,
            'planning': StageState.done,
            'executing': StageState.done,
          },
          warnings: const [],
          ingestionSteps: done,
          source: const {
            'spritesheets': ['sheet.png'],
          },
          summary: const JobSummary(
            mapWidth: 30,
            mapHeight: 30,
            ingestion: ingestion,
          ),
        ),
      ],
    );
    await _pump(
      tester,
      api,
      pick: (_) async => [LevelFile(name: 'sheet.png', bytes: _png)],
    );

    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Add files').first);
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.spritesheets.single.name, 'sheet.png');
    expect(api.lastRequest?.assetPack, isNull);
    expect(_stateOf(tester, '1. Data Ingestion'), 'running');
    expect(
      find.text('Pre-processor: 307 chips (tile size 64 x 32)'),
      findsOneWidget,
    );
    expect(
      find.text(
        'AI-powered tile classification is running... (3 of 10 batches)',
      ),
      findsOneWidget,
    );

    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump();
    await tester.pump();
    expect(
      find.text(
        'Classification agent (AI) (10 of 10 batches): 10 of 10 batches',
      ),
      findsOneWidget,
    );
    expect(find.text('sheet.png'), findsWidgets);
    expect(
      find.text('Quality gate: floor families: grass (16)'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('contact_sheet')), findsOneWidget);
    expect(find.text('175 of 307 chips'), findsOneWidget);
    expect(find.text('floor: 61, obstacle: 60'), findsOneWidget);
    expect(find.text('grass: 20, stone_path: 16'), findsOneWidget);
    expect(find.text('fragment: 50'), findsOneWidget);
    expect(
      find.text('41 calls, 110000 input + 62000 output tokens, 357.0 s'),
      findsOneWidget,
    );
    expect(find.text('Try Out'), findsOneWidget);
  });

  testWidgets('ingestion_no_floor shows a friendly message', (tester) async {
    final api = _FakeApi(
      jobs: [
        _job(
          'failed',
          [StageState.failed, StageState.pending, StageState.pending],
          errorCode: 'ingestion_no_floor',
        ),
      ],
    );
    await _pump(
      tester,
      api,
      pick: (_) async => [LevelFile(name: 'chars.png', bytes: _png)],
    );
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Add files').first);
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(_stateOf(tester, '1. Data Ingestion'), 'failed');
    expect(
      find.textContaining('The uploaded sheet has no usable isometric floor'),
      findsOneWidget,
    );
    expect(find.textContaining('(server message)'), findsOneWidget);
    expect(find.text('Try Out'), findsNothing);
  });

  testWidgets('agentic planning shows sub-steps and the validation badge', (
    tester,
  ) async {
    final api = _FakeApi(
      jobs: [
        _job('planning', [
          StageState.done,
          StageState.running,
          StageState.pending,
        ], steps: _steps.sublist(0, 1)),
        _job(
          'done',
          [StageState.done, StageState.done, StageState.done],
          summary: _agenticSummary,
          steps: _steps,
        ),
      ],
    );
    await _pump(tester, api);
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.planner, Planner.agentic);
    expect(_stateOf(tester, '2. Level Planning'), 'running');
    expect(
      find.text(
        'Topology agent (AI) (attempt 1): tile_group_exists: unknown tile '
        'group gravestones',
      ),
      findsOneWidget,
    );

    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump();
    expect(
      find.text('Topology agent (AI) (attempt 2): 4 rooms, 9 enemies'),
      findsOneWidget,
    );
    expect(
      find.text('Validator (attempt 1): all checks passed'),
      findsOneWidget,
    );
    expect(find.text('Validation passed'), findsOneWidget);
    expect(
      find.text('A graveyard around a cabin, the boss waits in the north.'),
      findsOneWidget,
    );
    expect(
      find.text('r1: entrance, small, 0 enemies - The cemetery gate.'),
      findsOneWidget,
    );
    expect(
      find.text('2 calls, 3600 input + 5000 output tokens, 24.0 s'),
      findsOneWidget,
    );
    // The planner is always the AI planner: no Planner row in the result.
    expect(find.text('Planner'), findsNothing);
    expect(find.text('AI planner (Gemini)'), findsNothing);
    expect(find.text('Try Out'), findsOneWidget);
  });

  testWidgets('verification section, zombie behaviors and bundle download', (
    tester,
  ) async {
    const summary = JobSummary(
      mapWidth: 30,
      mapHeight: 32,
      planner: 'agentic',
      rooms: [
        RoomSummary(
          id: 'r2',
          purpose: 'combat',
          size: 'medium',
          description: 'Graves.',
          enemyCount: 3,
          behavior: 'patrol_room',
          chaseRange: 5,
          stepIntervalMs: 450,
        ),
      ],
      verification: VerificationSummary(
        checksPassed: 5,
        checksTotal: 6,
        atlasUsePercent: 3.2,
        checks: [
          VerificationCheck(
            name: 'gids_resolve',
            status: 'passed',
            detail: 'every GID maps to a tileset tile',
          ),
          VerificationCheck(
            name: 'objects_on_walkable',
            status: 'failed',
            detail: 'Zombie at (3, 4) is on a blocking tile',
          ),
          VerificationCheck(
            name: 'dart_analyze',
            status: 'passed',
            detail: 'no issues',
          ),
        ],
      ),
    );
    final api = _FakeApi(
      jobs: [
        _job('done', [
          StageState.done,
          StageState.done,
          StageState.done,
        ], summary: summary),
      ],
    );
    final downloads = <(Uri, String)>[];
    await _pump(
      tester,
      api,
      download: (url, name) async {
        downloads.add((url, name));
        return true;
      },
    );
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();
    await tester.pump();

    expect(
      find.text(
        'r2: combat, medium, 3 enemies (patrol_room, chase 5 tiles, '
        '450 ms/step) - Graves.',
      ),
      findsOneWidget,
    );
    expect(find.byKey(const Key('verification_section')), findsOneWidget);
    expect(find.text('5 of 6 passed'), findsOneWidget);
    expect(find.text('3.2% of the 4096 x 4096 web atlas'), findsOneWidget);
    expect(find.text('passed: no issues'), findsOneWidget);
    expect(
      find.text(
        'objects_on_walkable (failed): Zombie at (3, 4) is on a blocking tile',
      ),
      findsOneWidget,
    );

    await _tap(tester, find.byKey(const Key('download_bundle')));
    await tester.pump();
    expect(downloads, [
      (
        Uri.parse('http://localhost:8000/api/levels/abc/bundle.zip'),
        'level_abc.zip',
      ),
    ]);
    expect(find.text('Download bundle (.zip)'), findsOneWidget);
  });

  testWidgets('without a browser the download shows the bundle URL', (
    tester,
  ) async {
    final api = _FakeApi(
      jobs: [
        _job('done', [
          StageState.done,
          StageState.done,
          StageState.done,
        ], summary: _summary),
      ],
    );
    await _pump(tester, api, download: (url, name) async => false);
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();
    await tester.pump();
    await _tap(tester, find.byKey(const Key('download_bundle')));
    await tester.pump();
    expect(
      find.text(
        'Download the bundle from http://localhost:8000/api/levels/abc/bundle.zip',
      ),
      findsOneWidget,
    );
  });

  testWidgets('failed validation shows the failing checks', (tester) async {
    final api = _FakeApi(
      jobs: [
        _job(
          'failed',
          [StageState.done, StageState.failed, StageState.pending],
          errorCode: 'plan_validation_failed',
          steps: _steps.sublist(0, 1),
          summary: const JobSummary(
            planner: 'agentic',
            validation: ValidationReport(
              passed: false,
              checks: [
                ValidationCheck(
                  name: 'rooms_reachable',
                  passed: false,
                  detail: 'room r4 unreachable',
                ),
              ],
            ),
          ),
        ),
      ],
    );
    await _pump(tester, api);
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(
      find.text(
        'No valid level after all planning attempts. Try a simpler prompt.',
      ),
      findsOneWidget,
    );
    expect(find.text('Validation failed'), findsOneWidget);
    expect(find.text('rooms_reachable: room r4 unreachable'), findsOneWidget);
    expect(find.text('Try Out'), findsNothing);
  });

  testWidgets('always the AI planner; LLM error message', (tester) async {
    final api = _FakeApi(
      jobs: [
        _job('failed', [
          StageState.done,
          StageState.failed,
          StageState.pending,
        ], errorCode: 'llm_unavailable'),
      ],
    );
    await _pump(tester, api);
    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    expect(find.byKey(const Key('planner')), findsNothing);
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.planner, Planner.agentic);
    expect(
      find.text(
        'The AI planner could not reach the model. Try again. (server message)',
      ),
      findsOneWidget,
    );
  });

  testWidgets('backend offline shows the retry message', (tester) async {
    final api = _FakeApi(offline: true);
    await _pump(tester, api);

    expect(
      find.text(
        'Backend not reachable at http://localhost:8000. Start it with: '
        'uv run uvicorn app.main:app --port 8000 (in backend/)',
      ),
      findsOneWidget,
    );

    api.offline = false;
    await _tap(tester, find.text('Retry'));
    await tester.pump();
    expect(find.textContaining('Backend not reachable'), findsNothing);
  });
}

const _stageLabelsInOrder = [
  '1. Data Ingestion',
  '2. Level Planning',
  '3. Execution',
];
