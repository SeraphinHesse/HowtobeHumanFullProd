"""Phase 10H: lightning strike + cheat menu.

Pure-Python, headless (no SDL) — the ``test_phase_loop`` fixture style: a synth
``TileMapDoc`` -> ``TileMap`` board + real balancing via ``load_balance``. The
radius tests use a REAL ``CoordinateSystem`` (Geometry tile_w 64 / tile_h 32)
so the projected-plane circle semantics are exercised against hand-computed
prototype geometry (radius is a Euclidean circle in the PROJECTED pixel plane,
NOT Chebyshev, NOT tile-space Euclidean). Values are read from
``CORE["LightningStrike"]`` so the tests track data, with the current literals
asserted once as a parity canary.
"""
import random
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.coords import CoordinateSystem, Geometry
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.buildings.research import LEAF_CLASSES, RESEARCH, buildable
from game.core import RunState, Session, load_balance
from game.core import lightning as lt
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.map.tile_map import TileMap
from game.ui.cheat_menu import CheatMenu

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
CORE = load_balance(REPO / "data", "core")
ENEM = load_balance(REPO / "data", "enemies")

LS = CORE["LightningStrike"]
HOLE = CORE["TheHole"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows):
    """A synth board with the base attached; returns (tilemap, scene, occ)."""
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def make_cs(zoom=1.0):
    """A real CoordinateSystem on the prototype's 64x32 iso pitch."""
    cs = CoordinateSystem(Geometry(
        tile_w=64, tile_h=32, map_cols=16, map_rows=16,
        zoom_levels=(1.0, zoom) if zoom != 1.0 else (1.0,)))
    if zoom != 1.0:
        cs.set_zoom(zoom)
    return cs


# A walkable field: base at (0,0), plenty of room for positioned enemies.
FIELD = ["bsssss"] + ["ssssss"] * 5


def spawn_enemy(scene, tm, col, row):
    e = create_enemy("standard", col, row, ENEM, tm)
    scene.spawn(e)
    return e


def frame(session, scene, tilemap_, dt):
    session.pre_sim(dt, scene)
    scene.update(dt)
    resolve_combat(scene, tilemap_, dt, BUILD, on_base_hit=session.on_base_hit,
                   on_enemy_death=session.on_enemy_death)
    session.post_sim(scene)


# ---------------------------------------------------------------------------
# 1. Seed + cost math
# ---------------------------------------------------------------------------
class TestSeedAndCosts(unittest.TestCase):
    def test_parity_canary_against_live_prototype_values(self):
        # The live Balancing_Core.json values (NOT the stale .py defaults).
        self.assertEqual(LS["cooldown"], [5, 3, 2])
        self.assertEqual(LS["damage"], [10, 15, 32])
        self.assertEqual(LS["radius"], [1, 2, 3])
        self.assertEqual(LS["max_level"], 3)
        self.assertEqual(LS["unlock_cost"], 20)
        self.assertEqual(LS["upgrade_costs"], [35, 80])

    def test_fresh_run_starts_at_level_1_no_cooldown(self):
        st = RunState.from_balance(CORE, BUILD)
        self.assertEqual(st.lightning_level, 1)   # prototype game.py:117
        self.assertEqual(st.lightning_cooldown, 0.0)

    def test_cost_ladder_and_upgrades(self):
        st = RunState.from_balance(CORE, BUILD)
        st.love = 35 + 80
        self.assertEqual(lt.next_cost(st, CORE), 35)      # L1 -> L2
        self.assertTrue(lt.upgrade(st, CORE))
        self.assertEqual(st.lightning_level, 2)
        self.assertEqual(st.love, 80)                     # exactly 35 spent
        self.assertEqual(lt.next_cost(st, CORE), 80)      # L2 -> L3
        self.assertTrue(lt.upgrade(st, CORE))
        self.assertEqual(st.lightning_level, 3)
        self.assertEqual(st.love, 0)

    def test_max_level_no_op(self):
        st = RunState.from_balance(CORE, BUILD)
        st.lightning_level = LS["max_level"]
        st.love = 9999
        self.assertIsNone(lt.next_cost(st, CORE))
        self.assertFalse(lt.upgrade(st, CORE))
        self.assertEqual(st.lightning_level, LS["max_level"])
        self.assertEqual(st.love, 9999)                   # no love spent

    def test_insufficient_love_refused(self):
        st = RunState.from_balance(CORE, BUILD)
        st.love = 34
        self.assertFalse(lt.upgrade(st, CORE))
        self.assertEqual(st.lightning_level, 1)
        self.assertEqual(st.love, 34)

    def test_unlock_branch_reachable_at_level_0(self):
        st = RunState.from_balance(CORE, BUILD)
        st.lightning_level = 0
        self.assertEqual(lt.next_cost(st, CORE), LS["unlock_cost"])  # 20
        st.love = LS["unlock_cost"]
        self.assertTrue(lt.upgrade(st, CORE))
        self.assertEqual(st.lightning_level, 1)


