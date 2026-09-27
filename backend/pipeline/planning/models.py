"""
Pydantic models for the Room Topology Graph contract (ARCHITECTURE.md 6.2),
used as the Gemini response schema for the Spatial Topology Planner Agent
(4.1.1) and to validate its output.

Adaptation for Gemini structured output: ``style_distribution`` is a list of
``StyleWeight`` (``tile_group``, ``weight``) instead of a free-form map. The
response schema subset ignores ``additionalProperties``: with a
``dict[str, float]`` the model returned ``{}``. Tile groups stay unique, as
map keys were. ``RoomTopologyGraph.style_map()`` gives the map form back.

Two levels of validation:
  * Pydantic validators (catalog-free): unique room ids, corridor endpoints
    exist, exactly one ``entrance`` room, weights 0 to 1, unique tile groups.
  * ``validate_with_catalog(graph, digest)``: the rules that need the catalog
    digest and the planner limits (groups exist, a floor group, 3 to 7 rooms,
    connected corridors, at most 20 enemies). The topology agent sends these
    errors back to the model.
Long ``description`` and ``design_notes`` texts are cut to their limit
instead of failing the whole graph.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from pipeline.planning.catalog_digest import CatalogDigest

RoomPurpose = Literal["entrance", "combat", "puzzle", "boss", "treasure"]
RelativePosition = Literal["north", "south", "east", "west", "center"]
RoomSize = Literal["small", "medium", "large"]
CorridorType = Literal["straight", "winding", "bridge"]

MIN_ROOMS, MAX_ROOMS = 3, 7
MAX_ENEMIES_PER_ROOM, MAX_ENEMIES = 6, 20
MAX_ROOM_DRESSING = 4
ROOM_DESCRIPTION_CHARS, DESIGN_NOTES_CHARS = 120, 400


def _cut(limit: int):
    def cut(value: object) -> object:
        return value[:limit] if isinstance(value, str) else value
    return cut


class StyleWeight(BaseModel):
    tile_group: str = Field(description="A tile group id from the catalog, for example floor.grass")
    weight: float = Field(ge=0, le=1, description="Share of this tile group, 0 to 1")


class Room(BaseModel):
    id: str = Field(description="Unique room id, for example r1")
    purpose: RoomPurpose
    relative_position: RelativePosition
    elevation: int = 0
    size: RoomSize
    enemy_count: int = Field(default=0, ge=0, le=MAX_ENEMIES_PER_ROOM, description="Zombies in this room")
    dressing: list[StyleWeight] = Field(
        default_factory=list, max_length=MAX_ROOM_DRESSING,
        description="Optional tile group weights inside this room; override the global weights",
    )
    description: str = Field(
        default="", max_length=ROOM_DESCRIPTION_CHARS, description="Short room description",
    )

    _cut_description = field_validator("description", mode="before")(_cut(ROOM_DESCRIPTION_CHARS))

    @model_validator(mode="after")
    def _unique_dressing(self) -> Room:
        groups = [s.tile_group for s in self.dressing]
        repeated = sorted({g for g in groups if groups.count(g) > 1})
        if repeated:
            raise ValueError(f"room {self.id}: dressing tile groups must be unique; repeated: {', '.join(repeated)}")
        return self


class Corridor(BaseModel):
    from_room: str = Field(description="Id of a room in rooms")
    to_room: str = Field(description="Id of a room in rooms")
    corridor_type: CorridorType


class RoomTopologyGraph(BaseModel):
    theme: str = Field(description="Short theme id, for example dungeon_crypt")
    design_notes: str = Field(
        default="", max_length=DESIGN_NOTES_CHARS, description="Why this layout fits the prompt",
    )
    style_distribution: list[StyleWeight] = Field(
        min_length=1, description="Global tile group weights for the dressing engine; tile groups are unique",
    )
    rooms: list[Room] = Field(min_length=1)
    corridors: list[Corridor]

    _cut_notes = field_validator("design_notes", mode="before")(_cut(DESIGN_NOTES_CHARS))

    @model_validator(mode="after")
    def _check_graph(self) -> RoomTopologyGraph:
        ids = [room.id for room in self.rooms]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"room ids must be unique; duplicated: {', '.join(duplicates)}")
        known = set(ids)
        for c in self.corridors:
            for end in (c.from_room, c.to_room):
                if end not in known:
                    raise ValueError(f"corridor {c.from_room} -> {c.to_room} uses unknown room {end!r}")
        entrances = sum(1 for room in self.rooms if room.purpose == "entrance")
        if entrances != 1:
            raise ValueError(f"exactly one room must have purpose 'entrance'; found {entrances}")
        groups = [s.tile_group for s in self.style_distribution]
        repeated = sorted({g for g in groups if groups.count(g) > 1})
        if repeated:
            raise ValueError(f"style_distribution tile groups must be unique; repeated: {', '.join(repeated)}")
        return self

    def style_map(self) -> dict[str, float]:
        """``style_distribution`` in the map form of ARCHITECTURE.md 6.2."""
        return {s.tile_group: s.weight for s in self.style_distribution}

    @property
    def entrance(self) -> Room:
        return next(r for r in self.rooms if r.purpose == "entrance")

    def neighbors(self) -> dict[str, list[str]]:
        """Corridor graph as adjacency lists (undirected), in corridor order."""
        adjacency: dict[str, list[str]] = {r.id: [] for r in self.rooms}
        for c in self.corridors:
            if c.to_room not in adjacency[c.from_room]:
                adjacency[c.from_room].append(c.to_room)
            if c.from_room not in adjacency[c.to_room]:
                adjacency[c.to_room].append(c.from_room)
        return adjacency

    def graph_distances(self, start: str) -> dict[str, int]:
        """Corridor hops from ``start`` to every reachable room."""
        adjacency, dist = self.neighbors(), {start: 0}
        queue = deque([start])
        while queue:
            room = queue.popleft()
            for nxt in adjacency[room]:
                if nxt not in dist:
                    dist[nxt] = dist[room] + 1
                    queue.append(nxt)
        return dist


def validate_with_catalog(graph: RoomTopologyGraph, digest: CatalogDigest) -> list[dict]:
    """
    Planner rules that need the catalog digest. Returns structured errors
    ``[{check, detail}]`` (empty when the graph is valid).
    """
    errors: list[dict] = []

    def fail(check: str, detail: str) -> None:
        errors.append({"check": check, "detail": detail})

    known = digest.by_id
    for s in graph.style_distribution:
        if s.tile_group not in known:
            fail("tile_group_exists", f"style_distribution uses unknown tile group {s.tile_group!r}")
    for room in graph.rooms:
        for s in room.dressing:
            if s.tile_group not in known:
                fail("tile_group_exists", f"room {room.id} dressing uses unknown tile group {s.tile_group!r}")
    if not any(s.tile_group in known and known[s.tile_group].is_floor for s in graph.style_distribution):
        fail("floor_group", "style_distribution needs at least one floor.* tile group")

    if not MIN_ROOMS <= len(graph.rooms) <= MAX_ROOMS:
        fail("room_count", f"{len(graph.rooms)} rooms; use {MIN_ROOMS} to {MAX_ROOMS}")

    reached = graph.graph_distances(graph.entrance.id)
    missing = [r.id for r in graph.rooms if r.id not in reached]
    if missing:
        fail("corridors_connected", f"rooms not connected to the entrance by corridors: {', '.join(missing)}")

    total = sum(r.enemy_count for r in graph.rooms)
    if total > MAX_ENEMIES:
        fail("enemy_total", f"{total} enemies in total; use at most {MAX_ENEMIES}")
    return errors
