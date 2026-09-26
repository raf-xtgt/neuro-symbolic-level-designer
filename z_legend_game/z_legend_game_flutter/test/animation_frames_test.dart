import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Tests that each animation's sidecar JSON specifies the correct frame count,
/// ensuring [CharacterComponent] will use per-animation metadata (not just
/// the idle metadata for every animation).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // Expected frame counts from the actual sidecar JSON files.
  final expected = {
    'assets/images/characters/player/survivor_idle.json': 1,
    'assets/images/characters/player/survivor_walk.json': 4,
    'assets/images/characters/player/survivor_attack.json': 1,
    'assets/images/characters/player/survivor_die.json': 2,
    'assets/images/characters/zombie/zombie_idle.json': 20,
    'assets/images/characters/zombie/zombie_walk.json': 20,
    'assets/images/characters/zombie/zombie_attack.json': 20,
    'assets/images/characters/zombie/zombie_die.json': 24,
  };

  for (final entry in expected.entries) {
    final path = entry.key;
    final expectedFrames = entry.value;
    test('$path: frames == $expectedFrames', () async {
      final jsonStr = await rootBundle.loadString(path);
      final data = jsonDecode(jsonStr) as Map<String, dynamic>;
      final frames = data['frames'] as int;
      expect(
        frames,
        expectedFrames,
        reason: '$path should have $expectedFrames frames',
      );
    });
  }
}
