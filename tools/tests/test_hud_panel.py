"""The building panel occludes the HUD's right-edge cluster (pause + End Turn).

The panel is a full-height right sidebar and ``main.py`` submits the HUD AFTER
it, so both right-edge buttons would otherwise paint ON TOP of the panel and
stay clickable through it. ``Hud`` therefore neither draws nor hit-tests them
while any panel mode (unlock / construct / upgrade / base_info) or the construct
preview is open.

Pure + headless (the ``test_lightning`` fixture style): a synth board, a real
``Session`` / ``BuildingUI`` / ``Hud``, and a recording stand-in renderer.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from engine.render import HudRect, HudText
from game.buildings import BaseBuilding, attach_base
from game.buildings.registry import build_cost
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui import widgets
from game.ui.building_ui import BuildingUI, ConstructPreview
from game.ui.hud import Hud

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 640, 360
FIELD = ["bsssss"] + ["ssssss"] * 5
PANEL_MODES = ("unlock", "construct", "upgrade", "base_info")


class RecordingRenderer:
    """``Hud`` only ever emits through ``submit_hud``."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)

    def rects(self):
        return [getattr(i, "rect", None) for i in self.items]


def build():
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(FIELD[0]), rows=len(FIELD),
        legend={}, terrain=[list(r) for r in FIELD],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[])
    tm = TileMap(doc, MAPBAL)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ)
    session.state.state = GameState.GAMEPLAY
    session.state.phase = GamePhase.BUILDING
    return session, BuildingUI(VIEW_W, VIEW_H, UI), Hud(VIEW_W, VIEW_H)


def centre(btn):
    x, y, w, h = btn.rect
    return x + w // 2, y + h // 2


class TestPanelOccludesHudButtons(unittest.TestCase):
    def test_both_buttons_really_sit_under_the_panel_column(self):
        """The premise: if they did not overlap, there would be no bug."""
        _, panel, hud = build()
        for btn in (hud.pause, hud.end_turn):
            bx, by, bw, bh = btn.rect
            self.assertGreaterEqual(bx, panel.panel_x)
            self.assertLess(by, VIEW_H)

    def test_buttons_live_while_the_panel_is_closed(self):
        session, panel, hud = build()
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud.hit(*centre(hud.pause)), "pause")
        self.assertEqual(hud.hit(*centre(hud.end_turn)), "end_turn")

    def test_open_panel_disables_both_buttons(self):
        session, panel, hud = build()
        for mode in PANEL_MODES:
            with self.subTest(mode=mode):
                panel.mode = mode
                hud.update(0.016, 0, 0, session, panel)
                self.assertTrue(panel.visible)
                self.assertIsNone(hud.hit(*centre(hud.pause)))
                self.assertIsNone(hud.hit(*centre(hud.end_turn)))
                self.assertFalse(hud.pause.enabled)
                self.assertFalse(hud.end_turn.enabled)

    def test_open_panel_stops_drawing_both_buttons(self):
        session, panel, hud = build()
        for mode in PANEL_MODES:
            with self.subTest(mode=mode):
                panel.mode = mode
                hud.update(0.016, 0, 0, session, panel)
                r = RecordingRenderer()
                hud.submit(r, session, VIEW_W, VIEW_H)
                drawn = r.rects()
                self.assertNotIn(hud.pause.rect, drawn)
                self.assertNotIn(hud.end_turn.rect, drawn)

    def test_construct_preview_also_hides_them(self):
        """The name-entry modal opens over a `construct` panel."""
        session, panel, hud = build()
        panel.mode, panel.preview = "construct", object()
        hud.update(0.016, 0, 0, session, panel)
        self.assertIsNone(hud.hit(*centre(hud.pause)))
        self.assertIsNone(hud.hit(*centre(hud.end_turn)))

    def test_closing_the_panel_restores_them(self):
        session, panel, hud = build()
        panel.mode = "upgrade"
        hud.update(0.016, 0, 0, session, panel)
        panel.close()
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud.hit(*centre(hud.pause)), "pause")
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        self.assertIn(hud.pause.rect, r.rects())
        self.assertIn(hud.end_turn.rect, r.rects())


