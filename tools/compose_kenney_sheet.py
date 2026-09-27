#!/usr/bin/env python3
"""
compose_kenney_sheet.py
Packs a Kenney isometric miniature pack into one spritesheet for upload tests.

Takes every file in the zip's ``Isometric/`` folder whose name ends with
``_S.png`` (one facing per object), in sorted order, and packs them in rows
of at most 2048 px, with 8 px transparent gutters around every sprite.

Usage (defaults resolve from the repository root, so any working directory):
    uv run --with pillow python tools/compose_kenney_sheet.py

    # one pack:
    uv run --with pillow python tools/compose_kenney_sheet.py \\
        game-assets/kenney_isometric-miniature-farm.zip game-assets/kenney_farm_sheet.png

The Kenney packs are CC0 (www.kenney.nl), and so are the sheets.
"""
from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "game-assets"
DEFAULT_PACKS = [
    (ASSETS / "kenney_isometric-miniature-farm.zip", ASSETS / "kenney_farm_sheet.png"),
    (ASSETS / "kenney_isometric-miniature-library.zip", ASSETS / "kenney_library_sheet.png"),
]
GUTTER = 8
MAX_WIDTH = 2048
FOLDER = "Isometric/"
SUFFIX = "_S.png"


def load_sprites(zip_path: Path) -> list[tuple[str, Image.Image]]:
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(
            n for n in archive.namelist()
            if n.startswith(FOLDER) and "/" not in n[len(FOLDER):] and n.endswith(SUFFIX)
        )
        return [(n, Image.open(io.BytesIO(archive.read(n))).convert("RGBA")) for n in names]


def pack(sprites: list[Image.Image], max_width: int = MAX_WIDTH, gutter: int = GUTTER) -> Image.Image:
    """Row (shelf) packing in the given order; ``gutter`` px around every sprite."""
    placements, x, y, row_h, width = [], gutter, gutter, 0, 0
    for sprite in sprites:
        w, h = sprite.size
        if w + 2 * gutter > max_width:
            raise ValueError(f"a sprite of {w} px does not fit a {max_width} px row")
        if x + w + gutter > max_width:
            x, y, row_h = gutter, y + row_h + gutter, 0
        placements.append((sprite, (x, y)))
        width = max(width, x + w + gutter)
        x += w + gutter
        row_h = max(row_h, h)
    sheet = Image.new("RGBA", (width, y + row_h + gutter), (0, 0, 0, 0))
    for sprite, pos in placements:
        sheet.alpha_composite(sprite, pos)
    return sheet


def compose(zip_path: Path, out_path: Path) -> tuple[int, tuple[int, int]]:
    sprites = load_sprites(zip_path)
    if not sprites:
        raise ValueError(f"no {FOLDER}*{SUFFIX} files in {zip_path}")
    sheet = pack([s for _, s in sprites])
    sheet.save(out_path, optimize=True)
    return len(sprites), sheet.size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip", nargs="?", type=Path, help="Kenney isometric miniature zip")
    parser.add_argument("out", nargs="?", type=Path, help="output PNG")
    args = parser.parse_args()
    jobs = [(args.zip, args.out)] if args.zip and args.out else DEFAULT_PACKS
    for zip_path, out_path in jobs:
        count, (w, h) = compose(zip_path, out_path)
        print(f"{out_path.name}: {count} objects, {w} x {h} px")


if __name__ == "__main__":
    main()
