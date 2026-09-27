import 'package:flame/components.dart';
import 'package:flutter/painting.dart';

import '../characters/player_health.dart';

/// HUD health bar (camera viewport, top left): an "HP" label and one
/// segment per health point, filled red or empty dark.
class HealthBar extends PositionComponent {
  HealthBar(this.health) : super(position: Vector2(16, 16));

  final PlayerHealth health;

  static const double segmentWidth = 18;
  static const double segmentHeight = 10;
  static const double gap = 3;
  static const double labelWidth = 28;

  static final _filled = Paint()..color = const Color(0xFFE53935);
  static final _empty = Paint()..color = const Color(0xFF3A1F1F);
  static final _border = Paint()
    ..color = const Color(0xCC000000)
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;
  static final _label = TextPaint(
    style: const TextStyle(
      color: Color(0xFFFFFFFF),
      fontSize: 12,
      fontWeight: FontWeight.bold,
      shadows: [Shadow(color: Color(0xFF000000), blurRadius: 3)],
    ),
  );

  /// Number of filled segments (the current health).
  int get filledSegments => health.hp;
  int get segments => health.max;

  @override
  void render(Canvas canvas) {
    _label.render(canvas, 'HP', Vector2(0, -2));
    for (var i = 0; i < segments; i++) {
      final rect = Rect.fromLTWH(
        labelWidth + i * (segmentWidth + gap),
        0,
        segmentWidth,
        segmentHeight,
      );
      canvas.drawRect(rect, i < filledSegments ? _filled : _empty);
      canvas.drawRect(rect, _border);
    }
  }
}
