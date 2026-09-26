#!/usr/bin/env python3
"""
prepare_characters.py
Converts raw character assets from zip files into game-ready spritesheets.

Usage (from any working directory):
    uv run --with pillow python tools/prepare_characters.py

    # or with explicit paths:
    uv run --with pillow python tools/prepare_characters.py \\
        --input-dir /path/to/game-assets \\
        --output-dir /path/to/characters

Defaults resolve from the repository root (the directory containing tools/),
so the script works regardless of the current working directory.
Relative paths passed on the command line resolve from the current working directory.

See ASSET_SPEC.md §4 for output format.
"""

import argparse
import io
import json
import os
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Direction mapping constants — correct these if the visual output looks wrong
# ---------------------------------------------------------------------------

# Zombie (engvee) angle → ASSET_SPEC direction.
# Angle 0 = zombie faces away from camera (back = N). Angles increase CW.
# 16 angles at 22.5° steps. We keep only every-other angle (8 of 16).
# Format: angle_string_as_in_zip → direction_name
ZOMBIE_ANGLE_TO_DIR = {
    "0":   "N",
    "045": "NE",
    "090": "E",
    "135": "SE",
    "180": "S",
    "225": "SW",
    "270": "W",
    "315": "NW",
}

# Survivor (Game Gland death_city) column → direction.
# survivor.png: COLUMNS are directions, ROWS are animation frames.
# Columns 0-7: S, SE, E, NE, N, NW, W, SW. Columns 8-9 are empty.
# Format: col_index → direction_name
SURVIVOR_COL_TO_DIR = {
    0: "S",
    1: "SE",
    2: "E",
    3: "NE",
    4: "N",
    5: "NW",
    6: "W",
    7: "SW",
}

# Survivor animation row ranges (rows are frames, each named animation occupies specific rows).
# Row 0   = idle   (1 frame)
# Row 1   = attack (1 frame)
# Rows 2-5 = walk  (4 frames)
# Rows 6-7 = die   (2 frames)
SURVIVOR_ANIM_ROWS = {
    "idle":   (0, 0),   # (first_row, last_row), inclusive
    "attack": (1, 1),
    "walk":   (2, 5),
    "die":    (6, 7),
}

# ---------------------------------------------------------------------------
# Animation config
# ---------------------------------------------------------------------------

# Zombie animation name in zip → output name
ZOMBIE_ANIMS = {
    "Idle":    "idle",
    "Walk":    "walk",
    "Attack1": "attack",
    "Death1":  "die",
}

# ASSET_SPEC canonical direction order
DIR_ORDER = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NATIVE_ZOMBIE_FRAME = 256  # px, native frame size in source zip


def count_frames(img: Image.Image, frame_px: int) -> int:
    """Return total frames in a strip/grid, skipping fully-transparent trailing frames."""
    cols = img.width // frame_px
    rows = img.height // frame_px
    total = cols * rows
    for i in range(total - 1, -1, -1):
        row, col = divmod(i, cols)
        frame = img.crop((col * frame_px, row * frame_px,
                          (col + 1) * frame_px, (row + 1) * frame_px))
        if frame.mode != "RGBA":
            frame = frame.convert("RGBA")
        if any(p > 0 for p in frame.split()[3].getdata()):
            return i + 1
    return 0


def load_png_from_zip(zf: zipfile.ZipFile, path: str) -> Image.Image:
    with zf.open(path) as f:
        img = Image.open(io.BytesIO(f.read()))
        img.load()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def alpha_composite_shadow_under_body(body: Image.Image, shadow: Image.Image) -> Image.Image:
    """Composite shadow beneath body (shadow = background, body = foreground)."""
    result = Image.new("RGBA", body.size, (0, 0, 0, 0))
    result.alpha_composite(shadow)
    result.alpha_composite(body)
    return result


