"""Bake the game's procedural UI rendering into spritesheet PNGs (Phase 10L
wave 3, "bake UI assets").

    py tools/bake_ui_sheets.py [--data-dir PATH]

The 10L UI pipeline (ui slot category, 4-state animated skins, nine-slice,
skinned ``widgets.Button``/``submit_panel``, editor screen mode) shipped with
NO ``ui_*`` art at all — every button/panel/icon in the live game still draws
as flat ``HudRect``s. This tool renders that SAME look to PNG sheets and wires
them into the manifest, so the editor's screen mode has something real to
skin screens with, pixel-faithful to the unskinned look it replaces.

Headless: SDL dummy drivers are set before any pygame-pulling import (mirrors
``tools/export_ui_layouts.py``); no window is ever created. Deterministic:
every surface is built from ``game.ui.widgets`` color constants + pure
``pygame.draw`` geometry (no fonts anywhere), so two runs with no code change
produce byte-identical PNGs and an unchanged, canonically-formatted manifest.
Idempotent: safe to re-run any time the palette/geometry here changes — it
always regenerates every ``ui_*`` sheet from scratch rather than patching.

-- Style audit (this phase's "enumerate distinct button styles" finding) -----
Every ``widgets.Button`` in the live game — shell/menu buttons (main_menu,
pause, settings, credits, add_name, game_over), HUD buttons (End Turn,
Pause), building-panel buttons (unlock/construct/upgrade/lightning/boss
popup), cheat-menu buttons, and the overlay RANGE/HEATMAP toggle pills —
submits through the SAME unskinned fill logic in ``Button.submit`` with NO
caller ever overriding ``color``/``text_color`` to a genuinely different
idle/hover fill. The one caller that passes ``color=`` at all
(``overlays.py``'s active-toggle branch) passes ``color=C_UI_BTN`` — the
SAME value the button would use unhovered by default; the visual difference
there is a separate gold `HudRect` rim drawn on top, not a different button
skin. Conclusion: there is exactly ONE distinct button LOOK in the codebase
today. **Wave-3 Fix 2 (USER DECISION)** overrides the earlier "one shared
slot" call anyway: designers want ONE SLOT PER BUTTON TYPE so each can get
individually repainted art later, even while they still bake identical
pixels today — ``ui_button`` (shell menus), ``ui_button_end_turn``,
``ui_button_pause``, ``ui_button_panel``, ``ui_button_card``,
``ui_button_cheat``, ``ui_button_pill`` (7 leaves under `slots.json`'s
Buttons family) each own their own PNG, no shared ``sheet`` path between
them. ``ui_choice_box`` is the 8th leaf, baking the SAME two-state
idle/hover choice-box look as ``ui_panel_stone`` below (kept registered and
baked separately — the type→slot table lives in `data/CLAUDE.md`).

Panels are NOT all identical, though: ``submit_panel`` (used unconditionally
by ``building_ui.py``'s main panel, the boss-choices popup, and — absent a
skin override — the cheat-menu panel) is a single always-on
fill=``C_UI_PANEL``/border=``C_UI_BORDER`` rect with no interaction state at
all. ``levelup.py``/``boss_cutscene.py``'s option/choice boxes are a
DIFFERENT, genuinely two-state look (idle ``C_UI_PANEL``/``C_UI_BORDER``,
hover ``C_UI_BTN_HOVER`` fill + ``C_GOLD`` border) — this is what
``ui_panel_stone`` (already registered in ``slots.json`` as its own Panel
leaf, not a "_v2" of ``ui_panel``) bakes. No additional panel slot is needed
either.
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
from engine.assets.registry import load_registry  # noqa: E402
from game.ui.widgets import (  # noqa: E402
    C_GOLD, C_RED, C_UI_BORDER, C_UI_BTN, C_UI_BTN_DISABLED, C_UI_BTN_HOVER,
    C_UI_PANEL,
)

FRAME = 64                       # ui category frame size (data/slots.json)
BUTTON_SLICE = [4, 4, 4, 4]      # nine-slice margins (frame px) for buttons/panels
_STATES = ["idle", "hover", "pressed", "disabled"]  # the ui animation vocabulary

# -- love/xp/lives icon palette (matches game/ui/widgets.py + hud.py usage) --
_LOVE_FILL = (220, 60, 90)        # warm red-pink, distinct from the C_RED
_LOVE_OUTLINE = (140, 30, 55)
_XP_PURPLE = (168, 105, 222)      # hud.py _XP_PURPLE, verbatim
_XP_OUTLINE = (100, 55, 150)
_LIVES_RED = (200, 55, 55)        # widgets.C_HP_RED, verbatim
_LIVES_OUTLINE = (120, 25, 25)
_LIVES_HIGHLIGHT = (235, 150, 150)


def _row(animation, *, frames=1, fps=8):
    return {
        "animation": animation,
        "frames": frames,
        "fps": fps,
        "hidden": [],
        "loop_start": 0,
        "loop_end": 0,
        "loop_count": 1,
    }


def _entry(slot, frame_w, frame_h, rows, *, slice_margins=None, sheet=None):
    entry = {
        "sheet": sheet or f"imported/{slot}.png",
        "frame_w": frame_w,
        "frame_h": frame_h,
        "offset_x": 0,
        "offset_y": 0,
        "rows": rows,
    }
    if slice_margins is not None:
        entry["slice"] = slice_margins
    return entry


# -- button sheet: 4 rows (idle/hover/pressed/disabled), 1 frame each --------
# Drawn EXACTLY as Button.submit() draws it unskinned: a filled, 1px-bordered,
# border_radius=3 rect (see widgets.py Button.submit). "pressed" bakes the
# not-enough-love FLASH red (C_RED) rather than the held-down-hover look
# (which is visually identical to plain hover, C_UI_BTN_HOVER, and so would
# be indistinguishable as a baked frame) — the state->row mapping this phase
# was briefed to use.
_BUTTON_ROW_FILLS = {
    "idle": C_UI_BTN,
    "hover": C_UI_BTN_HOVER,
    "pressed": C_RED,
    "disabled": C_UI_BTN_DISABLED,
}


def _button_frame(fill):
    surface = pygame.Surface((FRAME, FRAME), pygame.SRCALPHA)
    rect = surface.get_rect()
    pygame.draw.rect(surface, fill, rect, border_radius=3)
    pygame.draw.rect(surface, C_UI_BORDER, rect, width=1, border_radius=3)
    return surface


def build_ui_button_sheet():
    sheet = pygame.Surface((FRAME, FRAME * len(_STATES)), pygame.SRCALPHA)
    for i, state in enumerate(_STATES):
        sheet.blit(_button_frame(_BUTTON_ROW_FILLS[state]), (0, i * FRAME))
    return sheet


# -- panel sheets --------------------------------------------------------

def _panel_frame(fill, border):
    surface = pygame.Surface((FRAME, FRAME), pygame.SRCALPHA)
    surface.fill(fill)
    pygame.draw.rect(surface, border, surface.get_rect(), width=1)
    return surface


def build_ui_panel_sheet():
    """The static ``submit_panel`` look: one idle row, no interaction state."""
    return _panel_frame(C_UI_PANEL, C_UI_BORDER)


def build_ui_panel_stone_sheet():
    """The levelup/boss_cutscene choice-box look: idle + a real hover row
    (fill brightens to C_UI_BTN_HOVER, border golds — widgets.py
    LevelupWindow._submit_box / BossCutscene._submit_box, verbatim)."""
    sheet = pygame.Surface((FRAME, FRAME * 2), pygame.SRCALPHA)
    sheet.blit(_panel_frame(C_UI_PANEL, C_UI_BORDER), (0, 0))
    sheet.blit(_panel_frame(C_UI_BTN_HOVER, C_GOLD), (0, FRAME))
    return sheet


# -- icon sheets: single idle frame, pure geometry, no fonts -----------------

def _draw_heart(surface, fill, outline):
    cx, cy = FRAME // 2, FRAME // 2 + 2
    r = 13
    pygame.draw.circle(surface, fill, (cx - r + 1, cy - r), r)
    pygame.draw.circle(surface, fill, (cx + r - 1, cy - r), r)
    points = [(cx - 2 * r + 2, cy - r + 3), (cx + 2 * r - 2, cy - r + 3),
              (cx, cy + 2 * r - 2)]
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.circle(surface, outline, (cx - r + 1, cy - r), r, width=2)
    pygame.draw.circle(surface, outline, (cx + r - 1, cy - r), r, width=2)
    pygame.draw.polygon(surface, outline, points, width=2)


def build_ui_icon_love_sheet():
    surface = pygame.Surface((FRAME, FRAME), pygame.SRCALPHA)
    _draw_heart(surface, _LOVE_FILL, _LOVE_OUTLINE)
    return surface


def build_ui_icon_xp_sheet():
    """A 4-point diamond/star — the XP glyph, purple to match hud.py's XP bar
    fill (``_XP_PURPLE``)."""
    surface = pygame.Surface((FRAME, FRAME), pygame.SRCALPHA)
    cx, cy = FRAME // 2, FRAME // 2
    outer, inner = 26, 9
    points = []
    for i in range(8):
        radius = outer if i % 2 == 0 else inner
        angle = i * (math.pi / 4) - math.pi / 2
        points.append((cx + radius * math.cos(angle),
                       cy + radius * math.sin(angle)))
    pygame.draw.polygon(surface, _XP_PURPLE, points)
    pygame.draw.polygon(surface, _XP_OUTLINE, points, width=2)
    return surface


def build_ui_icon_lives_sheet():
    """A shield — the lives glyph, red to match ``widgets.C_HP_RED`` (the HUD
    LIVES readout's text colour)."""
    surface = pygame.Surface((FRAME, FRAME), pygame.SRCALPHA)
    cx, top, w, h = FRAME // 2, 8, 22, 46
    points = [
        (cx - w, top), (cx + w, top),
        (cx + w, top + h * 0.55),
        (cx, top + h),
        (cx - w, top + h * 0.55),
    ]
    pygame.draw.polygon(surface, _LIVES_RED, points)
    pygame.draw.polygon(surface, _LIVES_OUTLINE, points, width=2)
    pygame.draw.line(surface, _LIVES_HIGHLIGHT, (cx - w + 4, top + 4),
                      (cx - w + 4, top + h * 0.4), width=3)
    return surface


# -- the plan --------------------------------------------------------------

# Wave-3 Fix 2 (USER DECISION): the single shared ``ui_button`` is rejected —
# every button TYPE in the game gets its OWN slot/PNG so each is individually
# repaintable, even though all 7 bake identical art today (same style audit
# above still holds; only the identity of the slot changed, not the look).
# slot -> (builder, rows[list of animation names present], slice_margins)
_BUTTON_SLOTS = {
    "ui_button": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_end_turn": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_pause": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_panel": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_card": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_cheat": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_button_pill": (build_ui_button_sheet, _STATES, BUTTON_SLICE),
    "ui_choice_box": (build_ui_panel_stone_sheet, ["idle", "hover"], BUTTON_SLICE),
}
_PANEL_SLOTS = {
    "ui_panel": (build_ui_panel_sheet, ["idle"], BUTTON_SLICE),
    "ui_panel_stone": (build_ui_panel_stone_sheet, ["idle", "hover"], BUTTON_SLICE),
}
_ICON_SLOTS = {
    "ui_icon_love": (build_ui_icon_love_sheet, ["idle"], None),
    "ui_icon_xp": (build_ui_icon_xp_sheet, ["idle"], None),
    "ui_icon_lives": (build_ui_icon_lives_sheet, ["idle"], None),
}


def _write_sheet(data_dir, slot, surface):
    dest = Path(data_dir) / "sprites" / "imported" / f"{slot}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(dest))
    return dest


def bake(data_dir):
    """Render every ui_* sheet to disk and merge their manifest entries.
    Returns the sorted list of slot keys written (for the CLI + tests)."""
    data_dir = Path(data_dir)
    written = []

    entries = {}
    for slot, (builder, rows, slice_margins) in {
            **_BUTTON_SLOTS, **_PANEL_SLOTS, **_ICON_SLOTS}.items():
        surface = builder()
        _write_sheet(data_dir, slot, surface)
        entries[slot] = _entry(
            slot, FRAME, FRAME, [_row(a) for a in rows],
            slice_margins=slice_margins)
        written.append(slot)

    manifest_path = data_dir / "sprites" / "asset_manifest.json"
    schema_path = data_dir / "schemas" / "asset_manifest.schema.json"
    try:
        doc = data_io.load_json(manifest_path)
    except (OSError, ValueError):
        doc = {"version": 2, "entries": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        doc = {"version": 2, "entries": {}}

    # ui_bg_main_menu: this baker renders NO pixels for it — it only wires the
    # slot up, so every value below is READ rather than asserted, and a
    # designer's import always wins:
    #   * sheet — the slot's OWN imported PNG once one exists (a real import
    #     through the asset pipeline), else the shared
    #     imported/main_menu_bg.png (10K's backgrounds-category art). Either
    #     way no byte copy and no slice (a plain full-frame scale, D-1 "sheet
    #     is a path").
    #   * frame size — from the slot registry, never a literal here. It was
    #     hardcoded 480x270 until the slot was re-cut to 640x360; a literal
    #     means the next bake silently re-installs the stale size.
    #   * rows — whatever the existing entry carries (the import may be
    #     multi-frame), falling back to one idle frame when there is none.
    bg_slot = "ui_bg_main_menu"
    bg_own_png = (data_dir / "sprites" / "imported" / f"{bg_slot}.png")
    bg_prev = doc["entries"].get(bg_slot) or {}
    bg_w, bg_h = load_registry(data_dir).frame_size(bg_slot)
    entries[bg_slot] = _entry(
        bg_slot, bg_w, bg_h, bg_prev.get("rows") or [_row("idle")],
        sheet=(f"imported/{bg_slot}.png" if bg_own_png.is_file()
               else "imported/main_menu_bg.png"))
    written.append(bg_slot)

    doc["entries"].update(entries)
    data_io.write_validated(doc, manifest_path, schema_path)

    return sorted(written)


def main(data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    written = bake(data_dir)
    print(f"bake_ui_sheets: wrote {len(written)} manifest entries: "
          f"{', '.join(written)}")
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(main(data_dir=args.data_dir))
