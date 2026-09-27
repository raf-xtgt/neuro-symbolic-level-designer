import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../game/level/level_source.dart';
import '../screens/game_screen.dart';
import 'api/level_api.dart';
import 'api/models.dart';
import 'download/download.dart' as download;

/// Starts a browser download of [url]; false when there is no browser.
typedef DownloadUrl = Future<bool> Function(Uri url, String fileName);

/// Picks files with the given extensions (without dots).
typedef PickFiles = Future<List<LevelFile>> Function(List<String> extensions);

Future<List<LevelFile>> _pickWithFilePicker(List<String> extensions) async {
  final files = await FilePicker.pickFiles(
    type: FileType.custom,
    allowedExtensions: extensions,
  );
  return [
    for (final f in files)
      LevelFile(name: f.name, bytes: await f.readAsBytes()),
  ];
}

const int _maxPromptChars = 2000;
const int _maxFileBytes = 10 * 1024 * 1024;
const Duration _pollInterval = Duration(milliseconds: 500);

const Map<String, String> _stageLabels = {
  'ingesting': '1. Data Ingestion',
  'planning': '2. Level Planning',
  'executing': '3. Execution',
};

/// While a step runs: friendly text per step (ingestion, planning, execution).
const Map<String, String> _runningLabels = {
  'preprocess': 'Slicing the spritesheet...',
  'boundary_agent': 'AI-powered tile boundary analysis is running...',
  'classification_agent': 'AI-powered tile classification is running...',
  'collision_agent': 'AI-powered collision analysis is running...',
  'entity_agent': 'AI-powered entity detection is running...',
  'harmonizer': 'Building the asset catalog...',
  'quality_gate': 'Checking for floor tiles...',
  'topology_agent': 'AI-powered level layout planning is running...',
  'layout_builder': 'Placing rooms and corridors...',
  'stacking': 'Setting elevation...',
  'spawner': 'Placing the player, zombies, and exit...',
  'dressing': 'Dressing the level...',
  'validator': 'Validating playability...',
  'mechanics_agent': 'AI-powered enemy behavior design is running...',
  'codegen': 'Generating Flame code...',
  'verification': 'Verifying the bundle...',
};

/// Pipeline 1 steps for uploaded sheets (`ingestion_steps`).
const Map<String, String> _ingestionLabels = {
  'preprocess': 'Pre-processor',
  'boundary_agent': 'Tile boundary agent (AI)',
  'classification_agent': 'Classification agent (AI)',
  'collision_agent': 'Collision agent (AI)',
  'entity_agent': 'Entity agent (AI)',
  'harmonizer': 'Harmonizer',
  'quality_gate': 'Quality gate',
};

/// Pipeline 2 graph nodes (`planning_steps`).
const Map<String, String> _nodeLabels = {
  'topology_agent': 'Topology agent (AI)',
  'layout_builder': 'Layout builder',
  'stacking': 'Stacking',
  'spawner': 'Spawner',
  'dressing': 'Dressing',
  'validator': 'Validator',
};

/// Pipeline 3 steps (`execution_steps`).
const Map<String, String> _executionLabels = {
  'mechanics_agent': 'Enemy behavior agent (AI)',
  'codegen': 'Code generator',
  'verification': 'Verification',
};

/// Friendly text for a failed job, by error code.
String _errorText(JobStatus status) {
  final message = status.errorMessage ?? 'Generation failed.';
  return switch (status.errorCode) {
    'ingestion_no_floor' =>
      'The uploaded sheet has no usable isometric floor tiles (64 x 32 '
          'diamonds, or 128 x 64 / 32 x 16 ones that can be scaled). A level '
          'needs a walkable floor. ($message)',
    'llm_unavailable' =>
      'The AI planner could not reach the model. Try again. ($message)',
    'llm_output_invalid' =>
      'The AI planner returned an invalid room graph. Try again or rephrase '
          'the prompt. ($message)',
    'llm_config' =>
      'The AI planner is not configured on the server (backend .env). '
          '($message)',
    'plan_validation_failed' =>
      'No valid level after all planning attempts. Try a simpler prompt.',
    _ => message,
  };
}

