---
name: level-validator
description: Audits generated isometric maps for playability, A* pathfinding connectivity, and entity placement constraints.
---

# Level Validator Skill

## Overview
This skill acts as the deterministic quality gate before map export.
It checks:
1. **A\* Pathfinding Check:** An uninterrupted walkable path exists between `PlayerSpawn` and the level exit/objectives.
2. **Collision Overlap Check:** No entity or item spawns inside a solid wall hitbox.
3. **Asset Availability Check:** Every placed tile index exists in the provided tileset or asset catalog.
4. **Boundary Integrity Check:** All walkable rooms are bounded by impassable walls or barriers.

---

## Usage Instructions for IBM Bob
```bash
python3 .bob/skills/level-validator/scripts/validate_level.py \
  --level-plan <path_to_level_plan.json>
```

Outputs a JSON validation report (`summary.json`) with pass/fail status and pathfinding distance.
