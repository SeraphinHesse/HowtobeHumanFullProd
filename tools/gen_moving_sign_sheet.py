"""Generate the `moving_sign` spritesheet (core slot category) as starting art.

    py tools/gen_moving_sign_sheet.py [--data-dir PATH]

A one-shot ART GENERATOR, not runtime code — the exact shape of
`tools/gen_wall_sheets.py`: it draws a placeholder-but-real "this building is
moving" signpost for the `core` category's flat `moving_sign` slot and wires
it into `data/sprites/asset_manifest.json`. The PNG it writes is COMMITTED,
EDITABLE content (D-31) — repaint or re-import it freely; this script is only
how it was seeded, and re-running it overwrites it.

Headless + deterministic + idempotent: SDL dummy drivers are set before pygame
is imported (no window is ever created), every pixel comes from pure
`pygame.draw` geometry with NO RNG and no fonts, and every run regenerates the
sheet from scratch, so two runs with no code change produce a byte-identical
PNG and an unchanged, canonically-formatted manifest.

-- Sheet layout ------------------------------------------------------------
One 64x96 frame => a 64x96 PNG, SRCALPHA, transparent background. The single
row IS the `core` category's whole animation vocabulary (`data/slots.json`):
`idle`.

-- Frame geometry ----------------------------------------------------------
A frame blits CENTRED on the tile diamond's centre (`engine/render/CLAUDE.md`
anchor convention) with tile_w=64 / tile_h=32, so inside a 64x96 frame the
tile centre sits at (32, 48) and the diamond's corners land on fixed frame
pixels — the post is planted at the tile centre and the board rises above it,
so the sign reads as standing ON the tile it marks.
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

SLOT = "moving_sign"
FRAME_W, FRAME_H = 64, 96        # core category frame size (data/slots.json)
ROWS = ("idle",)                 # core category animation vocabulary

TILE_CENTRE = (32, 48)           # where the frame's own tile centre lands

BOARD = pygame.Rect(12, 14, 40, 26)   # the sign board
POST = pygame.Rect(30, 38, 4, 12)     # the post, planted at the tile centre

WOOD = (122, 84, 48)             # post + board border
BOARD_FILL = (236, 208, 120)     # the board face
ARROW = (58, 44, 30)             # the "moving that way" arrow
OUTLINE = (40, 28, 16)

# The arrow drawn on the board face: a right-pointing chevron+shaft, in FRAME
# pixels. Deliberately geometric (no font) so the sheet stays deterministic
# on every machine.
ARROW_SHAFT = pygame.Rect(19, 25, 16, 5)
ARROW_HEAD = ((33, 19), (45, 27), (33, 35))


def build_sheet():
    """Return the 64x96 SRCALPHA surface for the moving_sign slot."""
    sheet = pygame.Surface((FRAME_W, FRAME_H), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))

    # a small shadow ellipse where the post meets the tile centre
    pygame.draw.ellipse(sheet, (0, 0, 0, 70),
                        pygame.Rect(TILE_CENTRE[0] - 9, TILE_CENTRE[1] - 3,
                                    18, 7))
    pygame.draw.rect(sheet, WOOD, POST)
    pygame.draw.rect(sheet, OUTLINE, POST, 1)

    pygame.draw.rect(sheet, BOARD_FILL, BOARD)
    pygame.draw.rect(sheet, WOOD, BOARD, 3)
    pygame.draw.rect(sheet, OUTLINE, BOARD, 1)

    pygame.draw.rect(sheet, ARROW, ARROW_SHAFT)
    pygame.draw.polygon(sheet, ARROW, ARROW_HEAD)
    return sheet


def _row(animation):
    """One single-frame manifest row, using the manifest's stock defaults."""
    return {
        "animation": animation,
        "frames": 1,
        "fps": 8,
        "hidden": [],
        "loop_start": 0,
        "loop_end": 0,
        "loop_count": 1,
    }


def _entry(slot):
    return {
        "sheet": f"imported/{slot}.png",
        "frame_w": FRAME_W,
        "frame_h": FRAME_H,
        "offset_x": 0,
        "offset_y": 0,
        "rows": [_row(animation) for animation in ROWS],
    }


def generate(data_dir):
    """Write the PNG + its manifest entry. Returns the slot key."""
    pygame.init()
    try:
        imported = Path(data_dir) / "sprites" / "imported"
        imported.mkdir(parents=True, exist_ok=True)
        pygame.image.save(build_sheet(), str(imported / f"{SLOT}.png"))
    finally:
        pygame.quit()

    manifest_path = Path(data_dir) / "sprites" / "asset_manifest.json"
    schema_path = Path(data_dir) / "schemas" / "asset_manifest.schema.json"
    try:
        doc = data_io.load_json(manifest_path)
    except (OSError, ValueError):
        doc = {"version": 2, "entries": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        doc = {"version": 2, "entries": {}}
    doc["entries"][SLOT] = _entry(SLOT)
    data_io.write_validated(doc, manifest_path, schema_path)
    return SLOT


def main(data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    slot = generate(data_dir)
    print(f"gen_moving_sign_sheet: wrote 1 sheet ({FRAME_W}x{FRAME_H}) "
          f"+ manifest entry: {slot}")
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(main(data_dir=args.data_dir))