/// The optional and upload file inputs, with their limits.
enum _FileInput {
  spritesheets('spritesheets', ['png'], 10),
  tilesets('tilesets', ['tsx', 'tsj'], 10),
  maps('maps', ['tmx', 'tmj'], 5);

  const _FileInput(this.field, this.extensions, this.maxCount);

  /// Multipart field name, also the key of its errors.
  final String field;
  final List<String> extensions;
  final int maxCount;
}

/// Level Designer: prompt + spritesheet source + optional files in, the
/// 3 pipeline stages and the generated level out, with **Try Out** to play it.
class LevelDesignerScreen extends StatefulWidget {
  const LevelDesignerScreen({
    super.key,
    this.api,
    this.pickFiles,
    this.download,
  });

  /// Backend client. Defaults to one built from `assets/config.json`.
  final LevelApi? api;

  /// File picker. Defaults to `file_picker`; replaced in tests.
  final PickFiles? pickFiles;

  /// Bundle download. Defaults to a browser download; replaced in tests.
  final DownloadUrl? download;

  @override
  State<LevelDesignerScreen> createState() => _LevelDesignerScreenState();
}

class _LevelDesignerScreenState extends State<LevelDesignerScreen> {
  final _prompt = TextEditingController();
  LevelApi? _api;

  // Inputs.
  // Loaded once to detect an offline backend; the level always uses the
  // uploads, or the default grassland pack without uploads.
  List<AssetPack>? _packs;
  final Map<_FileInput, List<LevelFile>> _files = {
    for (final input in _FileInput.values) input: [],
  };

  // Errors, keyed by input (`prompt`, `asset_pack`, `spritesheets`, ...).
  Map<String, List<String>> _errors = {};
  bool _offline = false;
  String? _requestError;

  // Job.
  bool _submitting = false;
  CreateJobResult? _job;
  JobStatus? _status;
  Timer? _pollTimer;
  Uint8List? _preview;
  Uint8List? _contactSheet;

  bool get _running =>
      _submitting || (_job != null && !(_status?.isFinished ?? false));

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _init() async {
    _api = widget.api ?? await LevelApi.fromConfig();
    if (mounted) await _loadPacks();
  }

  Future<void> _loadPacks() async {
    try {
      final packs = await _api!.listAssetPacks();
      if (!mounted) return;
      setState(() => _packs = packs);
    } on ApiUnavailableException {
      if (mounted) setState(() => _offline = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _requestError = e.message);
    }
  }

  void _retry() {
    setState(() => _offline = false);
    if (_packs == null) _loadPacks();
    if (_job != null && !(_status?.isFinished ?? false)) _poll();
  }

  // -- Validation (mirrors the backend; the backend stays the authority) ----

  Map<String, List<String>> _validate() {
    final errors = <String, List<String>>{};
    void add(String key, String message) => (errors[key] ??= []).add(message);

    final prompt = _prompt.text.trim();
    if (prompt.isEmpty) add('prompt', 'Enter a prompt.');
    if (prompt.length > _maxPromptChars) {
      add('prompt', 'Use at most $_maxPromptChars characters.');
    }
    for (final input in _FileInput.values) {
      final files = _files[input]!;
      if (files.length > input.maxCount) {
        add(input.field, 'At most ${input.maxCount} files are allowed.');
      }
      for (final f in files) {
        final ext = f.name.split('.').last.toLowerCase();
        if (!f.name.contains('.') || !input.extensions.contains(ext)) {
          add(
            input.field,
            '${f.name}: must be ${input.extensions.map((e) => '.$e').join(' or ')}.',
          );
        }
        if (f.bytes.length > _maxFileBytes) {
          add(input.field, '${f.name}: larger than 10 MB.');
        }
      }
    }
    return errors;
  }

