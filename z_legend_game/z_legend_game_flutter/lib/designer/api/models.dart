import 'dart:typed_data';

/// A built-in asset pack (`GET /api/asset-packs`).
class AssetPack {
  const AssetPack({
    required this.id,
    required this.name,
    required this.description,
    required this.spritesheets,
    required this.tileWidth,
    required this.tileHeight,
  });

  factory AssetPack.fromJson(Map<String, dynamic> json) {
    final tileSize = json['tile_size'] as Map<String, dynamic>;
    return AssetPack(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String,
      spritesheets: (json['spritesheets'] as List).cast<String>(),
      tileWidth: tileSize['width'] as int,
      tileHeight: tileSize['height'] as int,
    );
  }

  final String id;
  final String name;
  final String description;
  final List<String> spritesheets;
  final int tileWidth;
  final int tileHeight;
}

/// A file chosen by the user, sent as one multipart part.
class LevelFile {
  const LevelFile({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

/// Pipeline 2 planners (`planner` form field).
enum Planner {
  agentic('agentic', 'AI planner (Gemini)'),
  placeholder('placeholder', 'Placeholder');

  const Planner(this.id, this.label);

  final String id;
  final String label;
}

/// Input for `POST /api/levels` (ARCHITECTURE.md section 1.2).
class LevelRequest {
  const LevelRequest({
    required this.prompt,
    this.planner = Planner.agentic,
    this.assetPack,
    this.spritesheets = const [],
    this.tilesets = const [],
    this.maps = const [],
  });

  final String prompt;
  final Planner planner;
  final String? assetPack;
  final List<LevelFile> spritesheets;
  final List<LevelFile> tilesets;
  final List<LevelFile> maps;
}

/// `202` body of `POST /api/levels`.
class CreateJobResult {
  const CreateJobResult({
    required this.jobId,
    required this.statusUrl,
    required this.bundleUrl,
  });

  factory CreateJobResult.fromJson(Map<String, dynamic> json) {
    return CreateJobResult(
      jobId: json['job_id'] as String,
      statusUrl: json['status_url'] as String,
      bundleUrl: json['bundle_url'] as String,
    );
  }

  final String jobId;
  final String statusUrl;
  final String bundleUrl;
}

enum StageState { pending, running, done, failed }

/// The pipeline stages, in order, keyed as in the job status.
const List<String> jobStages = ['ingesting', 'planning', 'executing'];

/// One node run of the planning graph (`planning_steps`).
class PlanningStep {
  const PlanningStep({
    required this.node,
    required this.status,
    required this.attempt,
    required this.message,
  });

  factory PlanningStep.fromJson(Map<String, dynamic> json) => PlanningStep(
    node: json['node'] as String,
    status: json['status'] as String,
    attempt: json['attempt'] as int,
    message: json['message'] as String,
  );

  /// E.g. `topology_agent`, `layout_builder`, `validator`.
  final String node;

  /// `done` or `failed`.
  final String status;
  final int attempt;
  final String message;

  bool get failed => status == 'failed';
}

/// One step of Pipeline 1 for uploaded sheets (`ingestion_steps`).
class IngestionStep {
  const IngestionStep({
    required this.node,
    required this.status,
    required this.message,
    this.done,
    this.total,
  });

  factory IngestionStep.fromJson(Map<String, dynamic> json) => IngestionStep(
    node: json['node'] as String,
    status: json['status'] as String,
    message: json['message'] as String,
    done: json['done'] as int?,
    total: json['total'] as int?,
  );

  /// E.g. `preprocess`, `classification_agent`, `harmonizer`, `quality_gate`.
  final String node;

  /// `running`, `done`, `failed` or `cached`.
  final String status;
  final String message;

  /// Batches done and in total, for the agent steps.
  final int? done;
  final int? total;
}

/// `GET /api/levels/{job_id}`.
class JobStatus {
  const JobStatus({
    required this.jobId,
    required this.status,
    required this.stages,
    required this.warnings,
    this.errorCode,
    this.errorMessage,
    this.summary,
    this.ingestionSteps = const [],
    this.planningSteps = const [],
  });

  factory JobStatus.fromJson(Map<String, dynamic> json) {
    final error = json['error'] as Map<String, dynamic>?;
    final summary = json['summary'] as Map<String, dynamic>?;
    return JobStatus(
      jobId: json['job_id'] as String,
      status: json['status'] as String,
      stages: (json['stages'] as Map<String, dynamic>).map(
        (stage, state) => MapEntry(stage, StageState.values.byName(state)),
      ),
      warnings: (json['warnings'] as List).cast<String>(),
      errorCode: error?['code'] as String?,
      errorMessage: error?['message'] as String?,
      summary: summary == null ? null : JobSummary.fromJson(summary),
      ingestionSteps: (json['ingestion_steps'] as List? ?? const [])
          .map((s) => IngestionStep.fromJson(s as Map<String, dynamic>))
          .toList(),
      planningSteps: (json['planning_steps'] as List? ?? const [])
          .map((s) => PlanningStep.fromJson(s as Map<String, dynamic>))
          .toList(),
    );
  }

  final String jobId;

  /// `queued`, `ingesting`, `planning`, `executing`, `done` or `failed`.
  final String status;
  final Map<String, StageState> stages;
  final List<String> warnings;
  final String? errorCode;
  final String? errorMessage;

  /// Also set for a failed agentic planning run (validation report, rooms).
  final JobSummary? summary;
  final List<IngestionStep> ingestionSteps;
  final List<PlanningStep> planningSteps;

  bool get isDone => status == 'done';
  bool get isFailed => status == 'failed';
  bool get isFinished => isDone || isFailed;
}

/// Summary of a job: complete when done; after a failed agentic planning run
/// only the planner facts (validation, rooms, usage) are set.
class JobSummary {
  const JobSummary({
    this.mapWidth = 0,
    this.mapHeight = 0,
    this.tilesByMaterial = const {},
    this.entitiesByType = const {},
    this.legacyFiles = const [],
    this.planner,
    this.designNotes,
    this.rooms = const [],
    this.validation,
    this.llmUsage,
    this.ingestion,
    this.verification,
  });

  factory JobSummary.fromJson(Map<String, dynamic> json) {
    final size = json['map_size'] as Map<String, dynamic>?;
    Map<String, int> counts(String key) =>
        (json[key] as Map<String, dynamic>? ?? const {}).cast<String, int>();
    final validation = json['validation'] as Map<String, dynamic>?;
    final usage = json['llm_usage'] as Map<String, dynamic>?;
    final ingestion = json['ingestion'] as Map<String, dynamic>?;
    final verification = json['verification'] as Map<String, dynamic>?;
    return JobSummary(
      mapWidth: size?['width'] as int? ?? 0,
      mapHeight: size?['height'] as int? ?? 0,
      tilesByMaterial: counts('tile_count_by_material'),
      entitiesByType: counts('entity_count_by_type'),
      legacyFiles: (json['legacy_files'] as List? ?? const [])
          .cast<Map<String, dynamic>>(),
      planner: json['planner'] as String?,
      designNotes: json['design_notes'] as String?,
      rooms: (json['rooms'] as List? ?? const [])
          .map((r) => RoomSummary.fromJson(r as Map<String, dynamic>))
          .toList(),
      validation: validation == null
          ? null
          : ValidationReport.fromJson(validation),
      llmUsage: usage == null ? null : LlmUsage.fromJson(usage),
      ingestion: ingestion == null
          ? null
          : IngestionSummary.fromJson(ingestion),
      verification: verification == null
          ? null
          : VerificationSummary.fromJson(verification),
    );
  }

  final int mapWidth;
  final int mapHeight;
  final Map<String, int> tilesByMaterial;
  final Map<String, int> entitiesByType;

  /// Parsed optional tilesets and maps, as reported by the backend.
  final List<Map<String, dynamic>> legacyFiles;

  /// `agentic` or `placeholder`.
  final String? planner;
  final String? designNotes;
  final List<RoomSummary> rooms;
  final ValidationReport? validation;
  final LlmUsage? llmUsage;

  /// Pipeline 1 facts, for uploaded spritesheets only.
  final IngestionSummary? ingestion;

  /// Pipeline 3 verification engine (`summary.verification`).
  final VerificationSummary? verification;
}

/// The verification block of a done job (the full report is `summary.json`).
class VerificationSummary {
  const VerificationSummary({
    required this.checksPassed,
    required this.checksTotal,
    this.checksSkipped = 0,
    this.atlasUsePercent,
    this.checks = const [],
  });

  factory VerificationSummary.fromJson(Map<String, dynamic> json) =>
      VerificationSummary(
        checksPassed: json['checks_passed'] as int? ?? 0,
        checksTotal: json['checks_total'] as int? ?? 0,
        checksSkipped: json['checks_skipped'] as int? ?? 0,
        atlasUsePercent: (json['atlas_use_percent'] as num?)?.toDouble(),
        checks: (json['checks'] as List? ?? const [])
            .map((c) => VerificationCheck.fromJson(c as Map<String, dynamic>))
            .toList(),
      );

  final int checksPassed;
  final int checksTotal;
  final int checksSkipped;
  final double? atlasUsePercent;
  final List<VerificationCheck> checks;

  VerificationCheck? get dartAnalyze {
    for (final c in checks) {
      if (c.name == 'dart_analyze') return c;
    }
    return null;
  }
}

/// One verification check: [status] is `passed`, `failed` or `skipped`.
class VerificationCheck {
  const VerificationCheck({
    required this.name,
    required this.status,
    this.detail = '',
  });

  factory VerificationCheck.fromJson(Map<String, dynamic> json) =>
      VerificationCheck(
        name: json['name'] as String,
        status: json['status'] as String? ?? 'failed',
        detail: json['detail'] as String? ?? '',
      );

  final String name;
  final String status;
  final String detail;
}

/// Pipeline 1 summary of an upload job (`summary.ingestion`).
class IngestionSummary {
  const IngestionSummary({
    required this.cached,
    required this.chips,
    required this.tiles,
    required this.tilesByCategory,
    required this.tilesByFamily,
    required this.exclusions,
    required this.conflicts,
    required this.tileSizes,
    this.llmUsage,
  });

  factory IngestionSummary.fromJson(Map<String, dynamic> json) {
    Map<String, int> counts(String key) =>
        (json[key] as Map<String, dynamic>? ?? const {}).cast<String, int>();
    final usage = json['llm_usage'] as Map<String, dynamic>?;
    return IngestionSummary(
      cached: json['cached'] as bool? ?? false,
      chips: json['chips'] as int? ?? 0,
      tiles: json['tiles'] as int? ?? 0,
      tilesByCategory: counts('tile_count_by_category'),
      tilesByFamily: counts('tile_count_by_family'),
      exclusions: counts('exclusions'),
      conflicts: json['conflicts'] as int? ?? 0,
      tileSizes: [
        for (final s
            in (json['sheets'] as List? ?? const [])
                .cast<Map<String, dynamic>>())
          '${s['name']}: ${(s['tile_size'] as List).join(' x ')}'
              '${(s['scale'] as num) == 1 ? '' : ', scaled x${s['scale']}'}',
      ],
      llmUsage: usage == null ? null : LlmUsage.fromJson(usage),
    );
  }

  final bool cached;
  final int chips;
  final int tiles;
  final Map<String, int> tilesByCategory;

  /// Most common first, as sent by the backend.
  final Map<String, int> tilesByFamily;
  final Map<String, int> exclusions;
  final int conflicts;

  /// Per sheet: detected base tile size and scale.
  final List<String> tileSizes;
  final LlmUsage? llmUsage;
}

/// A room of the planned topology.
class RoomSummary {
  const RoomSummary({
    required this.id,
    required this.purpose,
    required this.size,
    required this.description,
    required this.enemyCount,
    this.behavior,
    this.chaseRange,
    this.stepIntervalMs,
  });

  factory RoomSummary.fromJson(Map<String, dynamic> json) {
    final mechanics = json['mechanics'] as Map<String, dynamic>?;
    return RoomSummary(
      id: json['id'] as String,
      purpose: json['purpose'] as String,
      size: json['size'] as String,
      description: json['description'] as String? ?? '',
      enemyCount: json['enemy_count'] as int? ?? 0,
      behavior: mechanics?['behavior'] as String?,
      chaseRange: mechanics?['chase_range_tiles'] as int?,
      stepIntervalMs: mechanics?['step_interval_ms'] as int?,
    );
  }

  final String id;
  final String purpose;
  final String size;
  final String description;
  final int enemyCount;

  /// Zombie behavior from the entity mechanics agent (rooms with enemies).
  final String? behavior;
  final int? chaseRange;
  final int? stepIntervalMs;
}

/// The Pipeline 2 validator report.
class ValidationReport {
  const ValidationReport({required this.passed, required this.checks});

  factory ValidationReport.fromJson(Map<String, dynamic> json) =>
      ValidationReport(
        passed: json['passed'] as bool,
        checks: (json['checks'] as List? ?? const [])
            .map((c) => ValidationCheck.fromJson(c as Map<String, dynamic>))
            .toList(),
      );

  final bool passed;
  final List<ValidationCheck> checks;

  List<ValidationCheck> get failed => [
    for (final c in checks)
      if (!c.passed) c,
  ];
}

class ValidationCheck {
  const ValidationCheck({
    required this.name,
    required this.passed,
    required this.detail,
  });

  factory ValidationCheck.fromJson(Map<String, dynamic> json) =>
      ValidationCheck(
        name: json['name'] as String,
        passed: json['passed'] as bool,
        detail: json['detail'] as String? ?? '',
      );

  final String name;
  final bool passed;
  final String detail;
}

/// LLM calls of a planning run.
class LlmUsage {
  const LlmUsage({
    required this.calls,
    required this.inputTokens,
    required this.outputTokens,
    required this.latencyMs,
  });

  factory LlmUsage.fromJson(Map<String, dynamic> json) => LlmUsage(
    calls: json['calls'] as int? ?? 0,
    inputTokens: json['input_tokens'] as int? ?? 0,
    outputTokens: json['output_tokens'] as int? ?? 0,
    latencyMs: json['latency_ms'] as int? ?? 0,
  );

  final int calls;
  final int inputTokens;
  final int outputTokens;
  final int latencyMs;
}

/// One entry of a `422` body.
class FieldError {
  const FieldError({required this.field, required this.message});

  factory FieldError.fromJson(Map<String, dynamic> json) => FieldError(
    field: json['field'] as String,
    message: json['message'] as String,
  );

  /// E.g. `prompt`, `asset_pack`, `spritesheets` or `spritesheets[0]`.
  final String field;
  final String message;

  /// The input the error belongs to: [field] without an `[index]` suffix.
  String get input => field.split('[').first;
}

/// The backend rejected the request (`422`).
class ApiValidationException implements Exception {
  const ApiValidationException(this.errors);

  final List<FieldError> errors;

  @override
  String toString() => 'ApiValidationException(${errors.length} errors)';
}

/// The backend could not be reached.
class ApiUnavailableException implements Exception {
  const ApiUnavailableException(this.baseUrl, [this.cause]);

  final Uri baseUrl;
  final Object? cause;

  @override
  String toString() => 'ApiUnavailableException($baseUrl): $cause';
}

/// Any other unexpected response.
class ApiException implements Exception {
  const ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => 'ApiException($statusCode): $message';
}
