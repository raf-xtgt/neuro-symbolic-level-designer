Reviewed by eye by the executor (contact sheets, crops, and the end-to-end preview).

**Desert sample (item 2), 20 chips:** 17 are right or reasonable: dirt and dock floors, dark water,
rocks, fence posts, cliff pieces, and the teleporter quarter (#414) correctly called a part of a
multi-tile assembly. 3 are thin grid pieces of cliffs that were kept as `wall` (#195, #329, #336)
instead of `fragment`. Walls are not used by the planner, so they do not reach levels.

**Kenney (item 4):** the four block floors (dirt, farmland, planks, old planks) are found as 256 x 128
base diamonds on slabs and scaled x0.25; sacks, crate, fences, wood walls, chimney and ladder are
named correctly. Rows of corn are separate plants: after scaling their smallest pieces fall under
the noise limit, so the sheet gives 15 chips from 16 files.

**Family agreement (item 1):** all 10 most common families name the same thing as the answer key.
The equivalences used are listed in `EQUIVALENT_FAMILIES` in the tool; they were added from this
review (for example `tree_pine` = `tree_tall`, `tree_leafy` = `tree_fluffy`, `stone_path` = the
stone floor material).

**End-to-end level (item 5):** playable and validated. A cabin built from the house pieces on a
wooden deck (dock floor tiles) in the west, gravestones in the central yard, the boss clearing with
the exit in the north. An earlier run showed broken-looking floors (grid pieces of the wharf and
stairs classified as floor); the harmonizer now excludes floor chips that are not full base
diamonds (`not_a_floor_diamond`), which removed them without changing any metric above.

**Tuning on the answer key (disclosed):** two changes were made after looking at item 1 results on
this same sheet, so item 1 numbers are optimistic: the anchor rule (solid pixels and a lift scaled
by the base width; object anchor error median 9.5 -> 5.2 px, p90 20.4 -> 9.0 px on the answer key)
and the classification wording for fences (obstacle, not wall) and for connectors (worn floor
tiles are not connectors). Items 2 to 4 were not used for tuning.