  // -- Actions ----------------------------------------------------------

  Future<void> _pick(_FileInput input) async {
    final picked = await (widget.pickFiles ?? _pickWithFilePicker)(
      input.extensions,
    );
    if (!mounted || picked.isEmpty) return;
    setState(() {
      _files[input]!.addAll(picked);
      _errors.remove(input.field);
    });
  }

  Future<void> _generate() async {
    final errors = _validate();
    setState(() {
      _errors = errors;
      _requestError = null;
    });
    if (errors.isNotEmpty) return;

    _pollTimer?.cancel();
    setState(() {
      _submitting = true;
      _job = null;
      _status = null;
      _preview = null;
      _contactSheet = null;
    });
    final sheets = _files[_FileInput.spritesheets]!;
    try {
      final job = await _api!.createLevel(
        LevelRequest(
          prompt: _prompt.text.trim(),
          planner: Planner.agentic,
          assetPack: sheets.isEmpty ? defaultAssetPack : null,
          spritesheets: sheets,
          tilesets: _files[_FileInput.tilesets]!,
          maps: _files[_FileInput.maps]!,
        ),
      );
      if (!mounted) return;
      setState(() => _job = job);
      _poll();
    } on ApiValidationException catch (e) {
      if (!mounted) return;
      setState(() {
        _errors = {};
        for (final error in e.errors) {
          (_errors[error.input] ??= []).add(error.message);
        }
      });
    } on ApiUnavailableException {
      if (mounted) setState(() => _offline = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _requestError = e.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _poll() async {
    final job = _job;
    if (job == null) return;
    try {
      final status = await _api!.getJob(job.jobId);
      if (!mounted || _job != job) return;
      setState(() => _status = status);
      if (status.isDone) {
        final preview = await _api!.getBundleFile(
          job.jobId,
          'preview_level.png',
        );
        if (mounted && _job == job) setState(() => _preview = preview);
        if (status.summary?.ingestion != null) {
          final sheet = await _api!.getBundleFile(
            job.jobId,
            'contact_sheet.png',
          );
          if (mounted && _job == job) setState(() => _contactSheet = sheet);
        }
      } else if (!status.isFailed) {
        _pollTimer = Timer(_pollInterval, _poll);
      }
    } on ApiUnavailableException {
      if (mounted) setState(() => _offline = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _requestError = e.message);
    }
  }

  void _tryOut() {
    final job = _job!;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            GameScreen(source: LevelSource.network(_api!.bundleUrl(job.jobId))),
      ),
    );
  }

  Future<void> _downloadBundle() async {
    final jobId = _job!.jobId;
    final url = _api!.bundleZipUrl(jobId);
    final started = await (widget.download ?? download.downloadUrl)(
      url,
      'level_${jobId.length > 8 ? jobId.substring(0, 8) : jobId}.zip',
    );
    if (!started && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Download the bundle from $url')));
    }
  }

  // -- UI ---------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: const Text('Level Designer'),
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 1100;
          final inputs = _inputsPanel();
          final output = _outputPanel();
          final content = wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: inputs),
                    const SizedBox(width: 24),
                    Expanded(child: output),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [inputs, const SizedBox(height: 24), output],
                );
          return SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (_offline) ...[_offlineBanner(), const SizedBox(height: 16)],
                content,
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _offlineBanner() {
    final url = _api?.baseUrl.toString() ?? 'the configured API URL';
    return _Panel(
      color: Colors.red.shade900.withValues(alpha: 0.4),
      child: Row(
        children: [
          const Icon(Icons.cloud_off, color: Colors.redAccent),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'Backend not reachable at $url. Start it with: '
              'uv run uvicorn app.main:app --port 8000 (in backend/)',
            ),
          ),
          const SizedBox(width: 12),
          OutlinedButton(onPressed: _retry, child: const Text('Retry')),
        ],
      ),
    );
  }

  Widget _inputsPanel() {
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _Heading('Prompt'),
          TextField(
            key: const Key('prompt'),
            controller: _prompt,
            minLines: 3,
            maxLines: 6,
            maxLength: _maxPromptChars,
            decoration: const InputDecoration(
              hintText: 'Describe the level, e.g. "graveyard with a cabin"',
              border: OutlineInputBorder(),
            ),
          ),
          _ErrorList(_errors['prompt']),
          const SizedBox(height: 16),
          const _Heading('Spritesheets'),
          _uploadInput(),
          _ErrorList(_errors['asset_pack']),
          _ErrorList(_errors['planner']),
          const SizedBox(height: 16),
          const _Heading('Optional'),
          _fileInput(_FileInput.tilesets, 'Existing tilesets (.tsx, .tsj)'),
          const SizedBox(height: 8),
          _fileInput(_FileInput.maps, 'Existing maps (.tmx, .tmj)'),
          const SizedBox(height: 24),
          if (_requestError != null) ...[
            Text(
              _requestError!,
              style: const TextStyle(color: Colors.redAccent),
            ),
            const SizedBox(height: 8),
          ],
          ElevatedButton.icon(
            onPressed: _running ? null : _generate,
            icon: const Icon(Icons.auto_awesome),
            label: const Text('Generate level'),
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 18),
            ),
          ),
        ],
      ),
    );
  }

  Widget _uploadInput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Upload your isometric spritesheets (PNG). If you do not upload '
          'any, the default grassland spritesheet is used.',
          key: Key('upload_hint'),
        ),
        const SizedBox(height: 4),
        const Text(
          'A 2:1 base diamond (64 x 32, or 128 x 64 / 32 x 16, scaled). AI '
          'agents slice and classify the tiles; the first run of a sheet '
          'takes about a minute, later runs use the cache.',
          style: TextStyle(color: Colors.white70, fontSize: 12),
        ),
        const SizedBox(height: 8),
        _fileInput(_FileInput.spritesheets, 'Spritesheets (PNG, up to 10)'),
      ],
    );
  }

  Widget _fileInput(_FileInput input, String label) {
    final files = _files[input]!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(child: Text(label)),
            TextButton.icon(
              onPressed: () => _pick(input),
              icon: const Icon(Icons.attach_file),
              label: const Text('Add files'),
            ),
          ],
        ),
        for (final (i, f) in files.indexed)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.insert_drive_file_outlined),
            title: Text(f.name),
            subtitle: Text('${(f.bytes.length / 1024).toStringAsFixed(1)} KB'),
            trailing: IconButton(
              tooltip: 'Remove',
              icon: const Icon(Icons.close),
              onPressed: () => setState(() => files.removeAt(i)),
            ),
          ),
        _ErrorList(_errors[input.field]),
      ],
    );
  }

  Widget _outputPanel() {
    final status = _status;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _Heading('Progress'),
          for (final stage in jobStages) ...[
            _StageRow(
              label: _stageLabels[stage]!,
              state: status?.stages[stage] ?? StageState.pending,
            ),
            if (stage == 'ingesting' && status != null)
              for (final step in status.ingestionSteps) _IngestionStepRow(step),
            if (stage == 'planning' && status != null)
              for (final step in status.planningSteps)
                _PlanningStepRow(step, _nodeLabels),
            if (stage == 'executing' && status != null)
              for (final step in status.executionSteps)
                _PlanningStepRow(step, _executionLabels, showAttempt: false),
          ],
          if (status != null && status.isFailed) ...[
            const SizedBox(height: 12),
            Text(
              _errorText(status),
              style: const TextStyle(color: Colors.redAccent),
            ),
            if (status.summary?.validation case final report?) ...[
              const SizedBox(height: 8),
              _ValidationBadge(report),
            ],
          ],
          if (status != null && status.warnings.isNotEmpty) ...[
            const SizedBox(height: 12),
            for (final w in status.warnings)
              Text('Warning: $w', style: const TextStyle(color: Colors.amber)),
          ],
          if (status != null && status.isDone) ..._result(status),
        ],
      ),
    );
  }

  List<Widget> _result(JobStatus status) {
    final summary = status.summary;
    String counts(Map<String, int> m) =>
        m.entries.map((e) => '${e.key}: ${e.value}').join(', ');
    String legacy(Map<String, dynamic> f) => f['kind'] == 'tileset'
        ? '${f['file_name']} (tileset, ${f['tile_count']} tiles)'
        : '${f['file_name']} (map, ${f['width']} x ${f['height']}, '
              '${f['layer_count']} layers)';

    return [
      const SizedBox(height: 24),
      const _Heading('Result'),
      if (_preview != null)
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: Image.memory(
            _preview!,
            fit: BoxFit.contain,
            errorBuilder: (_, _, _) => const Text('Preview not available.'),
          ),
        )
      else
        const LinearProgressIndicator(),
      const SizedBox(height: 12),
      if (summary?.ingestion case final ingestion?) ...[
        const _Heading('Ingested tiles'),
        if (_contactSheet != null)
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.memory(
              _contactSheet!,
              key: const Key('contact_sheet'),
              fit: BoxFit.contain,
              errorBuilder: (_, _, _) =>
                  const Text('Contact sheet not available.'),
            ),
          ),
        const SizedBox(height: 8),
        ..._ingestionLines(ingestion),
        const SizedBox(height: 16),
      ],
      if (summary != null) ...[
        if (status.sourceLabel case final source?)
          _SummaryLine('Spritesheets', source),
        _SummaryLine(
          'Map size',
          '${summary.mapWidth} x ${summary.mapHeight} tiles',
        ),
        _SummaryLine('Tiles by material', counts(summary.tilesByMaterial)),
        _SummaryLine('Entities by type', counts(summary.entitiesByType)),
        _SummaryLine(
          'Legacy files',
          summary.legacyFiles.isEmpty
              ? 'none'
              : summary.legacyFiles.map(legacy).join('\n'),
        ),
        if (summary.planner != null)
          _SummaryLine(
            'Planner',
            Planner.values
                .firstWhere(
                  (p) => p.id == summary.planner,
                  orElse: () => Planner.placeholder,
                )
                .label,
          ),
        if (summary.designNotes case final notes? when notes.isNotEmpty)
          _SummaryLine('Design notes', notes),
        if (summary.rooms.isNotEmpty)
          _SummaryLine(
            'Rooms',
            summary.rooms
                .map(
                  (r) =>
                      '${r.id}: ${r.purpose}, ${r.size}, '
                      '${r.enemyCount} ${r.enemyCount == 1 ? 'enemy' : 'enemies'}'
                      '${r.behavior == null ? '' : ' (${r.behavior}, chase ${r.chaseRange} tiles, ${r.stepIntervalMs} ms/step)'}'
                      '${r.description.isEmpty ? '' : ' - ${r.description}'}',
                )
                .join('\n'),
          ),
        if (summary.llmUsage case final usage?)
          _SummaryLine(
            'LLM usage',
            '${usage.calls} ${usage.calls == 1 ? 'call' : 'calls'}, '
                '${usage.inputTokens} input + ${usage.outputTokens} output '
                'tokens, ${(usage.latencyMs / 1000).toStringAsFixed(1)} s',
          ),
        if (summary.validation case final report?) ...[
          const SizedBox(height: 8),
          _ValidationBadge(report),
        ],
        if (summary.verification case final verification?) ...[
          const SizedBox(height: 16),
          _VerificationSection(verification),
        ],
      ],
      const SizedBox(height: 16),
      ElevatedButton.icon(
        onPressed: _tryOut,
        icon: const Icon(Icons.play_arrow),
        label: const Text('Try Out'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 18),
        ),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('download_bundle'),
        onPressed: _downloadBundle,
        icon: const Icon(Icons.download),
        label: const Text('Download bundle (.zip)'),
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 14),
        ),
      ),
    ];
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, this.color});

  final Widget child;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    // A Material (not a decorated Container) so ListTiles paint on it.
    return Material(
      color: color ?? Colors.grey.shade900,
      borderRadius: BorderRadius.circular(8),
      child: Padding(padding: const EdgeInsets.all(16), child: child),
    );
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        text,
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
    );
  }
}

