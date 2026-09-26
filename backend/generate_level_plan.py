"""
Generate backend/fixtures/starter/level_plan.json deterministically (fixed seed 42).

20x20 isometric map:
  - Ground layer: random grass tile variants (IDs 0-15), seed=42.
  - Diagonal stone path from top-left (0,0) to bottom-right (19,19): tile IDs 16-31.
  - Objects: PlayerSpawn at (0,0), ExitTrigger at (19,19), 3 Zombies on grass cells.

Run from the workspace root:
  python neuro_symbolic_level_designer/backend/generate_level_plan.py
"""
import json
import random
import os

SEED = 42
W, H = 20, 20
GRASS_IDS = list(range(0, 16))    # catalog IDs 0..15
STONE_IDS = list(range(16, 32))   # catalog IDs 16..31

rng = random.Random(SEED)

# Build the ground grid with random grass variants
grid = [[rng.choice(GRASS_IDS) for _ in range(W)] for _ in range(H)]

# Lay a diagonal stone path: each step advances by 1 in both x and y → 20 cells
path_cells = [(i, i) for i in range(min(W, H))]
stone_rng = random.Random(SEED + 1)
for row, col in path_cells:
    grid[row][col] = stone_rng.choice(STONE_IDS)

# Choose 3 zombie positions on pure-grass cells (not on path)
path_set = set(path_cells)
grass_cells = [(r, c) for r in range(H) for c in range(W) if (r, c) not in path_set]
zombie_cells = rng.sample(grass_cells, 3)

# Object positions stored as tile coordinates (col, row).
# map_compiler converts these to Tiled isometric pixel coords at compile time.
objects = [
    {"name": "spawn_player", "type": "PlayerSpawn", "col":  0,                    "row":  0},
    {"name": "exit_trigger", "type": "ExitTrigger",  "col": 19,                    "row": 19},
    {"name": "zombie_0",     "type": "Zombie",        "col": zombie_cells[0][1],    "row": zombie_cells[0][0]},
    {"name": "zombie_1",     "type": "Zombie",        "col": zombie_cells[1][1],    "row": zombie_cells[1][0]},
    {"name": "zombie_2",     "type": "Zombie",        "col": zombie_cells[2][1],    "row": zombie_cells[2][0]},
]

level_plan = {
    "map_properties": {
        "width":       W,
        "height":      H,
        "tile_width":  64,
        "tile_height": 32,
        "orientation": "isometric"
    },
    "layers": [
        {
            "name":      "Ground",
            "elevation": 0,
            "grid":      grid
        }
    ],
    "objects": objects
}

out_path = os.path.join(os.path.dirname(__file__), "fixtures", "starter", "level_plan.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w") as f:
    json.dump(level_plan, f, indent=2)

print(f"Written {out_path}")
print(f"Path cells (first 5): {path_cells[:5]}")
print(f"Zombie cells: {zombie_cells}")
