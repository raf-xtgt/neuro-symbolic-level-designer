import 'dart:math' as math;

import 'package:flame/collisions.dart';
import 'package:flame/components.dart';

import 'character_component.dart';
import 'player_component.dart';
import 'zombie_config.dart';

/// Zombie enemy. Chases the player within [ZombieConfig.chaseRange] tiles,
/// along the shortest path on the [WalkabilityGrid] (around obstacles, never
/// into them); otherwise idles, patrols its room, or guards the exit
/// ([ZombieConfig.behavior], from the level's Tiled object properties).
/// Next to the player (or on its cell) it stops, faces the player and
/// attacks: 1 damage every [attackCooldown] seconds. It never steps onto the
/// player's cell.
class ZombieComponent extends CharacterComponent {
  ZombieComponent({
    required super.startCol,
    required super.startRow,
    required super.isoMath,
    required super.walkability,
    required this.player,
    this.config = const ZombieConfig(),
    (int, int)? exit,
    math.Random? random,
  }) : _brain = ZombieBrain(
         config: config,
         walkability: walkability,
         exit: exit,
         random: random ?? math.Random(startCol * 1000 + startRow),
       ),
       super(
         imageBaseName: 'characters/zombie',
         jsonBaseName: 'assets/images/characters/zombie',
       );

  final PlayerComponent player;
  final ZombieConfig config;
  final ZombieBrain _brain;

  /// Speed: one tile per [ZombieConfig.stepInterval] seconds.
  double _stepTimer = 0;

  /// Seconds between two attacks.
  static const double attackCooldown = 1.0;
  double _cooldown = 0;

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
    if (_cooldown > 0) _cooldown -= dt;

    final dcolPlayer = player.col - col;
    final drowPlayer = player.row - row;
    if (!player.isDead && dcolPlayer.abs() <= 1 && drowPlayer.abs() <= 1) {
      _stepTimer = 0;
      setFacing(
        IsoDirection.fromDelta(
          (dcolPlayer - drowPlayer).toDouble(),
          (dcolPlayer + drowPlayer).toDouble(),
        ),
      );
      if (_cooldown <= 0) {
        _cooldown = attackCooldown;
        replayAnimation(CharAnim.attack);
        player.takeHit();
      }
      return;
    }

    // The next cell along a BFS path, recomputed every update (the map is
    // small), so the zombie follows the player and goes around obstacles.
    final next = _brain.nextStep((col, row), (player.col, player.row));
    if (next == null) {
      _stepTimer = 0;
      playAnimation(CharAnim.idle);
      return;
    }
    final (nextCol, nextRow) = next;
    if (next == (player.col, player.row)) {
      _stepTimer = 0;
      return;
    }
    final dcol = nextCol - col;
    final drow = nextRow - row;

    // Face movement direction: convert grid delta to screen delta.
    final screenDx = (dcol - drow).toDouble();
    final screenDy = (dcol + drow).toDouble();
    setFacing(IsoDirection.fromDelta(screenDx, screenDy));
    playAnimation(CharAnim.walk);

    _stepTimer += dt;
    if (_stepTimer >= config.stepInterval) {
      _stepTimer = 0;
      if (isoMath.inBounds(nextCol, nextRow)) {
        setGridPosition(nextCol, nextRow);
      }
    }
  }

  /// Called by the game when the player attacks and this zombie is within range.
  void killByPlayer() {
    if (isDead) return;
    die(removeOnComplete: true);
  }
}
