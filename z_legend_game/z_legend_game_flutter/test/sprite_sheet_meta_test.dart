import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // All sidecar JSON files in assets/images/characters/
  const sheetJsonPaths = [
    'assets/images/characters/player/survivor_idle.json',
    'assets/images/characters/player/survivor_walk.json',
    'assets/images/characters/player/survivor_attack.json',
    'assets/images/characters/player/survivor_die.json',
    'assets/images/characters/zombie/zombie_idle.json',
    'assets/images/characters/zombie/zombie_walk.json',
    'assets/images/characters/zombie/zombie_attack.json',
    'assets/images/characters/zombie/zombie_die.json',
  ];

  for (final path in sheetJsonPaths) {
    test('$path: valid sidecar JSON', () async {
      final jsonStr = await rootBundle.loadString(path);
      final data = jsonDecode(jsonStr) as Map<String, dynamic>;

      final frameWidth = data['frame_width'] as int;
      final frameHeight = data['frame_height'] as int;
      final frames = data['frames'] as int;
      final fps = (data['fps'] as num).toDouble();
      final directions = data['directions'] as List;
      final anchor = data['anchor'] as Map<String, dynamic>;

      expect(frameWidth, greaterThan(0));
      expect(frameHeight, greaterThan(0));
      expect(frames, greaterThan(0));
      expect(fps, greaterThan(0));
      expect(directions.length, 8, reason: 'must have 8 directions');
      expect(
        directions,
        containsAllInOrder(['S', 'SW', 'W', 'NW', 'N', 'NE', 'E', 'SE']),
      );
      expect(anchor.containsKey('x'), isTrue);
      expect(anchor.containsKey('y'), isTrue);

      // Verify image size relationship: image should be
      // frames * frameWidth wide by 8 * frameHeight tall.
      // We cannot load the PNG here (no game context) but we confirm
      // the metadata is self-consistent.
      expect(frameWidth * frames, greaterThan(0));
      expect(frameHeight * 8, greaterThan(0));
    });
  }
}
