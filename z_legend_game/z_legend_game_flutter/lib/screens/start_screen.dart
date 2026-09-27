import 'package:flutter/material.dart';

import '../designer/level_designer_screen.dart';
import 'game_screen.dart';

/// Start screen with the product name, "Level Designer" and "Play starter
/// level" buttons.
class StartScreen extends StatelessWidget {
  const StartScreen({super.key});

  void _open(BuildContext context, Widget screen) {
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    final buttonStyle = ElevatedButton.styleFrom(
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 18),
      minimumSize: const Size(280, 0),
    );
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                'Neuro Symbolic Game Level Designer',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 36,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1,
                ),
              ),
            ),
            const SizedBox(height: 48),
            ElevatedButton(
              onPressed: () => _open(context, const LevelDesignerScreen()),
              style: buttonStyle,
              child: const Text(
                'Level Designer',
                style: TextStyle(fontSize: 20),
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _open(context, const GameScreen()),
              style: buttonStyle,
              child: const Text(
                'Play starter level',
                style: TextStyle(fontSize: 20),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
