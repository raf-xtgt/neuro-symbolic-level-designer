"""
Pipeline 1 (spritesheet ingestion), offline: pre-processor, contact sheets,
agents (completeness and repair), harmonizer (exclusions, conflict rules,
arbitration, families, atlas, quality gate), legacy tilesets and maps, cache.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pipeline.errors import StageError
from pipeline.ingestion import legacy
from pipeline.ingestion.agents import BOUNDARY, CLASSIFICATION, run_agent_batch
from pipeline.ingestion.agents.arbiter import ArbitrationBatch
from pipeline.ingestion.agents.boundary import BoundaryBatch, BoundaryRecord
from pipeline.ingestion.agents.classification import ClassificationBatch, ClassificationRecord
from pipeline.ingestion.agents.collision import CollisionRecord
from pipeline.ingestion.agents.entity import EntityRecord
from pipeline.ingestion.contact_sheet import BATCH_SIZE, CELL, LABEL_H, make_batches, render
from pipeline.ingestion.harmonizer import (
    anchor_from_hint, apply_arbitration, build_catalog, conflicts_of, detect_conflicts, merge, normalize_family,
    quality_gate,
)
from pipeline.ingestion.pipeline1 import Upload, cache_key, run_pipeline1
from pipeline.ingestion.preprocess import (
    ChipInfo, build_chips, collision_polygon, detect_tile_size, estimate_anchor, estimate_footprint,
    is_base_diamond, prepare_sheet,
)
from pipeline.llm.usage import UsageTracker
from tests.pipeline1_helpers import (
    FailingProvider, ScriptedProvider, character_sheet, default_rules, diamond, floor_sheet, paste, tree,
)

BACKEND_DIR = Path(__file__).parent.parent
KENNEY_SHEET = BACKEND_DIR / "tests" / "fixtures" / "kenney_farm_sheet.png"


def _job(tmp_path: Path) -> tuple[Path, Path]:
    job = tmp_path / "job"
    (job / "work").mkdir(parents=True)
    (job / "inputs").mkdir()
    return job, job / "work"


def _chips(tmp_path: Path, **kwargs):
    job, work = _job(tmp_path)
    path = floor_sheet(job / "inputs" / "0.png", **kwargs)
    info, scaled = prepare_sheet(path, 0, "floor.png", work, job)
    return info, build_chips(scaled, info, 0), scaled


# ---------------------------------------------------------------------------
# Pre-processor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("base", [32, 64, 128])
def test_tile_size_detection(tmp_path, base):
    path = floor_sheet(tmp_path / "s.png", base=base)
    width, diamonds = detect_tile_size(np.array(Image.open(path)))
    assert (width, diamonds) == (base, 4)


def test_tile_size_detection_row_of_touching_diamonds():
    sheet = np.zeros((64, 6 * 128, 4), dtype=np.uint8)
    for i in range(6):
        tile = diamond(128, 64)
        region = sheet[:, i * 128:(i + 1) * 128]
        region[tile[:, :, 3] > 0] = tile[tile[:, :, 3] > 0]
    assert detect_tile_size(sheet)[0] == 128


def test_block_tiles_count_as_diamonds():
    # A 256 x 128 top face on a 12 px thick slab (block-style tiles).
    slab = np.zeros((140, 256), dtype=np.uint8)
    slab[:128][diamond(256, 128)[:, :, 3] > 0] = 1
    slab[64:76, :] = 1
    for r in range(76, 140):
        inset = (r - 76) * 2
        slab[r, inset: 256 - inset] = 1
    assert is_base_diamond(slab, 256)
    assert not is_base_diamond(np.ones((128, 256), dtype=np.uint8), 256)  # a rectangle


def test_128_sheet_is_scaled_to_64(tmp_path):
    job, work = _job(tmp_path)
    path = floor_sheet(job / "inputs" / "0.png", base=128, with_tree=False)
    info, scaled = prepare_sheet(path, 0, "big.png", work, job)
    assert (info.tile_size, info.scale, info.source) == ((128, 64), 0.5, "work/sheet_0_scaled.png")
    assert Image.open(scaled).size == (info.original_size[0] // 2, info.original_size[1] // 2)
    chips = build_chips(scaled, info, 0, original_path=path)  # sliced at 128 x 64, rectangles scaled
    assert [c.rect[2:] for c in chips if c.is_diamond][:1] == [(64, 32)]


def test_no_diamond_assumes_64_with_a_warning(tmp_path):
    job, work = _job(tmp_path)
    info, _ = prepare_sheet(character_sheet(job / "inputs" / "0.png"), 0, "chars.png", work, job)
    assert info.scale == 1 and info.tile_size == (64, 32)
    assert "no isometric base diamond found" in info.warnings[0]


def test_noise_dropped_and_duplicates_merged(tmp_path):
    info, chips, _ = _chips(tmp_path)
    assert info.dropped_noise == 1  # the 3 x 3 speck
    assert info.merged_duplicates == 1  # the repeated diamond
    assert len(chips) == 4  # 3 distinct diamonds + the tree
    assert chips[0].duplicates == 1
    assert [c.number for c in chips] == [0, 1, 2, 3]


def test_anchor_and_footprint(tmp_path):
    _, chips, _ = _chips(tmp_path)
    floor = next(c for c in chips if c.is_diamond)
    assert floor.anchor == (floor.rect[2] // 2, 16) and floor.footprint == 1  # center of the tight diamond
    trunk = next(c for c in chips if not c.is_diamond)
    assert trunk.rect[2:] == (44, 96)  # tight box of the crown
    # Trunk center; a 6 px base lifts the foot by 16 * 6 / 64 = 1.5 px only.
    assert trunk.anchor == (22, 94)

    wide = np.zeros((60, 128), dtype=np.uint8)
    wide[:, :] = 1
    assert estimate_footprint(wide) == 2
    assert estimate_anchor(wide) == ((64, 60 - 16), False)  # a full-width base: H/2 above the bottom
    # A soft shadow below and to the right of a trunk does not move the foot.
    alpha = np.zeros((80, 64), dtype=np.uint8)
    alpha[:60, 20:44] = 255
    alpha[60:74, 29:35] = 255  # trunk
    alpha[74:80, 30:64] = 60  # a soft shadow below and right of the trunk
    # Lowest solid rows 70-73, columns 29-34: x 32; lift 16 * 6 / 64 = 1.5 from 74.
    assert estimate_anchor((alpha > 0).astype(np.uint8), alpha)[0] == (32, 72)


def test_collision_polygon_is_the_base():
    mask = np.zeros((96, 48), dtype=np.uint8)
    mask[:66, 2:46] = 1
    mask[66:, 21:27] = 1
    poly = collision_polygon(mask)
    assert 3 <= len(poly) <= 8
    assert all(y >= 96 - 32 for _, y in poly)


# ---------------------------------------------------------------------------
# Contact sheets
# ---------------------------------------------------------------------------

def _fake_chips(n: int, w: int = 10, h: int = 10) -> list[ChipInfo]:
    return [ChipInfo(i, 0, (0, 0, w, h), "contour", (w // 2, h - 1), False, 1, [], w * h, str(i)) for i in range(n)]


def test_batches_of_32_with_labels():
    sheet = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    batches = make_batches(_fake_chips(70), {0: sheet})
    assert [len(b.chips) for b in batches] == [BATCH_SIZE, BATCH_SIZE, 6]
    assert batches[2].numbers == [64, 65, 66, 67, 68, 69]
    assert batches[0].chip_list().splitlines()[3] == "chip 3: 10 x 10 px, anchor estimate (5, 9), footprint 1 tile"
    image = Image.open(io.BytesIO(batches[0].image))
    assert image.size == (8 * CELL, 4 * (CELL + LABEL_H))


def test_chips_are_never_upscaled_beyond_2x():
    sheet = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    image = np.array(Image.open(io.BytesIO(render(_fake_chips(1), {0: sheet}, anchors=False))).convert("RGB"))
    red = (image[:, :, 0] > 200) & (image[:, :, 1] < 60) & (image[:, :, 2] < 60)
    assert red.sum() == 20 * 20


# ---------------------------------------------------------------------------
# Agents: completeness and repair
# ---------------------------------------------------------------------------

def _batch(n: int = 5):
    return make_batches(_fake_chips(n), {0: Image.new("RGBA", (10, 10), (0, 0, 0, 255))})[0]


def test_agent_complete_batch():
    provider = ScriptedProvider()
    result = run_agent_batch(provider, BOUNDARY, _batch(), UsageTracker())
    assert sorted(result.records) == [0, 1, 2, 3, 4] and not result.repaired and not result.missing
    assert len(provider.calls) == 1
    assert isinstance(result.records[0], BoundaryRecord)


def test_agent_missing_chip_triggers_repair():
    provider = ScriptedProvider(drop_first={ClassificationBatch: {3}})
    usage = UsageTracker()
    result = run_agent_batch(provider, CLASSIFICATION, _batch(), usage)
    assert result.repaired and not result.missing and sorted(result.records) == [0, 1, 2, 3, 4]
    assert len(provider.calls) == 2 and usage.calls == 2
    assert "missing chips: 3" in provider.calls[1][1]


def test_agent_extra_and_still_missing():
    class Sloppy(ScriptedProvider):
        def generate_structured(self, schema, **kwargs):
            result = super().generate_structured(schema, **kwargs)
            records = [r for r in result.value.records if r.chip != 4]
            records.append(records[0].model_copy(update={"chip": 99}))
            value = schema(records=records)
            return result.__class__(value, "", "m", 1, 1, 1, 1)

    provider = Sloppy()
    result = run_agent_batch(provider, BOUNDARY, _batch(), UsageTracker())
    assert result.repaired and result.missing == [4] and 99 not in result.records
    assert "not in this contact sheet: 99" in provider.calls[1][1]


# ---------------------------------------------------------------------------
# Harmonizer
# ---------------------------------------------------------------------------

def _records(**overrides) -> dict:
    """One chip (number 0) with agent records; overrides per agent as dicts."""
    base = {
        "boundary_agent": BoundaryRecord(chip=0, kind="single_object", anchor_ok=True, anchor_hint="keep"),
        "classification_agent": ClassificationRecord(chip=0, category="obstacle", walkable=False, material="rock",
                                                     family="Rocks", connector=False, description="a rock"),
        "collision_agent": CollisionRecord(chip=0, blocks_movement=True, blocks_projectiles=False, height_class="low"),
        "entity_agent": EntityRecord(chip=0, is_character=False, is_interactive=False, is_editor_marker=False),
    }
    for agent, fields in overrides.items():
        base[agent] = base[agent].model_copy(update=fields) if fields is not None else None
    return {name: ({0: record} if record is not None else {}) for name, record in base.items()}


CHIP = ChipInfo(0, 0, (0, 0, 40, 50), "contour", (20, 34), False, 1, [(0, 40), (39, 40), (20, 49)], 1500, "h")
DIAMOND = ChipInfo(0, 0, (0, 0, 64, 32), "grid", (32, 16), True, 1, [], 1600, "d")


def _merged(chip: ChipInfo = CHIP, **overrides):
    return merge([chip], _records(**overrides))[0]


def test_merge_and_family_normalization():
    rec = _merged()
    assert (rec.category, rec.walkable, rec.family, rec.kind, rec.excluded) == ("obstacle", False, "rock", "single_object", None)
    assert rec.anchor == (20, 34) and rec.anchor_source == "estimate"
    assert [normalize_family(n) for n in ("Gravestones", "tree_dead_2", "Bushes", "tree", "boxes")] == [
        "gravestone", "tree_dead", "bush", "tree_plain", "box"]


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"boundary_agent": {"kind": "noise"}}, "noise"),
        ({"boundary_agent": {"kind": "fragment"}}, "fragment"),
        ({"boundary_agent": {"kind": "multi_tile_part"}}, "multi_tile_part"),
        ({"entity_agent": {"is_character": True}}, "character"),
        ({"entity_agent": {"is_editor_marker": True}}, "editor_marker"),
        ({"classification_agent": None}, "analysis_incomplete"),
        ({"boundary_agent": None}, "analysis_incomplete"),
        ({"classification_agent": {"category": "floor", "walkable": True}, "boundary_agent": {"kind": "floor_tile"},
          "collision_agent": {"blocks_movement": False}}, "not_a_floor_diamond"),
    ],
)
def test_exclusions(overrides, reason):
    assert _merged(**overrides).excluded == reason


def test_anchor_hint_is_converted():
    rec = _merged(boundary_agent={"anchor_ok": False, "anchor_hint": "left_edge"})
    assert rec.anchor == (20, 34) and rec.anchor_source == "agent_hint:left_edge"  # 40 px wide: min(32, 20)
    assert anchor_from_hint("bottom_center", 128, 224) == (64, 208)
    assert anchor_from_hint("diamond_center", 64, 32) == (32, 16)
    assert anchor_from_hint("right_edge", 128, 96) == (96, 80)


@pytest.mark.parametrize(
    "overrides,rule",
    [
        ({"classification_agent": {"category": "wall", "walkable": True}}, "blocking_category_walkable"),
        ({"classification_agent": {"category": "obstacle", "walkable": True}}, "blocking_category_walkable"),
        ({"classification_agent": {"category": "floor", "walkable": True},
          "boundary_agent": {"kind": "floor_tile"}}, "floor_blocks_movement"),
        ({"classification_agent": {"category": "floor", "walkable": True},
          "collision_agent": {"blocks_movement": False}}, "floor_not_floor_tile"),
        ({"classification_agent": {"category": "decoration", "walkable": True},
          "collision_agent": {"blocks_movement": False, "height_class": "tall"}}, "tall_decoration_not_blocking"),
    ],
)
def test_conflict_rules(overrides, rule):
    rec = _merged(DIAMOND, **overrides)  # a full diamond, so a floor is not excluded first
    assert conflicts_of(rec) == [rule]
    apply_arbitration(rec, None)  # no arbiter answer: the rule fixes it
    assert conflicts_of(rec) == [] and rec.resolution["resolved_by"] == "rule"


def test_no_conflict_for_consistent_chips():
    assert detect_conflicts([_merged()]) == []


def test_arbiter_decision_is_applied():
    rec = _merged(classification_agent={"category": "wall", "walkable": True})
    apply_arbitration(rec, {"category": "wall", "walkable": False, "blocks_movement": True, "height_class": "tall",
                            "kind": "single_object", "reason": "a cliff"})
    assert (rec.walkable, rec.height_class, rec.resolution) == (False, "tall", {"resolved_by": "arbiter", "reason": "a cliff"})


def test_catalog_atlas_cells_are_normalized():
    sheet = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    floor = ChipInfo(1, 0, (100, 0, 64, 32), "grid", (32, 16), True, 1, [], 1000, "f")
    recs = merge([CHIP, floor], {
        **_records(),
        "boundary_agent": {0: _records()["boundary_agent"][0], 1: BoundaryRecord(chip=1, kind="floor_tile", anchor_ok=True, anchor_hint="keep")},
        "classification_agent": {0: _records()["classification_agent"][0], 1: ClassificationRecord(
            chip=1, category="floor", walkable=True, material="grass", family="grass", connector=False, description="g")},
        "collision_agent": {0: _records()["collision_agent"][0], 1: CollisionRecord(
            chip=1, blocks_movement=False, blocks_projectiles=False, height_class="flat")},
        "entity_agent": {0: _records()["entity_agent"][0], 1: EntityRecord(
            chip=1, is_character=False, is_interactive=False, is_editor_marker=False)},
    })
    catalog, atlas = build_catalog(recs, {0: sheet}, {0: "s.png"}, "work/catalog_atlas.png")
    grass, rock = catalog["tiles"]
    assert (grass["name"], grass["rect"]["w"], grass["rect"]["h"], grass["anchor"]) == ("grass_00", 64, 32, {"x": 32, "y": 16})
    assert rock["rect"]["w"] % 64 == 0 and rock["rect"]["h"] % 32 == 0
    assert rock["anchor"] == {"x": rock["rect"]["w"] // 2, "y": rock["rect"]["h"] - 16}
    assert rock["tags"] == ["rock", "prop"] and rock["source_ref"] == "upload:s.png#0"
    assert "collision_polygon" in rock and "collision_polygon" not in grass
    assert atlas.size[0] == 2048


def test_quality_gate():
    floor_tiles = {"tiles": [{"category": "floor", "walkable": True, "tags": ["grass"]}] * 2}
    assert quality_gate(floor_tiles, [])["floor_families"] == {"grass": 2}
    with pytest.raises(StageError) as info:
        quality_gate({"tiles": [{"category": "floor", "walkable": True, "tags": ["grass"]}]}, [])
    assert info.value.code == "ingestion_no_floor"
    chars = [_merged(entity_agent={"is_character": True}) for _ in range(3)]
    with pytest.raises(StageError, match="looks like character sprites \\(3 of 3"):
        quality_gate({"tiles": []}, chars)


# ---------------------------------------------------------------------------
# Whole Pipeline 1 with the scripted provider
# ---------------------------------------------------------------------------

def _run(tmp_path, sheet_fn=floor_sheet, provider=None, tilesets=(), maps=(), cache=None, name="floor.png"):
    job, work = _job(tmp_path)
    sheet = sheet_fn(job / "inputs" / "0.png")
    steps = []
    result = run_pipeline1([Upload(sheet, name)], list(tilesets), list(maps), job, work,
                           provider or ScriptedProvider(), steps.append, cache)
    return result, steps, job


def test_pipeline1_end_to_end(tmp_path):
    provider = ScriptedProvider()
    result, steps, job = _run(tmp_path, provider=provider)
    catalog = json.loads(result.catalog_path.read_text())
    assert [t["name"] for t in catalog["tiles"]] == ["grass_00", "grass_01", "grass_02", "tree_pine_00"]
    assert all(t["source"] == "work/catalog_atlas.png" for t in catalog["tiles"])
    assert (job / "work" / "catalog_atlas.png").is_file() and result.contact_sheet_path.is_file()
    summary = result.summary
    assert summary["tile_count_by_category"] == {"floor": 3, "obstacle": 1}
    assert summary["llm_usage"]["calls"] == 4 and summary["conflicts"] == 0 and summary["arbitration_calls"] == 0
    final = steps[-1]
    assert [s["node"] for s in final] == ["preprocess", "boundary_agent", "classification_agent", "collision_agent",
                                          "entity_agent", "harmonizer", "quality_gate"]
    assert final[1]["done"] == final[1]["total"] == 1
    report = json.loads(result.report_path.read_text())
    assert report["quality_gate"]["passed"] and len(report["chips"]) == 4


def test_arbitration_only_for_conflicting_chips(tmp_path):
    rules = default_rules()
    classify = rules[ClassificationBatch]
    # The tree (not a diamond) is called a walkable obstacle: a conflict.
    rules[ClassificationBatch] = lambda c: classify(c) if c.diamond else classify(c).model_copy(update={"walkable": True})
    provider = ScriptedProvider(rules)
    result, _, _ = _run(tmp_path, provider=provider)
    arbiter_prompts = provider.calls_for(ArbitrationBatch)
    assert len(arbiter_prompts) == 1
    listed = [line for line in arbiter_prompts[0].split("\n\n")[1].splitlines() if line.startswith("chip ")]
    assert len(listed) == 1 and "blocking_category_walkable" in arbiter_prompts[0]
    assert result.summary["conflicts"] == 1 and result.summary["resolutions"] == {"arbiter": 1}
    catalog = json.loads(result.catalog_path.read_text())
    assert next(t for t in catalog["tiles"] if t["category"] == "obstacle")["walkable"] is False


def test_default_provider_is_used_for_agents_and_arbiter(tmp_path, monkeypatch):
    # Regression: with provider=None (the server), the arbiter must get the configured provider too.
    rules = default_rules()
    classify = rules[ClassificationBatch]
    rules[ClassificationBatch] = lambda c: classify(c) if c.diamond else classify(c).model_copy(update={"walkable": True})
    provider = ScriptedProvider(rules)
    monkeypatch.setattr("pipeline.llm.factory.get_provider", lambda config=None: provider)
    job, work = _job(tmp_path)
    sheet = floor_sheet(job / "inputs" / "0.png")
    result = run_pipeline1([Upload(sheet, "floor.png")], [], [], job, work, None)
    assert result.summary["arbitration_calls"] == 1 and len(provider.calls_for(ArbitrationBatch)) == 1


def test_character_sheet_fails_the_quality_gate(tmp_path):
    with pytest.raises(StageError) as info:
        _run(tmp_path, sheet_fn=character_sheet, provider=ScriptedProvider(default_rules(characters=True)))
    assert info.value.code == "ingestion_no_floor" and "character sprites" in info.value.message
    assert info.value.details["ingestion"]["exclusions"] == {"character": 8}


def test_cache_hit_makes_no_llm_call(tmp_path):
    cache = tmp_path / "cache"
    first, _, _ = _run(tmp_path / "a", cache=cache)
    second, steps, job = _run(tmp_path / "b", provider=FailingProvider(), cache=cache)
    assert second.summary["cached"] and second.summary["llm_usage"]["calls"] == 0
    assert second.summary["cold_llm_usage"]["calls"] == 4
    assert {s["status"] for s in steps[-1]} == {"cached"}
    assert json.loads(second.catalog_path.read_text()) == json.loads(first.catalog_path.read_text())
    assert (job / "work" / "catalog_atlas.png").is_file()


def test_failed_ingestion_is_cached_too(tmp_path):
    cache = tmp_path / "cache"
    chars = ScriptedProvider(default_rules(characters=True))
    with pytest.raises(StageError):
        _run(tmp_path / "a", sheet_fn=character_sheet, provider=chars, cache=cache)
    with pytest.raises(StageError) as info:
        _run(tmp_path / "b", sheet_fn=character_sheet, provider=FailingProvider(), cache=cache)
    assert info.value.code == "ingestion_no_floor"


def test_cache_key_covers_bytes_and_legacy_files(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    floor_sheet(a)
    floor_sheet(b, base=128)
    t = tmp_path / "t.tsj"
    t.write_text("{}")
    key = cache_key([Upload(a, "s.png")], [], [])
    assert key == cache_key([Upload(a, "s.png")], [], [])
    assert key != cache_key([Upload(b, "s.png")], [], [])
    assert key == cache_key([Upload(a, "renamed.png")], [], [])  # bytes, not names
    assert key != cache_key([Upload(a, "s.png")], [Upload(t, "t.tsj")], [])


# ---------------------------------------------------------------------------
# Legacy tilesets and maps
# ---------------------------------------------------------------------------

def _grid_sheet(path: Path) -> Path:
    """A 4 x 1 grid of 64 x 32 cells: 3 diamonds and one empty cell."""
    sheet = np.zeros((32, 256, 4), dtype=np.uint8)
    for i, color in enumerate([(60, 140, 60, 255), (70, 150, 60, 255), (120, 120, 120, 255)]):
        paste(sheet, diamond(64, 32, color), i * 64, 0)
    Image.fromarray(sheet, "RGBA").save(path)
    return path


TSJ = {
    "name": "meadow", "tilewidth": 64, "tileheight": 32, "columns": 4, "tilecount": 4, "margin": 0, "spacing": 0,
    "image": "images/meadow.png", "imagewidth": 256, "imageheight": 32,
    "tiles": [
        {"id": i, "type": family, "properties": [
            {"name": "category", "type": "string", "value": "floor"},
            {"name": "walkable", "type": "bool", "value": walkable},
            {"name": "material", "type": "string", "value": material}]}
        for i, (family, walkable, material) in enumerate(
            [("meadow", True, "grass"), ("meadow", True, "grass"), ("slab", False, "stone")])
    ],
}

TSX = """<?xml version="1.0" encoding="UTF-8"?>
<tileset name="meadow" tilewidth="64" tileheight="32" tilecount="4" columns="4">
 <image source="meadow.png" width="256" height="32"/>
 <tile id="0" type="meadow"><properties>
  <property name="category" value="floor"/><property name="walkable" type="bool" value="true"/>
  <property name="material" value="grass"/><property name="tags" value="soft,autotile_required"/>
 </properties></tile>
