import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/main.dart';

void main() {
  testWidgets('start screen shows Z Legend title and play button', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const ZLegendApp());
    expect(find.text('Z Legend'), findsOneWidget);
    expect(find.text('Play starter level'), findsOneWidget);
  });
}
