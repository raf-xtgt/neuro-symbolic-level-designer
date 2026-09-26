import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/main.dart';

void main() {
  testWidgets('placeholder screen shows coming soon text', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const MyApp());
    expect(find.text('Z Legend: Level Designer coming soon'), findsOneWidget);
  });
}
