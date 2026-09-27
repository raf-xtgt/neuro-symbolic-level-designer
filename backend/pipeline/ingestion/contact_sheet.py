"""
Contact sheets for the analysis agents (Pipeline 1, ARCHITECTURE.md 3.1).

Batches of at most ``BATCH_SIZE`` chips. Each chip is drawn in its own cell on
a neutral checkerboard, scaled to fit (never upscaled beyond 2x), labeled with
its chip number, with a magenta dot on the deterministic anchor estimate. The
text part of the prompt lists every chip with its pixel size and the
deterministic estimates.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from pipeline.ingestion.preprocess import ChipInfo

BATCH_SIZE = 32
COLUMNS = 8
CELL = 160  # drawing area per chip, px
LABEL_H = 18
MAX_UPSCALE = 2.0
_CHECK = 8
_LIGHT, _DARK = (200, 200, 200, 255), (160, 160, 160, 255)
_ANCHOR = (255, 0, 200, 255)


@dataclass
class Batch:
    index: int
    chips: list[ChipInfo]
    image: bytes  # PNG

    @property
    def numbers(self) -> list[int]:
        return [c.number for c in self.chips]

    def chip_list(self) -> str:
        """The text part: one line per chip with the deterministic estimates."""
        lines = []
        for c in self.chips:
            x, y, w, h = c.rect
            line = (
                f"chip {c.number}: {w} x {h} px, anchor estimate ({c.anchor[0]}, {c.anchor[1]}), "
                f"footprint {c.footprint} tile{'s' if c.footprint > 1 else ''}"
                f"{', full 64 x 32 base diamond' if c.is_diamond else ''}"
            )
            if c.duplicates:
                line += f", {c.duplicates} identical copies in the sheet"
            lines.append(line)
        return "\n".join(lines)


def make_batches(chips: list[ChipInfo], sheets: dict[int, Image.Image]) -> list[Batch]:
    return [
        Batch(i, chips[start:start + BATCH_SIZE], render(chips[start:start + BATCH_SIZE], sheets))
        for i, start in enumerate(range(0, len(chips), BATCH_SIZE))
    ]


def _checkerboard(w: int, h: int) -> Image.Image:
    board = Image.new("RGBA", (w, h), _LIGHT)
    draw = ImageDraw.Draw(board)
    for y in range(0, h, _CHECK):
        for x in range(0, w, _CHECK):
            if (x // _CHECK + y // _CHECK) % 2:
                draw.rectangle((x, y, x + _CHECK - 1, y + _CHECK - 1), fill=_DARK)
    return board


def render(chips: list[ChipInfo], sheets: dict[int, Image.Image], anchors: bool = True) -> bytes:
    """One contact sheet image (PNG bytes) for ``chips``."""
    rows = (len(chips) + COLUMNS - 1) // COLUMNS
    cols = min(COLUMNS, len(chips))
    sheet = Image.new("RGBA", (cols * CELL, rows * (CELL + LABEL_H)), (255, 255, 255, 255))
    board = _checkerboard(CELL, CELL)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, chip in enumerate(chips):
        cx, cy = (i % COLUMNS) * CELL, (i // COLUMNS) * (CELL + LABEL_H)
        sheet.paste(board, (cx, cy + LABEL_H))
        sprite = chip.image(sheets[chip.sheet])
        scale = min((CELL - 8) / sprite.width, (CELL - 8) / sprite.height, MAX_UPSCALE)
        size = (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale)))
        sprite = sprite.resize(size, Image.NEAREST if scale > 1 else Image.LANCZOS)
        ox, oy = cx + (CELL - size[0]) // 2, cy + LABEL_H + (CELL - size[1]) // 2
        sheet.alpha_composite(sprite, (ox, oy))
        if anchors:
            ax, ay = ox + chip.anchor[0] * scale, oy + chip.anchor[1] * scale
            draw.ellipse((ax - 3, ay - 3, ax + 3, ay + 3), fill=_ANCHOR, outline=(0, 0, 0, 255))
        draw.rectangle((cx, cy, cx + CELL - 1, cy + LABEL_H + CELL - 1), outline=(90, 90, 90, 255))
        draw.text((cx + 4, cy + 3), f"#{chip.number}", fill=(0, 0, 0, 255), font=font)
    buf = io.BytesIO()
    sheet.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
