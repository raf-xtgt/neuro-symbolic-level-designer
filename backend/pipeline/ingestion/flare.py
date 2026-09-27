"""
Parser for Flare tileset definitions (``tilesetdef`` text files), used as a
legacy definition and as the slicer's answer key.

Format: ``tile=<id>,<x>,<y>,<w>,<h>,<ox>,<oy>`` lines under ``# <section>``
comment lines. ``(x, y, w, h)`` is the sprite rectangle; ``(ox, oy)`` is the
foot point in the sprite (our ``anchor``). A section heading can repeat
(for example two ``# cliffs`` blocks); both map to the same slug.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TILE_RE = re.compile(r"^tile=(\d+),(\d+),(\d+),(\d+),(\d+),(-?\d+),(-?\d+)$")


@dataclass(frozen=True)
class FlareTile:
    section: str  # slug
    flare_id: int
    x: int
    y: int
    w: int
    h: int
    anchor_x: int
    anchor_y: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


def section_slug(heading: str) -> str:
    """'town objects (e.g. containers)' -> 'town_objects'."""
    base = heading.split("(")[0]
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")


def parse_flare_definition(path: str | Path) -> list[FlareTile]:
    """All ``tile=`` lines, with the slug of the ``# section`` above them."""
    tiles, section = [], ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            section = section_slug(line[1:])
            continue
        m = _TILE_RE.match(line.strip())
        if m:
            fid, x, y, w, h, ox, oy = map(int, m.groups())
            tiles.append(FlareTile(section, fid, x, y, w, h, ox, oy))
    return tiles
