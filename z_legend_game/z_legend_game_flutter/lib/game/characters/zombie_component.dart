import 'dart:math' as math;

import 'package:flame/collisions.dart';
import 'package:flame/components.dart';

import 'character_component.dart';
import 'player_component.dart';

/// Zombie enemy. Chases the player when within 5 tiles.
class ZombieComponent extends CharacterComponent {
  ZombieComponent({
    required super.startCol,
    required super.startRow,
    required super.isoMath,
    required this.player,
  }) : super(
         imageBaseName: 'characters/zombie',
         jsonBaseName: 'assets/images/characters/zombie',
       );

  final PlayerComponent player;

  /// Speed: one tile per [_stepInterval] seconds.
  static const double _stepInterval = 0.35;
  double _stepTimer = 0;

  /// Chase range in tiles.
  static const double _chaseRange = 5.0;

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    add(
      CircleHitbox(radius: 10, anchor: Anchor.center)
        ..collisionType = CollisionType.passive,
    );
  }

  @override
  Map<CharAnim, String> animationNames() => {
    CharAnim.idle: 'zombie_idle',
    CharAnim.walk: 'zombie_walk',
    CharAnim.attack: 'zombie_attack',
    CharAnim.die: 'zombie_die',
  };

  @override
  void update(double dt) {
    super.update(dt);
    if (isDead) return;

    final dist = _distanceToPlayer();
    if (dist > _chaseRange) {
      playAnimation(CharAnim.idle);
      return;
    }

    // Chase player
    final dcol = player.col - col;
    final drow = player.row - row;

    if (dcol == 0 && drow == 0) {
      playAnimation(CharAnim.idle);
      return;
    }

    // Face movement direction: convert grid delta to screen delta.
    final screenDx = (dcol - drow).toDouble();
    final screenDy = (dcol + drow).toDouble();
    setFacing(IsoDirection.fromDelta(screenDx, screenDy));
    playAnimation(CharAnim.walk);

    _stepTimer += dt;
    if (_stepTimer >= _stepInterval) {
      _stepTimer = 0;
      final stepCol = dcol.clamp(-1, 1);
      final stepRow = drow.clamp(-1, 1);
      final newCol = col + stepCol;
      final newRow = row + stepRow;
      if (isoMath.inBounds(newCol, newRow)) {
        setGridPosition(newCol, newRow);
      }
    }
  }

  double _distanceToPlayer() {
    final dcol = (player.col - col).toDouble();
    final drow = (player.row - row).toDouble();
    return math.sqrt(dcol * dcol + drow * drow);
  }

  /// Called by the game when the player attacks and this zombie is within range.
  void killByPlayer() {
    if (isDead) return;
    die(removeOnComplete: true);
  }
}
