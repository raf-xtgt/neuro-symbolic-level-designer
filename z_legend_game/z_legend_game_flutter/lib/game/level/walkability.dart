import 'dart:collection';

import 'package:flame_tiled/flame_tiled.dart';

/// Name of the tile layer that holds obstacles and decorations.
const String objectsLayerName = 'Objects';

/// The map's `Objects` tile layer, or null if the map has none.
TileLayer? objectsLayer(TiledMap map) {
  for (final layer in map.layers) {
    if (layer is TileLayer && layer.name == objectsLayerName) return layer;
  }
  return null;
}

/// The tile's `walkable` property (written by the tileset compiler). Tiles
/// without it are walkable.
bool tileWalkable(Tile tile) =>
    tile.properties.getValue<bool>('walkable') ?? true;

/// The 8 grid steps (dcol, drow), in a fixed order so paths are deterministic.
const List<(int, int)> gridSteps = [
  (-1, -1),
  (0, -1),
  (1, -1),
  (-1, 0),
  (1, 0),
  (-1, 1),
  (0, 1),
  (1, 1),
];

/// Which grid cells a character may stand on, and the movement rule.
///
/// The same rule as the planner's path check
/// (`backend/pipeline/planning/pathing.py`):
/// * A cell is blocked if its `Objects` tile has `walkable = false`. Empty
///   cells and walkable tiles (decorations) are open. Cells outside the map
///   are blocked.
/// * 8-direction movement. A diagonal step is allowed only if both
///   orthogonal neighbors are open (no corner cutting between obstacles).
class WalkabilityGrid {
  WalkabilityGrid({
    required this.cols,
    required this.rows,
    Iterable<(int, int)> blocked = const [],
  }) : _blocked = Set.unmodifiable(blocked);

  /// Reads the blocked cells from the map's `Objects` layer. A map without
  /// an `Objects` layer is fully open.
  factory WalkabilityGrid.fromMap(TiledMap map) {
    final blocked = <(int, int)>[];
    final tileData = objectsLayer(map)?.tileData;
    if (tileData != null) {
      for (var row = 0; row < tileData.length; row++) {
        for (var col = 0; col < tileData[row].length; col++) {
          final gid = tileData[row][col].tile;
          if (gid == 0) continue;
          final tile = map.tileByGid(gid);
          if (tile != null && !tileWalkable(tile)) blocked.add((col, row));
        }
      }
    }
    return WalkabilityGrid(cols: map.width, rows: map.height, blocked: blocked);
  }

  final int cols;
  final int rows;
  final Set<(int, int)> _blocked;

  /// The blocked cells inside the map, as (col, row).
  Set<(int, int)> get blockedCells => _blocked;

  /// True if (col, row) is inside the map and not blocked.
  bool isOpen(int col, int row) =>
      col >= 0 &&
      col < cols &&
      row >= 0 &&
      row < rows &&
      !_blocked.contains((col, row));

  /// True if a character on (col, row) may step by (dcol, drow).
  bool canStep(int col, int row, int dcol, int drow) {
    if (!isOpen(col + dcol, row + drow)) return false;
    if (dcol != 0 && drow != 0) {
      return isOpen(col + dcol, row) && isOpen(col, row + drow);
    }
    return true;
  }

  /// Shortest path (BFS under [canStep]) from [start] to [goal], both
  /// included, as (col, row) cells. Null if there is none.
  List<(int, int)>? findPath((int, int) start, (int, int) goal) {
    if (!isOpen(start.$1, start.$2) || !isOpen(goal.$1, goal.$2)) return null;
    final previous = <(int, int), (int, int)?>{start: null};
    final queue = Queue<(int, int)>()..add(start);
    while (queue.isNotEmpty) {
      final cell = queue.removeFirst();
      if (cell == goal) {
        final path = <(int, int)>[cell];
        while (previous[path.last] != null) {
          path.add(previous[path.last]!);
        }
        return path.reversed.toList();
      }
      final (col, row) = cell;
      for (final (dcol, drow) in gridSteps) {
        final next = (col + dcol, row + drow);
        if (!previous.containsKey(next) && canStep(col, row, dcol, drow)) {
          previous[next] = cell;
          queue.add(next);
        }
      }
    }
    return null;
  }
}
