#!/usr/bin/env python3
"""
A* Pathfinding and Geometry Validator for Isometric Levels in IBM Bob.
"""

import argparse
import heapq
import json
import sys

def astar(grid, start, goal):
    """Simple A* pathfinding on 2D grid where >0 is walkable."""
    height = len(grid)
    width = len(grid[0])

    def heuristic(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    open_set = []
    heapq.heappush(open_set, (0, start))
    came_from = {}
    g_score = {start: 0}
    f_score = {start: heuristic(start, goal)}

    while open_set:
        _, current = heapq.heappop(open_set)
        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            return path[::-1]

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            neighbor = (current[0] + dx, current[1] + dy)
            nx, ny = neighbor
            if 0 <= ny < height and 0 <= nx < width:
                # Walkable check (must be ground and not wall)
                if grid[ny][nx] > 0:
                    tentative = g_score[current] + 1
                    if tentative < g_score.get(neighbor, float('inf')):
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative
                        f_score[neighbor] = tentative + heuristic(neighbor, goal)
                        heapq.heappush(open_set, (f_score[neighbor], neighbor))
    return None

def validate_plan(plan_path):
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    ground_layer = next((l for l in plan["layers"] if l["name"] == "Ground"), None)
    if not ground_layer:
        return {"valid": False, "error": "Missing Ground layer"}

    grid = ground_layer["grid"]
    objects = plan.get("objects", [])

    player = next((o for o in objects if o.get("type") == "PlayerSpawn"), None)
    enemy = next((o for o in objects if o.get("type") in ["Enemy", "Boss"]), None)

    summary = {
        "valid": True,
        "total_tiles": sum(1 for row in grid for cell in row if cell > 0),
        "total_entities": len(objects),
        "pathfinding_verified": False,
        "issues": []
    }

    if player and enemy:
        # Convert coords to grid cells
        p_cell = (int(player["x"] // 64), int(player["y"] // 32))
        e_cell = (int(enemy["x"] // 64), int(enemy["y"] // 32))

        # Check bounds
        h, w = len(grid), len(grid[0])
        if 0 <= p_cell[1] < h and 0 <= p_cell[0] < w and 0 <= e_cell[1] < h and 0 <= e_cell[0] < w:
            path = astar(grid, p_cell, e_cell)
            if path is not None:
                summary["pathfinding_verified"] = True
                summary["path_length"] = len(path)
            else:
                summary["valid"] = False
                summary["issues"].append("No valid path between PlayerSpawn and Enemy/Objective.")

    print(json.dumps(summary, indent=2))
    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate level plan")
    parser.add_argument("--level-plan", required=True, help="Path to level_plan.json")
    args = parser.parse_args()
    validate_plan(args.level_plan)
