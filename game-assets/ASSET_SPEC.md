# Asset Specification

This document defines the standard format for all game assets. 
The starter Flame game, the level designer tool, and IBM Bob rules (`.bob/rules/`) must use these values.

## 1. Projection and Grid

| Property | Value |
|---|---|
| Projection | Isometric, 2:1 (dimetric) |
| Base tile diamond | **64 x 32 px** (width x height) |
| Tiled map orientation | `isometric` |
| Tiled render order | `right-down` |
| Elevation step (one Z level) | 32 px |
| Depth sort index | `X + Y + Z` |

## 2. Image Format

* PNG, 8-bit RGBA, straight (non-premultiplied) alpha.
* Transparent background. No color-key backgrounds.
* No JPG files in game assets.
* File names use `snake_case` (for example, `grass_01.png`, `zombie_walk.png`).

## 3. Tiles

* Floor tiles: sprite size 64 x 32 px. The diamond fills the full sprite.
* Tall tiles (walls, cliffs, trees, buildings): sprite width is a multiple of 64 px. Sprite height can be any value.
* The anchor of every tile is the **bottom-center of the base diamond**.
* For tall tiles, the Tiled `tileoffset` is set so that the base diamond aligns with the grid cell.
* Tilesets are exported as Tiled JSON (`.tsj`). Maps are exported as Tiled JSON (`.tmj`).

## 4. Characters and Entities

| Property | Value |
|---|---|
| Directions | **8** (S, SW, W, NW, N, NE, E, SE) |
| Sheet layout | One PNG per character per animation. One row per direction, in the order above. One column per frame. |
| Required animations | `idle`, `walk`, `attack`, `die` |
| Anchor | Bottom-center of the frame (the feet of the character) |
| Frame rate | 10 fps (default) |

Each character sheet has a sidecar JSON file with the same base name:

```json
{
  "frame_width": 64,
  "frame_height": 64,
  "directions": ["S", "SW", "W", "NW", "N", "NE", "E", "SE"],
  "frames": 10,
  "fps": 10,
  "anchor": { "x": 32, "y": 60 }
}
```

## 5. Per-Source Conversion Rules

| Source | Native format | Conversion to this standard |
|---|---|---|
| `grassland_tiles.png` (Flare) | 64 x 32 grid, 1024 x 1344 sheet | Use as is. |
| `tileset_desert.png` | 64 x 32 grid (Flare-derived), 1024 x 1129 sheet | Use as is. |
| `grassland_sheets.zip` (rubberduck) | 64 x 32 and 128 x 64 sheets, `shaded` and `cloudy` variants | Use `*_64x32_shaded.png`. Keep `*_128x64_*` only as a level designer test input. |
| Kenney Isometric Miniature (farm, library) | Separate 256 x 512 sprites, 4 facings (`_N`, `_E`, `_S`, `_W`), `Isometric/` folder | Use the `Isometric/` folder. Scale by **25%** (256 px wide to 64 px wide). |
| `death_city.zip` (Game Gland) | 64 x 64 frames, 8 rows (directions), for example `female.png` is 640 x 512 | Keep 64 x 64. Re-order rows to the direction order in Section 4 if needed. |
| engvee zombie (`Skin1_x256_Spritesheets.zip`) | 256 x 256 frames, 16 directions (0 to 337.5 degrees, 22.5 degree steps), one sheet per animation per direction | Scale to **128 x 128** frames. Keep every second direction (0, 45, 90, ... 315) and map each angle to the direction names in Section 4. Keep `Idle`, `Walk`, `Attack1`, `Death1`. Merge the separate `Shadow` layer into the body frame or drop it. |

## 6. Visual Scale Check

After conversion, the character body (not the frame) must be approximately **1 to 1.5 tiles tall** (48 to 64 px visible height). 
Verify the engvee zombie against the Game Gland player in one test scene. If the zombie is too large, reduce its frame size to 96 x 96.

## 7. Notes on `game-assets/`

* `grassland_tiles.png` is a packed atlas, not a uniform grid. Only the top two rows are a clean 64 x 32 grid: row 0 (y = 0 to 32) is 16 grass floor tiles, row 1 (y = 32 to 64) is 16 stone path floor tiles. Tall sprites (cliffs, props, trees, buildings) below y = 64 have mixed sizes and need contour slicing.
* No manual Tiled work is used. The legacy-format test input (`.tmj` / `.tsj`) will be a map produced by the Execution pipeline itself (round-trip test).
* `game-assets/` is inside the git repository. All paths in scripts and fixtures are relative to the repository root (`neuro-symbolic-level-designer/`).
* `death_city.zip` is git-ignored (license: no redistribution). A fresh clone must download it from Game Gland to regenerate the player sheets.
* Archives stay zipped. `tools/prepare_characters.py` reads the zips directly. Extract Kenney files only when building Pipeline 1 test fixtures.
