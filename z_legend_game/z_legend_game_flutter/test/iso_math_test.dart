import 'package:flutter_test/flutter_test.dart';

import 'package:z_legend_game_flutter/game/iso/iso_math.dart';

void main() {
  // Use the starter map dimensions (20×20, 64×32) for the object-coordinate tests.
  const iso = IsoMath.starter;

  // Object coords from the starter level.tmj:
  //   spawn(0,0)    → x=16,  y=16  → (16/32, 16/32)   = (0, 0)
  //   exit(19,19)   → x=624, y=624 → (624/32, 624/32)  = (19, 19)
  //   zombie(14,17) → x=464, y=560 → (14.5, 17.5) → floor = (14, 17)
  //   zombie(6,2)   → x=208, y=80  → (6.5,  2.5)  → floor = (6, 2)
  //   zombie(13,7)  → x=432, y=240 → (13.5, 7.5)  → floor = (13, 7)

  group('objectToGrid (starter 20×20)', () {
    test('PlayerSpawn (0,0) from x=16, y=16', () {
      expect(iso.objectToGrid(16.0, 16.0), (0, 0));
    });

    test('ExitTrigger (19,19) from x=624, y=624', () {
      expect(iso.objectToGrid(624.0, 624.0), (19, 19));
    });

    test('Zombie (14,17) from x=464, y=560', () {
      expect(iso.objectToGrid(464.0, 560.0), (14, 17));
    });

    test('Zombie (6,2) from x=208, y=80', () {
      expect(iso.objectToGrid(208.0, 80.0), (6, 2));
    });

    test('Zombie (13,7) from x=432, y=240', () {
      expect(iso.objectToGrid(432.0, 240.0), (13, 7));
    });
  });

  group('gridToWorld → worldToGrid round trip (starter 20×20)', () {
    for (final tc in [
      (0, 0),
      (10, 10),
      (19, 19),
      (0, 19),
      (19, 0),
    ]) {
      test('(${tc.$1}, ${tc.$2})', () {
        final world = iso.gridToWorld(tc.$1, tc.$2);
        final (col, row) = iso.worldToGrid(world);
        expect(col, tc.$1, reason: 'col mismatch');
        expect(row, tc.$2, reason: 'row mismatch');
      });
    }
  });

  group('gridToWorld → worldToGrid round trip (non-square 30×12)', () {
    const isoRect = IsoMath(
      tileWidth: 64,
      tileHeight: 32,
      mapCols: 30,
      mapRows: 12,
    );

    for (final tc in [
      (0, 0),
      (29, 11),
      (15, 6),
      (0, 11),
      (29, 0),
    ]) {
      test('(${tc.$1}, ${tc.$2})', () {
        final world = isoRect.gridToWorld(tc.$1, tc.$2);
        final (col, row) = isoRect.worldToGrid(world);
        expect(col, tc.$1, reason: 'col mismatch');
        expect(row, tc.$2, reason: 'row mismatch');
      });
    }
  });

  group('inBounds (starter 20×20)', () {
    test('(0,0) is in bounds', () => expect(iso.inBounds(0, 0), isTrue));
    test(
      '(19,19) is in bounds',
      () => expect(iso.inBounds(19, 19), isTrue),
    );
    test(
      '(-1,0) is out of bounds',
      () => expect(iso.inBounds(-1, 0), isFalse),
    );
    test(
      '(0,-1) is out of bounds',
      () => expect(iso.inBounds(0, -1), isFalse),
    );
    test(
      '(20,0) is out of bounds',
      () => expect(iso.inBounds(20, 0), isFalse),
    );
    test(
      '(0,20) is out of bounds',
      () => expect(iso.inBounds(0, 20), isFalse),
    );
  });

  group('depthPriority', () {
    test('(0,0,z=0) = 0', () => expect(IsoMath.depthPriority(0, 0), 0));
    test('(1,2,z=0) = 300', () => expect(IsoMath.depthPriority(1, 2), 300));
    test(
      '(5,3,z=2) = 802',
      () => expect(IsoMath.depthPriority(5, 3, z: 2), 802),
    );
  });
}
