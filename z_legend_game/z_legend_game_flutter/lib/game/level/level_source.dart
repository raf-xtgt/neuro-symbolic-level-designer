import 'package:flutter/services.dart';

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

  /// Loads a level bundle from a remote URL at runtime.
  ///
  /// [baseUrl] must point to the folder that contains `level.tmj`, e.g.
  /// `https://example.com/levels/my_level/`.
  factory LevelSource.network(Uri baseUrl) {
    final prefix = baseUrl.toString().endsWith('/')
        ? baseUrl.toString()
        : '${baseUrl.toString()}/';
    return LevelSource(
      bundle: NetworkAssetBundle(Uri.parse(prefix)),
      prefix: '',
    );
  }
}