class _ErrorList extends StatelessWidget {
  const _ErrorList(this.errors);

  final List<String>? errors;

  @override
  Widget build(BuildContext context) {
    final errors = this.errors;
    if (errors == null || errors.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final e in errors)
            Text(e, style: const TextStyle(color: Colors.redAccent)),
        ],
      ),
    );
  }
}

class _StageRow extends StatelessWidget {
  const _StageRow({required this.label, required this.state});

  final String label;
  final StageState state;

  @override
  Widget build(BuildContext context) {
    final icon = switch (state) {
      StageState.pending => const Icon(
        Icons.radio_button_unchecked,
        color: Colors.grey,
      ),
      StageState.running => const SizedBox.square(
        dimension: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      ),
      StageState.done => const Icon(Icons.check_circle, color: Colors.green),
      StageState.failed => const Icon(Icons.error, color: Colors.redAccent),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(width: 24, child: Center(child: icon)),
          const SizedBox(width: 12),
          Expanded(child: Text(label)),
          Text(state.name, style: const TextStyle(color: Colors.white70)),
        ],
      ),
    );
  }
}

List<Widget> _ingestionLines(IngestionSummary s) {
  String counts(Map<String, int> m, [int? take]) =>
      (take == null ? m.entries : m.entries.take(take))
          .map((e) => '${e.key}: ${e.value}')
          .join(', ');
  final usage = s.llmUsage;
  return [
    _SummaryLine(
      'Tiles',
      '${s.tiles} of ${s.chips} chips${s.cached ? ' (from the cache)' : ''}',
    ),
    _SummaryLine('Tile size', s.tileSizes.join('\n')),
    _SummaryLine('By category', counts(s.tilesByCategory)),
    _SummaryLine('Top families', counts(s.tilesByFamily, 8)),
    _SummaryLine(
      'Excluded',
      s.exclusions.isEmpty ? 'none' : counts(s.exclusions),
    ),
    _SummaryLine('Conflicts resolved', '${s.conflicts}'),
    if (usage != null)
      _SummaryLine(
        'Ingestion LLM',
        s.cached
            ? 'none (cache hit)'
            : '${usage.calls} calls, ${usage.inputTokens} input + '
                  '${usage.outputTokens} output tokens, '
                  '${(usage.latencyMs / 1000).toStringAsFixed(1)} s',
      ),
  ];
}

