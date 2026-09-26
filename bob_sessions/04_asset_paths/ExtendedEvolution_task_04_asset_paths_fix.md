Read @neuro-symbolic-level-designer/game-assets/ASSET_SPEC.md (section 7).

## Goal
`game-assets/` moved into the git repository: it is now `neuro-symbolic-level-designer/game-assets/`.
Make every asset path resolve from the repository root, independent of the current working directory.
Repository root = `neuro-symbolic-level-designer/`.

## 1. `tools/prepare_characters.py`
- Compute the repository root from the script location: `Path(__file__).resolve().parent.parent`.
- Default `--input-dir`: `<repo_root>/game-assets`.
- Default `--output-dir`: `<repo_root>/z_legend_game/z_legend_game_flutter/assets/images/characters`.
- Relative paths passed on the command line still resolve from the current working directory.
- Update the usage example in the module docstring.
- If `death_city.zip` is missing, exit with a clear message: the file is git-ignored (license) and must be
  downloaded from https://gamegland.itch.io/zombie-apocalypse-character-spritesheet into `game-assets/`.

## 2. Source image resolution in the backend
- In `backend/fixtures/starter/asset_catalog.json`, tile `source` values stay `game-assets/grassland_tiles.png`.
  Define this in one place: `source` paths are relative to the repository root.
- In `backend/pipeline/execution/compile.py`, replace `_resolve_source_image` (it tries parent folders one by one)
  with a single rule: `repo_root / source`, where `repo_root` is computed from the module location
  (`backend/pipeline/execution/compile.py` -> 3 levels up). Absolute `source` paths are used as they are.
  If the file does not exist, raise an error that shows the resolved path.
- Update the `source_image_path` docstring in `tileset_compiler.py` to match.
- Add a test: `source` in the fixture catalog resolves to an existing file.

## Constraints
- Do not change the output file formats, the fixtures (except as listed above), or any Dart code.
- Do not modify `game-assets/` files.

## Done when
- From `backend/`: `uv run pytest` passes, and the compile command in DEV_SETUP.md section 3.3 regenerates
  the starter level with no change to `level.tmj` and `tileset.tsj`.
- From `neuro-symbolic-level-designer/` AND from `tools/`: `uv run --with pillow python tools/prepare_characters.py`
  (adjust the script path for `tools/`) runs and produces the same character sheets as before.
- Show `git diff --stat` for the generated assets (it must be empty).
