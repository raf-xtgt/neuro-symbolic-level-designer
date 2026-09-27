import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'http_asset_bundle.dart';

/// Describes where to load a level bundle from.
///
/// Provides an [AssetBundle] and the [prefix] path that is prepended to every
/// filename inside the bundle (map file, tileset file, tileset image).
class LevelSource {
  const LevelSource({required this.bundle, required this.prefix});

  /// The asset bundle to load files from.
  final AssetBundle bundle;

  /// Path prefix (including trailing slash) prepended to every filename.
  final String prefix;

  /// Loads the starter level from the app's bundled assets.
  factory LevelSource.bundled(String assetFolder) {
    return LevelSource(bundle: rootBundle, prefix: assetFolder);
  }

  /// Loads a level bundle from a remote URL at runtime ("Try Out").
  ///
  /// [baseUrl] must point to the folder that contains `level.tmj`, e.g.
  /// `http://localhost:8000/api/levels/<job_id>/bundle/`. Pass [client] to
  /// serve the files from a mock in tests.
  factory LevelSource.network(Uri baseUrl, {http.Client? client}) {
    return LevelSource(
      bundle: HttpAssetBundle(baseUrl, client: client),
      prefix: '',
    );
  }
}
