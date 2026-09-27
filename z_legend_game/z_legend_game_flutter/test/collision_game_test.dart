import 'package:flame_test/flame_test.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/characters/character_component.dart';
import 'package:z_legend_game_flutter/game/level/object_sprites.dart';
import 'package:z_legend_game_flutter/game/z_legend_game.dart';

import 'fixture_source.dart';

/// The game on the `collision` fixture (see fixture_source.dart): spawn on
/// (2, 5), rock on (3, 4), tall tree on (6, 6), zombie on (11, 2) behind a
/// rock wall on (9, 1) to (9, 3). Cells are (col, row).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final tester = FlameTester<ZLegendGame>(
    () => ZLegendGame(source: fixtureSource('collision')),
  );

  Future<void> waitForLevel(ZLegendGame game) async {
    // flame_test runs setUp inside runAsync, so real asset IO can complete.
    final deadline = DateTime.now().add(const Duration(seconds: 10));
    while (!(game.playerForTest?.isMounted ?? false) ||
        game.zombiesForTest.any((z) => !z.isMounted)) {
      if (DateTime.now().isAfter(deadline)) fail('level did not load');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await game.ready();
    }
  }

  tester.testGameWidget(
    'pressing D towards a rock does not move the player',
    setUp: (game, _) => waitForLevel(game),
    verify: (game, widgetTester) async {
      await widgetTester.pump();
      final player = game.playerForTest!;
      expect((player.col, player.row), (2, 5));
      expect(game.walkabilityForTest!.isOpen(3, 4), isFalse);

      await widgetTester.sendKeyDownEvent(LogicalKeyboardKey.keyD);
      await widgetTester.pump(const Duration(milliseconds: 300));
      await widgetTester.pump(const Duration(milliseconds: 300));
      expect((player.col, player.row), (2, 5), reason: 'blocked by the rock');
      expect(player.facing, IsoDirection.e, reason: 'still turns to face it');
      expect(player.currentAnimation, CharAnim.idle);
      await widgetTester.sendKeyUpEvent(LogicalKeyboardKey.keyD);
      await widgetTester.pump();

      // S (col+1, row+1) is open: the player still moves.
      await widgetTester.sendKeyDownEvent(LogicalKeyboardKey.keyS);
      await widgetTester.pump(const Duration(milliseconds: 300));
      await widgetTester.sendKeyUpEvent(LogicalKeyboardKey.keyS);
      await widgetTester.pump();
      expect((player.col, player.row), (3, 6));
    },
  );

  tester.testGameWidget(
    'a zombie walks around a wall to reach the player',
    setUp: (game, _) => waitForLevel(game),
    verify: (game, widgetTester) async {
      final player = game.playerForTest!;
      final zombie = game.zombiesForTest.single;
      final grid = game.walkabilityForTest!;
      expect((zombie.col, zombie.row), (11, 2));

      // Straight west of the zombie, 4 cells away, with the wall between.
      player.setGridPosition(7, 2);
      final visited = <(int, int)>[(zombie.col, zombie.row)];
      for (var i = 0; i < 30 && !player.isDead; i++) {
        game.update(0.36); // just over one zombie step
        if (visited.last != (zombie.col, zombie.row)) {
          visited.add((zombie.col, zombie.row));
        }
      }

      expect(player.isDead, isTrue, reason: 'zombie reached the player');
      expect(visited.last, (7, 2));
      for (final (col, row) in visited) {
        expect(grid.isOpen(col, row), isTrue, reason: 'entered ($col, $row)');
      }
      for (var i = 1; i < visited.length; i++) {
        final (c0, r0) = visited[i - 1];
        final (c1, r1) = visited[i];
        expect(
          grid.canStep(c0, r0, c1 - c0, r1 - r0),
          isTrue,
          reason: 'step $i cut a corner or jumped',
        );
      }
      // It went around the wall, which spans rows 1 to 3.
      expect(visited.any((c) => c.$1 == 9), isTrue);
      expect(
        visited.where((c) => c.$1 == 9).single.$2,
        isNot(inInclusiveRange(1, 3)),
      );
    },
  );

  tester.testGameWidget(
    'a tall tree fades while the player stands behind it',
    setUp: (game, _) => waitForLevel(game),
    verify: (game, widgetTester) async {
      final player = game.playerForTest!;
      final tree = game.objectSpritesForTest.singleWhere(
        (s) => (s.col, s.row) == (6, 6),
      );
      expect(tree.isTall, isTrue);

      double opacityAt(int col, int row) {
        player.setGridPosition(col, row);
        game.update(0);
        return tree.opacity;
      }

      expect(opacityAt(5, 5), closeTo(OcclusionGuard.fadedOpacity, 0.01));
      expect(player.priority, lessThan(tree.priority));
      expect(opacityAt(7, 7), 1.0, reason: 'in front of the tree');
      expect(player.priority, greaterThan(tree.priority));
      expect(opacityAt(6, 5), closeTo(OcclusionGuard.fadedOpacity, 0.01));
      // Behind the tree (lower priority) but far to its left on screen.
      expect(opacityAt(0, 11), 1.0, reason: 'behind, but no overlap');
      expect(player.priority, lessThan(tree.priority));
      expect(opacityAt(5, 5), closeTo(OcclusionGuard.fadedOpacity, 0.01));
    },
  );
}
