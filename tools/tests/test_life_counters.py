"""UL-11: the three HUD life counters resolve alive / dying / dead.

D10 makes ``life_1``/``life_2``/``life_3`` three id'd widgets, not one
repeated draw, so each carries its own ``_state`` callable — the same seam
``ScreenSkinning.state_of``/``submit_layers`` already dispatch through for
Buttons. State rides the pinned four-token vocabulary: alive -> ``idle``,
dying -> ``pressed`` (plays once), dead -> ``disabled``.

The state machine is driven off ``RunState.base_lives`` DELTAS, never off
``RunState.life_lost_events``: ``main.py`` runs the floaters' effects step
(which DRAINS that ledger) BEFORE ``Hud.update()`` every frame, so the ledger
is already empty on the one frame that matters.

Pure + headless — the ``test_hud_panel.py`` fixture style: a synth board, a
real ``Session``, a real ``Hud``.
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
from game.ui.hud import Hud, _LIFE_TRANSITION_MS
from game.ui.skinning import ScreenSkinning

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 640, 360
FIELD = ["bsssss"] + ["ssssss"] * 5
DT = 0.016


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


def tokens(hud):
    """The three counters' states, read through the SAME seam the renderer
    uses (``state_of``), not by calling the resolver directly."""
    state_of = ScreenSkinning.empty().state_of
    return [state_of(w) for w in (hud._life_1, hud._life_2, hud._life_3)]


class TestLifeCounters(unittest.TestCase):
    def test_three_ids_exist_beside_the_untouched_lives_readout(self):
        _, _, hud = build()
        hud._layout_readouts()
        for key in ("life_1", "life_2", "life_3", "lives_text", "icon_lives"):
            self.assertIn(key, hud.ids, key)
        for key in ("life_1", "life_2", "life_3"):
            self.assertNotEqual(tuple(hud.ids[key][1].rect), (0, 0, 0, 0), key)

    def test_full_health_is_three_alive(self):
        session, panel, hud = build()
        session.state.base_lives = 3
        for _ in range(5):
            hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "idle", "idle"])

    def test_losing_a_life_puts_that_one_into_transition(self):
        session, panel, hud = build()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "idle", "pressed"])

    def test_the_transition_is_finite_and_settles_to_dead(self):
        session, panel, hud = build()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        elapsed = 0.0
        while elapsed < _LIFE_TRANSITION_MS / 1000.0 + DT:
            hud.update(DT, 0, 0, session, panel)
            elapsed += DT
        self.assertEqual(tokens(hud), ["idle", "idle", "disabled"])
        # and it does not re-trigger on later frames
        for _ in range(10):
            hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "idle", "disabled"])

    def test_starting_below_full_lives_never_transitions(self):
        session, panel, hud = build()
        session.state.base_lives = 1
        hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "disabled", "disabled"])
        self.assertIsNone(hud._life_transition_idx)


if __name__ == "__main__":
    unittest.main()