class _IngestionStepRow extends StatelessWidget {
  const _IngestionStepRow(this.step);

  final IngestionStep step;

  @override
  Widget build(BuildContext context) {
    final label = _ingestionLabels[step.node] ?? step.node;
    final icon = switch (step.status) {
      'running' => const SizedBox.square(
        dimension: 14,
        child: CircularProgressIndicator(strokeWidth: 2),
      ),
      'failed' => const Icon(
        Icons.error_outline,
        size: 16,
        color: Colors.redAccent,
      ),
      'cached' => const Icon(Icons.bolt, size: 16, color: Colors.amber),
      _ => const Icon(Icons.check, size: 16, color: Colors.green),
    };
    final progress = step.total == null || step.total == 0
        ? ''
        : ' (${step.done} of ${step.total} batches)';
    final text = step.status == 'running'
        ? '${_runningLabels[step.node] ?? label}$progress'
        : '$label$progress: ${step.message}';
    return Padding(
      padding: const EdgeInsets.only(left: 36, top: 2, bottom: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 16, child: Center(child: icon)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 13, color: Colors.white70),
            ),
          ),
        ],
      ),
    );
  }
}

/// A planning node or execution step: the friendly running text while it
/// runs, then its label and result message.
class _PlanningStepRow extends StatelessWidget {
  const _PlanningStepRow(this.step, this.labels, {this.showAttempt = true});

