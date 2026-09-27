Read @neuro-symbolic-level-designer/ARCHITECTURE.md sections 1.2, 4, 6.2, 6.3, 8 and 9, @BUILD_LOG.md Log-24 to Log-32,
and @neuro-symbolic-level-designer/backend/ (especially `pipeline/llm/`, `pipeline/planning/`,
`asset_packs/grassland_full/`, `app/jobs.py`).

## Goal
Replace the placeholder planner with the real Pipeline 2 (ARCHITECTURE.md section 4): a LangGraph `StateGraph`
where an LLM agent plans the macro structure and deterministic algorithms fill, dress, and validate the level, with
a self-healing retry loop. "Agents plan, algorithms fill." The prompt must visibly shape the level: room count and
layout, themes (for example gravestones in a graveyard), enemy placement, and where the exit is.

The LLM is Gemini on Vertex AI through `pipeline/llm/` (task 10). Use it only through `generate_structured`.
Paths starting with `lib/` or `test/` are in `z_legend_game/z_legend_game_flutter/`; all other paths are relative to
`neuro-symbolic-level-designer/backend/`.

## Secrets
Same rules as task 10: never print, log, commit, or copy values from `.env` or `creds.json`.

## 1. Richer tile groups in `grassland_full` (`asset_packs/grassland_full/build_pack.py`)
Add one **family tag** per tile so the planner can ask for specific things. Apply exactly (catalog names):

| Tiles | Family tag |
|---|---|
| `town_objects_00`, `_01` | `cart` |
| `town_objects_02`, `_03` | `sack` |
| `town_objects_04`, `_05` | `logs` |
| `town_objects_06` | `campfire` |
| `town_objects_07` | `anvil` |
| `town_objects_08` to `_15` | `fence` (already tagged) |
| `rocks_00` to `_03` | `rock_small` |
| `rocks_04` to `_07` | `rock_pillar` |
| `tall_town_objects_00`, `_01` | `stump` |
| `tall_town_objects_02`, `_03` | `signpost` |
| `tall_town_objects_04` to `_07` | `gravestone` |
| `blue_trees_*`, `dead_trees_*`, `tall_trees_*`, `fluffy_trees_*` | `tree_blue`, `tree_dead`, `tree_tall`, `tree_fluffy` |
| `shrubs_and_grass_tufts_00`, `_01` | `fern` |
| `_02`, `_03` | `weed` |
| `_04`, `_05` | `leafy_plant` |
| `_06`, `_07` | `flower` |
| `_08` to `_11` | `bush` |
| `_12` to `_15` | `dry_grass` |

Rebuild the pack. Keep the existing tags (`tree`, `tall`, `prop`, `fence`, `autotile_required`).

## 2. Catalog digest (`pipeline/planning/catalog_digest.py`, deterministic)
- Build **tile groups** from any catalog: `floor.<material>` for floors, and `<category>.<family tag>` for
  obstacles and decorations (fallback: `<category>.<material>`). Exclude tiles tagged `autotile_required` or `fence`
  from every group (no placement rules for them yet).
- Each group: id, category, walkable, tile ids, count, and a short human description (for example
  `obstacle.gravestone: 4 gravestones and stone crosses, blocks movement, tall`).
- The digest is the only catalog information the LLM sees. `grassland_starter` gives only `floor.grass` and
  `floor.stone`; the pipeline must still work with it (no obstacles, see section 5).

## 3. Topology contract (`pipeline/planning/models.py`, ARCHITECTURE.md 6.2)
Extend `RoomTopologyGraph` (keep the task 10 validators):
- `Room`: add `enemy_count: int` (0 to 6), `dressing: list[StyleWeight]` (optional, 0 to 4 items; overrides the
  global weights inside this room), `description: str` (max 120 characters, for example "sunken burial ground").
- Graph: add `design_notes: str` (max 400 characters: why this layout fits the prompt; shown in the UI).
- Validation with **catalog context** (a validation step or function that takes the digest, not only a static
  schema): every `tile_group` exists in the digest; the global `style_distribution` has at least one `floor.*` group;
  3 to 7 rooms; the corridor graph is connected; total `enemy_count` at most 20.
- The LLM gets these rules in the system instruction, and failures go back through the repair or retry loop.

