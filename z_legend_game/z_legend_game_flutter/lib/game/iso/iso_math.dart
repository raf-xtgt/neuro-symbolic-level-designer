import 'package:flame/components.dart';

/// All isometric coordinate math lives here.
///
/// [IsoMath] is an instance created from the loaded map dimensions so that
/// generated levels of any size work correctly.
///
/// Tiled isometric object coordinates:
///   x = col * tileHeight   (or (col + 0.5) * tileHeight for tile-center)
///   y = row * tileHeight
///
/// flame_tiled renders tile (col, row) with the map's horizontal offset equal
/// to `mapRows * tileWidth / 2` (it uses the *height* dimension for the X
/// centering shift):
///   worldX = (col - row) * tileWidth / 2  + mapRows * tileWidth / 2
///   worldY = (col + row) * tileHeight / 2
class IsoMath {
  const IsoMath({
    required this.tileWidth,
    required this.tileHeight,
    required this.mapCols,
    required this.mapRows,
  }) : _mapOffsetX = mapRows * tileWidth / 2;

  final double tileWidth;
  final double tileHeight;
  final int mapCols;
  final int mapRows;

  /// Horizontal world offset: flame_tiled shifts by mapRows * tileWidth / 2.
  final double _mapOffsetX;

  /// Convenience factory for the starter 20×20 / 64×32 map.
  static const IsoMath starter = IsoMath(
    tileWidth: 64,
    tileHeight: 32,
    mapCols: 20,
    mapRows: 20,
  );

  // -------------------------------------------------------------------------
  // Tiled object (x, y) → grid (col, row)
  // Both object axes are in tile-height units (see ARCHITECTURE.md §6.3).
  // -------------------------------------------------------------------------

  /// Converts a Tiled isometric object position to the grid tile it sits in.
  (int col, int row) objectToGrid(double objX, double objY) {
    final col = (objX / tileHeight).floor();
    final row = (objY / tileHeight).floor();
    return (col, row);
  }

  // -------------------------------------------------------------------------
  // Grid (col, row) → world position (Vector2)
  // Matches exactly where flame_tiled renders tile (col, row).
  // -------------------------------------------------------------------------

  /// Returns the world position of the top-corner of tile (col, row).
  Vector2 gridToWorld(int col, int row) {
    final x = (col - row) * tileWidth / 2 + _mapOffsetX;
    final y = (col + row) * tileHeight / 2;
    return Vector2(x, y);
  }

  /// Returns the world position of the centre of tile (col, row).
  Vector2 gridToWorldCenter(int col, int row) {
    return gridToWorld(col, row) + Vector2(0, tileHeight / 2);
  }

  // -------------------------------------------------------------------------
  // World position → grid (inverse)
  // -------------------------------------------------------------------------

  /// Converts a world position to the nearest grid tile.
  (int col, int row) worldToGrid(Vector2 world) {
    final dx = world.x - _mapOffsetX;
    final dy = world.y;
    // Solve: dx = (col - row) * tw/2,  dy = (col + row) * th/2
    final col = (dx / (tileWidth / 2) + dy / (tileHeight / 2)) / 2;
    final row = (dy / (tileHeight / 2) - dx / (tileWidth / 2)) / 2;
    return (col.floor(), row.floor());
  }

  // -------------------------------------------------------------------------
  // Bounds check
  // -------------------------------------------------------------------------

  /// Returns true if (col, row) is within the map grid.
  bool inBounds(int col, int row) {
    return col >= 0 && col < mapCols && row >= 0 && row < mapRows;
  }

  // -------------------------------------------------------------------------
  // Depth priority (Bob rule §2, ASSET_SPEC §1)
  // Priority = (col + row) * 100 + z
  // -------------------------------------------------------------------------

  /// Returns the rendering priority for a character at grid position (col, row)
  /// and elevation [z] (default 0).
  static int depthPriority(int col, int row, {int z = 0}) {
    return (col + row) * 100 + z;
  }
}
