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

/// Input for `POST /api/levels` (ARCHITECTURE.md section 1.2).
class LevelRequest {
  const LevelRequest({
    required this.prompt,
    this.assetPack,
    this.spritesheets = const [],
    this.tilesets = const [],
    this.maps = const [],
  });

  final String prompt;
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
    );
  }

  final String jobId;

  /// `queued`, `ingesting`, `planning`, `executing`, `done` or `failed`.
  final String status;
  final Map<String, StageState> stages;
  final List<String> warnings;
  final String? errorCode;
  final String? errorMessage;
  final JobSummary? summary;

  bool get isDone => status == 'done';
  bool get isFailed => status == 'failed';
  bool get isFinished => isDone || isFailed;
}

/// Summary of a finished job.
class JobSummary {
  const JobSummary({
    required this.mapWidth,
    required this.mapHeight,
    required this.tilesByMaterial,
    required this.entitiesByType,
    required this.legacyFiles,
  });

  factory JobSummary.fromJson(Map<String, dynamic> json) {
    final size = json['map_size'] as Map<String, dynamic>;
    Map<String, int> counts(String key) =>
        (json[key] as Map<String, dynamic>? ?? const {}).cast<String, int>();
    return JobSummary(
      mapWidth: size['width'] as int,
      mapHeight: size['height'] as int,
      tilesByMaterial: counts('tile_count_by_material'),
      entitiesByType: counts('entity_count_by_type'),
      legacyFiles: (json['legacy_files'] as List? ?? const [])
          .cast<Map<String, dynamic>>(),
    );
  }

  final int mapWidth;
  final int mapHeight;
  final Map<String, int> tilesByMaterial;
  final Map<String, int> entitiesByType;

  /// Parsed optional tilesets and maps, as reported by the backend.
  final List<Map<String, dynamic>> legacyFiles;
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