def compute_anchor_y(frames: list, frame_h: int, alpha_threshold: int = 128) -> int:
    """
    Return the median bottom-row of the alpha bounding box across all supplied frames.
    'Bottom row' = the highest y index (0-based) that contains at least one pixel
    whose alpha >= alpha_threshold.  Falls back to frame_h - 1 if every frame is
    fully transparent.
    """
    bottoms = []
    for frame in frames:
        if frame.mode != "RGBA":
            frame = frame.convert("RGBA")
        alpha = frame.split()[3]
        bottom = None
        for y in range(frame_h - 1, -1, -1):
            row = alpha.crop((0, y, frame.width, y + 1))
            if any(p >= alpha_threshold for p in row.getdata()):
                bottom = y
                break
        if bottom is not None:
            bottoms.append(bottom)
    if not bottoms:
        return frame_h - 1
    bottoms.sort()
    return bottoms[len(bottoms) // 2]


def save_sheet_and_json(
    frames_by_dir: dict,   # dir_name → list of RGBA Image
    out_path: Path,
    frame_w: int,
    frame_h: int,
    anchor_y: int,
    fps: int = 10,
) -> dict:
    """Build spritesheet ordered by DIR_ORDER, save PNG + JSON sidecar."""
    ordered_dirs = [d for d in DIR_ORDER if d in frames_by_dir]
    n_dirs = len(ordered_dirs)
    n_frames = max(len(frames_by_dir[d]) for d in ordered_dirs)

    sheet = Image.new("RGBA", (n_frames * frame_w, n_dirs * frame_h), (0, 0, 0, 0))

    for row_idx, direction in enumerate(ordered_dirs):
        frames = frames_by_dir[direction]
        for col_idx, frame in enumerate(frames):
            x = col_idx * frame_w
            y = row_idx * frame_h
            sheet.paste(frame, (x, y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG")

    meta = {
        "frame_width": frame_w,
        "frame_height": frame_h,
        "directions": ordered_dirs,
        "frames": n_frames,
        "fps": fps,
        "anchor": {"x": frame_w // 2, "y": anchor_y},
    }
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(meta, indent=2))
    return meta


# ---------------------------------------------------------------------------
# Zombie processing
# ---------------------------------------------------------------------------

def _load_zombie_anim_frames(zf: zipfile.ZipFile, zip_names: set,
                              zip_anim: str, frame_size: int) -> dict:
    """Load and composite all frames for one zombie animation. Returns frames_by_dir."""
    frames_by_dir: dict[str, list] = {}
    for angle_str, direction in ZOMBIE_ANGLE_TO_DIR.items():
        body_path = f"x256_Spritesheets/{zip_anim}/{zip_anim} Body {angle_str}.png"
        shadow_path = f"x256_Spritesheets/{zip_anim}/{zip_anim} Shadow {angle_str}.png"

        if body_path not in zip_names:
            print(f"  [WARN] Missing: {body_path}")
            continue

        body_sheet = load_png_from_zip(zf, body_path)

        has_shadow = shadow_path in zip_names
        if has_shadow:
            shadow_sheet = load_png_from_zip(zf, shadow_path)
            if shadow_sheet.size != body_sheet.size:
                has_shadow = False

        n_frames = count_frames(body_sheet, NATIVE_ZOMBIE_FRAME)
        cols = body_sheet.width // NATIVE_ZOMBIE_FRAME

        dir_frames = []
        for i in range(n_frames):
            row, col = divmod(i, cols)
            x0 = col * NATIVE_ZOMBIE_FRAME
            y0 = row * NATIVE_ZOMBIE_FRAME
            x1 = x0 + NATIVE_ZOMBIE_FRAME
            y1 = y0 + NATIVE_ZOMBIE_FRAME

            body_frame = body_sheet.crop((x0, y0, x1, y1))
            if has_shadow:
                shadow_frame = shadow_sheet.crop((x0, y0, x1, y1))
                composited = alpha_composite_shadow_under_body(body_frame, shadow_frame)
            else:
                composited = body_frame

            scaled = composited.resize((frame_size, frame_size), Image.LANCZOS)
            dir_frames.append(scaled)

        frames_by_dir[direction] = dir_frames
    return frames_by_dir


def process_zombie(input_dir: Path, output_dir: Path, frame_size: int) -> list:
    """Process engvee zombie sheets. Returns list of summary rows."""
    zombie_zip = input_dir / "Skin1_x256_Spritesheets.zip"
    out_subdir = output_dir / "zombie"
    summary = []

    with zipfile.ZipFile(zombie_zip) as zf:
        zip_names = set(zf.namelist())

        # Compute shared anchor from idle animation frames only.
        idle_frames_by_dir = _load_zombie_anim_frames(zf, zip_names, "Idle", frame_size)
        idle_all = [f for flist in idle_frames_by_dir.values() for f in flist]
        shared_anchor_y = compute_anchor_y(idle_all, frame_size)
        print(f"  zombie anchor.y (from idle): {shared_anchor_y}")

        for zip_anim, out_anim in ZOMBIE_ANIMS.items():
            # Re-use already-loaded idle frames; load others fresh.
            if zip_anim == "Idle":
                frames_by_dir = idle_frames_by_dir
            else:
                frames_by_dir = _load_zombie_anim_frames(zf, zip_names, zip_anim, frame_size)

            out_path = out_subdir / f"zombie_{out_anim}.png"
            meta = save_sheet_and_json(frames_by_dir, out_path, frame_size, frame_size,
                                       anchor_y=shared_anchor_y)
            summary.append({
                "character": "zombie",
                "animation": out_anim,
                "directions": len(frames_by_dir),
                "frames": meta["frames"],
                "sheet_size": f"{meta['frames'] * frame_size}x{len(frames_by_dir) * frame_size}",
                "output": str(out_path.name),
            })
            print(f"  zombie/{out_anim}: {len(frames_by_dir)} dirs x {meta['frames']} frames → {out_path.name}")

    return summary


# ---------------------------------------------------------------------------
# Survivor processing
# ---------------------------------------------------------------------------

def process_survivor(input_dir: Path, output_dir: Path) -> list:
    """
    Process Game Gland survivor sheet.

    Layout of survivor.png (64x64 frames, 640x512 = 10 cols x 8 rows):
      Columns 0-7 → directions: S, SE, E, NE, N, NW, W, SW  (cols 8-9 are empty)
      Rows        → animation frames:
                    0       = idle   (1 frame)
                    1       = attack (1 frame)
                    2-5     = walk   (4 frames)
                    6-7     = die    (2 frames)

    Output: one PNG per animation, rows = ASSET_SPEC DIR_ORDER, columns = frames.
    """
    death_city_zip = input_dir / "death_city.zip"
    out_subdir = output_dir / "player"
    summary = []

    FRAME_W = 64
    FRAME_H = 64

    with zipfile.ZipFile(death_city_zip) as zf:
        with zf.open("death_city/assets/survivor.png") as f:
            img = Image.open(io.BytesIO(f.read()))
            img.load()
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Build direction → source column lookup
    dir_to_src_col = {d: col for col, d in SURVIVOR_COL_TO_DIR.items()}

    # Build output row order: DIR_ORDER, mapping each direction to its source column
    ordered_dirs = [(d, dir_to_src_col[d]) for d in DIR_ORDER if d in dir_to_src_col]
    n_dirs = len(ordered_dirs)

    # Compute shared anchor from idle frames only (row 0 = idle).
    idle_row_start, idle_row_end = SURVIVOR_ANIM_ROWS["idle"]
    idle_frames = [
        img.crop((src_col * FRAME_W, r * FRAME_H, (src_col + 1) * FRAME_W, (r + 1) * FRAME_H))
        for _, src_col in ordered_dirs
        for r in range(idle_row_start, idle_row_end + 1)
    ]
    shared_anchor_y = compute_anchor_y(idle_frames, FRAME_H)
    print(f"  survivor anchor.y (from idle): {shared_anchor_y}")

    for anim_name, (row_start, row_end) in SURVIVOR_ANIM_ROWS.items():
        src_rows = list(range(row_start, row_end + 1))
        n_frames = len(src_rows)

        sheet = Image.new("RGBA", (n_frames * FRAME_W, n_dirs * FRAME_H), (0, 0, 0, 0))

        for out_row_idx, (direction, src_col) in enumerate(ordered_dirs):
            for out_col_idx, src_row in enumerate(src_rows):
                # In the source image: x = direction col, y = frame row
                frame = img.crop((
                    src_col * FRAME_W, src_row * FRAME_H,
                    (src_col + 1) * FRAME_W, (src_row + 1) * FRAME_H,
                ))
                sheet.paste(frame, (out_col_idx * FRAME_W, out_row_idx * FRAME_H))

        out_path = out_subdir / f"survivor_{anim_name}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path, "PNG")

        directions_list = [d for d, _ in ordered_dirs]
        meta = {
            "frame_width": FRAME_W,
            "frame_height": FRAME_H,
            "directions": directions_list,
            "frames": n_frames,
            "fps": 10,
            "anchor": {"x": FRAME_W // 2, "y": shared_anchor_y},
        }
        out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))

        summary.append({
            "character": "survivor",
            "animation": anim_name,
            "directions": n_dirs,
            "frames": n_frames,
            "sheet_size": f"{n_frames * FRAME_W}x{n_dirs * FRAME_H}",
            "output": out_path.name,
        })
        print(f"  survivor/{anim_name}: {n_dirs} dirs x {n_frames} frames → {out_path.name}")

    return summary


# ---------------------------------------------------------------------------
# Preview contact sheet
# ---------------------------------------------------------------------------

def build_preview(output_dir: Path, zombie_frame: int):
    """
    Build preview_directions.png: a contact sheet showing all 8 directions
    for both characters using the walk animation, labeled, with a
    checkerboard background to make transparency visible.
    """
    CELL_W = max(zombie_frame, 64)
    CELL_H = max(zombie_frame, 64)
    LABEL_H = 18
    PADDING = 4
    CHECKER = 8  # checker square size in px

    characters = []

    # Zombie walk — first frame of each direction row
    zombie_walk = output_dir / "zombie" / "zombie_walk.png"
    if zombie_walk.exists():
        sheet = Image.open(zombie_walk).convert("RGBA")
        json_data = json.loads((zombie_walk.with_suffix(".json")).read_text())
        fw = json_data["frame_width"]
        fh = json_data["frame_height"]
        dirs = json_data["directions"]
        frames = []
        for row_idx, d in enumerate(dirs):
            frame = sheet.crop((0, row_idx * fh, fw, (row_idx + 1) * fh))
            frame = frame.resize((CELL_W, CELL_H), Image.LANCZOS)
            frames.append((d, frame))
        characters.append(("Zombie (walk fr0)", frames))

    # Survivor walk — first frame of each direction row
    survivor_walk = output_dir / "player" / "survivor_walk.png"
    if survivor_walk.exists():
        sheet = Image.open(survivor_walk).convert("RGBA")
        json_data = json.loads((survivor_walk.with_suffix(".json")).read_text())
        fw = json_data["frame_width"]
        fh = json_data["frame_height"]
        dirs = json_data["directions"]
        frames = []
        for row_idx, d in enumerate(dirs):
            frame = sheet.crop((0, row_idx * fh, fw, (row_idx + 1) * fh))
            frame = frame.resize((CELL_W, CELL_H), Image.LANCZOS)
            frames.append((d, frame))
        characters.append(("Survivor (walk fr0)", frames))

    if not characters:
        print("  [WARN] No character sheets found for preview.")
        return

    n_dirs = 8
    n_chars = len(characters)
    label_col_w = 80  # left-side label column
    img_w = label_col_w + n_dirs * (CELL_W + PADDING) + PADDING
    row_h = CELL_H + LABEL_H + PADDING
    # header row + one row per character
    img_h = LABEL_H + PADDING + n_chars * (row_h + PADDING * 2)

    preview = Image.new("RGBA", (img_w, img_h), (240, 240, 240, 255))
    draw = ImageDraw.Draw(preview)

    # Checkerboard tile
    checker = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    for cy in range(0, CELL_H, CHECKER):
        for cx in range(0, CELL_W, CHECKER):
            color = (200, 200, 200, 255) if (cx // CHECKER + cy // CHECKER) % 2 == 0 else (160, 160, 160, 255)
            for py in range(min(CHECKER, CELL_H - cy)):
                for px in range(min(CHECKER, CELL_W - cx)):
                    checker.putpixel((cx + px, cy + py), color)

    # Direction header
    for i, d in enumerate(DIR_ORDER):
        x = label_col_w + PADDING + i * (CELL_W + PADDING) + CELL_W // 2
        draw.text((x, PADDING), d, fill=(60, 60, 60, 255), anchor="mt")

    y_cursor = LABEL_H + PADDING * 2

    for char_label, frames_list in characters:
        # Character label
        draw.text((4, y_cursor + CELL_H // 2), char_label, fill=(40, 40, 40, 255), anchor="lm")

        dir_map = {d: frm for d, frm in frames_list}
        for i, d in enumerate(DIR_ORDER):
            x = label_col_w + PADDING + i * (CELL_W + PADDING)
            # Paste checker background
            preview.alpha_composite(checker, (x, y_cursor))
            # Paste character frame
            if d in dir_map:
                preview.alpha_composite(dir_map[d], (x, y_cursor))
            # Direction label below frame
            draw.text((x + CELL_W // 2, y_cursor + CELL_H + 2), d,
                      fill=(80, 80, 80, 255), anchor="mt")

        y_cursor += row_h + PADDING * 2

    out_path = output_dir / "preview_directions.png"
    preview.save(out_path, "PNG")
    print(f"  preview → {out_path}")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(summary: list):
    print()
    print("=" * 80)
    print(f"{'CHARACTER':<12} {'ANIMATION':<28} {'DIRS':>5} {'FRAMES':>7} {'SHEET SIZE':>16}  OUTPUT")
    print("-" * 80)
    for row in summary:
        print(f"{row['character']:<12} {row['animation']:<28} {row['directions']:>5} {row['frames']:>7} {row['sheet_size']:>16}  {row['output']}")
    print("=" * 80)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Repository root = the directory containing tools/ = parent of this script's directory.
    _repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(description="Convert raw character assets to game-ready spritesheets.")
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory containing the source zip files "
             "(default: <repo_root>/game-assets)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for processed spritesheets "
             "(default: <repo_root>/z_legend_game/z_legend_game_flutter/assets/images/characters)",
    )
    parser.add_argument("--zombie-frame-size", type=int, default=128,
                        help="Output frame size in pixels for zombie sprites (default: 128)")
    args = parser.parse_args()

    # Use repo-root-relative defaults; honour explicit CLI paths relative to cwd.
    input_dir = Path(args.input_dir) if args.input_dir is not None else _repo_root / "game-assets"
    output_dir = (
        Path(args.output_dir)
        if args.output_dir is not None
        else _repo_root / "z_legend_game" / "z_legend_game_flutter" / "assets" / "images" / "characters"
    )
    frame_size = args.zombie_frame_size

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Zombie frame size: {frame_size}x{frame_size}")
    print()

    # Early check: death_city.zip is git-ignored (license).  Give the user a
    # clear message rather than a cryptic FileNotFoundError later.
    death_city_zip = input_dir / "death_city.zip"
    if not death_city_zip.exists():
        print(
            f"ERROR: {death_city_zip} not found.\n"
            "This file is git-ignored (license: no redistribution).\n"
            "Download it from https://gamegland.itch.io/zombie-apocalypse-character-spritesheet"
            f" and place it in {input_dir}/.",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1)

    summary = []

    print("Processing zombie (engvee Skin1)...")
    summary.extend(process_zombie(input_dir, output_dir, frame_size))

    print()
    print("Processing survivor (Game Gland death_city)...")
    summary.extend(process_survivor(input_dir, output_dir))

    print()
    print("Building preview_directions.png...")
    build_preview(output_dir, frame_size)

    print_summary(summary)


if __name__ == "__main__":
    main()
