"""Generate the Digger's dirt-pile decal (`vfx_dirt_pile`) from `base_hole`.

    py tools/gen_dirt_pile_sheet.py [--data-dir PATH]

A one-shot ART GENERATOR, not runtime code — the `tools/gen_wall_sheets.py`
precedent, but DERIVING from an existing imported sprite instead of drawing
from scratch: the user's own framing is "reuse and simplify the sprite for
our hole" for "the hole the Digger makes when digging in", and `base_hole`
(`data/sprites/imported/base_hole.png`, the map's `base` slot — the thing
this whole game is themed around protecting) is exactly that sprite. The PNG
this script writes is COMMITTED, EDITABLE content (D-31) — repaint it freely;
this script is only how it was seeded, and re-running it overwrites it.

Headless + deterministic + idempotent: SDL dummy drivers are set before
pygame is imported (no window is ever created beyond the offscreen display
mode `convert_alpha` needs), there is no RNG, and every run reproduces the
same PNG bytes from the same `base_hole.png` input.

-- The simplification -------------------------------------------------------
`base_hole` is a `core`-category frame (64x96, one `idle` row); `vfx_dirt_
pile` is a `vfx`-category slot (64x64, one `idle` row, `data/slots.json`) —
so this can never be a bare re-point, some real transform is unavoidable.
The whole sprite is a 64x96 frame with the actual hole graphic occupying a
small opaque region near its vertical centre (the universal frame-centred-on-
the-tile-diamond anchor convention, `engine/render/CLAUDE.md`); everything
else is transparent padding. "Simplify" here means: crop to that opaque
content (`Surface.get_bounding_rect`, alpha-based — no manual coordinates to
keep in sync with a repaint), scale it up by `SCALE_FACTOR` so it reads as an
intentional decal rather than a thumbnail, and centre it on a fresh 64x64
SRCALPHA canvas. No recolor, no new geometry — the dig-hole is deliberately
recognisable as a smaller cousin of the base hole, not a reinterpretation.
"""
import argparse
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pygame  # noqa: E402

from engine import data_io  # noqa: E402

SOURCE_SLOT = "base_hole"
TARGET_SLOT = "vfx_dirt_pile"
FRAME_W, FRAME_H = 64, 64        # the vfx category's frame size (slots.json)
SCALE_FACTOR = 1.4               # how much bigger than the cropped source


def build_sheet(source_path):
    """Return the 64x64 SRCALPHA surface for `vfx_dirt_pile`, cropped and
    scaled from `source_path` (a 64x96 `base_hole`-shaped sprite)."""
    source = pygame.image.load(str(source_path)).convert_alpha()
    content = source.get_bounding_rect()
    cropped = source.subsurface(content).copy()
    w, h = cropped.get_size()
    scaled_size = (max(1, round(w * SCALE_FACTOR)),
                   max(1, round(h * SCALE_FACTOR)))
    scaled = pygame.transform.scale(cropped, scaled_size)

    canvas = pygame.Surface((FRAME_W, FRAME_H), pygame.SRCALPHA)
    canvas.fill((0, 0, 0, 0))
    dest = ((FRAME_W - scaled_size[0]) // 2, (FRAME_H - scaled_size[1]) // 2)
    canvas.blit(scaled, dest)
    return canvas


def _entry():
    return {
        "sheet": f"imported/{TARGET_SLOT}.png",
        "frame_w": FRAME_W,
        "frame_h": FRAME_H,
        "offset_x": 0,
        "offset_y": 0,
        "rows": [{
            "animation": "idle",
            "frames": 1,
            "fps": 8,
            "hidden": [],
            "loop_start": 0,
            "loop_end": 0,
            "loop_count": 1,
        }],
    }


def generate(data_dir):
    """Write the PNG + its manifest entry. Returns the target slot key."""
    imported = Path(data_dir) / "sprites" / "imported"
    source_path = imported / f"{SOURCE_SLOT}.png"
    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} not found - {SOURCE_SLOT} must be imported first")

    pygame.init()
    try:
        pygame.display.set_mode((1, 1))  # convert_alpha needs a display mode
        sheet = build_sheet(source_path)
        pygame.image.save(sheet, str(imported / f"{TARGET_SLOT}.png"))
    finally:
        pygame.quit()

    manifest_path = Path(data_dir) / "sprites" / "asset_manifest.json"
    schema_path = Path(data_dir) / "schemas" / "asset_manifest.schema.json"
    doc = data_io.load_json(manifest_path)
    doc["entries"][TARGET_SLOT] = _entry()
    data_io.write_validated(doc, manifest_path, schema_path)
    return TARGET_SLOT


def main(data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    slot = generate(data_dir)
    print(f"gen_dirt_pile_sheet: wrote {slot} ({FRAME_W}x{FRAME_H}), "
          f"derived from {SOURCE_SLOT} + manifest entry")
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(main(data_dir=args.data_dir))
