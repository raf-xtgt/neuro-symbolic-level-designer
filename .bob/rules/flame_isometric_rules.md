# IBM Bob Rule: Flame 2D Isometric Engine Best Practices

## 1. Scope and Objective
This rule guides IBM Bob in generating, refactoring, and validating Flutter and Flame 2D isometric game code.
All generated code must adhere to strict type-safety, 2:1 isometric projection geometry, and clean component architecture.

---

## 2. Isometric Projection Geometry Standards
* **Tile Aspect Ratio:** The standard isometric ratio is 2:1 (Width : Height).
  * Standard tile base: `tileWidth = 64`, `tileHeight = 32`.
* **Coordinate Conversions:**
  * **Grid to Screen:**
    $$ScreenX = (GridX - GridY) \times \frac{TileWidth}{2}$$
    $$ScreenY = (GridX + GridY) \times \frac{TileHeight}{2} - (Z \times ElevationHeight)$$
  * **Screen to Grid:**
    $$GridX = \frac{ScreenX / (TileWidth / 2) + ScreenY / (TileHeight / 2)}{2}$$
    $$GridY = \frac{ScreenY / (TileHeight / 2) - ScreenX / (TileWidth / 2)}{2}$$
* **Depth Ordering (Z-Index / Priority):**
  * To avoid visual overlap artifacts, assign component rendering priority using the 3D depth formula:
    $$Priority = (GridX + GridY) \times 100 + Z$$

---

## 3. Flame Component Hierarchy
* Always use Flame 1.30+ component structure:
  * Extend `FlameGame` with `HasCollisionDetection` and `KeyboardEvents`.
  * Use `World` and `CameraComponent` for view management and viewport scaling.
  * Load maps using `TiledComponent.load(mapPath, Vector2(64, 32))`.
  * Separate visual terrain from interactive entities (Player, Enemies, Pickups, Triggers).

---

## 4. Collision and Hitbox Rules
* Attach `PolygonHitbox` with diamond coordinates for ground-level tile obstacles:
  * Points: `[Vector2(32, 0), Vector2(64, 16), Vector2(32, 32), Vector2(0, 16)]`.
* Attach `RectangleHitbox` or `CircleHitbox` for dynamic characters and collision triggers.
* Always add `CollisionCallbacks` mixin to components that respond to collisions.

---

## 5. Coding and Documentation Standards
* Keep all Dart code warning-free under `flutter_lints`.
* Document architecture, schemas, and PRs in ASD-STE100 Simplified Technical English.
