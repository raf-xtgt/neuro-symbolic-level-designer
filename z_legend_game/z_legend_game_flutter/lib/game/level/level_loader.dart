import 'dart:convert';

import 'package:flame/cache.dart';
import 'package:flame/components.dart';
import 'package:flame_tiled/flame_tiled.dart';

import 'level_source.dart';

/// Loads a Tiled level bundle from a [LevelSource] and returns a
/// [TiledComponent] ready to be added to the game world.
class LevelLoader {
  LevelLoader(this.source)
    : images = Images(prefix: source.prefix, bundle: source.bundle);

  final LevelSource source;

  /// The cache the tileset images are loaded into. Sprites cut from the same
  /// images (the `Objects` layer, see `object_sprites.dart`) reuse it.
  final Images images;

  /// Map filename inside the bundle.
  static const String _mapFile = 'level.tmj';

  /// Loads [_mapFile] from [source] and returns the [TiledComponent].
  ///
  /// `TiledComponent.load` only parses TMX (XML) in flame_tiled 3.1.2, so the
  /// JSON map is parsed with [TileMapParser.parseJson] instead. The tileset
  /// must be embedded in the map because the JSON parser does not resolve
  /// external tilesets.
  Future<TiledComponent> load() async {
    final contents = await source.bundle.loadString(
      '${source.prefix}$_mapFile',
    );
    final map = TileMapParser.parseJson(_normalizeForTiled(contents));
    final renderable = await RenderableTiledMap.fromTiledMap(
      map,
      Vector2(map.tileWidth.toDouble(), map.tileHeight.toDouble()),
      images: images,
      bundle: source.bundle,
    );
    return TiledComponent(renderable);
  }

  /// Reshapes a TMJ map into what tiled 0.11.1's JSON parser (pinned by
  /// flame_tiled 3.1.2) actually reads. That parser reuses several TMX
  /// element names as JSON keys, so a standard TMJ loses data silently:
  /// - tilesets are read from `tileset`, but TMJ uses `tilesets`, so the
  ///   map has no tilesets and nothing renders.
  /// - object-group children are read from `object`, but TMJ uses `objects`,
  ///   so every object layer parses as empty.
  /// - an image is read as a list of `{source, width, height}` objects under
  ///   `image`, but TMJ stores a plain string plus `imagewidth`/`imageheight`.
  /// - a tileset's `tileoffset` and `grid` are read as lists of child
  ///   objects, but TMJ stores single objects; a tileset with a `tileoffset`
  ///   (tall sprites) fails to parse. Wrap them in a list.
  /// - `ellipse` and `point` are required on every object, but Tiled only
  ///   writes them when true. Default them to false.
  /// - a tile's collision shapes (`objectgroup`, written for uploaded sheets)
  ///   are read as a list of child objects too, with the same object rules.
  static String _normalizeForTiled(String contents) {
    final json = jsonDecode(contents) as Map<String, dynamic>;

    void wrapImage(Map<String, dynamic> m) {
      final image = m['image'];
      if (image is String) {
        m['image'] = [
          {
            'source': image,
            'width': m['imagewidth'],
            'height': m['imageheight'],
          },
        ];
      }
    }

    void normalizeObjects(Map<String, dynamic> group) {
      final objects = group['objects'] as List<dynamic>?;
      if (objects == null) return;
      for (final obj in objects.cast<Map<String, dynamic>>()) {
        obj.putIfAbsent('ellipse', () => false);
        obj.putIfAbsent('point', () => false);
      }
      group['object'] = objects;
    }

    final tilesets = (json['tilesets'] as List<dynamic>? ?? const [])
        .cast<Map<String, dynamic>>();
    for (final tileset in tilesets) {
      wrapImage(tileset);
      for (final key in const ['tileoffset', 'grid']) {
        if (tileset[key] is Map) tileset[key] = [tileset[key]];
      }
      final tiles = tileset['tiles'] as List<dynamic>? ?? const [];
      for (final tile in tiles.cast<Map<String, dynamic>>()) {
        wrapImage(tile);
        final group = tile['objectgroup'];
        if (group is Map<String, dynamic>) {
          normalizeObjects(group);
          tile['objectgroup'] = [group];
        }
      }
    }
    json['tileset'] = tilesets;

    void visit(List<dynamic>? layers) {
      for (final layer in layers ?? const <dynamic>[]) {
        final l = layer as Map<String, dynamic>;
        if (l['type'] == 'objectgroup') normalizeObjects(l);
        if (l['type'] == 'imagelayer') wrapImage(l);
        visit(l['layers'] as List<dynamic>?);
      }
    }

    visit(json['layers'] as List<dynamic>?);
    return jsonEncode(json);
  }
}
