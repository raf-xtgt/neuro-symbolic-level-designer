"""
Pipeline 2 as a LangGraph ``StateGraph`` (ARCHITECTURE.md section 4):
"agents plan, algorithms fill".

    topology_agent (LLM) -> layout_builder -> stacking -> spawner -> dressing -> validator
          ^   |                  ^   |                                               |
          |   +- invalid topology |  +- layout error ---------+                      |
          |                       +---- layout-fixable failure (new seed, <= 2) -----+
          +---------------------------- other failures (error payload, <= 3 topologies)

* ``topology_agent``: the only LLM node. Prompt + catalog digest (+ the
  structured errors of the previous attempt) -> ``RoomTopologyGraph``, then
  the catalog-context rules (``validate_with_catalog``). A graph that breaks
  them is a failed topology attempt; its errors go into the next call.
* Layout-fixable failures (rooms overlap after separation, a room or the
  exit unreachable because of scattered props) retry the layout with the next
  seed, at most ``MAX_LAYOUT_RETRIES`` times per topology. Everything else,
  or when layout retries are used up, goes back to the topology agent, at
  most ``MAX_TOPOLOGY_ATTEMPTS`` topologies in total.
* All attempts fail -> ``PlanningFailed`` with the last validation report.
  No silent fallback.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pipeline.llm.base import LLMProvider
from pipeline.llm.usage import UsageTracker
from pipeline.planning.catalog_digest import CatalogDigest, build_digest
from pipeline.planning.dressing import dress
from pipeline.planning.layout import MAX_MAP, SIZES, Layout, LayoutError, build_layout
from pipeline.planning.models import (
    MAX_ENEMIES, MAX_ENEMIES_PER_ROOM, MAX_ROOM_DRESSING, MAX_ROOMS, MIN_ROOMS, RoomTopologyGraph,
    validate_with_catalog,
)
from pipeline.planning.spawner import Placement, place_entities
from pipeline.planning.validator import failed_checks, validate_plan

MAX_TOPOLOGY_ATTEMPTS = 3
MAX_LAYOUT_RETRIES = 2
LAYOUT_FIXABLE = {"rooms_layout", "rooms_reachable", "path_spawn_exit"}
TEMPERATURE = 0.4
MAX_OUTPUT_TOKENS = 8192
TIMEOUT_S = 120

StepCallback = Callable[[list[dict]], None]


class PlanningFailed(Exception):
    """Every attempt failed. ``report`` is the last validation report."""

    def __init__(self, message: str, outcome: PlanningOutcome):
        super().__init__(message)
        self.outcome = outcome


class PlanningState(TypedDict, total=False):
    prompt: str
    catalog: dict
    digest: CatalogDigest
    seed: int
    topology: RoomTopologyGraph | None
    previous_topology: RoomTopologyGraph | None
    error_payload: list[dict]
    layout: Layout | None
    placement: Placement | None
    plan: dict | None
    report: dict | None
    topology_attempts: int
    layout_attempts: int  # for the current topology
    layout_attempts_total: int
    next: str
    warnings: dict[str, list[str]]  # node -> warnings of the current attempt
    group_counts: dict[str, int]  # tile group -> placed cells, of the current plan


@dataclass
class PlanningOutcome:
    passed: bool
    plan: dict | None
    topology: RoomTopologyGraph | None
    layout: Layout | None
    report: dict | None
    steps: list[dict]
    usage: dict
    attempts: dict
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def system_instruction(digest: CatalogDigest) -> str:
    sizes = ", ".join(f"{k} {v} x {v}" for k, v in SIZES.items())
    return f"""You are the Spatial Topology Planner of an isometric 2D level generator.
You design the macro structure of ONE level as a room graph. Deterministic algorithms then
lay the rooms out on a grid, place the entities, and dress the tiles. You never output tiles.

