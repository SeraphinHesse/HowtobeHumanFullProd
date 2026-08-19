"""UL-11: the three HUD life counters resolve alive / dying / dead, and the
lost one flies to screen centre on the way.

D10 makes ``life_1``/``life_2``/``life_3`` three id'd widgets, not one
repeated draw, so each carries its own ``_state`` callable — the same seam
``ScreenSkinning.state_of``/``submit_layers`` already dispatch through for
Buttons. State rides the pinned four-token vocabulary: alive -> ``idle``,
dying -> ``pressed`` (plays once), dead -> ``disabled``.

Since the lost-life flight they are also the ONLY lives readout (the numeric
``lives_text`` and ``icon_lives`` are hidden by a screen override, ids intact).
A lost life leaves its HUD slot still ALIVE, plays its dying row enlarged at
screen centre under the announce banner, then flies home already dead.

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
from engine.render import HudSprite
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui.building_ui import BuildingUI
from game.ui.hud import Hud
from game.ui.skinning import ScreenSkinning

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 640, 360
FIELD = ["bsssss"] + ["ssssss"] * 5
DT = 0.016

FX = UI["FX"]["life_lost_anim"]
#: The dying hold is the imported ``pressed`` row's own length, so a Hud with
#: no asset store holds for zero seconds and the flight is out + back only.
FLIGHT = FX["fly_out"] + FX["fly_back"]

#: How long the stub store below claims the dying row runs for.
DYING_MS = 400


class _StubStore:
    """The two manifest questions the HUD asks, and nothing else.

    ``animation_total_ms`` returns None for a row a sheet does not carry —
    that None is the whole point (see ``Hud._dead_art_available``), so a stub
    that answered a number for everything would test nothing."""

    def __init__(self, rows=("idle", "pressed", "disabled")):
        self._rows = set(rows)

    def animation_total_ms(self, slot, animation):
        if animation not in self._rows:
            return None
        return DYING_MS if animation == "pressed" else 100


class _Recorder:
    """A bare HUD-primitive collector — ``test_ui_skinning.py``'s shape."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


def build(ui_balance=None):
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
    hud = Hud(VIEW_W, VIEW_H, ui_balance=ui_balance if ui_balance is not None
              else UI)
    return session, BuildingUI(VIEW_W, VIEW_H, UI), hud


def tokens(hud):
    """The three counters' states, read through the SAME seam the renderer
    uses (``state_of``), not by calling the resolver directly."""
    state_of = ScreenSkinning.empty().state_of
    return [state_of(w) for w in (hud._life_1, hud._life_2, hud._life_3)]


def life_sprites(hud, session):
    """Every life-icon sprite one ``submit`` emits, in draw order."""
    rec = _Recorder()
    hud.submit(rec, session, VIEW_W, VIEW_H)
    return [i for i in rec.items
            if isinstance(i, HudSprite) and i.slot_key == hud._life_1.skin]


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

    def test_the_lost_life_leaves_its_slot_still_alive(self):
        # Decision: the flight OUT shows alive art; the dying row plays only
        # once the icon has arrived and scaled up at centre.
        session, panel, hud = build()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "idle", "idle"])
        self.assertEqual(hud._life_transition_idx, 3)
        self.assertEqual(hud._life_anim()[0], "out")

    def test_the_flight_walks_out_then_dying_then_dead(self):
        session, panel, hud = build()
        hud.assets = _StubStore()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        seen = []
        for _ in range(int((FLIGHT + DYING_MS / 1000.0) / DT) + 4):
            phase = hud._life_anim()[0]
            if phase is not None and (not seen or seen[-1] != phase):
                seen.append(phase)
            hud.update(DT, 0, 0, session, panel)
        self.assertEqual(seen, ["out", "dying", "back"])
        self.assertEqual(tokens(hud), ["idle", "idle", "disabled"])

    def test_the_transition_is_finite_and_settles_to_dead(self):
        session, panel, hud = build()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        elapsed = 0.0
        while elapsed < FLIGHT + DT:
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

    def test_a_loss_after_update_is_drawn_the_same_frame(self):
        # Session.on_base_hit fires inside resolve_combat, which main.py runs
        # BETWEEN Hud.update and Hud.submit — so submit re-observes.
        session, panel, hud = build()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2          # ...after update, before submit
        hud.submit(_Recorder(), session, VIEW_W, VIEW_H)
        self.assertEqual(hud._life_transition_idx, 3)

    def test_the_centred_icon_is_scaled_and_horizontally_centred(self):
        session, panel, hud = build()
        hud.assets = _StubStore()
        session.state.base_lives = 3
        hud.update(DT, 0, 0, session, panel)
        session.state.base_lives = 2
        hud.update(DT, 0, 0, session, panel)
        # Park the clock inside the dying window: out, then half the hold.
        hud._life_transition_age = FX["fly_out"] + DYING_MS / 2000.0
        hud._layout_readouts()
        hw, hh = hud._life_3.rect[2], hud._life_3.rect[3]
        scale = FX["center_scale"]
        cw, ch = round(hw * scale), round(hh * scale)
        flying = [s for s in life_sprites(hud, session) if s.size == (cw, ch)]
        self.assertEqual(len(flying), 1, "exactly one icon is enlarged")
        self.assertEqual(flying[0].dest[0], VIEW_W // 2 - cw // 2)
        self.assertEqual(flying[0].animation, "pressed")

    def test_a_dead_life_with_no_disabled_row_draws_nothing(self):
        session, panel, hud = build()
        session.state.base_lives = 2          # seeded dead, no flight
        hud.update(DT, 0, 0, session, panel)
        self.assertEqual(tokens(hud), ["idle", "idle", "disabled"])
        # No store at all reads as "no dead art authored".
        hud.assets = None
        self.assertEqual(len(life_sprites(hud, session)), 2)
        # A sheet carrying a real `disabled` row brings it back.
        hud.assets = _StubStore()
        self.assertEqual(len(life_sprites(hud, session)), 3)
        # ...and a sheet WITHOUT one keeps it hidden, rather than falling back
        # to the idle art the manifest would otherwise serve.
        hud.assets = _StubStore(rows=("idle", "pressed"))
        self.assertEqual(len(life_sprites(hud, session)), 2)


if __name__ == "__main__":
    unittest.main()
