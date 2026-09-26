# Task 01: Character Spritesheet Conversion

This task ran in four Bob prompts: the initial conversion and three fixes found in review.
See BUILD_LOG.md Log-3 to Log-6 for the review findings.

## Prompt 1: Initial conversion

Read @game-assets/ASSET_SPEC.md and @game-assets/CREDITS.md. Follow ASSET_SPEC.md strictly.

Write a reusable Python script (`neuro-symbolic-level-designer/tools/prepare_characters.py`, Python 3 + Pillow,
reads directly from the zip files) that converts the raw character assets into game-ready spritesheets, then run it.

- Zombie (`game-assets/Skin1_x256_Spritesheets.zip`, engvee): animations Idle, Walk, Attack1, Death1 ->
  idle, walk, attack, die. Keep 8 of 16 angles (0, 045, ... 315). Composite the Shadow frame under the Body
  frame, scale to 128x128 (LANCZOS). One PNG per animation: rows = directions (S, SW, W, NW, N, NE, E, SE),
  columns = frames.
- Player (`game-assets/death_city.zip`, `death_city/assets/survivor.png`, Game Gland): 64x64 frames. Detect
  animation ranges; if not reliable, output the full sheet with TODO ranges.
- Put direction mappings in constants (`ZOMBIE_ANGLE_TO_DIR`, `PLAYER_ROW_TO_DIR`) for human correction.
- Output: `z_legend_game_flutter/assets/images/characters/{zombie,player}/` + sidecar JSON per sheet +
  `preview_directions.png` contact sheet.
- Do not commit raw death_city files. Do not modify ASSET_SPEC.md / CREDITS.md / Dart code.

## Prompt 2: Direction and layout fix

1. Zombie direction mapping is rotated 180 degrees. Set:
   ZOMBIE_ANGLE_TO_DIR = {"0":"N","045":"NE","090":"E","135":"SE","180":"S","225":"SW","270":"W","315":"NW"}
2. Survivor sheet: COLUMNS are directions (0-7 = S, SE, E, NE, N, NW, W, SW; 8-9 empty), ROWS are frames
   (0 = idle, 1 = attack, 2-5 = walk, 6-7 = die). Output survivor_{idle,walk,attack,die}.png + sidecar JSON.
   Remove survivor_all.*.
3. Output path is wrong. Write to `z_legend_game/z_legend_game_flutter/assets/images/characters/`.
   Delete the `zutter/` folder.
4. Regenerate preview_directions.png using the walk animation for both characters.

## Prompt 3: Anchor fix

In `tools/prepare_characters.py`, compute each character's `anchor.y` from the bottom of the body's alpha
bounding box (threshold 128) instead of a fixed offset, then regenerate the zombie and player sheets.

## Prompt 4: Single anchor per character

In `tools/prepare_characters.py`, use one anchor per character, taken from its `idle` animation, and write
that same anchor into every sidecar JSON for that character. Then run the script again.
