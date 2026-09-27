import 'package:flame_test/flame_test.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart' show KeyEventResult;
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/z_legend_game.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final tester = FlameTester<ZLegendGame>(ZLegendGame.new);

  tester.testGameWidget(
    'pressing D moves the player east (col+1, row-1)',
    setUp: (game, widgetTester) async {
      // flame_test already runs setUp inside runAsync, so real asset IO can
      // complete here. Wait for the level and the player to finish loading.
      final deadline = DateTime.now().add(const Duration(seconds: 10));
      while (!(game.playerForTest?.isMounted ?? false) &&
          DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        await game.ready();
      }
    },
    verify: (game, widgetTester) async {
      // The game may still be loading assets asynchronously; wait a frame.
      await widgetTester.pump();

      final player = game.playerForTest;
      expect(
        player,
        isNotNull,
        reason: 'player should spawn once the level loads',
      );
      if (player == null) return;

      // The starter spawn is the (0, 0) corner, where D (row-1) is out of
      // bounds. Move to the map centre so the step is valid.
      player.setGridPosition(10, 10);

      final colBefore = player.col;
      final rowBefore = player.row;

      // Simulate D key down.
      await widgetTester.sendKeyDownEvent(LogicalKeyboardKey.keyD);
      await widgetTester.pump(const Duration(milliseconds: 300));
      await widgetTester.sendKeyUpEvent(LogicalKeyboardKey.keyD);
      await widgetTester.pump();

      // D = screen right → iso east → col+1, row-1
      expect(player.col, greaterThan(colBefore), reason: 'col should increase');
      expect(player.row, lessThan(rowBefore), reason: 'row should decrease');
    },
  );

  test('Esc is not consumed, so the game screen can leave the game', () {
    final game = ZLegendGame();
    const event = KeyDownEvent(
      physicalKey: PhysicalKeyboardKey.escape,
      logicalKey: LogicalKeyboardKey.escape,
      timeStamp: Duration.zero,
    );
    expect(
      game.onKeyEvent(event, {LogicalKeyboardKey.escape}),
      KeyEventResult.ignored,
    );
  });
}
