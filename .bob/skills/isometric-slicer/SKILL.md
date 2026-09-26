---
name: isometric-slicer
description: Automated dual-strategy spritesheet slicing for 2D isometric games using OpenCV contour detection and uniform grid fallback.
---

# Isometric Spritesheet Slicer Skill

## Overview
This skill processes raw spritesheets (`.png`) and converts them into individual tile chips and metadata. 
It uses a **dual-strategy slicing approach**:
1. **Primary Strategy (Contour Slicing):** Uses `cv2.findContours` and alpha channel thresholding to locate sprite bounds with transparent gutters.
2. **Fallback Strategy (Uniform Grid Slicing):** When tiles touch without transparent gutters, it slices the texture into fixed isometric tiles (e.g., 64x32 base with height offsets).

---

## Usage Instructions for IBM Bob

### 1. Execution Command
To run the automated slicer:
```bash
python3 .bob/skills/isometric-slicer/scripts/slice_spritesheet.py \
  --input <path_to_spritesheet.png> \
  --output-dir <output_directory> \
  --tile-width 64 \
  --tile-height 32
```

### 2. Output Artifacts
* Individual tile chips saved as `<output_dir>/tile_XXX.png`.
* `slices_manifest.json` containing:
  * `tile_id`: Unique index.
  * `bounding_box`: `[x, y, width, height]`.
  * `anchor_offset`: `[offset_x, offset_y]` for vertical structures.
  * `is_transparent`: Boolean flag.

### 3. Downstream Hand-off
Pass `slices_manifest.json` and generated tile chips to the **Tile Classification Agent** and **Collision & Physics Agent** to compile the `asset_catalog.json`.
