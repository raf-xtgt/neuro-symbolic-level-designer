"""
Deterministic spritesheet slicer (Pipeline 1, ARCHITECTURE.md 3.1).

Two strategies:
  1. Contour slicing: threshold the alpha channel, label 8-connected
     components (``cv2.connectedComponentsWithStats``), and use each
     component's bounding box as a chip. Parts of one sprite that are a few
     pixels apart (branches, tufts) are joined by a small dilation first.
  2. Grid fallback: a component that spans a large area (wider than
     ``MERGED_MIN_WIDTH`` or taller than ``MERGED_MIN_HEIGHT``) is many sprites
     that touch, for example the floor rows where diamonds share edges. That
     region is split on the atlas-aligned ``grid`` (default 64 x 32), keeping
     cells with enough opaque pixels.

Chips are returned sorted by (y, x). The slicer does not classify anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ALPHA_THRESHOLD = 0      # alpha > threshold is opaque
DILATE_PX = 1            # join sprite parts 1-2 px apart (2+ merges neighbours)
MIN_AREA = 32            # components with fewer opaque pixels are noise
MERGED_MIN_WIDTH = 192   # 3 floor tiles wide (at the 64 x 32 grid; scales with the grid)
MERGED_MIN_HEIGHT = 256  # 8 floor tiles tall
GRID_MIN_FILL = 0.10     # grid cells with less opaque area are dropped

Rect = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True)
class Chip:
    rect: Rect
    strategy: str  # "contour" or "grid"


def _opaque_mask(path: str | Path) -> np.ndarray:
    alpha = np.array(Image.open(path).convert("RGBA"))[:, :, 3]
    return (alpha > ALPHA_THRESHOLD).astype(np.uint8)


def _grid_chips(mask: np.ndarray, region: Rect, grid: tuple[int, int]) -> list[Chip]:
    gw, gh = grid
    x, y, w, h = region
    chips = []
    for gy in range(y // gh * gh, y + h, gh):
        for gx in range(x // gw * gw, x + w, gw):
            cell = mask[gy : gy + gh, gx : gx + gw]
            if cell.size and cell.sum() >= GRID_MIN_FILL * gw * gh:
                chips.append(Chip((gx, gy, gw, gh), "grid"))
    return chips


def slice_spritesheet(path: str | Path, grid: tuple[int, int] = (64, 32)) -> list[Chip]:
    """Slices a spritesheet into sprite rectangles."""
    mask = _opaque_mask(path)
    merged_w = MERGED_MIN_WIDTH * grid[0] // 64
    merged_h = MERGED_MIN_HEIGHT * grid[1] // 32
    joined = mask
    if DILATE_PX:
        kernel = np.ones((2 * DILATE_PX + 1, 2 * DILATE_PX + 1), np.uint8)
        joined = cv2.dilate(mask, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    chips: list[Chip] = []
    for label in range(1, count):
        # Bounding box and area of the original (undilated) pixels.
        ys, xs = np.nonzero((labels == label) & (mask == 1))
        if len(xs) < MIN_AREA:
            continue
        x0, y0 = int(xs.min()), int(ys.min())
        rect = (x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1)
        if rect[2] >= merged_w or rect[3] >= merged_h:
            chips.extend(_grid_chips(mask, rect, grid))
        else:
            chips.append(Chip(rect, "contour"))
    return sorted(chips, key=lambda c: (c.rect[1], c.rect[0]))


def iou(a: Rect, b: Rect) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0
