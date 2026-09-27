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
}) => JobStatus(
  jobId: 'abc',
  status: status,
  stages: {for (final (i, s) in jobStages.indexed) s: stages[i]},
  warnings: const [],
  errorCode: errorCode,
  errorMessage: errorCode == null ? null : 'server message',
  summary: summary,
  planningSteps: steps,
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

Future<void> _pump(WidgetTester tester, LevelApi api, {PickFiles? pick}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData.dark(),
      home: LevelDesignerScreen(api: api, pickFiles: pick),
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
        _job('planning', [
          StageState.done,
          StageState.running,
          StageState.pending,
        ]),
        _job('executing', [
          StageState.done,
          StageState.done,
          StageState.running,
        ]),
        _job(
          'done',
          [StageState.done, StageState.done, StageState.done],
          summary: _summary,
        ),
      ],
    );
    await _pump(tester, api);
    expect(find.text('Grass and stone.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.prompt, 'graveyard');
    expect(api.lastRequest?.assetPack, 'grassland_starter');
    expect(_stateOf(tester, '1. Data Ingestion'), 'running');
    expect(find.text('Try Out'), findsNothing);

    await tester.pump(const Duration(milliseconds: 500));
    expect(_stateOf(tester, '1. Data Ingestion'), 'done');
    expect(_stateOf(tester, '2. Level Planning'), 'running');

    await tester.pump(const Duration(milliseconds: 500));
    expect(_stateOf(tester, '3. Execution'), 'running');

    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump();
    for (final label in _stageLabelsInOrder) {
      expect(_stateOf(tester, label), 'done');
    }
    expect(find.text('20 x 20 tiles'), findsOneWidget);
    expect(find.text('grass: 380, stone: 20'), findsOneWidget);
    expect(find.text('Try Out'), findsOneWidget);
    expect(find.byType(Image), findsOneWidget);

    // Polling stopped: no timers left.
    await tester.pump(const Duration(seconds: 2));
  });

  testWidgets('ingestion_not_implemented shows the upload message', (
    tester,
  ) async {
    final api = _FakeApi(
      jobs: [
        _job(
          'failed',
          [StageState.failed, StageState.pending, StageState.pending],
          errorCode: 'ingestion_not_implemented',
        ),
      ],
    );
    await _pump(
      tester,
      api,
      pick: (_) async => [LevelFile(name: 'sheet.png', bytes: _png)],
    );

    await tester.enterText(find.byKey(const Key('prompt')), 'graveyard');
    await _tap(tester, find.text('Upload spritesheets'));
    expect(
      find.textContaining('Custom spritesheet ingestion is not available yet'),
      findsOneWidget,
    );
    await _tap(tester, find.text('Add files').first);
    expect(find.text('sheet.png'), findsOneWidget);

    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.assetPack, isNull);
    expect(api.lastRequest?.spritesheets.single.name, 'sheet.png');
    expect(_stateOf(tester, '1. Data Ingestion'), 'failed');
    expect(
      find.text(
        'Spritesheet ingestion is not available yet. Choose a built-in asset '
        'pack.',
      ),
      findsOneWidget,
    );
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
    expect(find.text('AI planner (Gemini)'), findsWidgets);
    expect(find.text('Try Out'), findsOneWidget);
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

  testWidgets('placeholder planner choice and LLM error message', (
    tester,
  ) async {
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
    await _tap(tester, find.byKey(const Key('planner')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Placeholder').last);
    await tester.pumpAndSettle();
    await _tap(tester, find.text('Generate level'));
    await tester.pump();

    expect(api.lastRequest?.planner, Planner.placeholder);
    expect(
      find.text(
        'The AI planner could not reach the model. Try again, or choose the '
        'Placeholder planner. (server message)',
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
    expect(find.text('Grass and stone.'), findsOneWidget);
  });
}

const _stageLabelsInOrder = [
  '1. Data Ingestion',
  '2. Level Planning',
  '3. Execution',
];
