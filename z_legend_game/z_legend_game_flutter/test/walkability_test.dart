import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/level_source.dart';
import 'package:z_legend_game_flutter/game/level/walkability.dart';

import 'fixture_source.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('WalkabilityGrid from the collision fixture', () {
    late WalkabilityGrid grid;

    setUpAll(() async {
      final tiled = await LevelLoader(fixtureSource('collision')).load();
      grid = WalkabilityGrid.fromMap(tiled.tileMap.map);
    });

    test('obstacle cells are blocked, all others are open', () {
      expect(grid.blockedCells, {(3, 4), (6, 6), (9, 1), (9, 2), (9, 3)});
      expect(grid.isOpen(3, 4), isFalse);
      expect(grid.isOpen(6, 6), isFalse);
      expect(grid.isOpen(2, 5), isTrue); // spawn
      expect(grid.isOpen(0, 0), isTrue);
      expect(grid.isOpen(11, 11), isTrue);
    });

    test('cells outside the map are blocked', () {
      expect(grid.isOpen(-1, 0), isFalse);
      expect(grid.isOpen(0, -1), isFalse);
      expect(grid.isOpen(12, 0), isFalse);
      expect(grid.isOpen(0, 12), isFalse);
      expect(grid.canStep(0, 0, -1, 0), isFalse);
      expect(grid.canStep(11, 11, 1, 1), isFalse);
    });

    test('orthogonal steps only need the target cell open', () {
      expect(grid.canStep(2, 5, 1, -1), isFalse); // D from the spawn: rock
      expect(grid.canStep(2, 4, 1, 0), isFalse); // into the rock
      expect(grid.canStep(2, 5, 1, 0), isTrue);
    });

    test('a diagonal step needs both orthogonal neighbors open', () {
      // Diagonals past the rock on (3, 4), with both target cells open:
      // (2, 4) -> (3, 5) passes the corners (3, 4) [rock] and (2, 5).
      expect(grid.canStep(2, 4, 1, 1), isFalse);
      // (4, 4) -> (3, 3) passes (3, 4) [rock] and (4, 3).
      expect(grid.canStep(4, 4, -1, -1), isFalse);
      // A free diagonal.
      expect(grid.canStep(0, 0, 1, 1), isTrue);
    });
  });

  group('WalkabilityGrid rules', () {
    // Two rocks touching at a corner:
    //   . X .
    //   X . .
    //   . . .
    final grid = WalkabilityGrid(cols: 3, rows: 3, blocked: [(1, 0), (0, 1)]);

    test('no corner cutting between two obstacles', () {
      expect(grid.canStep(0, 0, 1, 1), isFalse);
      expect(grid.findPath((0, 0), (2, 2)), isNull);
    });

    test('paths go around obstacles and follow canStep', () {
      final open = WalkabilityGrid(cols: 3, rows: 3, blocked: [(1, 0)]);
      final path = open.findPath((0, 0), (2, 2))!;
      expect(path.first, (0, 0));
      expect(path.last, (2, 2));
      expect(path.length - 1, 3); // 2 diagonal steps are not allowed
      for (var i = 1; i < path.length; i++) {
        final (c0, r0) = path[i - 1];
        final (c1, r1) = path[i];
        expect(open.canStep(c0, r0, c1 - c0, r1 - r0), isTrue);
      }
    });

    test('without obstacles, diagonals are free', () {
      final open = WalkabilityGrid(cols: 20, rows: 20);
      expect(open.findPath((0, 0), (19, 19))!.length - 1, 19);
    });
  });

  test('a map without an Objects layer is fully open', () async {
    final tiled = await LevelLoader(
      LevelSource.bundled('assets/tiles/starter/'),
    ).load();
    expect(objectsLayer(tiled.tileMap.map), isNull);
    final grid = WalkabilityGrid.fromMap(tiled.tileMap.map);
    expect(grid.blockedCells, isEmpty);
    for (var row = 0; row < 20; row++) {
      for (var col = 0; col < 20; col++) {
        expect(grid.isOpen(col, row), isTrue);
      }
    }
    expect(grid.canStep(5, 5, 1, 1), isTrue);
  });
}
