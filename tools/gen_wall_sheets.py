"""Generate the 9 wall spritesheets (walls slot category) as starting art.

    py tools/gen_wall_sheets.py [--data-dir PATH]

A one-shot ART GENERATOR, not runtime code: it draws placeholder-but-real
wall sprites for the `walls` category's 9 slots (`wall_t{1..3}_lvl{1..3}`)
and wires them into `data/sprites/asset_manifest.json`. The PNGs it writes
are COMMITTED, EDITABLE content (D-31) — repaint them freely; this script is
only how they were seeded, and re-running it overwrites them.

Headless + deterministic + idempotent, exactly like `tools/bake_ui_sheets.py`:
SDL dummy drivers are set before pygame is imported (no window is ever
created), every pixel comes from pure `pygame.draw` geometry with NO RNG and
no fonts, and every run regenerates all 9 sheets from scratch, so two runs
with no code change produce byte-identical PNGs and an unchanged,
canonically-formatted manifest.

-- Sheet layout ------------------------------------------------------------
One sheet per slot: 1 column x 5 rows of 64x96 frames => a 64x480 PNG,
SRCALPHA, transparent background. The 5 rows ARE the `walls` category's
animation vocabulary (`data/slots.json`), in order:

    row 0  idle       a generic preview wall (draws the edge_se segment,
                      which reads best as a standalone icon in the editor's
                      slot list)
    row 1  edge_se    row 2  edge_sw    row 3  edge_nw    row 4  edge_ne

-- Frame geometry ----------------------------------------------------------
A frame blits CENTRED on the tile diamond's centre (`engine/render/CLAUDE.md`
anchor convention) with tile_w=64 / tile_h=32, so inside a 64x96 frame the
tile's four corners land on FIXED frame pixels — `CORNER_*` below. The four
side rows each draw a wall along one corner PAIR (`SIDE_EDGES`).

These constants are duplicated here on purpose, and only for now: the game's
`game/map/wall_render.py` (the delta->side table) does not exist yet when
this script runs, and this script must not grow a dependency on the game
package. Once that module lands, import the geometry FROM it and delete the
copies here.
"""
import argparse
import math
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

FRAME_W, FRAME_H = 64, 96        # walls category frame size (data/slots.json)
TILE_W, TILE_H = 64, 32          # tile pitch the corner table is derived from

# The tile diamond's corners, in FRAME pixels, for a frame centred on the
# tile centre. Tile (col,row) is the frame's own tile.
CORNER_TOP = (32, 32)            # (col,     row    )
CORNER_RIGHT = (64, 48)          # (col + 1, row    )
CORNER_BOTTOM = (32, 64)         # (col + 1, row + 1)
CORNER_LEFT = (0, 48)            # (col,     row + 1)
TILE_CENTRE = (32, 48)

# Which corner pair each side row runs between.
SIDE_EDGES = {
    "edge_se": (CORNER_RIGHT, CORNER_BOTTOM),
    "edge_sw": (CORNER_LEFT, CORNER_BOTTOM),
    "edge_nw": (CORNER_TOP, CORNER_LEFT),
    "edge_ne": (CORNER_TOP, CORNER_RIGHT),
}

# Sheet row order == the walls category's animation vocabulary. Row 0 is
# schema-forced to "idle" (manifest v2 prefixItems).
ROWS = ("idle", "edge_se", "edge_sw", "edge_nw", "edge_ne")
IDLE_EDGE = "edge_se"            # what the generic preview row draws

# Full-HP shade per tier, from the prototype's wall colours.
TIER_COLORS = {
    1: (60, 160, 60),            # bush
    2: (160, 100, 40),           # wood
    3: (160, 160, 160),          # stone
}

# The prototype's per-level wall thickness ramp, tier -> (lvl1, lvl2, lvl3).
# Drives both the drawn top-cap depth AND the wall height below.
TIER_THICKNESS = {
    1: (2, 3, 4),                # bush
    2: (5, 7, 9),                # wood
    3: (10, 12, 14),             # stone
}

