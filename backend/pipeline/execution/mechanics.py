"""
Entity mechanics agent (Pipeline 3, ARCHITECTURE.md 5.3). Structured output only:
the LLM chooses numbers and a behavior per room, never code (code comes from
the Jinja2 templates in ``codegen.py``).

One ``generate_structured`` call per level: the prompt, the rooms (id,
purpose, description, enemy count) and the entity types in, per room with
enemies ``chase_range_tiles`` (3 to 8), ``step_interval_ms`` (250 to 600,
lower = faster), ``behavior`` and a one-line ``rationale`` out.

This call never fails a level: an ``LLMError`` or an answer with unknown room
ids falls back to ``DEFAULTS`` with a warning. The placeholder planner skips
the call and uses the defaults.

``apply_to_plan`` writes the values as properties of every ``Zombie`` object
of the level plan (6.3 ``objects[].properties``), which the map compiler
turns into Tiled object properties: ``chase_range``, ``step_interval_ms``,
``behavior``, and, with a layout, ``room_id`` and the room rectangle
(``room_col``, ``room_row``, ``room_w``, ``room_h``) for ``patrol_room``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from pipeline.llm.base import LLMError, LLMProvider
from pipeline.llm.usage import UsageTracker
from pipeline.planning.layout import Layout

MECHANICS_VERSION = "1"
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 2048
THINKING_LEVEL = "low"
BEHAVIORS = ("idle_until_near", "patrol_room", "guard_exit")
DEFAULTS = {"chase_range_tiles": 5, "step_interval_ms": 350, "behavior": "idle_until_near"}
ENEMY_TYPES = ("Zombie",)


class RoomMechanics(BaseModel):
    room_id: str = Field(description="Id of a room from the list")
    chase_range_tiles: int = Field(ge=3, le=8, description="Tiles at which the enemies start chasing the player")
    step_interval_ms: int = Field(ge=250, le=600, description="Milliseconds per tile step; lower is faster")
    behavior: Literal["idle_until_near", "patrol_room", "guard_exit"] = Field(
        description="idle_until_near: wait in place; patrol_room: walk around the room; "
                    "guard_exit: stay near the level exit",
    )
    rationale: str = Field(description="One line: why these values fit the room")


class LevelMechanics(BaseModel):
    rooms: list[RoomMechanics] = Field(description="One entry per room that has enemies")


SYSTEM = (
    "You tune enemy behavior for a 2D isometric action game level. The player walks one tile per step. "
    "For every room that has enemies, choose how far away the enemies notice the player (chase_range_tiles, "
    "3 to 8), how fast they walk (step_interval_ms, 250 to 600, lower is faster), and a behavior: "
    "idle_until_near (wait in place), patrol_room (walk around the room), guard_exit (stay near the exit; "
    "use it for the room that holds the exit). Match the design prompt and each room's purpose: boss rooms "
    "are faster and notice earlier, entrance rooms are gentle. Answer only with the JSON object. "
    "Use only the room ids you are given."
)


@dataclass
class MechanicsResult:
    rooms: dict[str, dict]  # room id -> chase_range_tiles, step_interval_ms, behavior, rationale
    source: str  # llm | defaults
    usage: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def for_room(self, room_id: str | None) -> dict:
        return self.rooms.get(room_id or "", DEFAULTS)


def user_prompt(prompt: str, rooms: list[dict], entity_types: list[str], exit_room: str | None) -> str:
    lines = [f"Design prompt: {prompt}", f"Entity types in the level: {', '.join(entity_types)}"]
    if exit_room:
        lines.append(f"The exit is in room {exit_room}.")
    lines.append("Rooms (id, purpose, enemies, description):")
    lines += [
        f"- {r['id']}, {r['purpose']}, {r['enemy_count']} enemies, {r.get('description') or 'no description'}"
        for r in rooms
    ]
    return "\n".join(lines)


def defaults(rooms: list[dict], reason: str | None = None) -> MechanicsResult:
    values = {r["id"]: {**DEFAULTS, "rationale": "default"} for r in rooms if r.get("enemy_count", 0) > 0}
    warnings = [f"entity mechanics: {reason}; default enemy behavior used"] if reason else []
    return MechanicsResult(values, "defaults", {}, warnings)


def generate_mechanics(
    prompt: str, rooms: list[dict], entity_types: list[str], provider: LLMProvider, exit_room: str | None = None,
) -> MechanicsResult:
    """One LLM call; never raises for LLM problems (defaults + warning instead)."""
    with_enemies = [r for r in rooms if r.get("enemy_count", 0) > 0]
    if not with_enemies:
        return MechanicsResult({}, "defaults")
    usage = UsageTracker()
    try:
        result = usage.add(provider.generate_structured(
            LevelMechanics,
            system=SYSTEM,
            prompt=user_prompt(prompt, rooms, entity_types, exit_room),
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_level=THINKING_LEVEL,
        ))
    except LLMError as exc:
        return defaults(rooms, f"the LLM call failed ({exc})")

    known = {r["id"] for r in rooms}
    unknown = sorted({m.room_id for m in result.value.rooms} - known)
    if unknown:
        fallback = defaults(rooms, f"unknown room ids {', '.join(unknown)}")
        fallback.usage = usage.as_dict()
        return fallback
    chosen = {m.room_id: m.model_dump(exclude={"room_id"}) for m in result.value.rooms}
    values, warnings = {}, []
    for r in with_enemies:
        if r["id"] in chosen:
            values[r["id"]] = chosen[r["id"]]
        else:
            values[r["id"]] = {**DEFAULTS, "rationale": "default"}
            warnings.append(f"entity mechanics: no values for room {r['id']}; default enemy behavior used")
    return MechanicsResult(values, "llm", usage.as_dict(), warnings)


def apply_to_plan(plan: dict, mechanics: MechanicsResult, layout: Layout | None = None) -> None:
    """Writes the mechanics as properties of every enemy object in ``plan``."""
    for obj in plan["objects"]:
        if obj["type"] not in ENEMY_TYPES:
            continue
        room = _room_of(layout, (obj["col"], obj["row"])) if layout is not None else None
        values = mechanics.for_room(room)
        props = {
            "chase_range": values["chase_range_tiles"],
            "step_interval_ms": values["step_interval_ms"],
            "behavior": values["behavior"],
        }
        if room is not None:
            rect = layout.rooms[room]
            props.update(room_id=room, room_col=rect.col, room_row=rect.row, room_w=rect.w, room_h=rect.h)
        obj["properties"] = {**obj.get("properties", {}), **props}


def _room_of(layout: Layout, cell: tuple[int, int]) -> str | None:
    """The room holding ``cell``, else the nearest room (corridor guards)."""
    inside = layout.room_at(cell)
    if inside is not None or not layout.rooms:
        return inside

    def gap(rect) -> int:
        dc = max(rect.col - cell[0], 0, cell[0] - (rect.col + rect.w - 1))
        dr = max(rect.row - cell[1], 0, cell[1] - (rect.row + rect.h - 1))
        return max(dc, dr)

    return min(sorted(layout.rooms), key=lambda rid: gap(layout.rooms[rid]))


def summary(mechanics: MechanicsResult) -> dict:
    return {"source": mechanics.source, "rooms": mechanics.rooms, "llm_usage": mechanics.usage}

