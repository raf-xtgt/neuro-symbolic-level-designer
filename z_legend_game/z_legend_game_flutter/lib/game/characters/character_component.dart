import 'dart:math' as math;

import 'package:flame/components.dart';
import 'package:flame/extensions.dart' show Rect;
import 'package:flame/sprite.dart';

import '../iso/iso_math.dart';
import '../level/walkability.dart';
import 'sprite_sheet_meta.dart';

/// Direction indices matching ASSET_SPEC §4 row order.
enum IsoDirection {
  s,
  sw,
  w,
  nw,
  n,
  ne,
  e,
  se;

  int get rowIndex => index;

  /// Returns the direction closest to (dx, dy) screen delta.
  /// Uses [dart:math.atan2] for accurate angle computation.
  static IsoDirection fromDelta(double dx, double dy) {
    if (dx == 0 && dy == 0) return IsoDirection.s;
    // atan2 returns angle in radians: E=0, S=π/2, W=±π, N=-π/2
    final angleDeg = math.atan2(dy, dx) * 180.0 / math.pi;
    // Shift so 0=N, increasing clockwise: add 90 then mod 360
    double a = (angleDeg + 90) % 360;
    if (a < 0) a += 360;
    // 8 sectors of 45°, first sector centred on N (offset by 22.5°)
    final sector = ((a + 22.5) / 45).floor() % 8;
    const order = [
      IsoDirection.n,
      IsoDirection.ne,
      IsoDirection.e,
      IsoDirection.se,
      IsoDirection.s,
      IsoDirection.sw,
      IsoDirection.w,
      IsoDirection.nw,
    ];
    return order[sector];
  }
}

/// Animation names.
enum CharAnim { idle, walk, attack, die }

/// Base character component. Handles sprite-sheet loading, animation switching,
/// grid-based positioning, and depth sorting.
abstract class CharacterComponent extends PositionComponent
    with HasGameReference {
  CharacterComponent({
    required this.imageBaseName,
    required this.jsonBaseName,
    required this.isoMath,
    required this.walkability,
    required int startCol,
    required int startRow,
  }) : _col = startCol,
       _row = startRow;

  final String imageBaseName;
  final String jsonBaseName;

  /// Reference to the map's coordinate math. Provided by the level loader.
  final IsoMath isoMath;

  /// Which cells the character may enter (the shared movement rule).
  final WalkabilityGrid walkability;

  int _col;
  int _row;

  int get col => _col;
  int get row => _row;

  IsoDirection _facing = IsoDirection.s;
  CharAnim _currentAnim = CharAnim.idle;

  SpriteAnimationComponent? _sprite;

  /// Per-animation sidecar metadata (frames, fps, anchor).
  final Map<CharAnim, SpriteSheetMeta> _animMetas = {};

  /// Anchor from the first loaded meta (same for all animations of a character).
  SpriteSheetMeta? _anchorMeta;

  bool _dead = false;
  bool get isDead => _dead;

  /// The current animation.
  CharAnim get currentAnimation => _currentAnim;

  /// The direction the character faces.
  IsoDirection get facing => _facing;

  /// The sprite frame rectangle in world coordinates, once loaded.
  Rect? get spriteRect => _sprite?.toAbsoluteRect();

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    await _loadAnimations();
    _syncPosition();
    _playAnim(CharAnim.idle);
  }

  Future<void> _loadAnimations() async {
    final anims = animationNames();
    for (final entry in anims.entries) {
      final anim = entry.key;
      final baseName = entry.value;
      final imagePath = '$imageBaseName/$baseName.png';
      final jsonPath = '$jsonBaseName/$baseName.json';

      final meta = await SpriteSheetMeta.load(jsonPath);
      _animMetas[anim] = meta;
      _anchorMeta ??= meta; // anchor is shared; first loaded wins

      // Pre-load the image into Flame's cache.
      await game.images.load(imagePath);
    }
  }

  /// Subclasses return a map from [CharAnim] to the base filename.
  Map<CharAnim, String> animationNames();

  void _syncPosition() {
    final meta = _anchorMeta;
    if (meta == null) return;
    final worldCenter = isoMath.gridToWorldCenter(_col, _row);
    position = worldCenter;
    final sprite = _sprite;
    if (sprite != null) {
      sprite.anchor = Anchor(
        meta.anchor.x / meta.frameWidth,
        meta.anchor.y / meta.frameHeight,
      );
      sprite.size = Vector2(
        meta.frameWidth.toDouble(),
        meta.frameHeight.toDouble(),
      );
    }
    priority = IsoMath.depthPriority(_col, _row, DepthLayer.character);
  }

  void _playAnim(CharAnim anim) {
    final animation = _buildAnimationForDirection(anim, _facing);
    final meta = _anchorMeta!;
    if (_sprite == null) {
      final spriteComp = SpriteAnimationComponent(
        animation: animation,
        size: Vector2(meta.frameWidth.toDouble(), meta.frameHeight.toDouble()),
        anchor: Anchor(
          meta.anchor.x / meta.frameWidth,
          meta.anchor.y / meta.frameHeight,
        ),
      );
      _sprite = spriteComp;
      add(spriteComp);
    } else {
      final animMeta = _animMetas[anim] ?? meta;
      _sprite!.size = Vector2(
        animMeta.frameWidth.toDouble(),
        animMeta.frameHeight.toDouble(),
      );
      _sprite!.anchor = Anchor(
        meta.anchor.x / animMeta.frameWidth,
        meta.anchor.y / animMeta.frameHeight,
      );
      _sprite!.animation = animation;
    }
    _currentAnim = anim;
  }

  SpriteAnimation _buildAnimationForDirection(CharAnim anim, IsoDirection dir) {
    final baseName = animationNames()[anim]!;
    final imagePath = '$imageBaseName/$baseName.png';
    final meta = _animMetas[anim] ?? _anchorMeta!;
    final image = game.images.fromCache(imagePath);
    final sheet = SpriteSheet(
      image: image,
      srcSize: Vector2(meta.frameWidth.toDouble(), meta.frameHeight.toDouble()),
    );
    return sheet.createAnimation(
      row: dir.rowIndex,
      stepTime: 1.0 / meta.fps,
      from: 0,
      to: meta.frames,
      loop: anim != CharAnim.die && anim != CharAnim.attack,
    );
  }

  /// Changes the character's facing direction and updates animation frames.
  void setFacing(IsoDirection dir) {
    if (_facing == dir) return;
    _facing = dir;
    if (!_dead) _playAnim(_currentAnim);
  }

  /// Plays an animation. Ignored while dead (except [CharAnim.die]) and
  /// while [anim] is already playing: restarting it every frame would keep
  /// it on its first frame.
  void playAnimation(CharAnim anim) {
    if (_dead && anim != CharAnim.die) return;
    if (anim == _currentAnim && _sprite != null) return;
    _playAnim(anim);
  }

  /// Moves the character to a new grid position.
  void setGridPosition(int col, int row) {
    _col = col;
    _row = row;
    _syncPosition();
  }

  /// Starts the death sequence: plays die animation and sets dead flag.
  /// Zombies remove themselves when done; the player stays on the last frame.
  void die({bool removeOnComplete = false}) {
    if (_dead) return;
    _dead = true;
    _playAnim(CharAnim.die);
    if (removeOnComplete) {
      _sprite?.animationTicker?.onComplete = removeFromParent;
    }
  }

  @override
  void update(double dt) {
    super.update(dt);
    priority = IsoMath.depthPriority(_col, _row, DepthLayer.character);
  }
}
