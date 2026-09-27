import 'dart:math' as math;

import 'package:flame_tiled/flame_tiled.dart';

import '../level/walkability.dart';

/// What a zombie does while the player is out of its chase range.
enum ZombieBehavior {
  /// Waits in place.
  idleUntilNear('idle_until_near'),

  /// Walks to random open cells inside its room.
  patrolRoom('patrol_room'),

  /// Stays within [ZombieBrain.guardRadius] tiles of the exit.
  guardExit('guard_exit');

  const ZombieBehavior(this.id);

  /// The Tiled property value.
  final String id;

  static ZombieBehavior parse(String? id) => ZombieBehavior.values.firstWhere(
    (b) => b.id == id,
    orElse: () => ZombieBehavior.idleUntilNear,
  );
}

/// A room rectangle in grid cells.
class RoomRect {
  const RoomRect(this.col, this.row, this.width, this.height);

  final int col;
  final int row;
  final int width;
  final int height;

  bool contains(int c, int r) =>
      c >= col && c < col + width && r >= row && r < row + height;
}

/// Zombie settings from the Tiled object properties the planner writes
/// (entity mechanics agent, ARCHITECTURE.md 5.3): `chase_range`,
/// `step_interval_ms`, `behavior`, and `room_id` with the room rectangle
/// `room_col`, `room_row`, `room_w`, `room_h`. Missing values use defaults.
class ZombieConfig {
  const ZombieConfig({
    this.chaseRange = defaultChaseRange,
    this.stepIntervalMs = defaultStepIntervalMs,
    this.behavior = ZombieBehavior.idleUntilNear,
    this.roomId,
    this.room,
  });

  factory ZombieConfig.fromProperties(CustomProperties properties) {
    String? raw(String name) => properties.byName[name]?.value.toString();
    int? integer(String name) => int.tryParse(raw(name) ?? '');
    final (col, row, w, h) = (
      integer('room_col'),
      integer('room_row'),
      integer('room_w'),
      integer('room_h'),
    );
    return ZombieConfig(
      chaseRange: (integer('chase_range') ?? defaultChaseRange).toDouble(),
      stepIntervalMs: integer('step_interval_ms') ?? defaultStepIntervalMs,
      behavior: ZombieBehavior.parse(raw('behavior')),
      roomId: raw('room_id'),
      room: col != null && row != null && w != null && h != null
          ? RoomRect(col, row, w, h)
          : null,
    );
  }

  static const double defaultChaseRange = 5;
  static const int defaultStepIntervalMs = 350;

  /// Chase range in tiles.
  final double chaseRange;

  /// Milliseconds per tile step.
  final int stepIntervalMs;
  final ZombieBehavior behavior;
  final String? roomId;
  final RoomRect? room;

  double get stepInterval => stepIntervalMs / 1000;
}

/// The zombie's movement decisions, apart from the component so they can be
/// tested: chase the player in range, else follow [ZombieConfig.behavior].
class ZombieBrain {
  ZombieBrain({
    required this.config,
    required this.walkability,
    this.exit,
    math.Random? random,
  }) : _random = random ?? math.Random(0);

  /// `guard_exit` keeps the zombie within this many tiles of the exit.
  static const double guardRadius = 3;

  final ZombieConfig config;
  final WalkabilityGrid walkability;
  final (int, int)? exit;
  final math.Random _random;
  (int, int)? _patrolTarget;

  /// The next cell to step to, or null to stay (idle).
  (int, int)? nextStep((int, int) self, (int, int) player) {
    if (_distance(self, player) <= config.chaseRange) {
      _patrolTarget = null;
      return _toward(self, player);
    }
    return switch (config.behavior) {
      ZombieBehavior.idleUntilNear => null,
      ZombieBehavior.patrolRoom => _patrol(self),
      ZombieBehavior.guardExit => _guard(self),
    };
  }

  (int, int)? _patrol((int, int) self) {
    final room = config.room;
    if (room == null) return null;
    var target = _patrolTarget;
    if (target == null || target == self) {
      target = _patrolTarget = _randomCell(room);
      if (target == null) return null;
    }
    final next = _toward(self, target);
    final inside = room.contains(self.$1, self.$2);
    if (next == null || (inside && !room.contains(next.$1, next.$2))) {
      _patrolTarget = null; // never leave the room; try another target
      return null;
    }
    return next;
  }

  (int, int)? _guard((int, int) self) {
    final exit = this.exit;
    if (exit == null || _distance(self, exit) <= guardRadius) return null;
    return _toward(self, exit);
  }

  (int, int)? _randomCell(RoomRect room) {
    for (var i = 0; i < 20; i++) {
      final c = room.col + _random.nextInt(room.width);
      final r = room.row + _random.nextInt(room.height);
      if (walkability.isOpen(c, r)) return (c, r);
    }
    return null;
  }

  (int, int)? _toward((int, int) from, (int, int) to) {
    final path = walkability.findPath(from, to);
    return path == null || path.length < 2 ? null : path[1];
  }

  static double _distance((int, int) a, (int, int) b) {
    final dc = (a.$1 - b.$1).toDouble();
    final dr = (a.$2 - b.$2).toDouble();
    return math.sqrt(dc * dc + dr * dr);
  }
}
