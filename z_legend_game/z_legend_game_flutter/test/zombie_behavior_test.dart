import 'dart:math' as math;

import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/characters/zombie_config.dart';
import 'package:z_legend_game_flutter/game/level/walkability.dart';

/// Zombie settings from Tiled object properties (written by the planner's
/// entity mechanics agent) and the behaviors they select.
void main() {
  CustomProperties props(Map<String, String> values) => CustomProperties({
    for (final e in values.entries)
      e.key: StringProperty(name: e.key, value: e.value),
  });

  test('reads chase range, speed, behavior and room from properties', () {
    final config = ZombieConfig.fromProperties(
      props({
        'chase_range': '7',
        'step_interval_ms': '450',
        'behavior': 'patrol_room',
        'room_id': 'r2',
        'room_col': '4',
        'room_row': '5',
        'room_w': '6',
        'room_h': '3',
      }),
    );
    expect(config.chaseRange, 7);
    expect(config.stepIntervalMs, 450);
    expect(config.stepInterval, 0.45);
    expect(config.behavior, ZombieBehavior.patrolRoom);
    expect(config.roomId, 'r2');
    final room = config.room!;
    expect((room.col, room.row, room.width, room.height), (4, 5, 6, 3));
  });

  test('missing or bad properties use the defaults', () {
    for (final config in [
      ZombieConfig.fromProperties(CustomProperties.empty),
      ZombieConfig.fromProperties(
        props({'chase_range': 'far', 'behavior': 'dance', 'room_col': '1'}),
      ),
    ]) {
      expect(config.chaseRange, 5);
      expect(config.stepIntervalMs, 350);
      expect(config.behavior, ZombieBehavior.idleUntilNear);
      expect(config.room, isNull);
    }
  });

  // A 20 x 20 map, room (5, 5) to (10, 9) with a rock inside, player far away.
  final grid = WalkabilityGrid(
    cols: 20,
    rows: 20,
    blocked: const [(7, 7), (12, 7)],
  );
  const room = RoomRect(5, 5, 6, 5);
  const farPlayer = (0, 19);

  test('patrol_room walks around but stays inside its room', () {
    final brain = ZombieBrain(
      config: const ZombieConfig(
        behavior: ZombieBehavior.patrolRoom,
        chaseRange: 3,
        room: room,
      ),
      walkability: grid,
      random: math.Random(1),
    );
    var self = (6, 6);
    final visited = {self};
    for (var i = 0; i < 300; i++) {
      self = brain.nextStep(self, farPlayer) ?? self;
      expect(room.contains(self.$1, self.$2), isTrue, reason: '$self');
      expect(grid.isOpen(self.$1, self.$2), isTrue);
      visited.add(self);
    }
    expect(visited.length, greaterThan(8), reason: 'it patrols');
  });

  test('patrol_room returns to its room after a chase', () {
    final brain = ZombieBrain(
      config: const ZombieConfig(
        behavior: ZombieBehavior.patrolRoom,
        chaseRange: 3,
        room: room,
      ),
      walkability: grid,
      random: math.Random(2),
    );
    var self = (15, 15);
    for (var i = 0; i < 40; i++) {
      self = brain.nextStep(self, farPlayer) ?? self;
    }
    expect(room.contains(self.$1, self.$2), isTrue);
  });

  test('guard_exit stays within 3 tiles of the exit, chases in range', () {
    final brain = ZombieBrain(
      config: const ZombieConfig(behavior: ZombieBehavior.guardExit),
      walkability: grid,
      exit: (15, 3),
    );
    var self = (2, 3);
    for (var i = 0; i < 40; i++) {
      self = brain.nextStep(self, farPlayer) ?? self;
    }
    final dc = (self.$1 - 15).toDouble(), dr = (self.$2 - 3).toDouble();
    expect(math.sqrt(dc * dc + dr * dr), lessThanOrEqualTo(3));
    // The player comes within 5 tiles: the zombie leaves its post.
    final player = (self.$1 - 4, self.$2);
    expect(_steps(brain.nextStep(self, player)!, player), 3);
  });

  test('idle_until_near waits until the player is in range', () {
    final brain = ZombieBrain(
      config: const ZombieConfig(),
      walkability: grid,
    );
    expect(brain.nextStep((10, 10), (10, 16)), isNull);
    expect(_steps(brain.nextStep((10, 10), (10, 14))!, (10, 14)), 3);
  });
}

/// Grid steps (8 directions) between two cells.
int _steps((int, int) a, (int, int) b) =>
    math.max((a.$1 - b.$1).abs(), (a.$2 - b.$2).abs());