</tileset>
"""


def test_parse_tsj_and_tsx(tmp_path):
    (tmp_path / "m.tsj").write_text(json.dumps(TSJ))
    (tmp_path / "m.tsx").write_text(TSX)
    tsj = legacy.parse_tileset(tmp_path / "m.tsj", "m.tsj")
    tsx = legacy.parse_tileset(tmp_path / "m.tsx", "m.tsx")
    assert (tsj.image, tsj.image_size, tsj.rect(2)) == ("meadow.png", (256, 32), (128, 0, 64, 32))
    assert tsj.tiles[2] == {"category": "floor", "walkable": False, "material": "stone", "family": "slab"}
    assert tsx.tiles[0]["tags"] == ["soft", "autotile_required"] and tsx.tiles[0]["walkable"] is True
    assert legacy.matches(tsj, "meadow.png", (1, 1)) and legacy.matches(tsj, "other.png", (256, 32))
    assert not legacy.matches(tsj, "other.png", (100, 32))


def test_tileset_wins_and_skips_the_classification_agent(tmp_path):
    (tmp_path / "m.tsj").write_text(json.dumps(TSJ))
    rules = default_rules()
    classify = rules[ClassificationBatch]
    rules[ClassificationBatch] = lambda c: classify(c).model_copy(update={"walkable": True})  # would disagree
    provider = ScriptedProvider(rules)
    result, _, _ = _run(tmp_path, sheet_fn=_grid_sheet, provider=provider, name="meadow.png",
                        tilesets=[Upload(tmp_path / "m.tsj", "m.tsj")])
    assert provider.calls_for(ClassificationBatch) == []  # every classification field is in the tileset
    report = json.loads(result.report_path.read_text())
    chips = report["chips"]
    assert [c["strategy"] for c in chips] == ["legacy"] * 3  # the empty 4th cell is skipped
    assert chips[2]["fields_from_tileset"] == ["category", "family", "material", "walkable"]
    catalog = json.loads(result.catalog_path.read_text())
    assert {t["name"]: t["walkable"] for t in catalog["tiles"]} == {"meadow_00": True, "meadow_01": True, "slab_00": False}
    assert any("using the grid and properties of the tileset m.tsj" in w for w in result.warnings)
    assert report["legacy"][0]["tiles_with_properties"] == 3


def test_map_gid_usage(tmp_path):
    (tmp_path / "m.tmj").write_text(json.dumps({"width": 2, "height": 2, "layers": [
        {"type": "tilelayer", "data": [1, 1, 2, 0]},
        {"type": "group", "layers": [{"type": "tilelayer", "data": [2, 0, 0, 2147483649]}]}]}))
    (tmp_path / "m.tmx").write_text(
        '<map width="2" height="1"><layer><data encoding="csv">3,3</data></layer></map>')
    tmj = legacy.parse_map(tmp_path / "m.tmj", "m.tmj")
    assert tmj["gid_usage"] == {"1": 3, "2": 2}  # the flipped gid counts as 1
    assert legacy.parse_map(tmp_path / "m.tmx", "m.tmx")["gid_usage"] == {"3": 2}


# ---------------------------------------------------------------------------
# The Kenney evaluation sheet (committed fixture)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not KENNEY_SHEET.is_file(), reason="composed by tools/evaluate_ingestion.py")
def test_kenney_sheet_is_detected_as_256_and_scaled(tmp_path):
    job, work = _job(tmp_path)
    info, scaled = prepare_sheet(KENNEY_SHEET, 0, "kenney.png", work, job)
    assert (info.tile_size, info.scale) == ((256, 128), 0.25)
    chips = build_chips(scaled, info, 0, original_path=KENNEY_SHEET)
    # Multi-part sprites (rows of corn) split into pieces; the smallest are noise after scaling.
    assert 12 <= len(chips) <= 20 and sum(c.is_diamond for c in chips) == 4  # dirt, farmland, planks x 2
    assert all(c.anchor == (c.rect[2] // 2, 16) for c in chips if c.is_diamond)
