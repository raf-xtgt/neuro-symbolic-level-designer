# IBM Bob Task Session Summaries (`bob_sessions/`)

As mandated by the **IBM Bob 2.0 Hackathon Guidelines**, this directory contains task session consumption summary screenshots verifying authentic development workflows inside the **IBM Bob IDE**.

## Required File Naming Standard
```
<team_name>_task<number>_<task_description>_summary.png
```

## Folder Structure
Each IBM Bob task has its own folder. The folder contains the prompt given to Bob and the session summary screenshot.

```
<number>_<task_description>/
  prompt.md
  <team_name>_task<number>_<task_description>_summary.png
```

## Task Sessions
| # | Folder | Task | Status |
|---|---|---|---|
| 01 | `01_character_conversion/` | Convert player and zombie spritesheets to the ASSET_SPEC format (directions, scale, anchors). | Done |
| 02 | `02_execution_pipeline/` | Pipeline 3 first slice: fixtures, tileset compiler, map compiler, tests, preview. | Done |
| 03 | `03_remove_serverpod/` | Remove Serverpod from the Flutter app and tooling (Log-8 decision). | Done |
| 04 | `04_asset_paths/` | Resolve asset paths from the repository root after moving `game-assets/` into the repo. | Done |
| 05 | `05_flame_game/` | Task B: playable Flame game on the starter level (level loader, isometric math, player, zombies, exit). | Done (Prompts 1-2: IBM Bob; Prompt 3: Claude Code, Bob out of credits). Browser check passed. |
| 06 | `06_fastapi_backend/` | FastAPI backend: input contract validation, asset packs, job stages, bundle serving. | Done (Claude Code, Bob out of credits) |
| 07 | `07_level_designer/` | Level Designer screen, API client, progress, result, Try Out (web-safe network loading). | Done (Claude Code). Browser check passed. |
| 08 | `08_grassland_full_pack/` | Asset pack with walls, obstacles, decorations, water; multi-size tilesets; Pipeline 1 slicer measured against the Flare answer key. | Done (Claude Code) |
| 09 | `09_collision_depth/` | Obstacle collision, depth sorting of tall sprites with occlusion fade, shared movement rule, fence tag, tight-box slicer metric. | Code done (Claude Code). Browser check pending. |
