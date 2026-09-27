Read `z_legend_game/z_legend_game_flutter/lib/designer/level_designer_screen.dart` and its widget tests.

## Working rules
Write code only. **Do not run anything** (no tests, no builds): I run everything and report errors. Report briefly.

## Changes (UI only; keep the API and backend unchanged)
1. Remove the "Optional" section from the form: the heading and the "Existing tilesets (.tsx, .tsj)" and
   "Existing maps (.tmx, .tmj)" file inputs (around line 446). The request never sends tilesets or maps anymore.
   Remove the now unused state and code paths for them in the screen; keep `LevelApi` and the models as they are.
2. Remove the "Planner" row from the result summary (around line 627); the planner is always `agentic`.
3. Update the widget tests that reference these inputs or the Planner row. Add one assertion that the form shows no
   "Optional" heading.
