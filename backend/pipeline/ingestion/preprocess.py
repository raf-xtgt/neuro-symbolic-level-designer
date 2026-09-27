"""
Deterministic pre-processor (Pipeline 1, ARCHITECTURE.md 3.1).

1. Base tile size detection: the isometric base diamond (2:1) of the sheet,
   from floor-like chips whose opaque mask is a full diamond (or a diamond
   top face on a thin slab, as in block-style tiles). Candidates: 32 x 16,
   64 x 32, 128 x 64, 256 x 128. A sheet that is not 64 x 32 is scaled to the
   64 x 32 standard (``game-assets/ASSET_SPEC.md``) with LANCZOS before
   slicing. No diamond found: 64 x 32 is assumed, with a warning.
2. Slicing (``slicer.py``: contour + grid fallback at the detected tile
   size) on the ORIGINAL sheet, so scaling cannot close the gutters between
   sprites; the rectangles are then scaled. Or the grid of a matching legacy
   tileset.
3. Clean-up: chips smaller than 6 x 6 px or with fewer than 40 opaque pixels
   are noise; exact duplicates (same pixels) are merged and counted.
4. Geometry per chip: tight alpha box, anchor estimate (the diamond center
   for a full base diamond, the top face on a slab; otherwise the foot: the
   horizontal center of the lowest SOLID rows (alpha >= 200, so soft shadows
   do not count), lifted by ``H/2 * min(1, base width / W)``: a sprite that
   fills its base diamond reaches its front vertex, H/2 below the tile
   center, while a trunk or a post touches the ground at the center),
   footprint in tiles, and the
   collision polygon (contour of the lowest ``H`` px, at most 8 points).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pipeline.ingestion import slicer

BASE_W, BASE_H = 64, 32
CANDIDATE_WIDTHS = (32, 64, 128, 256)
MIN_SIDE = 6
MIN_OPAQUE = 40
DIAMOND_COVERAGE = 0.95  # opaque share of the diamond template
DIAMOND_SPILL = 0.10  # opaque share of the upper corners outside the diamond
DIAMOND_ALPHA = 128  # the diamond test counts solid pixels only (scaled sheets have soft edges)
HALO_ALPHA = 48  # after scaling, fainter pixels are resampling halo
MIN_DIAMONDS = 2
FOOT_ROWS = 4  # lowest solid rows used for the anchor
FOOT_ALPHA = 200  # solid pixels for the foot (shadows are softer)
MAX_POLYGON_POINTS = 8


@dataclass
class ChipInfo:
    number: int  # unique in the job
    sheet: int  # index of the sheet in the job
    rect: tuple[int, int, int, int]  # tight box in the (scaled) sheet: x, y, w, h
    strategy: str  # contour, grid, legacy
    anchor: tuple[int, int]  # in the tight box
    is_diamond: bool
    footprint: int  # tiles, from the width of the base
    collision_polygon: list[tuple[int, int]]
    opaque_pixels: int
    pixel_hash: str
    duplicates: int = 0  # other chips with the same pixels
    legacy: dict = field(default_factory=dict)  # tileset ground truth, if any

    def image(self, sheet: Image.Image) -> Image.Image:
        x, y, w, h = self.rect
        return sheet.crop((x, y, x + w, y + h))

    def as_dict(self) -> dict:
        return {
            "number": self.number, "sheet": self.sheet, "rect": list(self.rect), "strategy": self.strategy,
            "anchor": list(self.anchor), "is_diamond": self.is_diamond, "footprint": self.footprint,
            "collision_polygon": [list(p) for p in self.collision_polygon], "opaque_pixels": self.opaque_pixels,
            "duplicates": self.duplicates, "legacy": self.legacy,
        }


@dataclass
class SheetInfo:
    index: int
    name: str  # original upload name
    source: str  # catalog-style path of the (scaled) sheet, relative to the job folder
    size: tuple[int, int]  # after scaling
    original_size: tuple[int, int]
    tile_size: tuple[int, int]  # detected base diamond, before scaling
    scale: float
    diamonds: int
    warnings: list[str] = field(default_factory=list)
    dropped_noise: int = 0
    merged_duplicates: int = 0

    def as_dict(self) -> dict:
        return {
            "index": self.index, "name": self.name, "source": self.source, "size": list(self.size),
            "original_size": list(self.original_size), "tile_size": list(self.tile_size), "scale": self.scale,
            "diamonds": self.diamonds, "warnings": self.warnings, "dropped_noise": self.dropped_noise,
            "merged_duplicates": self.merged_duplicates,
        }


# ---------------------------------------------------------------------------
# Diamonds and tile size
# ---------------------------------------------------------------------------

def diamond_template(w: int, h: int) -> np.ndarray:
    """Boolean mask of a w x h diamond (pixel centers inside the rhombus)."""
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2
    return (np.abs(xs + 0.5 - cx) / (w / 2) + np.abs(ys + 0.5 - cy) / (h / 2)) <= 1.0 + 1e-9


def is_base_diamond(mask: np.ndarray, w: int) -> bool:
    """
    True if ``mask`` (opaque = 1, a chip's tight box) is a full w x w/2 base
    diamond, or a diamond top face on a slab no thicker than w/4.
    """
    h = w // 2
    mh, mw = mask.shape
    if abs(mw - w) > 2 or not h - 2 <= mh <= h + w // 4:
        return False
    # Center the chip horizontally in the w x h frame (edge columns may be empty).
    region = np.zeros((h, w), dtype=bool)
    left = (w - mw) // 2
    top = mask[:h, max(0, -left): max(0, -left) + w].astype(bool)
    region[: top.shape[0], max(0, left): max(0, left) + top.shape[1]] = top
    template = diamond_template(w, h)
    if (region & template).sum() < DIAMOND_COVERAGE * template.sum():
        return False
    upper = np.zeros_like(template)
    upper[: h // 2] = True
    corners = upper & ~template
    return bool((region & corners).sum() <= DIAMOND_SPILL * corners.sum())


def detect_tile_size(rgba: np.ndarray) -> tuple[int, int]:
    """(base tile width, number of diamonds found); width 0 when none found."""
    mask = (rgba[:, :, 3] >= DIAMOND_ALPHA).astype(np.uint8)
    counts = {w: 0 for w in CANDIDATE_WIDTHS}
    for x, y, w, h in _components(mask):
        region = mask[y:y + h, x:x + w]
        for cw in CANDIDATE_WIDTHS:
            if is_base_diamond(region, cw):
                counts[cw] += 1
            elif w >= 3 * cw or h >= 3 * cw // 2:  # touching sprites: try the grid of the region
                ch = cw // 2
                for gy in range(y, y + h - ch + 1, ch):
                    for gx in range(x, x + w - cw + 1, cw):
                        if is_base_diamond(mask[gy:gy + ch, gx:gx + cw], cw):
                            counts[cw] += 1
    best = max(CANDIDATE_WIDTHS, key=lambda cw: (counts[cw], cw == BASE_W))
    return (best if counts[best] >= MIN_DIAMONDS else 0), counts[best]


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return [tuple(int(v) for v in stats[i][:4]) for i in range(1, count) if stats[i][4] >= MIN_OPAQUE]


def prepare_sheet(path: Path, index: int, name: str, work_dir: Path, job_dir: Path) -> tuple[SheetInfo, Path]:
    """Detects the tile size and scales the sheet to 64 x 32 if needed."""
    image = Image.open(path).convert("RGBA")
    rgba = np.array(image)
    width, diamonds = detect_tile_size(rgba)
    warnings = []
    if width == 0:
        warnings.append(f"{name}: no isometric base diamond found; assuming 64 x 32 tiles")
        width = BASE_W
    scale = BASE_W / width
    sheet_path = path
    if scale != 1:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.LANCZOS)
        # LANCZOS rings a faint alpha halo around every sprite; clear it so
        # tight boxes and gutters stay as in the original.
        scaled = np.array(image)
        scaled[scaled[:, :, 3] < HALO_ALPHA] = 0
        image = Image.fromarray(scaled, "RGBA")
        sheet_path = work_dir / f"sheet_{index}_scaled.png"
        image.save(sheet_path)
    return SheetInfo(
        index=index,
        name=name,
        source=sheet_path.relative_to(job_dir).as_posix(),
        size=image.size,
        original_size=(rgba.shape[1], rgba.shape[0]),
        tile_size=(width, width // 2),
        scale=scale,
        diamonds=diamonds,
        warnings=warnings,
    ), sheet_path


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------

def tight_box(alpha: np.ndarray, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    x, y, w, h = rect
    ys, xs = np.nonzero(alpha[y:y + h, x:x + w] > slicer.ALPHA_THRESHOLD)
    if len(xs) == 0:
        return None
    return x + int(xs.min()), y + int(ys.min()), int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1


def estimate_anchor(mask: np.ndarray, alpha: np.ndarray | None = None) -> tuple[tuple[int, int], bool]:
    """(anchor in the chip, is a full base diamond). ``alpha``: the chip's alpha channel."""
    h, w = mask.shape
    if is_base_diamond(mask, BASE_W):
        return (BASE_W // 2, BASE_H // 2), True
    solid = alpha >= FOOT_ALPHA if alpha is not None else mask.astype(bool)
    if not solid.any():
        solid = mask.astype(bool)
    rows = [r for r in range(h) if solid[r].any()][-FOOT_ROWS:]
    cols = np.nonzero(solid[rows].any(axis=0))[0]
    x = int(round((cols.min() + cols.max() + 1) / 2))
    base = int(cols.max() - cols.min() + 1)
    lift = BASE_H / 2 * min(1.0, base / BASE_W)
    if rows[-1] + 1 < BASE_H:  # a small sprite: stay inside it
        lift = min(lift, (rows[-1] + 1) / 4)
    return (x, int(round(rows[-1] + 1 - lift))), False


def estimate_footprint(mask: np.ndarray) -> int:
    band = mask[-BASE_H // 2:] if mask.shape[0] > BASE_H // 2 else mask
    cols = np.nonzero(band.any(axis=0))[0]
    width = int(cols.max() - cols.min() + 1) if len(cols) else 0
    return max(1, round(width / BASE_W))


def collision_polygon(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contour of the opaque base (lowest ``BASE_H`` px), at most 8 points, in chip pixels."""
    h = mask.shape[0]
    top = max(0, h - BASE_H)
    band = np.zeros_like(mask, dtype=np.uint8)
    band[top:] = mask[top:]
    contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    epsilon = 1.0
    poly = cv2.approxPolyDP(contour, epsilon, True)
    while len(poly) > MAX_POLYGON_POINTS:
        epsilon *= 1.5
        poly = cv2.approxPolyDP(contour, epsilon, True)
    return [(int(p[0][0]), int(p[0][1])) for p in poly]


def scale_rect(rect: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x0, y0 = math.floor(x * scale), math.floor(y * scale)
    return x0, y0, max(1, math.ceil((x + w) * scale) - x0), max(1, math.ceil((y + h) * scale) - y0)


def build_chips(
    sheet_path: Path, sheet: SheetInfo, first_number: int, rects: list[tuple[tuple[int, int, int, int], str, dict]]
    | None = None, original_path: Path | None = None,
) -> list[ChipInfo]:
    """
    Chips of one (scaled) sheet: from ``rects`` (in scaled coordinates, legacy
    tileset grid) or the slicer run on ``original_path`` (default: the sheet
    itself) at the detected tile size, with the rectangles scaled. Noise is
    dropped and duplicates merged (counted on the first).
    """
    rgba = np.array(Image.open(sheet_path).convert("RGBA"))
    alpha = rgba[:, :, 3]
    if rects is None and original_path is not None:
        sliced = slicer.slice_spritesheet(original_path, grid=sheet.tile_size)
        rects = [(scale_rect(c.rect, sheet.scale), c.strategy, {}) for c in sliced]
    elif rects is None:  # the sheet is already at 64 x 32
        rects = [(c.rect, c.strategy, {}) for c in slicer.slice_spritesheet(sheet_path)]
    chips: list[ChipInfo] = []
    by_hash: dict[str, ChipInfo] = {}
    for rect, strategy, legacy in rects:
        box = tight_box(alpha, rect)
        if box is None:
            continue
        x, y, w, h = box
        mask = (alpha[y:y + h, x:x + w] > slicer.ALPHA_THRESHOLD).astype(np.uint8)
        solid = alpha[y:y + h, x:x + w] >= DIAMOND_ALPHA
        opaque = int(mask.sum())
        if (w < MIN_SIDE or h < MIN_SIDE or opaque < MIN_OPAQUE) and not legacy:
            sheet.dropped_noise += 1
            continue
        digest = hashlib.sha256(rgba[y:y + h, x:x + w].tobytes() + bytes(str((w, h)), "ascii")).hexdigest()
        if digest in by_hash and not legacy:
            by_hash[digest].duplicates += 1
            sheet.merged_duplicates += 1
            continue
        anchor, _ = estimate_anchor(mask, alpha[y:y + h, x:x + w])
        diamond = is_base_diamond(solid.astype(np.uint8), BASE_W) or is_base_diamond(mask, BASE_W)
        if diamond:  # the center of the (top face) diamond
            anchor = (w // 2, BASE_H // 2)
        chip = ChipInfo(
            number=first_number + len(chips),
            sheet=sheet.index,
            rect=box,
            strategy=strategy,
            anchor=anchor,
            is_diamond=diamond,
            footprint=estimate_footprint(mask),
            collision_polygon=collision_polygon(mask),
            opaque_pixels=opaque,
            pixel_hash=digest,
            legacy=legacy,
        )
        by_hash[digest] = chip
        chips.append(chip)
    return chips
