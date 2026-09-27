import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../game/level/level_source.dart';
import '../screens/game_screen.dart';
import 'api/level_api.dart';
import 'api/models.dart';

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
  const LevelDesignerScreen({super.key, this.api, this.pickFiles});

  /// Backend client. Defaults to one built from `assets/config.json`.
  final LevelApi? api;

  /// File picker. Defaults to `file_picker`; replaced in tests.
  final PickFiles? pickFiles;

  @override
  State<LevelDesignerScreen> createState() => _LevelDesignerScreenState();
}

class _LevelDesignerScreenState extends State<LevelDesignerScreen> {
  final _prompt = TextEditingController();
  LevelApi? _api;

  // Inputs.
  bool _useUpload = false;
  List<AssetPack>? _packs;
  String? _packId;
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
      setState(() {
        _packs = packs;
        _packId ??= packs.isEmpty ? null : packs.first.id;
      });
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
    if (!_useUpload && _packId == null) {
      add('asset_pack', 'Choose an asset pack.');
    }
    if (_useUpload && _files[_FileInput.spritesheets]!.isEmpty) {
      add('spritesheets', 'Choose 1 to 10 PNG spritesheets.');
    }

    for (final input in _FileInput.values) {
      if (input == _FileInput.spritesheets && !_useUpload) continue;
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
    });
    try {
      final job = await _api!.createLevel(
        LevelRequest(
          prompt: _prompt.text.trim(),
          assetPack: _useUpload ? null : _packId,
          spritesheets: _useUpload ? _files[_FileInput.spritesheets]! : [],
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
          const _Heading('Spritesheet source'),
          RadioGroup<bool>(
            groupValue: _useUpload,
            onChanged: (v) => setState(() => _useUpload = v ?? false),
            child: const Column(
              children: [
                RadioListTile(
                  value: false,
                  title: Text('Built-in asset pack'),
                  contentPadding: EdgeInsets.zero,
                ),
                RadioListTile(
                  value: true,
                  title: Text('Upload spritesheets'),
                  contentPadding: EdgeInsets.zero,
                ),
              ],
            ),
          ),
          if (_useUpload) _uploadInput() else _packInput(),
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

  Widget _packInput() {
    final packs = _packs;
    if (packs == null) {
      return _offline
          ? const Text('Asset packs are not loaded.')
          : const LinearProgressIndicator();
    }
    AssetPack? selected;
    for (final p in packs) {
      if (p.id == _packId) selected = p;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<String>(
          key: const Key('asset_pack'),
          initialValue: _packId,
          decoration: const InputDecoration(border: OutlineInputBorder()),
          items: [
            for (final p in packs)
              DropdownMenuItem(value: p.id, child: Text(p.name)),
          ],
          onChanged: (id) => setState(() => _packId = id),
        ),
        if (selected != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              selected.description,
              style: const TextStyle(color: Colors.white70),
            ),
          ),
        _ErrorList(_errors['asset_pack']),
      ],
    );
  }

  Widget _uploadInput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _Panel(
          color: Color(0x33FFC107),
          child: Row(
            children: [
              Icon(Icons.info_outline, color: Colors.amber),
              SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Custom spritesheet ingestion is not available yet. Use a '
                  'built-in asset pack to generate a level.',
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        _fileInput(_FileInput.spritesheets, 'Spritesheets (PNG, 1 to 10)'),
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
          for (final stage in jobStages)
            _StageRow(
              label: _stageLabels[stage]!,
              state: status?.stages[stage] ?? StageState.pending,
            ),
          if (status != null && status.isFailed) ...[
            const SizedBox(height: 12),
            Text(
              status.errorCode == 'ingestion_not_implemented'
                  ? 'Spritesheet ingestion is not available yet. Choose a '
                        'built-in asset pack.'
                  : status.errorMessage ?? 'Generation failed.',
              style: const TextStyle(color: Colors.redAccent),
            ),
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
      if (summary != null) ...[
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
