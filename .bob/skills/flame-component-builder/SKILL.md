---
name: flame-component-builder
description: Generates typed Flutter/Flame Dart components and LevelLoader code from Tiled .tmj map specifications.
---

# Flame Component Builder Skill

## Overview
This skill takes a validated `level_plan.json` or `.tmj` file and synthesizes:
1. Production-ready `LevelLoader` component extending Flame's `PositionComponent`.
2. Typed entity component classes (e.g. `PlayerComponent`, `EnemyComponent`, `ChestComponent`).
3. Automated hitbox generators attaching `PolygonHitbox` (for isometric ground tiles) and `RectangleHitbox` (for entities and blocking walls).

---

## Instructions for IBM Bob
When asked to build or update Flame game integration:
1. Use the template in `templates/level_loader.dart.jinja`.
2. Ensure all components mix in `HasGameReference<IsometricGame>` and `CollisionCallbacks`.
3. Verify that all entity coordinates convert correctly from Tiled isometric coordinates into Flame World coordinates.