  final PlanningStep step;
  final Map<String, String> labels;
  final bool showAttempt;

  @override
  Widget build(BuildContext context) {
    final label = labels[step.node] ?? step.node;
    final attempt = showAttempt ? ' (attempt ${step.attempt})' : '';
    return Padding(
      padding: const EdgeInsets.only(left: 36, top: 2, bottom: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 16,
            child: Center(
              child: step.running
                  ? const SizedBox.square(
                      dimension: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(
                      step.failed ? Icons.error_outline : Icons.check,
                      size: 16,
                      color: step.failed ? Colors.orangeAccent : Colors.green,
                    ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              step.running
                  ? _runningLabels[step.node] ?? label
                  : '$label$attempt: ${step.message}',
              style: const TextStyle(fontSize: 13, color: Colors.white70),
            ),
          ),
        ],
      ),
    );
  }
}

class _ValidationBadge extends StatelessWidget {
  const _ValidationBadge(this.report);

  final ValidationReport report;

  @override
  Widget build(BuildContext context) {
    final color = report.passed ? Colors.green : Colors.redAccent;
    return Container(
      key: const Key('validation_badge'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                report.passed ? Icons.verified : Icons.gpp_bad,
                color: color,
                size: 18,
              ),
              const SizedBox(width: 6),
              Text(
                report.passed ? 'Validation passed' : 'Validation failed',
                style: TextStyle(color: color, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          for (final check in report.failed)
            Text(
              '${check.name}: ${check.detail}',
              style: const TextStyle(color: Colors.redAccent),
            ),
        ],
      ),
    );
  }
}