Rules (a graph that breaks them is rejected and sent back to you):
- {MIN_ROOMS} to {MAX_ROOMS} rooms with unique ids; exactly one room with purpose "entrance".
- Corridors only between room ids you defined, and they must connect every room to the entrance.
- enemy_count per room 0 to {MAX_ENEMIES_PER_ROOM}; at most {MAX_ENEMIES} enemies (zombies) in total.
  Enemies never spawn right next to the player, so keep the entrance at 0 to 1.
- Every tile_group must be one of the catalog tile groups listed below, spelled exactly.
- style_distribution: the global weights (0 to 1); it must contain at least one floor.* group.
  Obstacle and decoration groups set which props appear inside rooms. Tree and rock pillar groups
  also shape the wall of trees and rock pillars that encloses the whole level.
- A room's dressing (0 to {MAX_ROOM_DRESSING} groups) overrides the global weights inside that room;
  use it to give rooms their own character (for example a stone floor plaza, gravestones in a burial ground).
- description: up to 120 characters per room. design_notes: up to 400 characters on why this layout
  fits the prompt.

Layout facts:
- relative_position is a screen direction from the level center: north = top of the screen,
  south = bottom, east = right, west = left, center = middle. Several rooms may share a direction;
  they are placed further out along it.
- Room sizes: {sizes} cells. The whole map is at most {MAX_MAP} x {MAX_MAP} cells, so prefer
  3 to 5 rooms and at most 2 large rooms.
- The exit is placed in the room farthest (in corridor hops) from the entrance, so the corridor
  graph decides where the level ends.
- Corridor types: straight, winding (2 to 3 bends), bridge (drawn straight for now).
- Elevation must be 0 (no ramps or raised tiles yet).

Follow the user's prompt closely: room purposes, positions, counts of enemies, themes and props
the prompt names must appear in the graph.

