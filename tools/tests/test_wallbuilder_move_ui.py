"""WallBuilder move feedback (feature: wallbuilder-restricted-move).

Covers the UI half of the feature the pure logic lives in
``game/buildings/movement.py`` (see ``tools/tests/test_building_movement.py``
for the move-legality tests this pins against): the MOVE BUILDING button's
enabled/disabled + hint state, and the move-picker's valid (cyan
``move_target``) vs greyed-out (``move_blocked``) tile split plus its own
wall-edge highlight.

Pure + headless, the ``test_hud_panel`` style: a synth board, a real
``Session``/``BuildingUI``, no window.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import attach_base, place_building
from game.buildings import BaseBuilding
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui.building_ui import BuildingUI

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 640, 360

#: Col 2 faces col 3 (COMBAT/SPAWNING, i.e. exterior) on every row, so a
#: WallBuilder placed anywhere in cols 0-2 claims exactly the six
#: (2, row)/(3, row) edges — the same board shape
#: ``test_building_movement.py``'s ``walled_board`` uses, plus a base tile so
#: ``Session.create`` has one to attach to.
WALLED_ROWS = [
    "Bbbccc",
    "bbbccc",
    "bbbccc",
    "bbbccc",
    "bbbccc",
    "bbbsss",
]


def _base_tile():
    for r, row in enumerate(WALLED_ROWS):
        for c, ch in enumerate(row):
            if ch == "B":
                return c, r
    raise AssertionError("no base tile painted")


def walled_world():
    """A real Session + BuildingUI over the walled board, with a WallBuilder
    placed at (1, 1) — its own wall-interior tiles are (2, 0)..(2, 5), all
    free BUILDABLE at construction."""
    rows = [r.replace("B", "b") for r in WALLED_ROWS]
    base_col, base_row = _base_tile()
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base_col, "row": base_row, "slot": "base_hole"}, deco=[])
    tm = TileMap(doc, MAPBAL)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ)
    session.state.state = GameState.GAMEPLAY
    session.state.phase = GamePhase.BUILDING

    wb, _ = place_building(tm, tm.get(1, 1), "wall_builder", 9999, BUILD,
                           scene, occ)
    scene.update(0.0)
    panel = BuildingUI(VIEW_W, VIEW_H, UI)
    return session, panel, scene, occ, wb


def _select_wall_builder(panel, session, wb):
    panel.open_for_tile(session.tilemap.get(wb.col, wb.row), session, BUILD)
    self_check = panel._selected is wb
    assert self_check, "open_for_tile did not select the WallBuilder"


def _click_move_button(panel, session, occ):
    mx, my = centre(panel.move_btn)
    return panel.handle_click(mx, my, session, BUILD, None, occ)


def centre(btn):
    x, y, w, h = btn.rect
    return x + w // 2, y + h // 2


class TestMoveButtonGating(unittest.TestCase):
    def test_enabled_with_a_free_wall_tile(self):
        session, panel, _scene, _occ, wb = walled_world()
        _select_wall_builder(panel, session, wb)
        self.assertTrue(panel.move_btn.enabled)
        self.assertIsNone(panel._upgrade_hint)

    def test_disabled_with_a_hint_when_every_owned_tile_is_taken(self):
        session, panel, scene, occ, wb = walled_world()
        # Occupy every one of the WallBuilder's own wall-interior tiles so it
        # has nowhere left to go.
        for row in range(6):
            if row == 1:
                continue   # (2, 1) stays free until the loop below
            place_building(session.tilemap, session.tilemap.get(2, row),
                           "defence", 9999, BUILD, scene, occ)
        place_building(session.tilemap, session.tilemap.get(2, 1),
                       "defence", 9999, BUILD, scene, occ)
        scene.update(0.0)

        _select_wall_builder(panel, session, wb)
        self.assertFalse(panel.move_btn.enabled)
        self.assertIsNotNone(panel._upgrade_hint)


class TestMoveSelectHighlighting(unittest.TestCase):
    def test_own_wall_tiles_are_move_target_everything_else_is_blocked(self):
        session, panel, _scene, occ, wb = walled_world()
        _select_wall_builder(panel, session, wb)
        self.assertTrue(_click_move_button(panel, session, occ))
        self.assertEqual(panel.mode, "move_select")

        by_event = {}
        for col, row, event in panel._highlight_tiles:
            by_event.setdefault(event, set()).add((col, row))

        self.assertEqual(by_event.get("move_target"),
                         {(2, r) for r in range(6)})
        # every OTHER buildable tile (cols 0-1, minus the WallBuilder's own
        # BUILT origin tile) is highlighted too, but greyed out.
        self.assertIn((0, 3), by_event.get("move_blocked", set()))
        self.assertIn((1, 4), by_event.get("move_blocked", set()))
        self.assertNotIn((1, 1), by_event.get("move_blocked", set()),
                         "the WallBuilder's own BUILT tile is not buildable")

    def test_its_own_wall_edges_draw_too(self):
        session, panel, _scene, occ, wb = walled_world()
        _select_wall_builder(panel, session, wb)
        self.assertTrue(_click_move_button(panel, session, occ))
        self.assertEqual(len(panel._highlight_edges), 6)

    def test_a_normal_building_still_only_shows_move_target(self):
        """No behaviour change for anything but a WallBuilder."""
        session, panel, scene, occ, _wb = walled_world()
        b, _ = place_building(session.tilemap, session.tilemap.get(0, 3),
                              "defence", 9999, BUILD, scene, occ)
        scene.update(0.0)
        panel.open_for_tile(session.tilemap.get(0, 3), session, BUILD)
        self.assertTrue(_click_move_button(panel, session, occ))
        events = {e for _c, _r, e in panel._highlight_tiles}
        self.assertEqual(events, {"move_target"})
        self.assertEqual(panel._highlight_edges, [])


if __name__ == "__main__":
    unittest.main()
