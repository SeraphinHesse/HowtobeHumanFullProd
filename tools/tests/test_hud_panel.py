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
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui.building_ui import BuildingUI
from game.ui.hud import Hud

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 1280, 720
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


if __name__ == "__main__":
    unittest.main()