Catalog tile groups:
{digest.as_text()}"""


def user_prompt(prompt: str, previous: RoomTopologyGraph | None, errors: list[dict]) -> str:
    text = f"Design prompt: {prompt}"
    if errors:
        text += (
            "\n\nYour previous room graph failed these checks. Return a corrected, complete room graph "
            "that keeps the intent of the prompt.\nFailed checks:\n"
            + "\n".join(f"- {e['check']}: {e['detail']}" for e in errors)
        )
        if previous is not None:
            text += "\nPrevious room graph:\n" + previous.model_dump_json()
    return text


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class Pipeline2:
    """Builds and runs the planning graph with one LLM provider."""

    def __init__(self, provider: LLMProvider, on_step: StepCallback | None = None):
        self.provider = provider
        self.on_step = on_step
        self.usage = UsageTracker()
        self._steps: list[dict] = []
        self.graph = self._build()

    def _step(self, node: str, status: str, attempt: int, message: str) -> dict:
        """Records a finished node run; it replaces the node's ``running`` step."""
        step = {"node": node, "status": status, "attempt": attempt, "message": message}
        if self._steps and self._steps[-1]["node"] == node and self._steps[-1]["status"] == "running":
            self._steps.pop()
        self._steps.append(step)
        self._emit()
        return step

    def _emit(self) -> None:
        if self.on_step is not None:
            self.on_step(list(self._steps))

    def _tracked(self, name: str, node):
        """Wraps a node: a ``running`` step while it runs (for the progress UI)."""
        def run(state: PlanningState) -> dict:
            attempt = 1 + sum(s["node"] == name for s in self._steps)
            self._steps.append({"node": name, "status": "running", "attempt": attempt, "message": ""})
            self._emit()
            try:
                return node(state)
            finally:
                last = self._steps[-1] if self._steps else None
                if last and last["node"] == name and last["status"] == "running":
                    self._steps.pop()  # the node raised before recording its result
        return run

    # -- nodes -----------------------------------------------------------

    def topology_agent(self, state: PlanningState) -> dict:
        attempt = state.get("topology_attempts", 0) + 1
        errors = state.get("error_payload", [])
        result = self.provider.generate_structured(
            RoomTopologyGraph,
            system=system_instruction(state["digest"]),
            prompt=user_prompt(state["prompt"], state.get("previous_topology"), errors),
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout_s=TIMEOUT_S,
        )
        self.usage.add(result)
        topology = result.value
        problems = validate_with_catalog(topology, state["digest"])
        if problems:
            self._step(
                "topology_agent", "failed", attempt, "; ".join(f"{p['check']}: {p['detail']}" for p in problems),
            )
            report = {
                "passed": False,
                "checks": [{"name": p["check"], "passed": False, "detail": p["detail"]} for p in problems],
                "warnings": [],
            }
            last = attempt >= MAX_TOPOLOGY_ATTEMPTS
            return {
                "topology": None, "previous_topology": topology, "error_payload": problems, "report": report,
                "topology_attempts": attempt, "next": END if last else "topology_agent",
            }
        enemies = sum(r.enemy_count for r in topology.rooms)
        self._step("topology_agent", "done", attempt, f"{len(topology.rooms)} rooms, {enemies} enemies")
        return {
            "topology": topology, "previous_topology": topology, "error_payload": [], "topology_attempts": attempt,
            "layout_attempts": 0, "warnings": {}, "next": "layout_builder",
        }

    def layout_builder(self, state: PlanningState) -> dict:
        attempt = state.get("layout_attempts", 0) + 1
        total = state.get("layout_attempts_total", 0) + 1
        seed = state["seed"] + 1000 * state["topology_attempts"] + attempt
        update: dict[str, Any] = {"layout_attempts": attempt, "layout_attempts_total": total}
        try:
            layout = build_layout(state["topology"], seed)
        except LayoutError as exc:
            report = {
                "passed": False, "checks": [{"name": exc.check, "passed": False, "detail": exc.detail}],
                "warnings": [],
            }
            self._step("layout_builder", "failed", attempt, exc.detail)
            fixable = {exc.check} if exc.fixable else {"not_fixable"}
            return {**update, **self._route_failure(state, report, fixable, attempt), "report": report}
        self._step(
            "layout_builder", "done", attempt,
            f"{layout.width} x {layout.height} map, {len(layout.corridors)} corridors (seed {seed})",
        )
        warnings = {**state.get("warnings", {}), "layout_builder": layout.warnings}
        return {**update, "layout": layout, "warnings": warnings, "next": "stacking"}

    def stacking(self, state: PlanningState) -> dict:
        raised = [r.id for r in state["topology"].rooms if r.elevation != 0]
        warnings = (
            [f"elevation ignored for rooms {', '.join(raised)}: the pack has no ramps or raised tiles"]
            if raised else []
        )
        self._step(
            "stacking", "done", state["layout_attempts"],
            "all rooms at elevation 0" + (f" ({len(raised)} flattened)" if raised else ""),
        )
        return {"warnings": {**state["warnings"], "stacking": warnings}}

    def spawner(self, state: PlanningState) -> dict:
        placement = place_entities(state["topology"], state["layout"], state["seed"] + state["layout_attempts"])
        self._step(
            "spawner", "done", state["layout_attempts"],
            f"spawn in {state['topology'].entrance.id}, exit in {placement.exit_room}, {len(placement.zombies)} zombies",
        )
        return {"placement": placement, "warnings": {**state["warnings"], "spawner": placement.warnings}}

    def dressing(self, state: PlanningState) -> dict:
        layout, catalog = state["layout"], state["catalog"]
        dressed = dress(state["topology"], layout, state["placement"], state["digest"], layout.seed)
        plan = {
            "map_properties": {
                "width": layout.width,
                "height": layout.height,
                "tile_width": catalog["tile_size"]["width"],
                "tile_height": catalog["tile_size"]["height"],
                "orientation": "isometric",
            },
            "layers": [
                {"name": "Ground", "elevation": 0, "grid": dressed.ground},
                {"name": "Objects", "elevation": 0, "grid": dressed.objects},
            ],
            "objects": state["placement"].objects(),
        }
        props = sum(n for g, n in dressed.group_counts.items() if not g.startswith("floor."))
        self._step("dressing", "done", state["layout_attempts"], f"{props} props and wilderness tiles placed")
        return {"plan": plan, "warnings": {**state["warnings"], "dressing": dressed.warnings},
                "group_counts": dict(dressed.group_counts)}

    def validator(self, state: PlanningState) -> dict:
        report = validate_plan(state["plan"], state["catalog"], state["layout"].rooms)
        if report["passed"]:
            self._step("validator", "done", state["layout_attempts"], "all checks passed")
            return {"report": report, "next": END}
        failed = failed_checks(report)
        self._step(
            "validator", "failed", state["layout_attempts"], "; ".join(f"{c['name']}: {c['detail']}" for c in failed),
        )
        route = self._route_failure(state, report, {c["name"] for c in failed}, state["layout_attempts"])
        return {"report": report, **route}

    def _route_failure(self, state: PlanningState, report: dict, failed: set[str], layout_attempt: int) -> dict:
        if failed <= LAYOUT_FIXABLE and layout_attempt <= MAX_LAYOUT_RETRIES:
            return {"next": "layout_builder"}
        if state["topology_attempts"] < MAX_TOPOLOGY_ATTEMPTS:
            payload = [{"check": c["name"], "detail": c["detail"]} for c in failed_checks(report)]
            return {"next": "topology_agent", "error_payload": payload}
        return {"next": END}

    # -- wiring ----------------------------------------------------------

    def _build(self):
        graph = StateGraph(PlanningState)
        for name in ("topology_agent", "layout_builder", "stacking", "spawner", "dressing", "validator"):
            graph.add_node(name, self._tracked(name, getattr(self, name)))
        graph.add_edge(START, "topology_agent")
        route = lambda state: state["next"]  # noqa: E731
        graph.add_conditional_edges("topology_agent", route, ["topology_agent", "layout_builder", END])
        graph.add_conditional_edges("layout_builder", route, ["stacking", "layout_builder", "topology_agent", END])
        graph.add_edge("stacking", "spawner")
        graph.add_edge("spawner", "dressing")
        graph.add_edge("dressing", "validator")
        graph.add_conditional_edges("validator", route, ["layout_builder", "topology_agent", END])
        return graph.compile()

    def run(self, prompt: str, catalog: dict, seed: int) -> PlanningOutcome:
        state = self.graph.invoke(
            {
                "prompt": prompt, "catalog": catalog, "digest": build_digest(catalog), "seed": seed,
                "topology_attempts": 0, "layout_attempts": 0, "layout_attempts_total": 0,
            },
            config={"recursion_limit": 200},
        )
        report = state.get("report")
        passed = bool(report and report["passed"] and state.get("plan") is not None and state.get("topology"))
        warnings = [w for ws in state.get("warnings", {}).values() for w in ws]
        if report:
            warnings += report.get("warnings", [])
        outcome = PlanningOutcome(
            passed=passed,
            plan=state.get("plan") if passed else None,
            topology=state.get("topology") or state.get("previous_topology"),
            layout=state.get("layout"),
            report=report,
            steps=list(self._steps),
            usage=self.usage.as_dict(),
            attempts={"topology": state.get("topology_attempts", 0),
                      "layout": state.get("layout_attempts_total", 0)},
            warnings=warnings if passed else [],
        )
        if not passed:
            names = ", ".join(c["name"] for c in failed_checks(report)) if report else "unknown"
            raise PlanningFailed(
                f"the level failed validation after {outcome.attempts['topology']} topology and "
                f"{outcome.attempts['layout']} layout attempts (failed checks: {names})",
                outcome,
            )
        return outcome


def plan_with_llm(
    prompt: str, catalog: dict, seed: int, provider: LLMProvider, on_step: StepCallback | None = None,
) -> PlanningOutcome:
    return Pipeline2(provider, on_step).run(prompt, catalog, seed)


def topology_json(topology: RoomTopologyGraph) -> str:
    return json.dumps(topology.model_dump(), indent=2)
