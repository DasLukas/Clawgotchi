# CONTRIBUTOR Guide

This guide explains how to create new pet assets and animations for Clawgotchi using the sprite-based theme pipeline.

## 1) Theme Folder Structure

Create a new folder under `themes/`:

```text
themes/
  my_pet/
    manifest.json
    assets/
      idle_0.png
      idle_1.png
      scratch_0.png
      scratch_1.png
      style.css (optional)
```

Required files:
- `manifest.json`
- At least one animation with at least one frame

## 2) Required Manifest Fields

Every theme needs these fields:
- `id`
- `name`
- `default_animation`
- `animations`

Recommended for sprite themes:
- `render.base_sprite_size`
- `placement.mode = "sprite"`
- `placement.anchor`
- `placement.scale_mode`
- `placement.scale`

## 3) Recommended Sprite Format

Use RGBA PNG frames with transparent background:
- Recommended sprite source sizes: `128x128` or `160x160`
- Keep silhouettes clean and high contrast
- Avoid anti-aliased gray edges when possible for stable 1-bit conversion

The renderer scales with nearest-neighbor and converts to 1-bit for hardware and web mirror output.

## 4) Asset Creation Workflow

Recommended workflow when creating a new pet asset pack:
1. Design a master sprite in `128x128` or `160x160`.
2. Export animation frames as RGBA PNG files with transparent background.
3. Name frames using `<animation_name>_<index>.png` (for example `idle_0.png`, `idle_1.png`).
4. Keep frame dimensions consistent within one animation sequence.
5. Place exported files under `themes/<theme_id>/assets/`.
6. Reference every frame in `manifest.json` under `animations.<name>.frames`.

Asset path rules:
- Frame paths in `manifest.json` are relative to the theme directory.
- Reusing assets from another theme is supported via relative paths (for example `../classic/assets/idle_0.png`).
- Missing frame files will fail theme loading at runtime and in tests.

## 5) Sprite Placement and Sidebar-Aware Layout

Clawgotchi always reserves a left sidebar in the framebuffer.

Runtime layout:
- `sidebar_width = clamp(round(width * 0.18), 40, 72)`
- Pet sprites render only in the content rectangle to the right of the sidebar

Placement controls:
- `anchor`: default `bottom_center`
- `offset_x`, `offset_y`: fine position adjustment inside the content area
- `scale_mode`:
  - `integer_only`: rounds to integer scale factors (`1x`, `2x`, ...)
  - `free`: allows fractional scale

## 6) Animation Setup and FPS Guidance

Use short loops and conservative FPS for monochrome displays:
- `idle`: `0.25` to `0.5` FPS
- reaction animation like `scratch`: `1.5` to `3.0` FPS

Keep frame count low to avoid unnecessary refresh overhead.

## 7) Minimal Sprite Manifest Example

```json
{
  "id": "my_pet",
  "name": "My Pet",
  "version": "0.1.0",
  "description": "Sprite-based pet theme",
  "stylesheet": "assets/style.css",
  "render": {
    "base_sprite_size": [160, 160],
    "dither": false,
    "threshold": 128
  },
  "placement": {
    "mode": "sprite",
    "anchor": "bottom_center",
    "offset_x": 0,
    "offset_y": -2,
    "scale_mode": "integer_only",
    "scale": 1.0
  },
  "default_animation": "idle",
  "animations": {
    "idle": {
      "fps": 0.33,
      "frames": [
        "assets/idle_0.png",
        "assets/idle_1.png"
      ]
    },
    "scratch": {
      "fps": 2.0,
      "duration_ms": 1200,
      "frames": [
        "assets/scratch_0.png",
        "assets/scratch_1.png"
      ]
    }
  }
}
```

## 8) Legacy Fullframe Example (Deprecated)

Legacy fullframe is still supported for compatibility, but new themes should use `sprite` mode.

```json
{
  "id": "legacy_pet",
  "name": "Legacy Pet",
  "placement": {
    "mode": "legacy_fullframe"
  },
  "canvas_width": 264,
  "canvas_height": 176,
  "default_animation": "idle",
  "animations": {
    "idle": {
      "fps": 0.33,
      "frames": ["assets/idle_full_0.png"]
    }
  }
}
```

Notes:
- Fullframe frames should match canvas dimensions exactly
- Sidebar remains visible because rendering is clipped to preserve the left menu area

## 9) Testing in Dashboard

1. Start Clawgotchi.
2. Open `/dashboard`.
3. Ensure the mirrored display updates while the pet animates.
4. Use virtual buttons (`NEXT`, `BACK`, `CONFIRM`, `SPECIAL`) to navigate the sidebar menu.

If hardware is enabled, both hardware and dashboard should show the same framebuffer output.

Validation command for asset-related changes:

```bash
python -m pytest -q tests/test_theme_loader.py tests/test_animation_selection.py
```

## 10) 1-bit Quality Checklist

To keep output clean on monochrome displays:
- Prefer solid black/white shapes over gray gradients
- Avoid noisy dithering unless absolutely needed
- Keep edges thick enough for low-resolution readability
- Use high-contrast sprites with minimal texture noise

## 11) Architecture Doc Maintenance

Architecture changes must update `docs/ARCHITECTURE.md` in the same commit.

Relevant architecture paths:
- `app/**`
- `core/**`
- `plugins/**`
- `themes/**`
- `config/**`
- `clawgotchi/**`
- `main.py`
- `install.sh`
- `update.sh`

One-time hook setup:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit scripts/check_architecture_doc_updated.sh
```

What the hook does:
- Runs `scripts/check_architecture_doc_updated.sh`.
- Blocks commit if relevant paths are staged but `docs/ARCHITECTURE.md` is not staged.
