import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/characters/player_health.dart';

void main() {
  test('6 hits kill the player, 5 do not', () {
    final health = PlayerHealth();
    for (var i = 0; i < 5; i++) {
      expect(health.hit(), isTrue);
      health.update(PlayerHealth.invulnerableTime + 0.01);
    }
    expect(health.hp, 1);
    expect(health.isDead, isFalse);
    expect(health.hit(), isTrue);
    expect(health.isDead, isTrue);
    health.update(1);
    expect(health.hit(), isFalse, reason: 'no hits after death');
    expect(health.hp, 0);
  });

  test('0.6 s of invulnerability after a hit, flashing meanwhile', () {
    final health = PlayerHealth();
    expect(health.opacity, 1);
    expect(health.hit(), isTrue);
    expect(health.isInvulnerable, isTrue);
    final seen = <double>{};
    for (var t = 0.0; t < 0.55; t += 0.05) {
      seen.add(health.opacity);
      expect(health.hit(), isFalse, reason: 'invulnerable at $t s');
      health.update(0.05);
    }
    expect(seen, containsAll(<double>[0.3, 1]), reason: 'it blinks');
    health.update(0.06);
    expect(health.isInvulnerable, isFalse);
    expect(health.opacity, 1);
    expect(health.hit(), isTrue);
    expect(health.hp, 4);
  });
}
