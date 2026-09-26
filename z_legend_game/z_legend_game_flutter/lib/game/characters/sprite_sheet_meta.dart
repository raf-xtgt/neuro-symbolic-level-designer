import 'dart:convert';

import 'package:flame/components.dart';
import 'package:flutter/services.dart';

/// Parsed contents of a character sidecar JSON file.
class SpriteSheetMeta {
  const SpriteSheetMeta({
    required this.frameWidth,
    required this.frameHeight,
    required this.directions,
    required this.frames,
    required this.fps,
    required this.anchor,
  });

  final int frameWidth;
  final int frameHeight;
  final List<String> directions;
  final int frames;
  final double fps;

  /// Anchor in pixels relative to the top-left of a single frame.
  final Vector2 anchor;

  /// Number of directions (always 8 for valid sheets).
  int get directionCount => directions.length;

  /// Loads and parses a sidecar JSON file from [assetPath].
  static Future<SpriteSheetMeta> load(String assetPath) async {
    final jsonStr = await rootBundle.loadString(assetPath);
    return fromJson(jsonDecode(jsonStr) as Map<String, dynamic>);
  }

  /// Loads and parses a sidecar JSON file from a custom [bundle].
  static Future<SpriteSheetMeta> loadFromBundle(
    String assetPath,
    AssetBundle bundle,
  ) async {
    final jsonStr = await bundle.loadString(assetPath);
    return fromJson(jsonDecode(jsonStr) as Map<String, dynamic>);
  }

  /// Parses a sidecar JSON map into a [SpriteSheetMeta].
  static SpriteSheetMeta fromJson(Map<String, dynamic> json) {
    final anchorMap = json['anchor'] as Map<String, dynamic>;
    return SpriteSheetMeta(
      frameWidth: json['frame_width'] as int,
      frameHeight: json['frame_height'] as int,
      directions: List<String>.from(json['directions'] as List),
      frames: json['frames'] as int,
      fps: (json['fps'] as num).toDouble(),
      anchor: Vector2(
        (anchorMap['x'] as num).toDouble(),
        (anchorMap['y'] as num).toDouble(),
      ),
    );
  }
}
