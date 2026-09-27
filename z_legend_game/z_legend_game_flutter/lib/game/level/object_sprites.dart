import 'package:flame/cache.dart';
import 'package:flame/components.dart';
import 'package:flame/extensions.dart' show Rect;
import 'package:flame_tiled/flame_tiled.dart';

import '../iso/iso_math.dart';
import 'walkability.dart';

/// The sprite pixel (from its top-left) that sits on the tile center.
///
/// flame_tiled 3.1.2 draws a sprite of size [spriteWidth] x [spriteHeight]
/// with its pixel `(w - W/2, h - H/2)` on the tile center plus the tileset
/// `tileoffset` (W x H = map tile size, ARCHITECTURE.md 5.2). So the pixel on
/// the tile center is `(w - W/2 - tileoffset.x, h - H/2 - tileoffset.y)`.
Vector2 tileAnchorPixel({
  required double spriteWidth,
  required double spriteHeight,
  required double mapTileWidth,
  required double mapTileHeight,
  double offsetX = 0,
  double offsetY = 0,
}) {
  return Vector2(
    spriteWidth - mapTileWidth / 2 - offsetX,
    spriteHeight - mapTileHeight / 2 - offsetY,
  );
}

/// One tile of the `Objects` layer (obstacle or decoration) as its own
/// component, so it depth-sorts with the characters.
class ObjectSprite extends SpriteComponent {
  ObjectSprite({
    required this.col,
    required this.row,
    required this.walkable,
    required this.tags,
    required Sprite sprite,
    required Vector2 anchorPixel,
    required IsoMath isoMath,
  }) : super(
         sprite: sprite,
         size: sprite.srcSize.clone(),
         anchor: Anchor(
           anchorPixel.x / sprite.srcSize.x,
           anchorPixel.y / sprite.srcSize.y,
         ),
         position: isoMath.gridToWorldCenter(col, row),
         priority: IsoMath.depthPriority(
           col,
           row,
           walkable ? DepthLayer.decoration : DepthLayer.obstacle,
         ),
       );

  final int col;
  final int row;
  final bool walkable;
  final Set<String> tags;

  /// Tall obstacles (trees, tall town objects) can hide a character behind
  /// them, so the occlusion guard fades them.
  bool get isTall =>
      !walkable && (tags.contains('tall') || tags.contains('tree'));
}

/// Replaces the flat `Objects` tile layer of [tiled] with one [ObjectSprite]
/// per non-empty cell: hides the layer (the `Ground` layer stays) and returns
/// the sprites, to add to the world next to the characters.
///
/// [images] must be the cache the level loader used, so the tileset images
/// are not fetched twice. A map without an `Objects` layer returns no sprites.
Future<List<ObjectSprite>> extractObjectSprites(
  TiledComponent tiled,
  IsoMath isoMath,
  Images images,
) async {
  final map = tiled.tileMap.map;
  final layer = objectsLayer(map);
  final tileData = layer?.tileData;
  if (layer == null || tileData == null) return const [];

  tiled.tileMap.setLayerVisibility(map.layers.indexOf(layer), visible: false);

  final sprites = <ObjectSprite>[];
  for (var row = 0; row < tileData.length; row++) {
    for (var col = 0; col < tileData[row].length; col++) {
      final gid = tileData[row][col].tile;
      if (gid == 0) continue;
      final tile = map.tileByGid(gid);
      final tileset = map.tilesetByTileGId(gid);
      final source = (tile?.image ?? tileset.image)?.source;
      if (tile == null || source == null) continue;

      final rect = tileset.computeDrawRect(tile);
      final sprite = Sprite(
        await images.load(source),
        srcPosition: Vector2(rect.left.toDouble(), rect.top.toDouble()),
        srcSize: Vector2(rect.width.toDouble(), rect.height.toDouble()),
      );
      final tags = tile.properties.getValue<String>('tags') ?? '';
      sprites.add(
        ObjectSprite(
          col: col,
          row: row,
          walkable: tileWalkable(tile),
          tags: {
            for (final t in tags.split(','))
              if (t.trim().isNotEmpty) t.trim(),
          },
          sprite: sprite,
          anchorPixel: tileAnchorPixel(
            spriteWidth: rect.width.toDouble(),
            spriteHeight: rect.height.toDouble(),
            mapTileWidth: map.tileWidth.toDouble(),
            mapTileHeight: map.tileHeight.toDouble(),
            offsetX: tileset.tileOffset?.x.toDouble() ?? 0,
            offsetY: tileset.tileOffset?.y.toDouble() ?? 0,
          ),
          isoMath: isoMath,
        ),
      );
    }
  }
  return sprites;
}

/// Occlusion guard (ARCHITECTURE.md 4.1.2): a tall obstacle drawn in front of
/// the player whose sprite overlaps the player's sprite on screen is drawn at
/// [fadedOpacity], so the player stays visible behind it.
class OcclusionGuard {
  OcclusionGuard(Iterable<ObjectSprite> sprites)
    : _tall = [
        for (final s in sprites)
          if (s.isTall) s,
      ];

  static const double fadedOpacity = 0.4;

  final List<ObjectSprite> _tall;

  /// [playerRect] is the player's sprite rectangle in world coordinates (the
  /// camera maps world to screen the same way for every component, so an
  /// overlap in the world is an overlap on screen).
  void update(Rect playerRect, int playerPriority) {
    for (final s in _tall) {
      final hides =
          s.priority > playerPriority &&
          s.toAbsoluteRect().overlaps(playerRect);
      final opacity = hides ? fadedOpacity : 1.0;
      // Paint stores alpha in 8 bits, so compare with a tolerance.
      if ((s.opacity - opacity).abs() > 0.01) s.opacity = opacity;
    }
  }
}