# height = 4 * thickness, capped: the highest corner the wall can be raised
# from is the TOP corner at y=32, and the top cap rises a further
# ~0.45*thickness above that (see _cap_offset), so 24 keeps even the thickest
# stone wall (t=14) inside the frame with ~1px to spare.
HEIGHT_PER_THICKNESS = 4
MAX_HEIGHT = 24

CAP_DARKEN = 0.7                 # top cap = tier colour * this
OUTLINE = (0, 0, 0)


def wall_height(thickness):
    """Drawn wall height in px for a given thickness (see MAX_HEIGHT)."""
    return min(HEIGHT_PER_THICKNESS * thickness, MAX_HEIGHT)


def _round_pt(pt):
    return (int(round(pt[0])), int(round(pt[1])))


def _cap_offset(p0, p1, thickness):
    """Screen-space offset from the raised top edge to the far cap edge.

    The wall's top face is its footprint strip translated up; in iso that
    strip's depth direction is the tile-space perpendicular of the edge,
    which maps to the screen direction between the edge midpoint and the
    tile centre. The sign is then forced UPWARD (negative y) so every row
    shows its darker cap ON TOP of the lit face rather than behind it.
    """
    mid_x = (p0[0] + p1[0]) / 2.0
    mid_y = (p0[1] + p1[1]) / 2.0
    vx = TILE_CENTRE[0] - mid_x
    vy = TILE_CENTRE[1] - mid_y
    length = math.hypot(vx, vy)
    ux, uy = vx / length, vy / length
    if uy > 0:
        ux, uy = -ux, -uy
    return (ux * thickness, uy * thickness)


def _darken(color, factor=CAP_DARKEN):
    return tuple(int(c * factor) for c in color)


def draw_segment(surface, edge, color, thickness, top_y):
    """Draw one wall segment into `surface`, `top_y` px down from its top."""
    (x0, y0), (x1, y1) = SIDE_EDGES[edge]
    height = wall_height(thickness)
    base = [(x0, y0 + top_y), (x1, y1 + top_y)]
    raised = [(x, y - height) for x, y in base]

    # 1. the wall face: the two base points plus the same two raised.
    face = [_round_pt(base[0]), _round_pt(base[1]),
            _round_pt(raised[1]), _round_pt(raised[0])]
    pygame.draw.polygon(surface, color, face)

    # 2. the darker top cap along the raised edge, `thickness` px deep.
    off_x, off_y = _cap_offset(*SIDE_EDGES[edge], thickness)
    cap = [_round_pt(raised[0]), _round_pt(raised[1]),
           _round_pt((raised[1][0] + off_x, raised[1][1] + off_y)),
           _round_pt((raised[0][0] + off_x, raised[0][1] + off_y))]
    pygame.draw.polygon(surface, _darken(color), cap)

    # 3. a 1px outline around the face.
    pygame.draw.polygon(surface, OUTLINE, face, 1)


def build_sheet(tier, level):
    """Return the 64x480 SRCALPHA surface for one wall slot."""
    color = TIER_COLORS[tier]
    thickness = TIER_THICKNESS[tier][level - 1]
    sheet = pygame.Surface((FRAME_W, FRAME_H * len(ROWS)), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))
    for index, animation in enumerate(ROWS):
        edge = IDLE_EDGE if animation == "idle" else animation
        draw_segment(sheet, edge, color, thickness, index * FRAME_H)
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
    """Write the 9 PNGs + their manifest entries. Returns the slot keys."""
    pygame.init()
    try:
        imported = Path(data_dir) / "sprites" / "imported"
        imported.mkdir(parents=True, exist_ok=True)
        slots = []
        for tier in sorted(TIER_COLORS):
            for level in (1, 2, 3):
                slot = f"wall_t{tier}_lvl{level}"
                pygame.image.save(build_sheet(tier, level),
                                  str(imported / f"{slot}.png"))
                slots.append(slot)
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
    doc["entries"].update({slot: _entry(slot) for slot in slots})
    data_io.write_validated(doc, manifest_path, schema_path)
    return slots


def main(data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    slots = generate(data_dir)
    print(f"gen_wall_sheets: wrote {len(slots)} sheets "
          f"({FRAME_W}x{FRAME_H * len(ROWS)}) + manifest entries: "
          f"{', '.join(slots)}")
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(main(data_dir=args.data_dir))
