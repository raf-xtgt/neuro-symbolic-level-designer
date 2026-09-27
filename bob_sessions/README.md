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
| 09 | `09_collision_depth/` | Obstacle collision, depth sorting of tall sprites with occlusion fade, shared movement rule, fence tag, tight-box slicer metric. | Done (Claude Code). Browser check passed after the ground priority fix. |
| 10 | `10_llm_client/` | LLM client foundation: Gemini on Vertex AI, Pydantic structured output, retries, record/replay fixtures, smoke test, topology schema check. | Done (Claude Code). Location set to global. |
| 11 | `11_pipeline2_langgraph/` | Real Pipeline 2: LangGraph topology agent, layout, spawner, dressing, validator, retry loop; UI planning steps; evaluation report. | Done (Claude Code). Browser check passed. |
| 12 | `12_pipeline1_agents/` | Pipeline 1: tile size detection, slicing, 4 vision agents, harmonizer with LLM arbitration, legacy tilesets, cache, UI, evaluation against the Flare answer key. | Code done (Claude Code). Browser check pending. |
| 13 | `13_theme_polish/` | Hedge wilderness, reachability boundary check, clustered themed props, multi-tile parts and structures. | Done (Claude Code). Browser check passed (asset pack and upload). |
| 14 | `14_pipeline3_verification_codegen/` | Pipeline 3 remainder: entity mechanics agent, Jinja2 Flame code generator, verification report (summary.json, dart analyze), bundle zip, zombie behaviors in the game. | Done (Claude Code). Browser check passed. |
| 15 | `15_demo_polish/` | Player health (6 HP, HUD), Kenney sample sheets and small-catalog robustness, hidden planner choice, friendly progress text, default grassland with uploads only. | Done (Claude Code). Browser check passed. |
| 16 | `16_catalog_visual_fixes/` | Sparse wilderness without natural blockers, 40% cap per prop group in rooms, void and dark floor outlier exclusion. | Done (Claude Code). Browser check pending. |
