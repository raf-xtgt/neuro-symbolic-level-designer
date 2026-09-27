"""
Deterministic constraint validator (Pipeline 2, ARCHITECTURE.md 4.2).

All movement checks use the movement rule of ``pathing.py`` (the same rule
as the game): 8 directions, no corner cutting, blocked = a non-walkable tile.

Checks (``name``):
  * ``ids_exist``          every placed id exists in the catalog
  * ``entities_walkable``  every entity is inside the map on a walkable cell
  * ``path_spawn_exit``    a path from PlayerSpawn to ExitTrigger
  * ``rooms_reachable``    every room has a cell reachable from the spawn
  * ``boundary_integrity`` no cell reachable from the spawn on the outermost
                           ring; unreachable open cells (the front zone behind
                           the hedge) are fine (skipped with a warning when the
                           catalog has no blocking tiles)
  * ``rooms_layout``       rooms inside the map and not overlapping

Report: ``{passed, checks: [{name, passed, detail}], warnings}``.
"""
from __future__ import annotations

from pipeline.planning.layout import RoomRect
from pipeline.planning.pathing import Cell, reachable, shortest_path

CHECKS = (
    "ids_exist", "entities_walkable", "path_spawn_exit", "rooms_reachable", "boundary_integrity", "rooms_layout",
)


def validate_plan(plan: dict, catalog: dict, rooms: dict[str, RoomRect]) -> dict:
    props = plan["map_properties"]
    width, height = props["width"], props["height"]
    walkable = {t["id"]: t["walkable"] for t in catalog["tiles"]}
    has_blocking = not all(walkable.values())
    layers = plan["layers"]
    checks: list[dict] = []
    warnings: list[str] = []

    def check(name: str, problems: list[str], ok_detail: str) -> None:
        shown = "; ".join(problems[:5]) + (f"; and {len(problems) - 5} more" if len(problems) > 5 else "")
        checks.append({"name": name, "passed": not problems, "detail": shown if problems else ok_detail})

    # Blocked cells as (row, col), as pathing.py expects. Unknown ids block.
    blocked: set[Cell] = set()
    unknown: list[str] = []
    for index, layer in enumerate(layers):
        for r, row in enumerate(layer["grid"]):
            for c, tile_id in enumerate(row):
                if index > 0 and tile_id == 0:
                    continue
                if tile_id not in walkable:
                    unknown.append(f"id {tile_id} at ({c}, {r}) in {layer['name']}")
                    blocked.add((r, c))
                elif not walkable[tile_id]:
                    blocked.add((r, c))
    check("ids_exist", unknown, "every placed id is in the catalog")

    entities = plan["objects"]
    problems = []
    for o in entities:
        c, r = o["col"], o["row"]
        if not (0 <= c < width and 0 <= r < height):
            problems.append(f"{o['name']} at ({c}, {r}) is outside the map")
        elif (r, c) in blocked:
            problems.append(f"{o['name']} at ({c}, {r}) is on a blocked cell")
    check("entities_walkable", problems, f"{len(entities)} entities on walkable cells")

    ends = {o["type"]: (o["row"], o["col"]) for o in entities if o["type"] in ("PlayerSpawn", "ExitTrigger")}
    spawn = ends.get("PlayerSpawn")
    if spawn is None or "ExitTrigger" not in ends:
        check("path_spawn_exit", ["PlayerSpawn or ExitTrigger is missing"], "")
    else:
        path = shortest_path(width, height, blocked, spawn, ends["ExitTrigger"])
        check(
            "path_spawn_exit",
            [] if path else ["no path from PlayerSpawn to ExitTrigger"],
            f"path of {len(path) - 1 if path else 0} steps",
        )

    seen = reachable(width, height, blocked, spawn) if spawn else set()
    unreachable = [
        f"room {rid} unreachable" for rid, rect in rooms.items()
        if not any((r, c) in seen for c, r in rect.cells())
    ]
    check("rooms_reachable", unreachable, f"all {len(rooms)} rooms reachable from the spawn")

    if has_blocking:
        ring = {(r, c) for r in range(height) for c in range(width) if r in (0, height - 1) or c in (0, width - 1)}
        open_ring = sorted(ring & seen)
        check(
            "boundary_integrity",
            [f"{len(open_ring)} reachable cells on the map edge, first at ({open_ring[0][1]}, {open_ring[0][0]})"]
            if open_ring else [],
            "no cell on the map edge is reachable from the spawn",
        )
    else:
        checks.append({"name": "boundary_integrity", "passed": True, "detail": "skipped: no blocking tiles"})
        warnings.append("boundary integrity not checked: the catalog has no blocking tiles; the map edge is the boundary")

    problems = [
        f"room {rid} is outside the map" for rid, rect in rooms.items()
        if rect.col < 0 or rect.row < 0 or rect.col + rect.w > width or rect.row + rect.h > height
    ]
    items = list(rooms.values())
    problems += [
        f"rooms {a.id} and {b.id} overlap"
        for i, a in enumerate(items) for b in items[i + 1:] if a.gap_to(b) < 0
    ]
    check("rooms_layout", problems, f"{len(rooms)} rooms inside the map, no overlap")

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "warnings": warnings}


def failed_checks(report: dict) -> list[dict]:
    return [c for c in report["checks"] if not c["passed"]]
