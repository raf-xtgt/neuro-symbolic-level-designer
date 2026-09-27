import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/main.dart';

void main() {
  testWidgets('start screen shows the title and both buttons', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const ZLegendApp());
    expect(find.text('Neuro Symbolic Game Level Designer'), findsOneWidget);
    expect(find.text('Z Legend'), findsNothing);
    expect(find.text('Level Designer'), findsOneWidget);
    expect(find.text('Play starter level'), findsOneWidget);
  });
}
