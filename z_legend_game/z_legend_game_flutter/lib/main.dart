import 'package:flutter/material.dart';

import 'screens/start_screen.dart';

void main() {
  runApp(const ZLegendApp());
}

class ZLegendApp extends StatelessWidget {
  const ZLegendApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Neuro Symbolic Game Level Designer',
      theme: ThemeData.dark(),
      home: const StartScreen(),
    );
  }
}
