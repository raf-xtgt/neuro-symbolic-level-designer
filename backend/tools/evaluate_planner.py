"""
Evaluate Pipeline 2 (the agentic planner) on 5 fixed prompts with the
``grassland_full`` pack.

For each prompt: run the LangGraph planner, compile the plan with Pipeline 3,
save the preview to ``eval/previews/<n>.png``, and check whether the level
matches the prompt (automatic checks, listed in the report). Writes
``eval/pipeline2_report.md`` and ``eval/results.json``.

The LLM mode comes from ``LLM_MODE`` (see ``pipeline/llm/config.py``):
    LLM_MODE=record uv run python tools/evaluate_planner.py   # live, saves fixtures
    uv run python tools/evaluate_planner.py                    # live (default mode)
    LLM_MODE=replay uv run python tools/evaluate_planner.py   # offline, from fixtures

Run from ``backend/``.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pipeline.execution.compile import run_compile  # noqa: E402
from pipeline.llm.base import LLMError  # noqa: E402
from pipeline.llm.config import load_config  # noqa: E402
from pipeline.llm.factory import get_provider  # noqa: E402
from pipeline.planning.catalog_digest import group_id  # noqa: E402
from pipeline.planning.graph import PlanningFailed, PlanningOutcome, plan_with_llm  # noqa: E402
from pipeline.planning.placeholder_planner import seed_from_prompt  # noqa: E402

CATALOG = BACKEND_DIR / "asset_packs" / "grassland_full" / "asset_catalog.json"
EVAL_DIR = BACKEND_DIR / "eval"
PROMPTS = [
    "graveyard with a cabin and a boss arena",
    "dense forest maze with a hidden treasure grove",
    "open meadow with a stone plaza in the center guarded by 6 zombies",
    "a winding path through dead trees to a boss clearing in the north",
    "small campsite with firewood and a treasure room to the east",
]


# ---------------------------------------------------------------------------
# Facts about a planned level
# ---------------------------------------------------------------------------

class Facts:
    def __init__(self, outcome: PlanningOutcome, catalog: dict):
        self.outcome = outcome
        self.topology = outcome.topology
        self.layout = outcome.layout
        plan = outcome.plan
        groups = {t["id"]: group_id(t) for t in catalog["tiles"]}
        playable = self.layout.playable_cells
        self.room_props: Counter = Counter()  # tile group -> count inside rooms and corridors
        self.wild: Counter = Counter()  # tile group -> count in the wilderness
        for r, row in enumerate(plan["layers"][1]["grid"]):
            for c, tile_id in enumerate(row):
                if tile_id:
                    (self.room_props if (c, r) in playable else self.wild)[groups[tile_id]] += 1
        self.room_floors: dict[str, Counter] = {}
        ground = plan["layers"][0]["grid"]
        for rid, rect in self.layout.rooms.items():
            self.room_floors[rid] = Counter(groups[ground[r][c]] for c, r in rect.cells())
        self.zombies = [(o["col"], o["row"]) for o in plan["objects"] if o["type"] == "Zombie"]
        spawn = next(o for o in plan["objects"] if o["type"] == "PlayerSpawn")
        exit_ = next(o for o in plan["objects"] if o["type"] == "ExitTrigger")
        self.spawn_room = self.layout.room_at((spawn["col"], spawn["row"]))
        self.exit_room = self.layout.room_at((exit_["col"], exit_["row"]))

    def rooms(self, purpose: str | None = None, position: str | None = None) -> list:
        return [
            r for r in self.topology.rooms
            if (purpose is None or r.purpose == purpose) and (position is None or r.relative_position == position)
        ]

    def props(self, *prefixes: str) -> int:
        return sum(n for g, n in self.room_props.items() if g.startswith(prefixes))

    def zombies_near(self, room_id: str, margin: int = 2) -> int:
        rect = self.layout.rooms[room_id]
        return sum(
            1 for z in self.zombies
            if rect.col - margin <= z[0] < rect.col + rect.w + margin
            and rect.row - margin <= z[1] < rect.row + rect.h + margin
        )

    def text(self) -> str:
        t = self.topology
        return " ".join([t.theme, t.design_notes] + [r.description for r in t.rooms]).lower()


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(ok), "detail": detail}


def judge(n: int, f: Facts) -> list[dict]:
    """Prompt-specific checks: does the level match the prompt?"""
    corridor_types = Counter(c.corridor_type for c in f.topology.corridors)
    if n == 1:
        boss = f.rooms("boss")
        return [
            _check("gravestones in the rooms", f.props("obstacle.gravestone") > 0,
                   f"{f.props('obstacle.gravestone')} gravestones"),
            _check("a boss arena", bool(boss), ", ".join(r.id for r in boss) or "no boss room"),
            _check("a cabin (wood props or a cabin room)",
                   f.props("obstacle.logs", "obstacle.cart", "obstacle.sack", "obstacle.anvil") > 0 or "cabin" in f.text(),
                   f"{f.props('obstacle.logs', 'obstacle.cart', 'obstacle.sack', 'obstacle.anvil')} wood props"),
        ]
    if n == 2:
        trees = sum(v for g, v in f.wild.items() if g.startswith("obstacle.tree_"))
        wild_total = sum(f.wild.values()) or 1
        return [
            _check("a treasure room", bool(f.rooms("treasure")), ", ".join(r.id for r in f.rooms("treasure")) or "none"),
            _check("maze-like: 4+ rooms or winding corridors", len(f.topology.rooms) >= 4 or corridor_types["winding"] > 0,
                   f"{len(f.topology.rooms)} rooms, {corridor_types['winding']} winding corridors"),
            _check("forest: trees in the rooms or most of the wilderness", f.props("obstacle.tree_") > 0 or trees / wild_total > 0.3,
                   f"{f.props('obstacle.tree_')} trees in rooms, {trees / wild_total:.0%} of the wilderness"),
            _check("treasure room is the exit (hidden at the end)", f.exit_room in {r.id for r in f.rooms("treasure")},
                   f"exit in {f.exit_room}"),
        ]
    if n == 3:
        center = f.rooms(position="center")
        plaza = max(center, key=lambda r: f.room_floors[r.id]["floor.stone"], default=None)
        stone = f.room_floors[plaza.id]["floor.stone"] / sum(f.room_floors[plaza.id].values()) if plaza else 0
        near = f.zombies_near(plaza.id) if plaza else 0
        others = Counter()
        for rid, floors in f.room_floors.items():
            if plaza is None or rid != plaza.id:
                others.update(floors)
        grass = others["floor.grass"] / (sum(others.values()) or 1)
        return [
            _check("a room in the center", bool(center), ", ".join(r.id for r in center) or "none"),
            _check("the center room is a stone plaza", stone >= 0.5, f"{stone:.0%} stone floor in {plaza.id if plaza else '-'}"),
            _check("6 zombies at the plaza", near >= 6, f"{near} zombies in or within 2 cells of the plaza"),
            _check("open meadow: mostly grass floors outside the plaza", grass >= 0.7,
                   f"{grass:.0%} grass floor in the other rooms"),
        ]
    if n == 4:
        boss_north = f.rooms("boss", "north")
        dead = f.wild.get("obstacle.tree_dead", 0) + f.props("obstacle.tree_dead")
        return [
            _check("boss room in the north", bool(boss_north), ", ".join(r.id for r in boss_north) or "no northern boss room"),
            _check("the exit is in the boss room", f.exit_room in {r.id for r in f.rooms("boss")}, f"exit in {f.exit_room}"),
            _check("winding corridors", corridor_types["winding"] > 0, f"{corridor_types['winding']} winding"),
            _check("dead trees", dead > 0 and f.wild.get("obstacle.tree_dead", 0) >= max(
                [v for g, v in f.wild.items() if g.startswith("obstacle.tree_")] or [0]),
                f"{dead} dead trees (the most common tree in the wilderness)"),
        ]
    treasure_east = f.rooms("treasure", "east")
    return [
        _check("campfire or firewood", f.props("obstacle.campfire", "obstacle.logs") > 0,
               f"{f.props('obstacle.campfire')} campfires, {f.props('obstacle.logs')} log stacks"),
        _check("treasure room to the east", bool(treasure_east), ", ".join(r.id for r in treasure_east) or "none"),
        _check("small: at most 5 rooms, no large room",
               len(f.topology.rooms) <= 5 and not any(r.size == "large" for r in f.topology.rooms),
               f"{len(f.topology.rooms)} rooms, sizes {', '.join(r.size for r in f.topology.rooms)}"),
    ]


# ---------------------------------------------------------------------------
# Run and report
# ---------------------------------------------------------------------------

def run_one(n: int, prompt: str, catalog: dict, provider, work: Path) -> dict:
    try:
        outcome = plan_with_llm(prompt, catalog, seed_from_prompt(prompt), provider)
    except PlanningFailed as exc:
        return {"n": n, "prompt": prompt, "passed": False, "error": str(exc), "outcome": exc.outcome}
    except LLMError as exc:
        return {"n": n, "prompt": prompt, "passed": False, "error": str(exc), "outcome": None}

    plan_path = work / f"{n}_level_plan.json"
    plan_path.write_text(json.dumps(outcome.plan), encoding="utf-8")
    bundle = work / f"{n}_bundle"
    with contextlib.redirect_stdout(io.StringIO()):
        run_compile(str(plan_path), str(CATALOG), str(bundle))
    previews = EVAL_DIR / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle / "preview_level.png", previews / f"{n}.png")

    facts = Facts(outcome, catalog)
    return {"n": n, "prompt": prompt, "passed": True, "outcome": outcome, "facts": facts, "checks": judge(n, facts)}


def _rooms_table(topology) -> list[str]:
    lines = ["| Room | Purpose | Position | Size | Enemies | Description |", "|---|---|---|---|---:|---|"]
    lines += [
        f"| {r.id} | {r.purpose} | {r.relative_position} | {r.size} | {r.enemy_count} | {r.description} |"
        for r in topology.rooms
    ]
    return lines


def report(results: list[dict], mode: str, model: str) -> str:
    lines = [
        "# Pipeline 2 evaluation: 5 prompts, `grassland_full`",
        "",
        "Generated by `tools/evaluate_planner.py`. Each prompt runs the LangGraph planner",
        "(`pipeline/planning/graph.py`): the LLM topology agent plans the room graph, deterministic",
        "nodes lay it out, place entities, dress the tiles and validate. The level is then compiled",
        "with Pipeline 3 for the preview (green: spawn, yellow: exit, red: zombies).",
        f"Model `{model}`, LLM mode `{mode}` (latency 0 in replay mode).",
        "",
        "| # | Prompt | Valid | Matches prompt | Topology attempts | Layout attempts | LLM calls | Input tokens | Output tokens | Latency |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for res in results:
        o = res["outcome"]
        usage = o.usage if o else {}
        checks = res.get("checks", [])
        match = f"{sum(c['passed'] for c in checks)}/{len(checks)}" if checks else "-"
        attempts = o.attempts if o else {"topology": "-", "layout": "-"}
        lines.append(
            f"| {res['n']} | {res['prompt']} | {'yes' if res['passed'] else 'no'} | {match} "
            f"| {attempts['topology']} | {attempts['layout']} | {usage.get('calls', 0)} "
            f"| {usage.get('input_tokens', 0)} | {usage.get('output_tokens', 0)} "
            f"| {usage.get('latency_ms', 0) / 1000:.1f} s |"
        )
    for res in results:
        o = res["outcome"]
        lines += ["", f"## {res['n']}. \"{res['prompt']}\"", ""]
        if not res["passed"]:
            lines += [f"**Failed:** {res['error']}", ""]
            if o and o.report:
                lines += [f"- {c['name']}: {c['detail']}" for c in o.report["checks"] if not c["passed"]]
            continue
        checks = res["checks"]
        verdict = "matches the prompt" if all(c["passed"] for c in checks) else "partly matches the prompt"
        lines += [
            f"![preview {res['n']}](previews/{res['n']}.png)",
            "",
            f"**Judgement:** {verdict} ({sum(c['passed'] for c in checks)} of {len(checks)} checks).",
            "",
        ]
        lines += [f"- {'yes' if c['passed'] else 'NO'}: {c['name']} ({c['detail']})" for c in checks]
        t = o.topology
        replans = [s for s in o.steps if s["status"] == "failed"]
        lines += [
            "",
            f"**Theme:** `{t.theme}`. **Design notes:** {t.design_notes}",
            "",
            *_rooms_table(t),
            "",
            "**Corridors:** " + ", ".join(f"{c.from_room} -> {c.to_room} ({c.corridor_type})" for c in t.corridors),
            "",
            "**Style:** " + ", ".join(f"{s.tile_group} {s.weight:g}" for s in t.style_distribution),
            "",
            f"**Map:** {o.layout.width} x {o.layout.height}; exit in `{res['facts'].exit_room}`; "
            f"{len(res['facts'].zombies)} zombies.",
            "",
            f"**Attempts:** {o.attempts['topology']} topology, {o.attempts['layout']} layout. "
            f"**Validation:** {'passed' if o.report['passed'] else 'failed'} "
            f"({', '.join(c['name'] for c in o.report['checks'])}).",
            "",
            f"**LLM:** {o.usage['calls']} calls, {o.usage['attempts']} API attempts, "
            f"{o.usage['input_tokens']} input and {o.usage['output_tokens']} output tokens, "
            f"{o.usage['latency_ms'] / 1000:.1f} s.",
        ]
        if replans:
            lines += ["", "**Replans:**"] + [f"- {s['node']} attempt {s['attempt']}: {s['message']}" for s in replans]
        if o.warnings:
            lines += ["", "**Warnings:** " + "; ".join(o.warnings)]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    provider = get_provider(config)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    EVAL_DIR.mkdir(exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, prompt in enumerate(PROMPTS, start=1):
            print(f"[{n}/5] {prompt} ...", flush=True)
            res = run_one(n, prompt, catalog, provider, Path(tmp))
            results.append(res)
            o = res["outcome"]
            print(f"      {'valid' if res['passed'] else 'FAILED: ' + res['error']}"
                  + (f"; attempts {o.attempts}; {o.usage}" if o else ""), flush=True)
    (EVAL_DIR / "pipeline2_report.md").write_text(report(results, config.mode, config.model), encoding="utf-8")
    (EVAL_DIR / "results.json").write_text(json.dumps([
        {
            "n": r["n"], "prompt": r["prompt"], "passed": r["passed"], "error": r.get("error"),
            "attempts": r["outcome"].attempts if r["outcome"] else None,
            "usage": r["outcome"].usage if r["outcome"] else None,
            "checks": r.get("checks", []),
            "steps": r["outcome"].steps if r["outcome"] else [],
        }
        for r in results
    ], indent=2) + "\n", encoding="utf-8")
    print(f"-> {EVAL_DIR / 'pipeline2_report.md'}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
