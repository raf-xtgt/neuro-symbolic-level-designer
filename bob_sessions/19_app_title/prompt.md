Paths are in `z_legend_game/z_legend_game_flutter/`.

## Working rules
Write code only. **Do not run anything** (no tests, no builds): I run everything and report errors. Report briefly.

## Change: product name "Neuro Symbolic Game Level Designer" (display text only)
1. `lib/screens/start_screen.dart`: the start screen heading `'Z Legend'` becomes
   `'Neuro Symbolic Game Level Designer'`. At 48 px it does not fit on one line on small screens: use `fontSize: 36`,
   `letterSpacing: 1`, `textAlign: TextAlign.center`, and horizontal padding 24, so it wraps cleanly.
2. `lib/main.dart`: `MaterialApp.title` -> `'Neuro Symbolic Game Level Designer'` (the browser tab title).
3. `web/index.html`: `<title>` and `apple-mobile-web-app-title` -> `Neuro Symbolic Game Level Designer`;
   `<meta name="description">` -> `Describe a level in words; AI agents plan it and algorithms build a playable
   isometric Flame level.`
4. `web/manifest.json`: `name` -> `Neuro Symbolic Game Level Designer`, `short_name` -> `Level Designer`,
   `description` as in step 3.
5. `test/widget_test.dart`: expect the new heading text.

Do not rename packages, folders, classes, or file names (`z_legend_game_flutter`, `ZLegendGame` stay).
