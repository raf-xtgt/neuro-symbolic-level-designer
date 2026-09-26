import 'package:flame/components.dart';
import 'package:flame/events.dart';
import 'package:flame/game.dart';
import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter/material.dart'
    show Colors, TextStyle, FontWeight, Shadow;
import 'package:flutter/painting.dart';
import 'package:flutter/services.dart'
    show KeyDownEvent, KeyEvent, LogicalKeyboardKey;
import 'package:flutter/widgets.dart' show KeyEventResult;

import 'characters/player_component.dart';
import 'characters/zombie_component.dart';
import 'iso/iso_math.dart';
import 'level/level_loader.dart';
import 'level/level_source.dart';
import 'triggers/exit_trigger.dart';

/// Game states.
enum _GameState { playing, dead, complete }

/// The main Flame game for Z Legend.
///
/// [HasKeyboardHandlerComponents] propagates keyboard events to components
/// (e.g. [PlayerComponent] with [KeyboardHandler]) while also allowing the
/// game itself to intercept F1 and R via [onKeyEvent].
class ZLegendGame extends FlameGame
    with HasCollisionDetection, HasKeyboardHandlerComponents {
  ZLegendGame({LevelSource? source})
    : _source = source ?? LevelSource.bundled('assets/tiles/starter/');

  final LevelSource _source;

  /// Exposed for tests only.
  // ignore: invalid_use_of_visible_for_testing_member
  PlayerComponent? get playerForTest => _player;

  PlayerComponent? _player;
  final List<ZombieComponent> _zombies = [];
  ExitTrigger? _exitTrigger;
  IsoMath? _isoMath;

  _GameState _state = _GameState.playing;
  bool _debugOverlay = false;
  final List<_DebugMarker> _debugMarkers = [];

  late World _world;
  late CameraComponent _camera;
  TextComponent? _overlayText;

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    // World and camera are created once; _loadLevel() reuses them.
    _world = World();
    _camera = CameraComponent(world: _world);
    _camera.viewfinder.anchor = Anchor.center;
    await addAll([_world, _camera]);
    await _loadLevel();
  }

  /// Loads (or reloads) the level: clears the world, loads the map, spawns
  /// the player and then the zombies.
  Future<void> _loadLevel() async {
    _world.removeAll(_world.children.toList());
    _player = null;
    _zombies.clear();
    _exitTrigger = null;
    _debugMarkers.clear();

    final loader = LevelLoader(_source);
    final tiledMap = await loader.load();

    // Build IsoMath from the actual map dimensions.
    final tileMap = tiledMap.tileMap;
    _isoMath = IsoMath(
      tileWidth: tileMap.map.tileWidth.toDouble(),
      tileHeight: tileMap.map.tileHeight.toDouble(),
      mapCols: tileMap.map.width,
      mapRows: tileMap.map.height,
    );

    await _world.add(tiledMap);
    _spawnEntities(tiledMap);

    // After player is available, spawn zombies (they need a player reference).
    final player = _player;
    if (player != null) {
      for (final (col, row) in _pendingZombieSpawns) {
        final z = ZombieComponent(
          startCol: col,
          startRow: row,
          isoMath: _isoMath!,
          player: player,
        );
        _zombies.add(z);
        _world.add(z);
      }
      _pendingZombieSpawns.clear();
      _camera.follow(player);

      // Wire up attack callback: kill zombies within 1 tile when attack starts.
      player.onAttackStart = _killZombiesInAttackRange;
    }
  }

  final List<(int, int)> _pendingZombieSpawns = [];

  void _spawnEntities(TiledComponent tiledMap) {
    final objectGroup = tiledMap.tileMap.getLayer<ObjectGroup>('Entities');
    if (objectGroup == null) return;

    for (final obj in objectGroup.objects) {
      final (col, row) = _isoMath!.objectToGrid(obj.x, obj.y);
      switch (obj.type) {
        case 'PlayerSpawn':
          final p = PlayerComponent(
            startCol: col,
            startRow: row,
            isoMath: _isoMath!,
          );
          _player = p;
          _world.add(p);
          _debugMarkers.add(_DebugMarker(col: col, row: row, label: 'P'));
        case 'Zombie':
          _debugMarkers.add(_DebugMarker(col: col, row: row, label: 'Z'));
          _pendingZombieSpawns.add((col, row));
        case 'ExitTrigger':
          final exit = ExitTrigger(col: col, row: row, isoMath: _isoMath!);
          _exitTrigger = exit;
          _world.add(exit);
          _debugMarkers.add(_DebugMarker(col: col, row: row, label: 'X'));
      }
    }
  }

  void _killZombiesInAttackRange() {
    final player = _player;
    if (player == null) return;
    for (final z in _zombies) {
      if (z.isDead) continue;
      final dcol = (z.col - player.col).abs();
      final drow = (z.row - player.row).abs();
      if (dcol <= 1 && drow <= 1) {
        z.killByPlayer();
      }
    }
  }

  @override
  KeyEventResult onKeyEvent(
    KeyEvent event,
    Set<LogicalKeyboardKey> keysPressed,
  ) {
    // F1 toggles debug overlay – handled here, not forwarded.
    if (event is KeyDownEvent && event.logicalKey == LogicalKeyboardKey.f1) {
      _debugOverlay = !_debugOverlay;
      return KeyEventResult.handled;
    }

    // R restarts the game when not playing.
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.keyR &&
        _state != _GameState.playing) {
      _restart();
      return KeyEventResult.handled;
    }

    // Forward all other events to components (player's KeyboardHandler).
    return super.onKeyEvent(event, keysPressed);
  }

  void _restart() {
    _state = _GameState.playing;
    _hideOverlay();
    _loadLevel();
  }

  @override
  void update(double dt) {
    super.update(dt);
    if (_state != _GameState.playing) return;

    _checkZombieHitsPlayer();
    _checkPlayerAtExit();
  }

  void _checkZombieHitsPlayer() {
    final player = _player;
    if (player == null || player.isDead) return;
    for (final z in _zombies) {
      if (z.isDead) continue;
      if (z.col == player.col && z.row == player.row) {
        _playerDied();
        return;
      }
    }
  }

  void _checkPlayerAtExit() {
    final player = _player;
    final exit = _exitTrigger;
    if (player == null || exit == null || player.isDead) return;
    if (player.col == exit.col && player.row == exit.row) {
      _levelComplete();
    }
  }

  void _playerDied() {
    _state = _GameState.dead;
    _player?.die(); // player stays on last frame (removeOnComplete: false)
    _showOverlay('You died — press R to restart');
  }

  void _levelComplete() {
    _state = _GameState.complete;
    _showOverlay('Level complete — press R to restart');
  }

  void _showOverlay(String message) {
    _overlayText?.removeFromParent();
    final text = TextComponent(
      text: message,
      textRenderer: TextPaint(
        style: const TextStyle(
          color: Colors.white,
          fontSize: 28,
          fontWeight: FontWeight.bold,
          shadows: [Shadow(color: Colors.black, blurRadius: 4)],
        ),
      ),
      anchor: Anchor.center,
    );
    _overlayText = text;
    _camera.viewport.add(text);
    text.position = _camera.viewport.size / 2;
  }

  void _hideOverlay() {
    _overlayText?.removeFromParent();
    _overlayText = null;
  }

  @override
  void render(Canvas canvas) {
    super.render(canvas);
    if (_debugOverlay) _renderDebug(canvas);
  }

  void _renderDebug(Canvas canvas) {
    final player = _player;
    final iso = _isoMath;
    if (iso == null) return;
    final paint = Paint()
      ..color = const Color(0xFFFF0000)
      ..style = PaintingStyle.fill;

    for (final marker in _debugMarkers) {
      final world = iso.gridToWorldCenter(marker.col, marker.row);
      final screen = _camera.localToGlobal(world);
      canvas.drawCircle(Offset(screen.x, screen.y), 5, paint);
    }

    if (player != null) {
      final textPainter = TextPainter(
        text: TextSpan(
          text: 'Grid: (${player.col}, ${player.row})',
          style: const TextStyle(
            color: Color(0xFFFFFF00),
            fontSize: 14,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      textPainter.paint(canvas, const Offset(8, 8));
    }
  }
}

class _DebugMarker {
  const _DebugMarker({
    required this.col,
    required this.row,
    required this.label,
  });
  final int col;
  final int row;
  final String label;
}
