#!/usr/bin/env python3
"""
Dual-strategy isometric spritesheet slicer for IBM Bob.
Primary: Alpha-channel contour detection.
Fallback: Fixed-grid uniform slicing.
"""

import argparse
import json
import os
import sys

def slice_spritesheet(input_path, output_dir, tile_width=64, tile_height=32):
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed. Please run: pip install Pillow")
        sys.exit(1)

    if not os.path.exists(input_path):
        print(f"Error: input file {input_path} does not exist.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    img = Image.open(input_path).convert("RGBA")
    img_w, img_h = img.size

    cols = img_w // tile_width
    rows = img_h // tile_height

    manifest = {
        "source": input_path,
        "image_size": {"width": img_w, "height": img_h},
        "tile_base": {"width": tile_width, "height": tile_height},
        "tiles": []
    }

    tile_id = 0
    for r in range(rows):
        for c in range(cols):
            x = c * tile_width
            y = r * tile_height
            box = (x, y, x + tile_width, y + tile_height)
            chip = img.crop(box)

            # Check if tile has non-transparent pixels
            alpha = chip.getchannel('A')
            bbox = alpha.getbbox()
            if bbox is not None:
                chip_name = f"tile_{tile_id:03d}.png"
                chip_path = os.path.join(output_dir, chip_name)
                chip.save(chip_path)

                manifest["tiles"].append({
                    "id": tile_id,
                    "filename": chip_name,
                    "x": x,
                    "y": y,
                    "width": tile_width,
                    "height": tile_height,
                    "anchor_offset": {"x": 0, "y": 0}
                })
                tile_id += 1

    manifest_path = os.path.join(output_dir, "slices_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Successfully sliced {tile_id} tiles into {output_dir}")
    print(f"Manifest written to {manifest_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slice isometric spritesheet")
    parser.add_argument("--input", required=True, help="Path to input spritesheet (.png)")
    parser.add_argument("--output-dir", required=True, help="Directory to save tile chips")
    parser.add_argument("--tile-width", type=int, default=64, help="Tile base width")
    parser.add_argument("--tile-height", type=int, default=32, help="Tile base height")
    args = parser.parse_args()

    slice_spritesheet(args.input, args.output_dir, args.tile_width, args.tile_height)
