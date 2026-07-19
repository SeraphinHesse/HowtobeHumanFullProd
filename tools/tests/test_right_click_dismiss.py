"""``BuildingUI.dismiss()`` — the staged Esc / right-click dismiss ladder.

A right-click anywhere peels ONE stage off whatever is open: a sub-overlay
first (construct preview -> the card list, boss popup -> base_info), and only a
bare panel closes outright. The host wiring that turns a short right-press into
this call lives in ``main.py``'s event loop (right-DRAG still pans); it is a
closure and is covered by the live run, not here.

Headless: real TileMap/Session/BuildingUI over the shipped starter map, no
pygame window (the UI layer is pure) — the ``test_10j_qol`` fixture style.
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
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.map.tiles import TileState
from game.ui.building_ui import BuildingUI

MAP = FIXTURE_DATA / "maps" / "first_light.json"
MAP_SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
MAP_BAL = load_balance(FIXTURE_DATA, "map")
BUILDINGS_BAL = load_balance(FIXTURE_DATA, "buildings")
ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VIEW_W, VIEW_H = 1280, 720


def make_world():
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    tm = TileMap(doc, MAP_BAL)
    scene = Scene()
    occupancy = TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE_BAL),
                scene, occupancy)
    session = Session.create(Spawner(), tm, ENEMIES_BAL, CORE_BAL,
                             BUILDINGS_BAL, occupancy=occupancy)
    session.state.love = 999
    return tm, scene, occupancy, session


def click(btn):
    """Centre coordinates of a widgets.Button."""
    x, y, w, h = btn.rect
    return x + w // 2, y + h // 2


class DismissTestCase(unittest.TestCase):
    def setUp(self):
        self.tm, self.scene, self.occupancy, self.session = make_world()
        self.panel = BuildingUI(VIEW_W, VIEW_H, UI_BAL)

    def open(self, tile):
        self.panel.open_for_tile(tile, self.session, BUILDINGS_BAL)

    def place_defender(self, col, row):
        """Build on a BUILDABLE tile -> the panel reopens in upgrade mode."""
        tile = self.tm.get(col, row)
        self.open(tile)
        _, card = next((bt, b) for bt, b in self.panel.cards
                       if bt == "defence")
        self.panel.handle_click(*click(card), self.session, BUILDINGS_BAL,
                                None, None)
        self.panel.handle_click(*click(self.panel.preview.confirm_btn),
                                self.session, BUILDINGS_BAL, self.scene,
                                self.occupancy)
        return tile


class TestDismissClosesEveryMode(DismissTestCase):
    def test_unlock(self):
        tile = self.tm.get(3, 1)
        self.assertEqual(tile.state, TileState.COMBAT)
        self.open(tile)
        self.assertEqual(self.panel.mode, "unlock")
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)

    def test_construct(self):
        self.open(self.tm.get(2, 1))
        self.assertEqual(self.panel.mode, "construct")
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)

    def test_upgrade(self):
        self.place_defender(2, 1)
        self.assertEqual(self.panel.mode, "upgrade")
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)

    def test_base_info(self):
        self.open(self.tm.get(self.tm.base_col, self.tm.base_row))
        self.assertEqual(self.panel.mode, "base_info")
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)

    def test_dismiss_clears_the_multi_select_batch(self):
        tiles = [self.tm.get(2, 1), self.tm.get(2, 2)]
        self.panel.open_for_tile(tiles[0], self.session, BUILDINGS_BAL,
                                 selected_tiles=tiles)
        self.assertEqual(len(self.panel.selected_tiles), 2)
        self.panel.dismiss()
        self.assertEqual(self.panel.selected_tiles, [])


class TestDismissIsStaged(DismissTestCase):
    def test_preview_peels_off_before_the_panel(self):
        self.open(self.tm.get(2, 1))
        _, card = next((bt, b) for bt, b in self.panel.cards
                       if bt == "defence")
        self.panel.handle_click(*click(card), self.session, BUILDINGS_BAL,
                                None, None)
        self.assertIsNotNone(self.panel.preview)
        # 1st: back to the card list, panel still open
        self.assertTrue(self.panel.dismiss())
        self.assertIsNone(self.panel.preview)
        self.assertEqual(self.panel.mode, "construct")
        # 2nd: now the panel goes
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)

    def test_boss_popup_peels_off_before_the_panel(self):
        self.open(self.tm.get(self.tm.base_col, self.tm.base_row))
        self.panel._boss_popup_open = True
        # 1st: popup only, base_info survives
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel._boss_popup_open)
        self.assertEqual(self.panel.mode, "base_info")
        # 2nd: now the panel goes
        self.assertTrue(self.panel.dismiss())
        self.assertFalse(self.panel.visible)


class TestDismissOnNothing(DismissTestCase):
    def test_closed_panel_is_a_no_op(self):
        self.assertFalse(self.panel.visible)
        self.assertFalse(self.panel.dismiss())
        self.assertFalse(self.panel.visible)
        self.assertIsNone(self.panel.mode)


if __name__ == "__main__":
    unittest.main()
