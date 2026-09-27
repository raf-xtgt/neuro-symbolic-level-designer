import 'dart:math' as math;

/// The player's health: [max] points, and a short invulnerability after
/// each hit during which the player flashes.
class PlayerHealth {
  PlayerHealth({this.max = defaultMax}) : _hp = max;

  static const int defaultMax = 6;

  /// Seconds of invulnerability after a hit.
  static const double invulnerableTime = 0.6;

  /// Seconds per flash half-period while invulnerable.
  static const double flashPeriod = 0.1;

  final int max;
  int _hp;
  double _invulnerable = 0;

  int get hp => _hp;
  bool get isDead => _hp <= 0;
  bool get isInvulnerable => _invulnerable > 0;

  /// Deals [damage]; false (no effect) while invulnerable or dead.
  bool hit([int damage = 1]) {
    if (isDead || isInvulnerable) return false;
    _hp = math.max(0, _hp - damage);
    _invulnerable = invulnerableTime;
    return true;
  }

  void update(double dt) {
    if (_invulnerable > 0) _invulnerable = math.max(0, _invulnerable - dt);
  }

  /// Sprite opacity: blinks while invulnerable, else 1.
  double get opacity {
    if (!isInvulnerable) return 1;
    return (_invulnerable / flashPeriod).floor().isEven ? 0.3 : 1;
  }
}