/// Pipeline 3 verification: each check passed / failed / skipped, the atlas
/// use and the `dart analyze` result of the generated `level_loader.dart`.
class _VerificationSection extends StatelessWidget {
  const _VerificationSection(this.verification);

  final VerificationSummary verification;

  @override
  Widget build(BuildContext context) {
    final v = verification;
    return Column(
      key: const Key('verification_section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _Heading('Verification'),
        _SummaryLine(
          'Checks',
          '${v.checksPassed} of ${v.checksTotal} passed'
              '${v.checksSkipped == 0 ? '' : ', ${v.checksSkipped} skipped'}',
        ),
        if (v.atlasUsePercent case final percent?)
          _SummaryLine('Atlas use', '$percent% of the 4096 x 4096 web atlas'),
        if (v.dartAnalyze case final dart?)
          _SummaryLine('dart analyze', '${dart.status}: ${dart.detail}'),
        const SizedBox(height: 4),
        for (final check in v.checks) _VerificationRow(check),
      ],
    );
  }
}

class _VerificationRow extends StatelessWidget {
  const _VerificationRow(this.check);

  final VerificationCheck check;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (check.status) {
      'passed' => (Icons.check_circle, Colors.green),
      'skipped' => (Icons.remove_circle_outline, Colors.white54),
      _ => (Icons.cancel, Colors.redAccent),
    };
    return Padding(
      key: Key('verification_${check.name}'),
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              '${check.name} (${check.status}): ${check.detail}',
              style: TextStyle(color: color == Colors.green ? null : color),
            ),
          ),
        ],
      ),
    );
  }
}

class _SummaryLine extends StatelessWidget {
  const _SummaryLine(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: Text(label, style: const TextStyle(color: Colors.white70)),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