## 4. LangGraph pipeline (`pipeline/planning/graph.py`)
A `StateGraph` over a typed state (prompt, catalog, digest, seed, topology, layout, plan, validation report,
attempt counters, a step trace, LLM usage). Nodes:

1. **`topology_agent`** (LLM, Spatial Topology Planner, 4.1.1): prompt + digest (+ structured errors from the
   previous attempt, if any) -> `RoomTopologyGraph`. `temperature` 0.4, `max_output_tokens` 8192, and a thinking
   setting from configuration (see section 7).
2. **`layout_builder`** (deterministic, 4.1.1): room graph -> grid footprint.
   - Room sizes: small 5 x 5, medium 7 x 7, large 9 x 9 (seeded jitter of +/- 1).
   - Bearings are screen directions in isometric view: north = up on screen = (-1 col, -1 row) per step,
     south = (+1, +1), east = (+1, -1), west = (-1, +1), center = origin. Several rooms with the same bearing are
     placed further out along it, with a perpendicular offset.
   - Separate overlapping rooms (keep at least 2 cells between rooms).
   - Corridors 2 cells wide: `straight` = shortest L-shape, `winding` = 2 or 3 bends (seeded), `bridge` = straight
     (no bridge tiles yet; record a warning).
   - Map size = bounding box + a margin of 3 cells on each side, clamped to 20 to 48 per axis.
3. **`stacking`** (deterministic placeholder for 4.1.2): the packs have no ramps or elevated tiles, so every room
   gets elevation 0; if the topology asks for elevation, add a warning. (The occlusion guard already runs in the
   game.)
4. **`spawner`** (deterministic, 4.1.3): `PlayerSpawn` at the entrance room center; `ExitTrigger` in the room at the
   largest corridor-graph distance from the entrance (tie: largest grid distance); zombies per room from
   `enemy_count`, on walkable cells, at least 3 cells from the spawn, spread out (seeded). Combat and boss rooms may
   also put 1 zombie in a connecting corridor if the room count allows.
5. **`dressing`** (deterministic, 4.1.4, weighted autotile-lite):
   - Room floors from the floor groups of the room's `dressing` (else global weights); corridors use a path floor
     (`floor.stone` if present, else the main floor).
   - Inside rooms: obstacles and decorations from the style weights, at a density by purpose (entrance 3%, combat 6%,
     puzzle 10%, treasure 8% decorations mostly, boss 4% with the center 3 x 3 kept clear). Never on corridor cells,
     entity cells, or the 8 neighbors of the spawn and exit.
   - **Wilderness:** every cell outside rooms and corridors gets a blocking obstacle (trees and rock pillars,
     weighted toward the style), with decorations under nothing. This encloses the playable area (boundary integrity).
   - If the catalog has no blocking obstacles (`grassland_starter`), leave the wilderness as the main floor and add
     a warning; the map edge is the boundary.
   - Output: the `level_plan.json` layers `Ground` and `Objects` in the current 6.3 format.
6. **`validator`** (deterministic, 4.2), all checks with the movement rule from task 09 (`pathing.py`):
   - Path from `PlayerSpawn` to `ExitTrigger`.
   - Every room reachable from the entrance.
   - Every entity on a walkable cell.
   - Every placed id exists in the catalog.
   - Boundary integrity: no walkable cell on the outermost ring of the map (skip with a warning when the catalog has
     no blocking tiles).
   - Rooms do not overlap and stay inside the map.
   - Output: a validation report `{passed, checks: [{name, passed, detail}], warnings}`.
7. **Retry routing** (conditional edges):
   - Failures a new layout can fix (overlap after separation, unreachable room due to scattered props) -> back to
     `layout_builder` with the next seed, at most 2 times per topology.
   - Otherwise, or when layout retries are used up -> back to `topology_agent` with a structured error payload
     (failed check names and details), at most 3 topology attempts in total.
   - All attempts fail -> the job fails with the last validation report (no silent fallback).

Write `work/topology_graph.json` and `work/validation_report.json` next to `work/level_plan.json`.

## 5. Planner selection and API
- `pipeline/planning/run.py`: `planner` = `agentic` (default) or `placeholder`. The API accepts an optional
  `planner` form field; the job summary records which planner ran.
- Job status: during planning, report the graph steps in `planning_steps`:
  `[{node, status, attempt, message}]` (for example `topology_agent done attempt 1 "5 rooms, 9 enemies"`,
  `validator failed attempt 1 "room r4 unreachable"`). Update `job.json` after every node.
