import 'package:flame/collisions.dart';
import 'package:flame/components.dart';
import 'package:flutter/services.dart';

import 'character_component.dart';

/// The player character. Responds to WASD / arrow key input.
///
/// Key events are delivered by the game's [HasKeyboardHandlerComponents] mixin
/// via [KeyboardHandler].
class PlayerComponent extends CharacterComponent with KeyboardHandler {
  PlayerComponent({
    required super.startCol,
    required super.startRow,
    required super.isoMath,
  }) : super(
         imageBaseName: 'characters/player',
         jsonBaseName: 'assets/images/characters/player',
       );

  /// Movement speed: one tile per [_stepInterval] seconds.
  static const double _stepInterval = 0.18;
  double _stepTimer = 0;

  final Set<LogicalKeyboardKey> _held = {};

  bool _attacking = false;

  /// True while the attack animation is playing.
  bool get isAttacking => _attacking;

  /// Called once at the start of each attack. Kill nearby zombies via callback.
  void Function()? onAttackStart;

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    add(
      CircleHitbox(radius: 10, anchor: Anchor.center)
        ..collisionType = CollisionType.active,
    );
  }

  @override
  Map<CharAnim, String> animationNames() => {
    CharAnim.idle: 'survivor_idle',
    CharAnim.walk: 'survivor_walk',
    CharAnim.attack: 'survivor_attack',
    CharAnim.die: 'survivor_die',
  };

  @override
  bool onKeyEvent(KeyEvent event, Set<LogicalKeyboardKey> keysPressed) {
    _held.clear();
    _held.addAll(keysPressed);

    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.space &&
        !isDead) {
      _doAttack();
    }
    return false;
  }

  void _doAttack() {
    if (_attacking) return;
    _attacking = true;
    // Notify game to kill nearby zombies at attack start.
    onAttackStart?.call();
    playAnimation(CharAnim.attack);
    _getSpriteComp()?.animationTicker?.onComplete = () {
      _attacking = false;
      playAnimation(CharAnim.idle);
    };
  }

  SpriteAnimationComponent? _getSpriteComp() {
    for (final child in children) {
      if (child is SpriteAnimationComponent) return child;
    }
    return null;
  }

  @override
  void update(double dt) {
    super.update(dt);
    if (isDead || _attacking) return;

    final (dx, dy) = _inputDelta();
    if (dx == 0 && dy == 0) {
      playAnimation(CharAnim.idle);
      return;
    }

    // Convert isometric grid delta to screen delta for direction facing.
    // dcol = sdx + sdy,  drow = -sdx + sdy  →  sdx = (dcol-drow)/2
    final sdx = ((dx - dy) / 2).toDouble();
    final sdy = ((dx + dy) / 2).toDouble();
    setFacing(IsoDirection.fromDelta(sdx, sdy));
    playAnimation(CharAnim.walk);

    _stepTimer += dt;
    if (_stepTimer >= _stepInterval) {
      _stepTimer = 0;
      final newCol = col + dx;
      final newRow = row + dy;
      if (isoMath.inBounds(newCol, newRow)) {
        setGridPosition(newCol, newRow);
      }
    }
  }

  /// Returns the grid delta (dcol, drow) from the currently held keys.
  ///
  /// Isometric screen mapping:
  ///   W/Up    → col-1, row-1  (screen NW = iso north)
  ///   S/Down  → col+1, row+1
  ///   A/Left  → col-1, row+1
  ///   D/Right → col+1, row-1
  (int, int) _inputDelta() {
    final up =
        _held.contains(LogicalKeyboardKey.keyW) ||
        _held.contains(LogicalKeyboardKey.arrowUp);
    final down =
        _held.contains(LogicalKeyboardKey.keyS) ||
        _held.contains(LogicalKeyboardKey.arrowDown);
    final left =
        _held.contains(LogicalKeyboardKey.keyA) ||
        _held.contains(LogicalKeyboardKey.arrowLeft);
    final right =
        _held.contains(LogicalKeyboardKey.keyD) ||
        _held.contains(LogicalKeyboardKey.arrowRight);

    // Screen space deltas
    int sdx = (right ? 1 : 0) - (left ? 1 : 0);
    int sdy = (down ? 1 : 0) - (up ? 1 : 0);

    // Convert screen delta to isometric grid delta
    int dcol = sdx + sdy;
    int drow = -sdx + sdy;

    // Clamp to max 1 per axis
    if (dcol > 1) dcol = 1;
    if (dcol < -1) dcol = -1;
    if (drow > 1) drow = 1;
    if (drow < -1) drow = -1;

    return (dcol, drow);
  }

  /// Grid delta exposed for testing, given an explicit key set.
  (int, int) inputDeltaForKeys(Set<LogicalKeyboardKey> keys) {
    _held
      ..clear()
      ..addAll(keys);
    return _inputDelta();
  }
}
