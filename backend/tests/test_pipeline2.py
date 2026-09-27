"""
Pipeline 2 deterministic parts: catalog digest, catalog-context topology
validation, layout builder (property tests), spawner, dressing, validator.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pipeline.llm.fake import FakeProvider
from pipeline.planning.catalog_digest import build_digest
from pipeline.planning.dressing import (
    CLUSTER_SIZE, LOW_FAMILIES, PILLAR_DEPTH, SHORT_DEPTH, _clearance_depth, _hedge, dress,
)
from pipeline.planning.graph import plan_with_llm
from pipeline.planning.layout import GAP, MARGIN, MAX_MAP, MIN_MAP, LayoutError, RoomRect, build_layout
from pipeline.planning.models import RoomTopologyGraph, StyleWeight, validate_with_catalog
from pipeline.planning.pathing import reachable
from pipeline.planning.spawner import MIN_SPAWN_DISTANCE, chebyshev, place_entities
from pipeline.planning.validator import CHECKS, validate_plan

BACKEND_DIR = Path(__file__).parent.parent
FULL = json.loads((BACKEND_DIR / "asset_packs" / "grassland_full" / "asset_catalog.json").read_text())
STARTER = json.loads((BACKEND_DIR / "fixtures" / "starter" / "asset_catalog.json").read_text())
FULL_DIGEST, STARTER_DIGEST = build_digest(FULL), build_digest(STARTER)

GRAVEYARD_STYLE = [
    {"tile_group": "floor.grass", "weight": 0.7}, {"tile_group": "floor.stone", "weight": 0.3},
    {"tile_group": "obstacle.gravestone", "weight": 0.5}, {"tile_group": "obstacle.tree_dead", "weight": 0.4},
    {"tile_group": "decoration.dry_grass", "weight": 0.3},
]


def topology(rooms: list[tuple], corridors: list[tuple], style=None, **extra) -> RoomTopologyGraph:
    """rooms: (id, purpose, position, size[, enemies]); corridors: (from, to, type)."""
    return RoomTopologyGraph.model_validate({
        "theme": "test",
        "style_distribution": style or GRAVEYARD_STYLE,
        "rooms": [
            {"id": r[0], "purpose": r[1], "relative_position": r[2], "size": r[3],
             "enemy_count": r[4] if len(r) > 4 else 0, **extra.get(r[0], {})}
            for r in rooms
        ],
        "corridors": [{"from_room": a, "to_room": b, "corridor_type": t} for a, b, t in corridors],
    })


# A set of hand-made topologies: 3 to 7 rooms, every bearing, every corridor type.
TOPOLOGIES = {
    "three_line": topology(
        [("e", "entrance", "south", "small"), ("c", "combat", "center", "medium", 3), ("b", "boss", "north", "large", 4)],
        [("e", "c", "straight"), ("c", "b", "winding")],
    ),
    "four_compass": topology(
        [("e", "entrance", "west", "medium"), ("c", "combat", "center", "large", 5),
         ("t", "treasure", "east", "small", 1), ("p", "puzzle", "north", "medium", 2)],
        [("e", "c", "bridge"), ("c", "t", "winding"), ("c", "p", "straight")],
    ),
    "five_same_bearing": topology(
        [("e", "entrance", "south", "small"), ("n1", "combat", "north", "small", 2),
         ("n2", "combat", "north", "medium", 3), ("n3", "boss", "north", "medium", 4),
         ("w", "treasure", "west", "small", 1)],
        [("e", "n1", "winding"), ("n1", "n2", "straight"), ("n2", "n3", "winding"), ("e", "w", "bridge")],
    ),
    "six_ring": topology(
        [("e", "entrance", "south", "small"), ("a", "combat", "east", "small", 2), ("b", "puzzle", "north", "small", 1),
         ("c", "combat", "west", "small", 3), ("d", "treasure", "center", "small", 1), ("f", "boss", "north", "medium", 5)],
        [("e", "a", "straight"), ("a", "b", "winding"), ("b", "c", "straight"), ("c", "e", "winding"),
         ("e", "d", "straight"), ("b", "f", "winding")],
    ),
    "seven_star": topology(
        [("e", "entrance", "center", "small"), ("n", "combat", "north", "small", 2), ("s", "combat", "south", "small", 2),
         ("w", "puzzle", "west", "small", 1), ("x", "treasure", "east", "small", 1),
         ("n2", "combat", "north", "small", 2), ("b", "boss", "east", "medium", 5)],
        [("e", "n", "straight"), ("e", "s", "winding"), ("e", "w", "bridge"), ("e", "x", "straight"),
         ("n", "n2", "winding"), ("x", "b", "straight")],
    ),
    "center_pair": topology(
        [("e", "entrance", "center", "medium"), ("c", "combat", "center", "medium", 3),
         ("b", "boss", "south", "large", 4)],
        [("e", "c", "winding"), ("c", "b", "straight")],
    ),
}


# ---------------------------------------------------------------------------
# Catalog digest
# ---------------------------------------------------------------------------

def test_digest_grassland_full():
    ids = [g.id for g in FULL_DIGEST.groups]
    assert ids[:2] == ["floor.grass", "floor.stone"]
    assert {"obstacle.gravestone", "obstacle.rock_pillar", "obstacle.tree_dead", "decoration.flower"} <= set(ids)
    assert not any("fence" in i or i.startswith(("wall.", "water.")) for i in ids)
    by_id = FULL_DIGEST.by_id
    gravestone = by_id["obstacle.gravestone"]
    assert (gravestone.count, gravestone.walkable, gravestone.tall) == (4, False, True)
    assert gravestone.description == "obstacle.gravestone: 4 gravestones and stone crosses, blocks movement, tall"
    assert by_id["decoration.bush"].walkable and by_id["floor.stone"].tile_ids == tuple(range(16, 32))
    placed = {i for g in FULL_DIGEST.groups for i in g.tile_ids}
    fences = {t["id"] for t in FULL["tiles"] if "fence" in t.get("tags", [])}
    autotiles = {t["id"] for t in FULL["tiles"] if "autotile_required" in t.get("tags", [])}
    assert fences and autotiles and not placed & (fences | autotiles)
    assert len(ids) == 22 and FULL_DIGEST.has_blocking


def test_digest_grassland_starter():
    assert [g.id for g in STARTER_DIGEST.groups] == ["floor.grass", "floor.stone"]
    assert not STARTER_DIGEST.has_blocking


def test_digest_fallback_to_material():
    catalog = {"tiles": [
        {"id": 0, "category": "floor", "walkable": True, "material": "sand"},
        {"id": 1, "category": "obstacle", "walkable": False, "material": "crystal", "tags": ["prop"]},
    ]}
    assert [g.id for g in build_digest(catalog).groups] == ["floor.sand", "obstacle.crystal"]


# ---------------------------------------------------------------------------
# Topology validation with catalog context
# ---------------------------------------------------------------------------

def _checks(graph: RoomTopologyGraph, digest=FULL_DIGEST) -> set[str]:
    return {e["check"] for e in validate_with_catalog(graph, digest)}


def test_valid_topologies_pass():
    for graph in TOPOLOGIES.values():
        assert validate_with_catalog(graph, FULL_DIGEST) == []


def test_unknown_tile_group():
    graph = topology(*_three(), style=[{"tile_group": "floor.grass", "weight": 1}, {"tile_group": "gravestones", "weight": 1}])
    errors = validate_with_catalog(graph, FULL_DIGEST)
    assert errors == [{"check": "tile_group_exists", "detail": "style_distribution uses unknown tile group 'gravestones'"}]
    room_dressing = topology(*_three(), e={"dressing": [{"tile_group": "obstacle.fence", "weight": 1}]})
    assert _checks(room_dressing) == {"tile_group_exists"}


def test_no_floor_group():
    graph = topology(*_three(), style=[{"tile_group": "obstacle.gravestone", "weight": 1}])
    assert _checks(graph) == {"floor_group"}
    # Starter pack: obstacle groups do not exist there.
    assert _checks(TOPOLOGIES["three_line"], STARTER_DIGEST) == {"tile_group_exists"}


def test_disconnected_corridors():
    rooms, _ = _three()
    assert _checks(topology(rooms, [("e", "c", "straight")])) == {"corridors_connected"}


def test_too_many_enemies_and_rooms():
    rooms = [("e", "entrance", "south", "small")] + [(f"r{i}", "combat", "north", "small", 6) for i in range(4)]
    corridors = [("e", f"r{i}", "straight") for i in range(4)]
    assert _checks(topology(rooms, corridors)) == {"enemy_total"}
    rooms = [("e", "entrance", "south", "small")] + [(f"r{i}", "combat", "north", "small") for i in range(7)]
    assert _checks(topology(rooms, [("e", f"r{i}", "straight") for i in range(7)])) == {"room_count"}
    assert _checks(topology(rooms[:2], [("e", "r0", "straight")])) == {"room_count"}


def _three():
    return (
        [("e", "entrance", "south", "small"), ("c", "combat", "center", "medium", 2), ("b", "boss", "north", "large", 3)],
        [("e", "c", "straight"), ("c", "b", "straight")],
    )


# ---------------------------------------------------------------------------
# Layout builder: property tests
# ---------------------------------------------------------------------------

def _corridor_connects(layout, corridor) -> bool:
    """Corridor cells plus both rooms form one walkable region (movement rule)."""
    a, b = layout.rooms[corridor.from_room], layout.rooms[corridor.to_room]
    cells = set(corridor.cells) | set(a.cells()) | set(b.cells())
    blocked = {(r, c) for c in range(layout.width) for r in range(layout.height)} - {(r, c) for c, r in cells}
    start = a.center
    seen = reachable(layout.width, layout.height, blocked, (start[1], start[0]))
    touches_a = any(a.contains(c) for c in corridor.cells)
    touches_b = any(b.contains(c) for c in corridor.cells)
    return touches_a and touches_b and (b.center[1], b.center[0]) in seen


@pytest.mark.parametrize("name", sorted(TOPOLOGIES))
def test_layout_properties_over_200_seeds(name):
    graph = TOPOLOGIES[name]
    bends = set()
    for seed in range(200):
        layout = build_layout(graph, seed)
        assert MIN_MAP <= layout.width <= MAX_MAP and MIN_MAP <= layout.height <= MAX_MAP
        rooms = list(layout.rooms.values())
        assert [r.id for r in rooms] == [r.id for r in graph.rooms]
        for room in rooms:
            assert room.col >= MARGIN and room.row >= MARGIN, (seed, room)
            assert room.col + room.w <= layout.width - MARGIN and room.row + room.h <= layout.height - MARGIN
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                assert a.gap_to(b) >= GAP, (seed, a, b)
        for cell in layout.corridor_cells:
            assert MARGIN <= cell[0] < layout.width - MARGIN and MARGIN <= cell[1] < layout.height - MARGIN
        for corridor, planned in zip(layout.corridors, graph.corridors):
            assert (corridor.from_room, corridor.to_room) == (planned.from_room, planned.to_room)
            assert _corridor_connects(layout, corridor), (seed, corridor.from_room, corridor.to_room)
            if corridor.corridor_type == "winding":
                bends.add(corridor.bends)
                assert corridor.bends >= 2 or _aligned(layout, corridor), (seed, corridor.bends)
            elif corridor.corridor_type in ("straight", "bridge"):
                assert corridor.bends <= 1
    if any(c.corridor_type == "winding" for c in graph.corridors):
        assert bends & {2, 3}


def _aligned(layout, corridor) -> bool:
    (c0, r0), (c1, r1) = layout.rooms[corridor.from_room].center, layout.rooms[corridor.to_room].center
    return abs(c1 - c0) < 2 and abs(r1 - r0) < 2


def test_layout_is_deterministic_per_seed():
    graph = TOPOLOGIES["four_compass"]
    assert build_layout(graph, 5).as_dict() == build_layout(graph, 5).as_dict()
    assert any(build_layout(graph, 5).as_dict() != build_layout(graph, s).as_dict() for s in range(6, 10))


def test_bearings_are_screen_directions():
    layout = build_layout(TOPOLOGIES["four_compass"], 0)
    center = layout.rooms["c"].center

    def screen(cell):  # screen x ~ col - row, screen y ~ col + row
        return cell[0] - cell[1] - (center[0] - center[1]), cell[0] + cell[1] - (center[0] + center[1])

    assert screen(layout.rooms["p"].center)[1] < 0  # north: up
    assert screen(layout.rooms["e"].center)[0] < 0  # west: left
    assert screen(layout.rooms["t"].center)[0] > 0  # east: right


def test_bridge_is_straight_with_a_warning():
    layout = build_layout(TOPOLOGIES["four_compass"], 1)
    assert any("bridge" in w for w in layout.warnings)


def test_too_large_layout_is_not_layout_fixable():
    rooms = [("e", "entrance", "south", "large")] + [(f"n{i}", "combat", "north", "large") for i in range(6)]
    graph = topology(rooms, [("e", "n0", "straight")] + [(f"n{i}", f"n{i + 1}", "straight") for i in range(5)])
    with pytest.raises(LayoutError) as info:
        build_layout(graph, 0)
    assert (info.value.check, info.value.fixable) == ("map_size", False)


# ---------------------------------------------------------------------------
# Spawner and dressing
# ---------------------------------------------------------------------------

def _plan(graph, seed: int, catalog=FULL):
    return plan_with_llm("test", catalog, seed, FakeProvider([graph]))


@pytest.mark.parametrize("name", sorted(TOPOLOGIES))
def test_spawner_and_dressing(name):
    graph = TOPOLOGIES[name]
    walkable = {t["id"]: t["walkable"] for t in FULL["tiles"]}
    for seed in range(8):
        outcome = _plan(graph, seed)
        plan, layout = outcome.plan, outcome.layout
        ground, objects = plan["layers"][0]["grid"], plan["layers"][1]["grid"]
        ents = {o["type"]: (o["col"], o["row"]) for o in plan["objects"] if o["type"] != "Zombie"}
        zombies = [(o["col"], o["row"]) for o in plan["objects"] if o["type"] == "Zombie"]
        spawn, exit_ = ents["PlayerSpawn"], ents["ExitTrigger"]

        assert spawn == layout.rooms[graph.entrance.id].center
        assert len(zombies) == sum(r.enemy_count for r in graph.rooms)
        assert len(set(zombies) | {spawn, exit_}) == len(zombies) + 2
        for c, r in [spawn, exit_, *zombies]:
            assert walkable[ground[r][c]] and objects[r][c] == 0
        assert all(chebyshev(z, spawn) >= MIN_SPAWN_DISTANCE for z in zombies)
        for c0, r0 in (spawn, exit_):  # neighborhoods clear
            assert all(objects[r0 + dr][c0 + dc] == 0 for dc in (-1, 0, 1) for dr in (-1, 0, 1))
        for room in graph.rooms:  # boss center 3 x 3 clear
            if room.purpose == "boss":
                cc, cr = layout.rooms[room.id].center
                assert all(objects[cr + dr][cc + dc] == 0 for dc in (-1, 0, 1) for dr in (-1, 0, 1))
        for c, r in layout.corridor_cells:
            assert objects[r][c] == 0
        # The hedge encloses the playable area: nothing outside the rooms and
        # corridors is reachable. Low blockers in front, open front zone.
        playable = layout.playable_cells
        depth = _clearance_depth(playable)
        hedge = _hedge(playable, layout.width, layout.height, depth)
        low = {i for g in FULL_DIGEST.groups if g.family in LOW_FAMILIES for i in g.tile_ids}
        front: dict = {}
        for r in range(layout.height):
            for c in range(layout.width):
                if (c, r) in playable:
                    continue
                tile, d = objects[r][c], depth.get((c, r))
                if (c, r) in hedge:
                    assert tile and not walkable[tile], (seed, c, r)
                    if d is not None and d <= SHORT_DEPTH:
                        assert tile in low, (seed, c, r)
                        assert any((c + dc, r + dr) in playable for dc in (-1, 0, 1) for dr in (-1, 0, 1))
                        front[(c, r)] = tile
                elif d is not None:
                    assert tile == 0 or walkable[tile], (seed, c, r)
                else:
                    assert tile and not walkable[tile], (seed, c, r)
        for (c, r), tile in front.items():  # no identical variants side by side along the front hedge
            assert all(front.get((c + dc, r + dr)) != tile for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0))
        blocked = {(r, c) for r, row in enumerate(objects) for c, v in enumerate(row) if v and not walkable[v]}
        seen = reachable(layout.width, layout.height, blocked, (spawn[1], spawn[0]))
        assert {(c, r) for r, c in seen} <= playable
        assert outcome.report["passed"]


def test_exit_prefers_the_boss_room_on_ties():
    # r3 (east) and r4 (boss, north) are both 2 corridor hops from the entrance.
    graph = topology(
        [("r1", "entrance", "south", "medium"), ("r2", "combat", "center", "medium", 2),
         ("r3", "combat", "east", "small", 1), ("r4", "boss", "north", "large", 3)],
        [("r1", "r2", "winding"), ("r2", "r3", "straight"), ("r2", "r4", "winding")],
    )
    for seed in range(20):
        assert place_entities(graph, build_layout(graph, seed), seed).exit_room == "r4"


def test_corridor_guard_stays_near_its_room():
    graph = topology(
        [("e", "entrance", "south", "medium"), ("p", "combat", "center", "large", 6), ("t", "treasure", "north", "medium")],
        [("e", "p", "straight"), ("p", "t", "straight")],
    )
    for seed in range(20):
        layout = build_layout(graph, seed)
        placement = place_entities(graph, layout, seed)
        rect = layout.rooms["p"]
        guards = [cell for where, cell in placement.zombies if where.startswith("corridor:")]
        assert len(placement.zombies) == 6 and len(guards) == 1
        grown = RoomRect("g", rect.col - 2, rect.row - 2, rect.w + 4, rect.h + 4)
        assert grown.contains(guards[0]) and not rect.contains(guards[0])


def test_starter_pack_works_without_obstacles():
    graph = topology(*_three(), style=[{"tile_group": "floor.grass", "weight": 0.8}, {"tile_group": "floor.stone", "weight": 0.2}])
    outcome = _plan(graph, 3, catalog=STARTER)
    assert outcome.report["passed"]
    assert all(v == 0 for row in outcome.plan["layers"][1]["grid"] for v in row)
    assert any("no blocking obstacles" in w for w in outcome.warnings)
    boundary = next(c for c in outcome.report["checks"] if c["name"] == "boundary_integrity")
    assert boundary["detail"].startswith("skipped")


def test_room_dressing_overrides_global_floors():
    graph = topology(*_three(), c={"dressing": [{"tile_group": "floor.stone", "weight": 1.0}]})
    outcome = _plan(graph, 1)
    ground, rect = outcome.plan["layers"][0]["grid"], outcome.layout.rooms["c"]
    stone = FULL_DIGEST.by_id["floor.stone"].tile_ids
    assert all(ground[r][c] in stone for c, r in rect.cells())


def test_dressing_is_deterministic():
    graph = TOPOLOGIES["six_ring"]
    layout = build_layout(graph, 4)
    placement = place_entities(graph, layout, 4)
    a = dress(graph, layout, placement, FULL_DIGEST, 4)
    b = dress(graph, layout, placement, FULL_DIGEST, 4)
    assert (a.ground, a.objects) == (b.ground, b.objects)


# ---------------------------------------------------------------------------
# Validator: one crafted failing plan per check
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def good():
    outcome = _plan(TOPOLOGIES["three_line"], 11)
    assert outcome.report["passed"]
    assert [c["name"] for c in outcome.report["checks"]] == list(CHECKS)
    return outcome


def _failing(report: dict) -> set[str]:
    return {c["name"] for c in report["checks"] if not c["passed"]}


def _entity(plan, kind):
    return next(o for o in plan["objects"] if o["type"] == kind)


ROCK = next(t["id"] for t in FULL["tiles"] if t["name"] == "rocks_04")
FLOWER = next(t["id"] for t in FULL["tiles"] if t["name"] == "shrubs_and_grass_tufts_06")


def test_validator_ids_exist(good):
    plan = copy.deepcopy(good.plan)
    plan["layers"][0]["grid"][5][5] = 999
    assert _failing(validate_plan(plan, FULL, good.layout.rooms)) == {"ids_exist"}


def test_validator_entities_walkable(good):
    plan = copy.deepcopy(good.plan)
    zombie = _entity(plan, "Zombie")
    plan["layers"][1]["grid"][zombie["row"]][zombie["col"]] = ROCK
    assert "entities_walkable" in _failing(validate_plan(plan, FULL, good.layout.rooms))
    plan = copy.deepcopy(good.plan)
    _entity(plan, "Zombie")["col"] = 999
    assert _failing(validate_plan(plan, FULL, good.layout.rooms)) == {"entities_walkable"}


def test_validator_path_and_room_reachability(good):
    plan = copy.deepcopy(good.plan)
    exit_ = _entity(plan, "ExitTrigger")
    grid = plan["layers"][1]["grid"]
    rect = good.layout.rooms[good.topology.rooms[-1].id]  # the exit room: wall it off
    for c, r in rect.cells():
        if max(abs(c - exit_["col"]), abs(r - exit_["row"])) == 1:
            grid[r][c] = ROCK
    assert _failing(validate_plan(plan, FULL, good.layout.rooms)) == {"path_spawn_exit"}
    for c, r in rect.cells():
        grid[r][c] = ROCK
    grid[exit_["row"]][exit_["col"]] = 0
    for z in (o for o in plan["objects"] if o["type"] == "Zombie"):
        grid[z["row"]][z["col"]] = 0
    assert _failing(validate_plan(plan, FULL, good.layout.rooms)) == {"path_spawn_exit", "rooms_reachable"}


def test_validator_boundary_integrity(good):
    plan = copy.deepcopy(good.plan)
    plan["layers"][1]["grid"][0][3] = FLOWER  # walkable but unreachable edge cell: fine
    assert validate_plan(plan, FULL, good.layout.rooms)["passed"]
    spawn = _entity(plan, "PlayerSpawn")
    for r in range(spawn["row"]):  # open a lane from the spawn to the top edge
        plan["layers"][1]["grid"][r][spawn["col"]] = 0
    report = validate_plan(plan, FULL, good.layout.rooms)
    assert _failing(report) == {"boundary_integrity"}
    assert f"({spawn['col']}, 0)" in next(c["detail"] for c in report["checks"] if c["name"] == "boundary_integrity")


def test_validator_rooms_layout(good):
    rooms = copy.deepcopy(good.layout.rooms)
    ids = list(rooms)
    rooms[ids[1]].col, rooms[ids[1]].row = rooms[ids[0]].col, rooms[ids[0]].row
    assert "rooms_layout" in _failing(validate_plan(good.plan, FULL, rooms))
    rooms = copy.deepcopy(good.layout.rooms)
    rooms[ids[0]].col = good.layout.width - 2
    assert "rooms_layout" in _failing(validate_plan(good.plan, FULL, rooms))


# ---------------------------------------------------------------------------
# Theme polish: prop clusters, style trees, structures
# ---------------------------------------------------------------------------

def _components(cells: set) -> list[set]:
    """8-connected components of (col, row) cells."""
    out, left = [], set(cells)
    while left:
        stack, comp = [left.pop()], set()
        while stack:
            c, r = stack.pop()
            comp.add((c, r))
            for n in [(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)]:
                if n in left:
                    left.discard(n)
                    stack.append(n)
        out.append(comp)
    return out


def _group_of(digest=FULL_DIGEST) -> dict:
    return {i: g.id for g in digest.groups for i in g.tile_ids}


@pytest.mark.parametrize("name", sorted(TOPOLOGIES))
def test_room_props_come_in_clusters(name):
    group_of = _group_of()
    for seed in range(4):
        outcome = _plan(TOPOLOGIES[name], seed)
        objects, layout = outcome.plan["layers"][1]["grid"], outcome.layout
        props = {(c, r) for c, r in layout.room_cells if objects[r][c]}
        for comp in _components(props):
            assert CLUSTER_SIZE[0] <= len(comp) <= CLUSTER_SIZE[1], (seed, comp)
            assert len({group_of[objects[r][c]] for c, r in comp}) == 1


def test_room_dressing_gets_its_own_clusters():
    dressing = {"dressing": [{"tile_group": "floor.grass", "weight": 0.8}, {"tile_group": "obstacle.gravestone", "weight": 1.0}]}
    graph = topology(*_three(), c=dressing)
    gravestones = set(FULL_DIGEST.by_id["obstacle.gravestone"].tile_ids)
    for seed in range(6):
        outcome = _plan(graph, seed)
        objects, rect = outcome.plan["layers"][1]["grid"], outcome.layout.rooms["c"]
        cells = {(c, r) for c, r in rect.cells() if objects[r][c] in gravestones}
        assert len(_components(cells)) >= 2, seed


def test_wilderness_trees_follow_the_style():
    trees = {i: g.id for g in FULL_DIGEST.groups if g.family.startswith("tree_") for i in g.tile_ids}
    for name in ("three_line", "six_ring"):
        outcome = _plan(TOPOLOGIES[name], 2)
        objects, layout = outcome.plan["layers"][1]["grid"], outcome.layout
        depth = _clearance_depth(layout.playable_cells)
        picked = [
            trees[objects[r][c]] for r in range(layout.height) for c in range(layout.width)
            if (c, r) not in layout.playable_cells and (c, r) not in depth and objects[r][c] in trees
        ]
        assert picked and sum(g == "obstacle.tree_dead" for g in picked) / len(picked) >= 0.8


def _with_structures() -> dict:
    catalog = copy.deepcopy(FULL)
    base = next(t for t in catalog["tiles"] if t["name"] == "rocks_04")
    n = len(catalog["tiles"])
    catalog["tiles"] += [
        {**base, "id": n, "name": "house_00", "rect": {**base["rect"], "w": 192},
         "tags": ["house", "tall", "structure", "footprint_3"]},
        {**base, "id": n + 1, "name": "house_01", "tags": ["house", "structure_part"]},
    ]
    return catalog


def test_digest_structure_groups():
    digest = build_digest(_with_structures())
    group = digest.by_id["structure.house"]
    assert group.is_structure and group.footprint == 3 and group.tile_ids == (len(FULL["tiles"]),)
    assert "at most once per room" in group.description
    assert not digest.of_category("obstacle") or all(not g.is_structure for g in digest.of_category("obstacle"))
    assert all(len(FULL["tiles"]) + 1 not in g.tile_ids for g in digest.groups)  # the slice is left out


def test_structure_is_placed_once_on_its_footprint():
    catalog = _with_structures()
    house = len(FULL["tiles"])
    dressing = {"dressing": [{"tile_group": "floor.grass", "weight": 1.0}, {"tile_group": "structure.house", "weight": 1.0},
                             {"tile_group": "obstacle.gravestone", "weight": 0.5}]}
    graph = topology(*_three(), c=dressing)
    for seed in range(6):
        outcome = _plan(graph, seed, catalog=catalog)
        assert outcome.report["passed"]
        objects, layout = outcome.plan["layers"][1]["grid"], outcome.layout
        placed = [(c, r) for r, row in enumerate(objects) for c, v in enumerate(row) if v == house]
        assert len(placed) == 1 and layout.rooms["c"].contains(placed[0])
        c, r = placed[0]
        footprint = [(c - 1, r + 1), (c, r), (c + 1, r - 1)]  # east diagonal, sprite on the middle cell
        assert all(layout.rooms["c"].contains(cell) and cell not in layout.corridor_cells for cell in footprint)
        assert objects[r + 1][c - 1] == 0 and objects[r - 1][c + 1] == 0


def test_low_hedge_families_are_natural():
    assert set(LOW_FAMILIES) == {"rock_small", "stump", "logs"}


def test_hedge_encloses_a_diagonal_front_edge():
    # A staircase room: its front (south-east on screen) edge runs diagonally.
    playable = {(c, r) for r in range(6, 16) for c in range(6, 16) if (c - 6) + (r - 6) <= 12}
    width = height = 24
    depth = _clearance_depth(playable)
    hedge = _hedge(playable, width, height, depth)
    front = {cell for cell in hedge if depth.get(cell, SHORT_DEPTH + 1) <= SHORT_DEPTH}
    assert front and all(  # 1 cell thick in front
        any((c + dc, r + dr) in playable for dc in (-1, 0, 1) for dr in (-1, 0, 1)) for c, r in front
    )
    # Only the hedge blocks; everything else is open. Nothing outside is reachable.
    blocked = {(r, c) for c, r in hedge}
    seen = reachable(width, height, blocked, (10, 10))
    assert {(c, r) for r, c in seen} == playable


# ---------------------------------------------------------------------------
# Small or unusual catalogs (uploads): no trees, one floor family
# ---------------------------------------------------------------------------

def _catalog(tiles: list[tuple[str, str, bool, list[str], int]]) -> dict:
    """tiles: (category, material, walkable, tags, count)."""
    out = []
    for category, material, walkable, tags, count in tiles:
        for _ in range(count):
            out.append({
                "id": len(out), "name": f"{tags[0]}_{len(out)}", "source": "sheet.png", "category": category,
                "walkable": walkable, "material": material, "rect": {"x": 0, "y": 0, "w": 64, "h": 64},
                "anchor": {"x": 32, "y": 48}, "tags": tags,
            })
    return {"tile_size": {"width": 64, "height": 32}, "tiles": out, "entities": FULL["entities"]}


FARM = _catalog([
    ("floor", "grass", True, ["grass"], 3), ("floor", "dirt", True, ["dirt"], 2),
    ("obstacle", "wood", False, ["crate", "prop"], 2), ("obstacle", "plant", False, ["hay_bale", "prop"], 2),
    ("obstacle", "cloth", False, ["sack", "prop"], 1), ("obstacle", "wood", False, ["barn", "structure_part"], 2),
])
LIBRARY = _catalog([
    ("floor", "wood", True, ["wood"], 3),
    ("obstacle", "wood", False, ["bookcase", "prop"], 3), ("obstacle", "wood", False, ["table", "prop"], 2),
    ("decoration", "paper", True, ["book", "prop"], 2), ("obstacle", "stone", False, ["wall", "structure_part"], 2),
])
SMALL_CATALOGS = {
    "farm": (FARM, [{"tile_group": "floor.grass", "weight": 0.7}, {"tile_group": "floor.dirt", "weight": 0.3},
                    {"tile_group": "obstacle.crate", "weight": 0.3}, {"tile_group": "obstacle.hay_bale", "weight": 0.3}]),
    "library": (LIBRARY, [{"tile_group": "floor.wood", "weight": 1.0}, {"tile_group": "obstacle.bookcase", "weight": 0.4},
                          {"tile_group": "obstacle.table", "weight": 0.2}, {"tile_group": "decoration.book", "weight": 0.3}]),
}


@pytest.mark.parametrize("name", sorted(SMALL_CATALOGS))
def test_small_catalogs_make_enclosed_levels(name):
    catalog, style = SMALL_CATALOGS[name]
    digest = build_digest(catalog)
    assert not any(g.family.startswith("tree_") for g in digest.groups)
    parts = {t["id"] for t in catalog["tiles"] if "structure_part" in t["tags"]}
    walkable = {t["id"]: t["walkable"] for t in catalog["tiles"]}
    floors = {i for g in digest.floors for i in g.tile_ids}
    for topo in ("three_line", "four_compass"):
        base = TOPOLOGIES[topo]
        graph = base.model_copy(update={"style_distribution": [StyleWeight(**s) for s in style]})
        for seed in range(4):
            outcome = _plan(graph, seed, catalog=catalog)
            assert outcome.report["passed"], outcome.report
            layout, plan = outcome.layout, outcome.plan
            ground, objects = plan["layers"][0]["grid"], plan["layers"][1]["grid"]
            assert not parts & {v for row in objects for v in row}, "a structure_part was placed"
            playable = layout.playable_cells
            for cell in _hedge(playable, layout.width, layout.height, _clearance_depth(playable)):
                tile = objects[cell[1]][cell[0]]
                assert tile and not walkable[tile], (name, seed, cell)
            blocked = {(r, c) for r, row in enumerate(objects) for c, v in enumerate(row) if v and not walkable[v]}
            spawn = next(o for o in plan["objects"] if o["type"] == "PlayerSpawn")
            seen = reachable(layout.width, layout.height, blocked, (spawn["row"], spawn["col"]))
            assert {(c, r) for r, c in seen} <= playable
            assert all(ground[r][c] in floors for c, r in layout.corridor_cells)