- Job summary additions: `planner`, `design_notes`, room list (id, purpose, size, description, enemy count),
  validation report, attempts (topology and layout), LLM usage (calls, input and output tokens, latency).
- Bundle: also serve `topology_graph.json` and `validation_report.json` (add them to the allowed names).
- LLM errors: `LLMUnavailableError`, `LLMOutputError`, and `LLMConfigError` fail the job with their safe message and
  error codes `llm_unavailable`, `llm_output_invalid`, `llm_config`.

## 6. Level Designer UI (Flutter, small)
- Under "2. Level Planning", show the `planning_steps` as indented sub-rows while planning runs and after it ends.
- Result: show `design_notes`, the room list, the validation badge (passed, or failed with the failing checks), and
  the LLM usage line (calls, tokens, time).
- A "Planner" choice: "AI planner (Gemini)" (default) or "Placeholder". Send it as the `planner` field.
- Map friendly messages for the new error codes.

## 7. LLM settings
- Add an optional thinking setting to `generate_structured`: `thinking_level` or `thinking_budget` (the SDK's
  `ThinkingConfig` has both; Gemini 3.x models use `thinking_level`). Use what the configured model accepts; make it
  configurable through `.env`-style settings with a default of `LLM_THINKING_LEVEL=medium` (or the closest
  supported value). Report what you used.
- Budget per level: at most 3 topology calls plus repair attempts. The token budget can be generous; quality comes
  first.

## 8. Tests (offline by default)
- Catalog digest for both packs (group ids, excluded fence and autotile tiles).
- Topology validation with catalog context (unknown tile group, no floor group, disconnected corridors, too many
  enemies).
- Layout builder, property tests over at least 200 seeds and a set of hand-made topologies (3 to 7 rooms, all
  bearings, all corridor types): rooms inside the map, no overlap, at least 2 cells apart, corridors connect the
  intended rooms.
- Spawner and dressing: entities on walkable cells, spawn and exit neighborhoods clear, boss center clear,
  wilderness encloses the playable area.
- Validator: one crafted failing plan per check.
- Graph with `FakeProvider`: first topology invalid (unknown tile group) -> the error payload reaches the second
  call -> pass; layout-only failure retries layout without a new LLM call; all attempts fail -> failed job with the
  report.
- End to end in replay mode for the 5 evaluation prompts in section 9 (recorded fixtures): valid plan, compiles with
  Pipeline 3, loads in the API test.
- The placeholder planner and `grassland_starter` placeholder output stay unchanged.
- Flutter: widget test for the planning sub-steps and the validation badge with a fake API; `dart analyze` 0 issues.

## 9. Evaluation (live, then recorded)
Run these prompts with `grassland_full`, `LLM_MODE=record`:
1. "graveyard with a cabin and a boss arena"
2. "dense forest maze with a hidden treasure grove"
3. "open meadow with a stone plaza in the center guarded by 6 zombies"
4. "a winding path through dead trees to a boss clearing in the north"
5. "small campsite with firewood and a treasure room to the east"

`tools/evaluate_planner.py` writes `eval/pipeline2_report.md`: per prompt the room list, design notes, attempts,
validation result, LLM tokens and latency, and a link to its preview image (`eval/previews/<n>.png`). Add a short
judgement per prompt: does the level match the prompt (for example gravestones present in the graveyard, the boss
room in the north for prompt 4, 6 zombies near the plaza for prompt 3)?

## Constraints
- Do not change `game-assets/`, `tools/prepare_characters.py`, `.bob/`, or the docs (I update ARCHITECTURE.md from
  your report).
- Keep game code changes to the Level Designer screen and its API models.
- No LangChain wrappers around the model; use `pipeline/llm/`.

## Done when
- Backend `uv run pytest` passes offline. Flutter `dart analyze` 0 issues, `flutter test` passes,
  `flutter build web` succeeds.
- The 5 evaluation prompts pass validation live; `eval/pipeline2_report.md` and the previews exist.
- A live job through the API (`planner=agentic`) finishes; report its summary.
- Report: schema changes, the thinking setting used, retry statistics, total tokens and latency per level, and any
  prompt that needed a replan and why. No secret values in the report.
