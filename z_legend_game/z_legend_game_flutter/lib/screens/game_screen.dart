import 'package:flame/game.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../game/level/level_source.dart';
import '../game/z_legend_game.dart';

/// Wraps the [ZLegendGame] in a [GameWidget]. Pressing Esc returns to the
/// previous screen.
class GameScreen extends StatefulWidget {
  const GameScreen({super.key, this.source});

  /// Where to load the level from. Defaults to the bundled starter level.
  final LevelSource? source;

  @override
  State<GameScreen> createState() => _GameScreenState();
}

class _GameScreenState extends State<GameScreen> {
  late final ZLegendGame _game;

  @override
  void initState() {
    super.initState();
    _game = ZLegendGame(source: widget.source);
  }

  KeyEventResult _handleKey(FocusNode node, KeyEvent event) {
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.escape) {
      Navigator.of(context).pop();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    return Focus(
      autofocus: true,
      onKeyEvent: _handleKey,
      child: GameWidget(game: _game),
    );
  }
}
