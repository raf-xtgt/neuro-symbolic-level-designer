"""Validators of the Room Topology Graph models (pipeline/planning/models.py)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.planning.models import RoomTopologyGraph


def _graph(**changes) -> dict:
    graph = {
        "theme": "graveyard",
        "style_distribution": [{"tile_group": "grass", "weight": 0.7}, {"tile_group": "stone", "weight": 0.3}],
        "rooms": [
            {"id": "a", "purpose": "entrance", "relative_position": "south", "size": "small"},
            {"id": "b", "purpose": "combat", "relative_position": "center", "size": "medium"},
            {"id": "c", "purpose": "boss", "relative_position": "north", "size": "large"},
        ],
        "corridors": [
            {"from_room": "a", "to_room": "b", "corridor_type": "straight"},
            {"from_room": "b", "to_room": "c", "corridor_type": "winding"},
        ],
    }
    graph.update(changes)
    return graph


def test_valid_graph():
    graph = RoomTopologyGraph.model_validate(_graph())
    assert graph.rooms[0].elevation == 0
    assert graph.style_map() == {"grass": 0.7, "stone": 0.3}


def test_duplicate_room_ids():
    rooms = _graph()["rooms"]
    rooms[2]["id"] = "b"
    with pytest.raises(ValidationError, match="unique; duplicated: b"):
        RoomTopologyGraph.model_validate(_graph(rooms=rooms))


def test_unknown_corridor_endpoint():
    corridors = [{"from_room": "a", "to_room": "z", "corridor_type": "bridge"}]
    with pytest.raises(ValidationError, match="unknown room 'z'"):
        RoomTopologyGraph.model_validate(_graph(corridors=corridors))


@pytest.mark.parametrize("purposes,found", [(["combat", "combat", "boss"], 0), (["entrance", "entrance", "boss"], 2)])
def test_exactly_one_entrance(purposes, found):
    rooms = _graph()["rooms"]
    for room, purpose in zip(rooms, purposes):
        room["purpose"] = purpose
    with pytest.raises(ValidationError, match=f"exactly one room .* found {found}"):
        RoomTopologyGraph.model_validate(_graph(rooms=rooms))


@pytest.mark.parametrize("weight", [-0.1, 1.5])
def test_weights_between_0_and_1(weight):
    style = [{"tile_group": "grass", "weight": weight}]
    with pytest.raises(ValidationError, match="weight"):
        RoomTopologyGraph.model_validate(_graph(style_distribution=style))


def test_tile_groups_are_unique():
    style = [{"tile_group": "grass", "weight": 0.5}, {"tile_group": "grass", "weight": 0.5}]
    with pytest.raises(ValidationError, match="repeated: grass"):
        RoomTopologyGraph.model_validate(_graph(style_distribution=style))


def test_enums_from_the_contract():
    rooms = _graph()["rooms"]
    rooms[1]["purpose"] = "shop"
    with pytest.raises(ValidationError, match="purpose"):
        RoomTopologyGraph.model_validate(_graph(rooms=rooms))
    corridors = [{"from_room": "a", "to_room": "b", "corridor_type": "chokepoint"}]
    with pytest.raises(ValidationError, match="corridor_type"):
        RoomTopologyGraph.model_validate(_graph(corridors=corridors))