class TestHudButtonZOrder(unittest.TestCase):
    """``panel -> button -> text`` (game/ui/CLAUDE.md, engine/render/CLAUDE.md
    "HUD pass": submission order IS draw order). The round-cluster separator
    used to be submitted AFTER the End Turn button, so it drew ON TOP of the
    button's top edge; it must draw BEHIND it instead."""

    def test_separator_precedes_end_turn_button(self):
        session, panel, hud = build()
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        bx, by, bw, _bh = hud.end_turn.rect
        separator = HudRect((bx, by - 2, bw, 1), widgets.C_UI_BORDER)
        sep_idx = r.items.index(separator)
        btn_idx = next(i for i, item in enumerate(r.items)
                       if isinstance(item, HudRect)
                       and item.rect == hud.end_turn.rect)
        self.assertLess(sep_idx, btn_idx,
                        "separator must draw BEHIND (before) the End Turn button")


class TestButtonStates(unittest.TestCase):
    """UL-5: a ``states`` offset patch nudges what is DRAWN and nothing else.
    ``self.rect`` is the hit-test truth (``_surface_hit``/``hit`` read it on
    the very next frame), so a state that moved it would make a hovered
    button un-clickable at the position it appears to occupy."""

    def test_hover_state_patch_offsets_draw_not_rect(self):
        btn = widgets.Button((40, 50, 60, 20), "END TURN")
        btn.states = {"hover": {"offset": [0, -4]}}
        btn.hover(45, 55, mouse_down=False)          # inside -> hovered
        self.assertTrue(btn.hovered)
        before = btn.rect

        r = RecordingRenderer()
        btn.submit(r)

        drawn = [i for i in r.items if isinstance(i, HudRect)][0]
        self.assertEqual(drawn.rect, (40, 46, 60, 20))
        self.assertEqual(btn.rect, before)
        self.assertTrue(btn.hit(45, 55))             # still hit-tests as laid out


class TestConstructPreviewZOrder(unittest.TestCase):
    """``ConstructPreview.submit()`` used to intersperse TEXT submissions
    between the panel/name-box and the confirm/cancel/close/dice BUTTONS.
    Every standalone text label (title, cost, name label, stat rows) must now
    draw on top of (after) every button — game/ui/CLAUDE.md "panel -> button
    -> text"."""

    def _preview(self):
        cost = build_cost("defence", BUILD, 0)
        preview = ConstructPreview("defence", cost, BUILD, UI,
                                   VIEW_W, VIEW_H)
        preview.hover(-1000, -1000, False)
        preview.update(0.016)
        return preview

    def test_every_text_submission_follows_every_button_submission(self):
        preview = self._preview()
        r = RecordingRenderer()
        preview.submit(r)

        button_rects = {preview.dice_btn.rect, preview.confirm_btn.rect,
                        preview.close_btn.rect}
        if preview.cancel_btn is not None:
            button_rects.add(preview.cancel_btn.rect)
        button_indices = [i for i, item in enumerate(r.items)
                          if isinstance(item, HudRect)
                          and item.rect in button_rects]
        self.assertTrue(button_indices)
        last_button_idx = max(button_indices)

        # The standalone labels the bug used to draw BEFORE the buttons —
        # not a button's own label (that always rides with its own button).
        standalone = {preview.title,
                     f"Cost  {preview.total_cost}", "Name:"}
        standalone |= {label for label, _value in preview.stats}
        text_indices = [i for i, item in enumerate(r.items)
                        if isinstance(item, HudText) and item.text in standalone]
        self.assertTrue(text_indices)
        self.assertTrue(all(i > last_button_idx for i in text_indices),
                        "every standalone text submission must follow every "
                        "button submission")


if __name__ == "__main__":
    unittest.main()
