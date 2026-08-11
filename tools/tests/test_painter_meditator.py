"""Phase 10C: Painter (risky lump-sum) + Meditator (compounding streak).

Pure-Python, headless — same fixtures as ``test_phase_loop`` (a synth
``TileMap`` + real balancing via ``load_balance``). ``run_payday`` is driven
directly (no enemy timing) with the ``occupancy`` + ``scene`` handles the Painter
slot needs to free a completed painter's tile.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats, YieldEconomy
from game.buildings.meditator import Meditator
from game.buildings.registry import PlacementError
from game.core import RunState, Session, load_balance, run_payday
from game.core.phases import GamePhase
from game.enemies import Spawner, resolve_combat
from game.map.tile_map import TileMap
from game.map.tiles import TileState

ENEM = load_balance(FIXTURE_DATA, "enemies")

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
VFX = load_balance(FIXTURE_DATA, "vfx")
HOLE = CORE["TheHole"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def board(rows):
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def run_state(**unlocks):
    """A RunState with the given types force-unlocked/researched for placement."""
    st = RunState.from_balance(CORE, BUILD)
    for btype in unlocks.get("unlocked", ()):
        st.unlocked_buildings[btype] = True
    for btype, n in unlocks.get("tiers", {}).items():
        st.tiers_unlocked[btype] = n
    return st


# ---------------------------------------------------------------------------
class TestMeditatorStreak(unittest.TestCase):
    """Prototype ``MeditatorBuilding``: base, base·g, base·g² … capped, reset on
    damage. Unit-level via ``collect_income`` (the payday income-time method)."""

    def med(self):
        return Meditator(1, 0, BUILD)

    def test_compounding_sequence_capped(self):
        m = self.med()
        # tier-1 level-1: base_yield 4, growth 1.25, cap 5 ->
        # round(4·1.25^s) for s = 0..5 then held at the cap.
        seq = [m.collect_income(disturbed=False) for _ in range(7)]
        self.assertEqual(seq, [4, 5, 6, 8, 10, 12, 12])
        self.assertEqual(m.get_component(YieldEconomy).streak, m.streak_max())

    def test_damage_resets_streak_to_base_then_resumes(self):
        m = self.med()
        m.collect_income(False)          # streak 0 -> pay 4, streak 1
        m.collect_income(False)          # streak 1 -> pay 5, streak 2
        self.assertEqual(m.streak, 2)
        # A disturbed phase pays base and restarts the climb from streak 1.
        self.assertEqual(m.collect_income(disturbed=True), 4)
        self.assertEqual(m.streak, 1)
        self.assertEqual(m.collect_income(False), 5)

    def test_yield_amount_is_pure(self):
        """The panel/HUD read ``yield_amount()`` — it must NOT advance the streak
        (only ``collect_income`` does)."""
        m = self.med()
        before = m.streak
        self.assertEqual(m.yield_amount(), 4)
        self.assertEqual(m.yield_amount(), 4)
        self.assertEqual(m.streak, before)

    def test_disturbance_read_from_roundstats_in_payday(self):
        """End-to-end: a meditator that took damage last round pays base at the
        next payday (payday derives ``disturbed`` from RoundStats)."""
        tm, scene, occ = board(["bb"])
        st = run_state(unlocked=("meditator",), tiers={"meditator": 1})
        m, _ = place_building(tm, tm.get(1, 0), "meditator", 9999, BUILD,
                              scene, occ, state=st)
        love0 = st.love
        run_payday(st, tm, CORE, occ, scene)          # undisturbed: pays base 4
        self.assertEqual(st.love - love0, HOLE["base_income"] + 4)
        # Simulate damage this round, then payday: snapshot rolls it to
        # last_round, collect_income sees disturbed -> pays base again.
        m.get_component(RoundStats).dmg_taken_this_round = 20
        love1 = st.love
        run_payday(st, tm, CORE, occ, scene)
        self.assertEqual(st.love - love1, HOLE["base_income"] + 4)


# ---------------------------------------------------------------------------
class TestPainterPayout(unittest.TestCase):
    def place_painter(self, tm, scene, occ, st, at=(1, 0)):
        return place_building(tm, tm.get(*at), "painter", 9999, BUILD, scene,
                              occ, state=st)

    def test_pays_lump_sum_then_frees_and_bars_tile(self):
        tm, scene, occ = board(["bb"])
        st = run_state(unlocked=("painter",))
        painter, _ = self.place_painter(tm, scene, occ, st)
        payout = painter.payout_amount()               # tier1 lvl1 = 40
        rounds = painter.rounds_to_payout()            # 3

        # Painter yields nothing on the way to payout — only base income lands.
        for _ in range(rounds - 1):
            love0 = st.love
            run_payday(st, tm, CORE, occ, scene)
            self.assertEqual(st.love - love0, HOLE["base_income"])

        love0 = st.love
        run_payday(st, tm, CORE, occ, scene)           # the payout round
        self.assertEqual(st.love - love0, HOLE["base_income"] + payout)

        tile = tm.get(1, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)
        self.assertIsNone(tile.occupant)
        self.assertIsNone(occ.get((1, 0)))
        self.assertIn((1, 0), st.used_painter_tiles)
        self.assertIn((1, 0, "painting finished", "finished"),
                      st.painter_events)
        scene.update(0.0)                              # flush the despawn
        self.assertNotIn(painter, scene.by_tag("building"))

        # A completed tile permanently refuses another Painter.
        with self.assertRaises(PlacementError):
            self.place_painter(tm, scene, occ, st)

    def test_death_before_payout_pays_nothing_and_frees_without_barring(self):
        tm, scene, occ = board(["bb"])
        st = run_state(unlocked=("painter",))
        painter, _ = self.place_painter(tm, scene, occ, st)
        painter.get_component(Health).hp = 0           # died this round
        love0 = st.love

        run_payday(st, tm, CORE, occ, scene)

        # No payout; tier is gone-for-good so the painter is removed + "lost".
        self.assertEqual(st.love - love0, HOLE["base_income"])
        tile = tm.get(1, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)
        self.assertIsNone(tile.occupant)
        self.assertNotIn((1, 0), st.used_painter_tiles)   # NOT barred
        self.assertIn((1, 0, "painting lost!", "lost"), st.painter_events)
        # A lost tile can host a fresh Painter.
        self.place_painter(tm, scene, occ, st)

    def test_dead_painter_earns_no_progress(self):
        tm, scene, occ = board(["bb"])
        st = run_state(unlocked=("painter",))
        painter, _ = self.place_painter(tm, scene, occ, st)
        painter.get_component(Health).hp = 0
        run_payday(st, tm, CORE, occ, scene)
        # It was removed (gone-for-good) — the point is it never advanced /
        # paid: love only grew by base income (asserted above); here confirm the
        # slot skipped the dead painter rather than crediting a payout.
        self.assertNotIn((1, 0), st.used_painter_tiles)


# ---------------------------------------------------------------------------
class TestPainterThroughSession(unittest.TestCase):
    """End-to-end via the real ``Session`` round loop (not a direct payday) — so
    the occupancy + scene the Painter slot needs really arrive from the host."""

    def _frame(self, session, scene, tm, dt):
        session.pre_sim(dt, scene)
        scene.update(dt)
        resolve_combat(scene, tm, dt, BUILD, VFX, on_base_hit=session.on_base_hit)
        session.post_sim(scene)

    def test_painter_pays_and_frees_tile_over_real_rounds(self):
        tm, scene, occ = board(["bb"])          # no 's' -> empty waves
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ)
        session.state.unlocked_buildings["painter"] = True
        painter, _ = place_building(tm, tm.get(1, 0), "painter", 9999, BUILD,
                                    scene, occ, state=session.state)
        rounds = painter.rounds_to_payout()

        # Play through exactly `rounds` full rounds (End Turn -> empty wave ->
        # ROUND_END -> INCOME -> BUILDING). The payout lands on the last one.
        for target in range(2, 2 + rounds):
            session.end_turn()
            for _ in range(80):
                self._frame(session, scene, tm, 0.1)
                if session.state.phase == GamePhase.ENEMY_INTRO:
                    session.resolve_enemy_intro()
                if (session.state.phase == GamePhase.BUILDING
                        and session.state.round_num == target):
                    break
            self.assertEqual(session.state.round_num, target)

        tile = tm.get(1, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)   # freed
        self.assertIsNone(occ.get((1, 0)))                  # occupancy cleared
        self.assertIn((1, 0), session.state.used_painter_tiles)
        self.assertNotIn(painter, scene.by_tag("building"))  # despawned


if __name__ == "__main__":
    unittest.main()
