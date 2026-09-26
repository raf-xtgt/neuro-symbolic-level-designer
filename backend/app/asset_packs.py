"""Built-in asset packs: ``asset_packs/<id>/pack.json`` manifests."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import jsonschema

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_PACKS_DIR = BACKEND_DIR / "asset_packs"
_CATALOG_SCHEMA = BACKEND_DIR / "pipeline" / "schemas" / "asset_catalog.schema.json"


@dataclass(frozen=True)
class AssetPack:
    id: str
    name: str
    description: str
    spritesheets: list[Path]  # absolute, from repo-root-relative manifest paths
    catalog: Path  # absolute, from backend-relative manifest path
    tile_width: int
    tile_height: int


def _load_pack(manifest_path: Path, catalog_schema: dict) -> AssetPack:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    if m["id"] != manifest_path.parent.name:
        raise ValueError(f"id '{m['id']}' does not match folder '{manifest_path.parent.name}'")
    sheets = [REPO_ROOT / s for s in m["spritesheets"]]
    catalog = BACKEND_DIR / m["catalog"]
    for p in [*sheets, catalog]:
        if not p.is_file():
            raise ValueError(f"missing file {p}")
    jsonschema.validate(json.loads(catalog.read_text(encoding="utf-8")), catalog_schema)
    return AssetPack(
        id=m["id"],
        name=m["name"],
        description=m["description"],
        spritesheets=sheets,
        catalog=catalog,
        tile_width=int(m["tile_size"]["width"]),
        tile_height=int(m["tile_size"]["height"]),
    )


def discover_packs(packs_dir: Path = DEFAULT_PACKS_DIR) -> dict[str, AssetPack]:
    """Loads every valid pack. Invalid packs are skipped with a warning."""
    schema = json.loads(_CATALOG_SCHEMA.read_text(encoding="utf-8"))
    packs: dict[str, AssetPack] = {}
    for manifest in sorted(packs_dir.glob("*/pack.json")):
        try:
            pack = _load_pack(manifest, schema)
        except Exception as exc:  # noqa: BLE001 - any bad manifest is skipped
            log.warning("Skipping asset pack %s: %s", manifest.parent.name, exc)
            continue
        packs[pack.id] = pack
    return packs
