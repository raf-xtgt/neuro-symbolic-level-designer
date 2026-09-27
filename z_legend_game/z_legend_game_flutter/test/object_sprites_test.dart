import 'dart:ui' show RSTransform;

import 'package:flame/components.dart';
import 'package:flame_tiled/flame_tiled.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/iso/iso_math.dart';
import 'package:z_legend_game_flutter/game/level/level_loader.dart';
import 'package:z_legend_game_flutter/game/level/object_sprites.dart';
import 'package:z_legend_game_flutter/game/level/walkability.dart';

import 'fixture_source.dart';

/// The grassland_full fixture: the Objects layer becomes one sprite per cell,
/// placed exactly where flame_tiled draws the same tile.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late TiledComponent tiled;
  late IsoMath iso;
  late List<ObjectSprite> sprites;

  // flame_tiled's own placement, from a second load where the Objects layer
  // is still drawn by the TiledComponent.
  late TiledComponent reference;

  setUpAll(() async {
    final loader = LevelLoader(fixtureSource('grassland_full'));
    tiled = await loader.load();
    final map = tiled.tileMap.map;
    iso = IsoMath(
      tileWidth: map.tileWidth.toDouble(),
      tileHeight: map.tileHeight.toDouble(),
      mapCols: map.width,
      mapRows: map.height,
    );
    sprites = await extractObjectSprites(tiled, iso, loader.images);
    reference = await LevelLoader(fixtureSource('grassland_full')).load();
  });

  List<(int, int, int)> nonEmptyCells(TiledComponent t, String layerName) {
    final layer = t.tileMap.getLayer<TileLayer>(layerName)!;
    return [
      for (var row = 0; row < layer.height; row++)
        for (var col = 0; col < layer.width; col++)
          if (layer.tileData![row][col].tile != 0)
            (col, row, layer.tileData![row][col].tile),
    ];
  }

  /// The transform flame_tiled 3.1.2 caches for tile (col, row) of a layer.
  /// `transforms` is on the internal tile layer class, so reach it
  /// dynamically.
  RSTransform flameTransform(String layerName, int col, int row) {
    final layer = reference.tileMap.renderableLayers.singleWhere(
      (l) => l.layer.name == layerName,
    );
    final transforms =
        (layer as dynamic).transforms as List<List<RSTransform?>>;
    return transforms[col][row]!;
  }

  /// Where flame_tiled draws the sprite pixel (px, py) of tile (col, row).
  Vector2 flamePixel(String layerName, int col, int row, Vector2 pixel) {
    final t = flameTransform(layerName, col, row);
    return Vector2(
      t.scos * pixel.x - t.ssin * pixel.y + t.tx,
      t.ssin * pixel.x + t.scos * pixel.y + t.ty,
    );
  }

  test('one sprite per non-empty Objects cell', () {
    final cells = nonEmptyCells(tiled, objectsLayerName);
    expect(cells, isNotEmpty);
    expect(sprites.length, cells.length);
    expect(
      {for (final s in sprites) (s.col, s.row)},
      {for (final (col, row, _) in cells) (col, row)},
    );
  });

  test('the Objects layer is hidden, the Ground layer is not', () {
    final layers = tiled.tileMap.map.layers;
    final objects = layers.indexWhere((l) => l.name == objectsLayerName);
    final ground = layers.indexWhere((l) => l.name == 'Ground');
    expect(tiled.tileMap.getLayerVisibility(objects), isFalse);
    expect(tiled.tileMap.getLayerVisibility(ground), isTrue);
  });

  test('priorities: obstacles 50, decorations 20 on their cell', () {
    for (final s in sprites) {
      final bias = s.walkable ? 20 : 50;
      expect(s.priority, (s.col + s.row) * 100 + bias);
    }
    expect(sprites.where((s) => s.walkable), isNotEmpty);
    expect(sprites.where((s) => s.isTall), isNotEmpty);
  });

  test('a 64 x 32 tile: anchor pixel lands on the tile center', () {
    final (col, row, gid) = nonEmptyCells(reference, 'Ground')[57];
    final tileset = reference.tileMap.map.tilesetByTileGId(gid);
    expect((tileset.tileWidth, tileset.tileHeight), (64, 32));
    final anchor = tileAnchorPixel(
      spriteWidth: 64,
      spriteHeight: 32,
      mapTileWidth: 64,
      mapTileHeight: 32,
    );
    expect(anchor, Vector2(32, 16));
    expect(
      flamePixel('Ground', col, row, anchor),
      iso.gridToWorldCenter(col, row),
    );
  });

  for (final (w, h) in [(64, 96), (128, 224)]) {
    test('a $w x $h tile: the sprite matches flame_tiled to the pixel', () {
      final bySize = sprites.where(
        (s) => s.size.x == w && s.size.y == h,
      );
      expect(bySize, isNotEmpty, reason: 'fixture needs a $w x $h object');
      for (final s in bySize) {
        // The sprite's top-left and the anchor pixel, as flame_tiled draws them.
        final topLeft = s.positionOfAnchor(Anchor.topLeft);
        expect(
          topLeft,
          flamePixel(objectsLayerName, s.col, s.row, Vector2.zero()),
        );
        final anchorPixel = Vector2(s.anchor.x * w, s.anchor.y * h);
        expect(
          flamePixel(objectsLayerName, s.col, s.row, anchorPixel),
          iso.gridToWorldCenter(s.col, s.row),
        );
      }
    });
  }

  test('tall trees: anchor from the tileoffset (32, 0)', () {
    // Catalog anchor (64, 208) for a 128 x 224 tree: 128 - 32 - 32 = 64,
    // 224 - 16 - 0 = 208.
    expect(
      tileAnchorPixel(
        spriteWidth: 128,
        spriteHeight: 224,
        mapTileWidth: 64,
        mapTileHeight: 32,
        offsetX: 32,
      ),
      Vector2(64, 208),
    );
  });
}
