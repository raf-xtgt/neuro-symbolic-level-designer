Read `backend/pipeline/planning/dressing.py`, `backend/pipeline/planning/catalog_digest.py`,
`backend/pipeline/ingestion/harmonizer.py` (paths relative to `neuro-symbolic-level-designer/`).

## Working rules (token budget)
Code plus small unit tests for the new logic only. Run `uv run pytest` once. No live LLM runs. Report briefly.

## Problems (browser, uploaded sheets)
1. **Farm + library upload:** the whole map outside the rooms is a wall of bookcases. Cause: with no tree, pillar, or
   low-blocker families, the wilderness fallback fills every non-playable cell with any blocking group
   (bookcases, the largest group).
2. **Desert upload:** black sprites stick out (void, pit, and dark cave pieces placed as obstacles in the wilderness),
   and dark square floor tiles are scattered in the rooms (dark pit or shadow floor variants).

## Fix 1: sparse wilderness without natural blockers (`dressing.py`)
When the catalog has no tree, pillar, or low-blocker families (the fallback case):
- Only the **hedge ring** is blocking (1 cell in front, 2 cells elsewhere, as now), using the blocking groups with the
  **smallest** sprites first (low props such as crates, sacks, hay, chairs before bookcases), style weighted.
- Every cell beyond the hedge is the main floor with sparse walkable decorations (about 10%), like the front zone.
  These cells are unreachable, so the reachability boundary check still passes.
- Inside rooms, one group may take at most 40% of the placed props (so bookcases cannot dominate a room).

## Fix 2: no void or dark outlier sprites (`harmonizer.py`, deterministic)
- Tag `void` and exclude from the catalog: sprites where more than 35% of the opaque pixels are near black
  (luminance < 24). Record them in the ingestion report as excluded with reason `void`.
- Floor outliers: inside each floor family, compute the median luminance of the opaque pixels; tag `floor_outlier`
  every floor tile more than 35% darker than its family median. `catalog_digest.py` excludes `void` and
  `floor_outlier` tiles from all groups (keep them in the catalog for inspection).
- Bump `PIPELINE1_VERSION` so cached ingestion results are rebuilt.

## Tests
- Synthetic library-like catalog (bookcases, tables, chairs, one floor family): wilderness beyond the hedge has no
  blocking tile; no group exceeds 40% of a room's props; validation passes.
- Harmonizer: a mostly black sprite is excluded as `void`; a dark floor variant is tagged `floor_outlier` and absent
  from the digest.

## Done when
`uv run pytest` passes. Report the changed constants.