# ---------------------------------------------------------------------------
# 2. Cooldown gating
# ---------------------------------------------------------------------------
class TestCooldown(unittest.TestCase):
    def test_strike_spends_cooldown_and_upgrade_never_resets_it(self):
        tm, scene, occ = build_board(FIELD)
        st = RunState.from_balance(CORE, BUILD)
        cs = make_cs()
        self.assertTrue(lt.strike(st, CORE, scene, cs, 3.0, 3.0))  # whiff ok
        self.assertEqual(st.lightning_cooldown, LS["cooldown"][0])
        st.love = 35
        lt.upgrade(st, CORE)                       # upgrade mid-cooldown
        self.assertEqual(st.lightning_cooldown, LS["cooldown"][0])  # untouched

    def test_strike_while_cooling_is_a_silent_noop(self):
        tm, scene, occ = build_board(FIELD)
        st = RunState.from_balance(CORE, BUILD)
        cs = make_cs()
        e = spawn_enemy(scene, tm, 3, 3)
        scene.update(0.0)
        hp0 = e.get_component(Health).hp
        st.lightning_cooldown = 2.0
        self.assertFalse(lt.can_strike(st))
        self.assertFalse(lt.strike(st, CORE, scene, cs,
                                   *e.transform.world_pos))
        scene.update(0.0)
        self.assertEqual(e.get_component(Health).hp, hp0)   # no damage
        self.assertEqual(scene.by_tag("lightning_fx"), [])  # no FX
        self.assertEqual(st.lightning_cooldown, 2.0)        # unchanged

    def test_whiff_still_spends_full_cooldown_and_plays_fx(self):
        tm, scene, occ = build_board(FIELD)   # no enemies at all
        st = RunState.from_balance(CORE, BUILD)
        cs = make_cs()
        self.assertTrue(lt.strike(st, CORE, scene, cs, 4.0, 4.0))
        scene.update(0.0)
        self.assertEqual(st.lightning_cooldown, LS["cooldown"][0])
        self.assertEqual(len(scene.by_tag("lightning_fx")), 1)

    def test_tick_drains_linearly_and_clamps_at_zero(self):
        st = RunState.from_balance(CORE, BUILD)
        st.lightning_cooldown = 3.0
        lt.tick(st, 1.0)
        self.assertAlmostEqual(st.lightning_cooldown, 2.0)
        lt.tick(st, 10.0)
        self.assertEqual(st.lightning_cooldown, 0.0)
        lt.tick(st, 1.0)                                    # already 0: stable
        self.assertEqual(st.lightning_cooldown, 0.0)

    def test_pre_sim_drains_only_in_enemy_phase(self):
        tm, scene, occ = build_board(["bb"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        st = session.state
        st.lightning_cooldown = 3.0
        st.phase = GamePhase.ENEMY
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(st.lightning_cooldown, 2.0)  # ENEMY: drains
        st.phase = GamePhase.BUILDING
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(st.lightning_cooldown, 2.0)  # BUILDING: frozen
        st.phase = GamePhase.INCOME
        st.phase_timer = 99.0
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(st.lightning_cooldown, 2.0)  # INCOME: frozen

    def test_fx_ages_and_self_despawns(self):
        tm, scene, occ = build_board(FIELD)
        st = RunState.from_balance(CORE, BUILD)
        lt.strike(st, CORE, scene, make_cs(), 4.0, 4.0)
        scene.update(0.0)
        fx = scene.by_tag("lightning_fx")[0]
        scene.update(0.3)
        self.assertGreater(fx.bolt_frac, 0.0)
        self.assertGreater(fx.fade_frac, 0.0)
        scene.update(0.3)                       # age 0.6 > BOLT_LIFE
        self.assertEqual(fx.bolt_frac, 0.0)
        self.assertGreater(fx.fade_frac, 0.0)
        scene.update(0.5)                       # age 1.1 >= MARKER_LIFE
        scene.update(0.0)                       # flush the despawn queue
        self.assertEqual(scene.by_tag("lightning_fx"), [])


# ---------------------------------------------------------------------------
# 3. Radius vs hand-computed prototype geometry (projected-plane circle)
# ---------------------------------------------------------------------------
class TestRadiusGeometry(unittest.TestCase):
    """With tile_w 64 the projected threshold per radius unit is 32 px. Iso
    deltas: Δ(+1,+1) world -> (0, 32) px = 32.0; Δ(+1,0) -> (32, 16) px
    ≈ 35.78; Δ(+2,0) -> (64, 32) px ≈ 71.55 (prototype game.py:505-508)."""

    def _board_with(self, deltas, zoom=1.0):
        """Enemies at world offsets ``deltas`` from the strike point (4, 4).
        Returns (scene, cs, strike point, [enemies])."""
        tm, scene, occ = build_board(FIELD)
        enemies = []
        for dwx, dwy in deltas:
            e = spawn_enemy(scene, tm, 4, 4)
            enemies.append((e, dwx, dwy))
        scene.update(0.0)
        origin = enemies[0][0].transform.world_pos
        for e, dwx, dwy in enemies:
            e.transform.wx = origin[0] + dwx
            e.transform.wy = origin[1] + dwy
        return scene, make_cs(zoom), origin, [e for e, _, _ in enemies]

    def _strike(self, st, scene, cs, wx, wy):
        hp0 = {id(e): e.get_component(Health).hp
               for e in scene.by_tag("enemy")}
        self.assertTrue(lt.strike(st, CORE, scene, cs, wx, wy))
        return {id(e): hp0[id(e)] - e.get_component(Health).hp
                for e in scene.by_tag("enemy")}

    def test_radius_1_boundary_hit_and_near_miss(self, zoom=1.0):
        scene, cs, (wx, wy), (center, diag, adj) = self._board_with(
            [(0, 0), (1, 1), (1, 0)], zoom=zoom)
        st = RunState.from_balance(CORE, BUILD)          # level 1, radius 1
        dealt = self._strike(st, scene, cs, wx, wy)
        dmg = LS["damage"][0]
        self.assertEqual(dealt[id(center)], dmg)  # on the strike point
        self.assertEqual(dealt[id(diag)], dmg)    # d = 32 px: boundary <= HITS
        self.assertEqual(dealt[id(adj)], 0)       # d ≈ 35.78 px: MISS

    def test_zoom_invariance(self):
        # The same layout at zoom 2 produces the identical hit set.
        self.test_radius_1_boundary_hit_and_near_miss(zoom=2.0)

    def test_radius_2_and_3_widen_the_circle(self):
        scene, cs, (wx, wy), (center, adj, two) = self._board_with(
            [(0, 0), (1, 0), (2, 0)])
        st = RunState.from_balance(CORE, BUILD)
        st.lightning_level = 2                     # radius 2 -> 64 px
        dealt = self._strike(st, scene, cs, wx, wy)
        dmg2 = LS["damage"][1]
        self.assertEqual(dealt[id(adj)], dmg2)     # 35.78 <= 64: HIT
        self.assertEqual(dealt[id(two)], 0)        # 71.55 > 64: MISS

        st.lightning_level = 3                     # radius 3 -> 96 px
        st.lightning_cooldown = 0.0
        dealt = self._strike(st, scene, cs, wx, wy)
        self.assertEqual(dealt[id(two)], LS["damage"][2])  # 71.55 <= 96: HIT

    def test_all_in_radius_take_full_flat_damage(self):
        scene, cs, (wx, wy), (a, b) = self._board_with([(0, 0), (1, 1)])
        st = RunState.from_balance(CORE, BUILD)
        dealt = self._strike(st, scene, cs, wx, wy)
        self.assertEqual(dealt[id(a)], LS["damage"][0])   # no falloff
        self.assertEqual(dealt[id(b)], LS["damage"][0])   # no target cap

    def test_lightning_kill_pays_xp_through_the_normal_sweep(self):
        tm, scene, occ = build_board(FIELD)
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        st = session.state
        st.phase = GamePhase.ENEMY
        e = spawn_enemy(scene, tm, 4, 4)
        scene.update(0.0)
        e.get_component(Health).hp = LS["damage"][0]  # exactly lethal
        lt.strike(st, CORE, scene, make_cs(), *e.transform.world_pos)
        self.assertFalse(e.alive)
        frame(session, scene, tm, 0.0)                # the next combat sweep
        scene.update(0.0)                             # flush despawns
        self.assertEqual(scene.by_tag("enemy"), [])
        self.assertEqual(st.enemies_killed, 1)        # on_enemy_death fired
        self.assertGreater(st.player_xp, 0)           # XP paid


# ---------------------------------------------------------------------------
# 4. Cheat operations on session state
# ---------------------------------------------------------------------------
class TestCheats(unittest.TestCase):
    def _session(self, rows, rng=None):
        tm, scene, occ = build_board(rows)
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, rng=rng)
        return session, scene, tm

    def test_add_love_and_inf_money(self):
        session, scene, tm = self._session(["bb"])
        love0 = session.state.love
        session.cheat_add_love(10)
        self.assertEqual(session.state.love, love0 + 10)
        session.cheat_add_love(999999)
        self.assertEqual(session.state.love, love0 + 10 + 999999)

    def test_cheats_frozen_on_game_over(self):
        session, scene, tm = self._session(["bb"])
        session.state.state = GameState.GAME_OVER
        love0, round0 = session.state.love, session.state.round_num
        session.cheat_add_love(10)
        session.cheat_skip_round(scene)
        session.cheat_goto_round(9, scene)
        session.cheat_trigger_levelup()
        session.cheat_unlock_all()
        self.assertEqual(session.state.love, love0)
        self.assertEqual(session.state.round_num, round0)
        self.assertEqual(session.state.phase, GamePhase.BUILDING)

    def test_skip_round_mid_enemy_no_xp_then_exactly_one_payday(self):
        session, scene, tm = self._session(["bsss"],
                                           rng=random.Random(11))
        st = session.state
        session.end_turn()                          # queue a real wave
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertTrue(session.spawner.pending())  # something queued
        love0, round0 = st.love, st.round_num

        session.cheat_skip_round(scene)

        scene.update(0.0)                           # flush despawns
        self.assertEqual(st.phase, GamePhase.ROUND_END)
        self.assertEqual(scene.by_tag("enemy"), []) # field wiped
        self.assertEqual(session.spawner.pending(), [])
        self.assertEqual(st.player_xp, 0)           # NO XP paid (quick-skip)
        # Ride ROUND_END + INCOME back to BUILDING: exactly ONE payday.
        for _ in range(80):
            frame(session, scene, tm, 0.1)
            if st.phase == GamePhase.BUILDING:
                break
        self.assertEqual(st.phase, GamePhase.BUILDING)
        self.assertEqual(st.round_num, round0 + 1)  # round advanced ONCE
        self.assertEqual(st.love, love0 + HOLE["base_income"])  # one payout

    def test_goto_round_jumps_without_payday(self):
        session, scene, tm = self._session(["bsss"], rng=random.Random(3))
        st = session.state
        love0, lives0 = st.love, st.base_lives
        session.cheat_goto_round(7, scene)
        self.assertEqual(st.round_num, 7)
        self.assertEqual(st.phase, GamePhase.BUILDING)
        self.assertEqual(st.love, love0)            # no payday, no love change
        self.assertEqual(st.base_lives, lives0)
        # The next end_turn composes a ROUND-7 wave: same count a control
        # spawner produces for round 7 on an identical board + rng.
        session.end_turn()
        control = Spawner()
        control.begin_round(7, synth(["bsss"]), ENEM, rng=random.Random(3))
        self.assertEqual(len(session.spawner.pending()),
                         len(control.pending()))
        self.assertGreater(len(session.spawner.pending()), 0)

    def test_trigger_levelup_from_building_returns_with_no_payday(self):
        session, scene, tm = self._session(["bb"])
        st = session.state
        round0, lvl0 = st.round_num, st.village_level

        session.cheat_trigger_levelup()

        self.assertEqual(st.phase, GamePhase.LEVELUP)
        self.assertEqual(len(st.levelup_options), 3)  # rolled (pad-to-3)
        session.resolve_levelup(st.levelup_options[0], scene)
        self.assertEqual(st.phase, GamePhase.BUILDING)  # return_phase restored
        self.assertEqual(st.round_num, round0)          # NO payday ran
        self.assertEqual(st.village_level, lvl0 + 1)    # level math identical
        self.assertFalse(st.levelup_pending)

    def test_trigger_levelup_mid_enemy_defers_to_the_payday_path(self):
        session, scene, tm = self._session(["bb"])      # spawnless: empty wave
        st = session.state
        session.end_turn()
        self.assertEqual(st.phase, GamePhase.ENEMY)
        round0 = st.round_num

        session.cheat_trigger_levelup()
        self.assertEqual(st.phase, GamePhase.ENEMY)     # only the flag is set
        self.assertTrue(st.levelup_pending)

        for _ in range(80):                             # natural round end
            frame(session, scene, tm, 0.1)
            if st.phase == GamePhase.LEVELUP:
                break
        self.assertEqual(st.phase, GamePhase.LEVELUP)
        session.resolve_levelup(st.levelup_options[0], scene)
        # Regression on the DEFAULT path: payday ran (round++, -> INCOME).
        self.assertEqual(st.phase, GamePhase.INCOME)
        self.assertEqual(st.round_num, round0 + 1)

    def test_unlock_all_covers_every_research_type(self):
        session, scene, tm = self._session(["bb"])
        st = session.state
        session.cheat_unlock_all()
        for bt in RESEARCH:
            self.assertTrue(st.unlocked_buildings[bt], bt)
            tiers = LEAF_CLASSES[bt]._resolve_tiers(BUILD)
            self.assertEqual(st.tiers_unlocked[bt], len(tiers), bt)
            self.assertTrue(buildable(st, bt), bt)
        # The documented prototype-omission fix: meditator + blocker included.
        self.assertTrue(buildable(st, "meditator"))
        self.assertTrue(buildable(st, "blocker"))


# ---------------------------------------------------------------------------
# 5. Cheat menu actions (pure modal) + purity
# ---------------------------------------------------------------------------
class TestCheatMenuActions(unittest.TestCase):
    def _center(self, rect):
        x, y, w, h = rect
        return x + w // 2, y + h // 2

    def test_buttons_return_their_actions(self):
        menu = CheatMenu(1280, 720)
        menu.open()
        expected = ("add_love", "skip_round", "trigger_levelup", "inf_money",
                    "unlock_all")
        for (action, btn), want in zip(menu.buttons, expected):
            self.assertEqual(action, want)
            self.assertEqual(menu.hit(*self._center(btn.rect)), want)
        self.assertEqual(menu.hit(*self._center(menu.close_btn.rect)), "close")
        self.assertIsNone(menu.hit(0, 0))          # off-panel click swallowed

    def test_goto_round_field_digits_only_max_4_commit(self):
        menu = CheatMenu(1280, 720)
        menu.open()
        menu.hit(*self._center(menu.field_rect))   # click-to-focus
        self.assertTrue(menu.field_focused)
        for ch in "2x0!71":                        # non-digits ignored
            menu.handle_key(ch, None)
        self.assertEqual(menu.round_text, "2071")  # capped at 4 digits
        menu.handle_key("", "backspace")
        self.assertEqual(menu.round_text, "207")
        self.assertEqual(menu.handle_key("", "return"), ("goto_round", 207))

    def test_empty_or_invalid_commit_is_a_noop(self):
        menu = CheatMenu(1280, 720)
        menu.open()
        menu.hit(*self._center(menu.field_rect))
        self.assertIsNone(menu.handle_key("", "return"))   # empty field
        self.assertIsNone(menu.hit(*self._center(menu.go_btn.rect)))
        menu.round_text = "0"                              # n < 1
        self.assertIsNone(menu._commit())

    def test_reopen_resets_the_round_field(self):
        # Review finding: open() must clear the input state every time
        # (prototype clears _buf/_active on open).
        menu = CheatMenu(1280, 720)
        menu.open()
        menu.hit(*self._center(menu.field_rect))
        menu.handle_key("4", None)
        menu.handle_key("2", None)
        self.assertEqual(menu.round_text, "42")
        menu.close()
        menu.open()
        self.assertEqual(menu.round_text, "")
        self.assertFalse(menu.field_focused)

    def test_escape_closes_and_all_other_keys_swallowed(self):
        menu = CheatMenu(1280, 720)
        menu.open()
        self.assertEqual(menu.handle_key("", "escape"), "close")
        self.assertIsNone(menu.handle_key("p", None))  # not the quick-skip!


class TestPurity(unittest.TestCase):
    def test_core_lightning_imports_no_pygame(self):
        code = ("import sys; import game.core.lightning; "
                "assert 'pygame' not in sys.modules, "
                "'pygame leaked into game.core.lightning'")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_cheat_menu_has_no_direct_pygame_import(self):
        # The directory-wide game/ui scan in test_shell covers this too; this
        # is the explicit 10H guard per the phase brief.
        src = (REPO / "game" / "ui" / "cheat_menu.py").read_text(
            encoding="utf-8")
        for line in src.splitlines():
            s = line.strip()
            self.assertFalse(
                s.startswith(("import pygame", "from pygame")),
                f"cheat_menu.py imports pygame directly: {s}")


if __name__ == "__main__":
    unittest.main()
