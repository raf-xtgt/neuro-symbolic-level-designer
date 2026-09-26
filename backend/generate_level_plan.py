"""
Generate backend/fixtures/starter/level_plan.json deterministically (fixed seed 42)
with the placeholder planner (pipeline/planning/placeholder_planner.py).

Run from anywhere:
  python neuro-symbolic-level-designer/backend/generate_level_plan.py
"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from pipeline.planning.placeholder_planner import plan_level  # noqa: E402

SEED = 42
FIXTURES_DIR = os.path.join(BACKEND_DIR, "fixtures", "starter")

with open(os.path.join(FIXTURES_DIR, "asset_catalog.json")) as f:
    catalog = json.load(f)

level_plan = plan_level(catalog, SEED)

out_path = os.path.join(FIXTURES_DIR, "level_plan.json")
with open(out_path, "w") as f:
    json.dump(level_plan, f, indent=2)

print(f"Written {out_path}")
print(f"Objects: {[(o['type'], o['col'], o['row']) for o in level_plan['objects']]}")
