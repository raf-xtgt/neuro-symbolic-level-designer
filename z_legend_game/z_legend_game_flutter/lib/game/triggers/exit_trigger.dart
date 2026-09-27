import 'package:flame/collisions.dart';
import 'package:flame/components.dart';

import '../iso/iso_math.dart';

/// Marks the exit tile. When the player reaches this tile, the game ends.
class ExitTrigger extends PositionComponent {
  ExitTrigger({required this.col, required this.row, required this.isoMath}) {
    final worldCenter = isoMath.gridToWorldCenter(col, row);
    position = worldCenter;
    priority = IsoMath.depthPriority(col, row, DepthLayer.exitTrigger);
  }

  final int col;
  final int row;
  final IsoMath isoMath;

  @override
  Future<void> onLoad() async {
    await super.onLoad();
    // Diamond hitbox matching the isometric tile diamond (from flame rules §4).
    add(
      PolygonHitbox(
        [
          Vector2(0, -isoMath.tileHeight / 2),
          Vector2(isoMath.tileWidth / 2, 0),
          Vector2(0, isoMath.tileHeight / 2),
          Vector2(-isoMath.tileWidth / 2, 0),
        ],
        collisionType: CollisionType.passive,
      ),
    );
  }
}
