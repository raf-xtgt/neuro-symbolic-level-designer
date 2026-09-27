"""
Template-assisted Flame code generator (Pipeline 3, ARCHITECTURE.md 5.3).

Renders ``templates/level_loader.dart.j2`` (Jinja2) into ``level_loader.dart``:
a self-contained Dart file (flame, flame_tiled, flutter only) with the level
metadata, the TMJ loading helper for flame_tiled 3.1.2, one typed config
class per enemy entity type (fields from the object properties of the level),
an abstract ``LevelEntityFactory`` with one ``spawn<Type>`` method per entity
type present, and a ``GeneratedLevel`` component.

No LLM writes code: every name comes from the level (entity types, property
names) and must be a valid Dart identifier, else ``CodegenError``.

Public API:
    render_level_loader(tmj, prompt, entity_categories) -> str
    write_level_loader(tmj, prompt, entity_categories, out_dir) -> Path
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

CODEGEN_VERSION = "1"
OUTPUT_NAME = "level_loader.dart"
TEMPLATE = "level_loader.dart.j2"
ENTITY_LAYER = "Entities"
_TEMPLATES = Path(__file__).parent / "templates"

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_DART_RESERVED = {
    "abstract", "as", "assert", "async", "await", "base", "break", "case", "catch", "class", "const", "continue",
    "covariant", "default", "deferred", "do", "dynamic", "else", "enum", "export", "extends", "extension",
    "external", "factory", "false", "final", "finally", "for", "Function", "get", "hide", "if", "implements",
    "import", "in", "interface", "is", "late", "library", "mixin", "new", "null", "on", "operator", "part",
    "required", "rethrow", "return", "sealed", "set", "show", "static", "super", "switch", "sync", "this",
    "throw", "true", "try", "type", "typedef", "var", "void", "when", "while", "with", "yield",
}
# Defaults of known properties (the entity mechanics agent's defaults).
KNOWN_DEFAULTS: dict[str, Any] = {
    "chase_range": 5, "step_interval_ms": 350, "behavior": "idle_until_near", "room_id": "",
}


class CodegenError(ValueError):
    """A name from the level is not a valid Dart identifier."""


def dart_identifier(name: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(name) or name in _DART_RESERVED:
        raise CodegenError(f"{what} {name!r} is not a valid Dart identifier")
    return name


def camel_case(name: str) -> str:
    """``step_interval_ms`` -> ``stepIntervalMs`` (validated)."""
    dart_identifier(name, "property name")
    head, *rest = name.split("_")
    out = head[0].lower() + head[1:] + "".join(w[:1].upper() + w[1:] for w in rest if w)
    return dart_identifier(out, "property name")


def dart_string(text: str) -> str:
    """A Dart string literal (JSON escapes are valid Dart; ``$`` is escaped)."""
    return json.dumps(text, ensure_ascii=True).replace("$", "\\$")


def _entity_objects(tmj: dict) -> list[dict]:
    return [
        obj for layer in tmj.get("layers", []) if layer.get("type") == "objectgroup"
        and layer.get("name") == ENTITY_LAYER for obj in layer.get("objects", [])
    ]


def _kind(values: list[str]) -> str:
    def all_parse(cast) -> bool:
        try:
            for v in values:
                cast(v)
            return True
        except ValueError:
            return False

    if all_parse(int):
        return "int"
    if all_parse(float):
        return "double"
    return "string"


def _field(name: str, values: list[str]) -> dict:
    kind = _kind(values)
    default = KNOWN_DEFAULTS.get(name, {"int": 0, "double": 0.0, "string": ""}[kind])
    if kind == "string":
        default_dart = dart_string(str(default))
    elif kind == "double":
        default_dart = repr(float(default))
    else:
        default_dart = str(int(default))
    return {
        "name": name, "dart_name": camel_case(name), "kind": kind, "default": default_dart,
        "dart_type": {"int": "int", "double": "double", "string": "String"}[kind],
    }


def render_context(tmj: dict, prompt: str, entity_categories: dict[str, str]) -> dict:
    objects = _entity_objects(tmj)
    counts = Counter(obj["type"] for obj in objects)
    order = sorted(counts)
    entities, configs = [], []
    for type_ in order:
        dart_identifier(type_, "entity type")
        if entity_categories.get(type_) != "enemy":
            entities.append({"type": type_, "config": None})
            continue
        values: dict[str, list[str]] = {}
        for obj in objects:
            if obj["type"] == type_:
                for prop in obj.get("properties", []):
                    values.setdefault(prop["name"], []).append(str(prop["value"]))
        class_name = dart_identifier(f"{type_[0].upper()}{type_[1:]}Config", "config class")
        configs.append({"type": type_, "class_name": class_name, "fields": [_field(n, values[n]) for n in sorted(values)]})
        entities.append({"type": type_, "config": class_name})
    kinds = sorted({f["kind"] for c in configs for f in c["fields"]})
    return {
        "prompt_line": " ".join(prompt.split()),
        "prompt_dart": dart_string(prompt),
        "generator_version": CODEGEN_VERSION,
        "map_width": tmj["width"],
        "map_height": tmj["height"],
        "tile_width": tmj["tilewidth"],
        "tile_height": tmj["tileheight"],
        "entity_counts": [(t, counts[t]) for t in order],
        "entity_counts_line": ", ".join(f"{t} {counts[t]}" for t in order) or "none",
        "entities": entities,
        "configs": configs,
        "kinds": kinds,
    }


def render_level_loader(tmj: dict, prompt: str, entity_categories: dict[str, str]) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES), undefined=StrictUndefined, keep_trailing_newline=True,
        autoescape=False,
    )
    return env.get_template(TEMPLATE).render(**render_context(tmj, prompt, entity_categories))


def write_level_loader(tmj: dict, prompt: str, entity_categories: dict[str, str], out_dir: str | Path) -> Path:
    path = Path(out_dir) / OUTPUT_NAME
    path.write_text(render_level_loader(tmj, prompt, entity_categories), encoding="utf-8")
    return path
