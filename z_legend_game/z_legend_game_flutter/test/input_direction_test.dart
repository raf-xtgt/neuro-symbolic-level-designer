import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/characters/character_component.dart';
import 'package:z_legend_game_flutter/game/characters/player_component.dart';
import 'package:z_legend_game_flutter/game/iso/iso_math.dart';

void main() {
  // Test that key combinations map to the correct 8 IsoDirection values.
  // PlayerComponent._inputDelta converts held keys to (dcol, drow).
  // IsoDirection.fromDelta then maps screen (dx, dy) to a direction.
  //
  // The 8 WASD/arrow combos and their expected facing directions:
  //   W only  → screen up   → IsoDirection.n  (NW in iso = col-1,row-1)
  //   S only  → screen down → IsoDirection.s
  //   A only  → screen left → IsoDirection.w   (SW in iso = col-1,row+1)
  //   D only  → screen right→ IsoDirection.e
  //   W+D     → NE
  //   W+A     → NW
  //   S+D     → SE
  //   S+A     → SW

  final player = PlayerComponent(
    startCol: 5,
    startRow: 5,
    isoMath: IsoMath.starter,
  );

  Map<String, dynamic> dirCase(
    String label,
    Set<LogicalKeyboardKey> keys,
    IsoDirection expected,
  ) => {'label': label, 'keys': keys, 'expected': expected};

  final cases = [
    dirCase('W → N', {LogicalKeyboardKey.keyW}, IsoDirection.n),
    dirCase('S → S', {LogicalKeyboardKey.keyS}, IsoDirection.s),
    dirCase('A → W', {LogicalKeyboardKey.keyA}, IsoDirection.w),
    dirCase('D → E', {LogicalKeyboardKey.keyD}, IsoDirection.e),
    dirCase('W+D → NE', {
      LogicalKeyboardKey.keyW,
      LogicalKeyboardKey.keyD,
    }, IsoDirection.ne),
    dirCase('W+A → NW', {
      LogicalKeyboardKey.keyW,
      LogicalKeyboardKey.keyA,
    }, IsoDirection.nw),
    dirCase('S+D → SE', {
      LogicalKeyboardKey.keyS,
      LogicalKeyboardKey.keyD,
    }, IsoDirection.se),
    dirCase('S+A → SW', {
      LogicalKeyboardKey.keyS,
      LogicalKeyboardKey.keyA,
    }, IsoDirection.sw),
    // Arrow keys mirror WASD
    dirCase('Up → N', {LogicalKeyboardKey.arrowUp}, IsoDirection.n),
    dirCase('Down → S', {LogicalKeyboardKey.arrowDown}, IsoDirection.s),
    dirCase('Left → W', {LogicalKeyboardKey.arrowLeft}, IsoDirection.w),
    dirCase('Right → E', {LogicalKeyboardKey.arrowRight}, IsoDirection.e),
  ];

  for (final tc in cases) {
    test(tc['label'] as String, () {
      final keys = tc['keys'] as Set<LogicalKeyboardKey>;
      final expected = tc['expected'] as IsoDirection;

      final (dcol, drow) = player.inputDeltaForKeys(keys);
      // Map grid delta back to screen delta for direction computation
      // dcol = sdx + sdy,  drow = -sdx + sdy  →  sdx = (dcol-drow)/2, sdy=(dcol+drow)/2
      final sdx = ((dcol - drow) / 2).toDouble();
      final sdy = ((dcol + drow) / 2).toDouble();
      final dir = IsoDirection.fromDelta(sdx, sdy);
      expect(dir, expected, reason: 'dcol=$dcol drow=$drow sdx=$sdx sdy=$sdy');
    });
  }
}
