---
name: wfc-level-planner
description: Procedural Wave Function Collapse and topological layout solver that expands high-level room graphs into valid Tiled isometric maps.
---

# Wave Function Collapse Level Planner Skill

## Overview
This skill executes the neuro-symbolic bridge:
1. Takes the high-level semantic room graph (`topology_graph.json`) and style weights from the **Spatial Topology Agent**.
2. Runs a deterministic constraint-satisfaction solver (WFC / autotiler) to place micro-tiles (floors, wall perimeters, corners, and props).
3. Executes a 3-step contradiction recovery protocol (Backtracking $\rightarrow$ Seed Restart $\rightarrow$ Safe Default Fallback) to prevent unsolvable map states.

---

## Usage Instructions for IBM Bob

### 1. Execution Command
```bash
python3 .bob/skills/wfc-level-planner/scripts/wfc_generator.py \
  --topology <path_to_topology_graph.json> \
  --catalog <path_to_asset_catalog.json> \
  --output <path_to_output_level_plan.json> \
  --width 25 \
  --height 25
```

### 2. Contradiction Recovery Protocol
If the solver encounters an unsolvable socket constraint:
* **Step 1:** Automatically rewinds up to 10 collapse steps to explore alternative branches.
* **Step 2:** If backtracking fails, restarts with an incremented random seed (up to 3 retries).
* **Step 3:** If retries are exhausted, places a neutral default floor tile (`walkable: true`, elevation: 0) to guarantee completion.

### 3. Output Artifact
Generates the fully populated `level_plan.json` conforming strictly to the schema in `ARCHITECTURE.md`.
