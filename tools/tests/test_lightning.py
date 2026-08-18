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
import copy
import random
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.coords import CoordinateSystem, Geometry
from engine.core import Health, Scene, SpriteAnimator
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, create, place_building
from game.buildings.research import LEAF_CLASSES, RESEARCH, buildable
from game.core import RunState, Session, load_balance
from game.core import lightning as lt
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.components import apply_slow, buff_total
from game.map.tile_map import TileMap
from game.ui.cheat_menu import CheatMenu

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

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


def spawn_storm_priest(scene, tier_idx=0, col=0, row=0):
    """A Storm Priest GameObject spawned directly into ``scene`` — bypassing
    ``place_building`` (real tile occupancy). ``lt.strike``/``tick``/
    ``can_strike`` only ever consult ``scene.by_tag("lightning_source")``,
    never tile state, so this is enough for tests that need a real
    ``LightningCaster`` at a given tier but don't care where it stands
    (radius/damage/cooldown geometry). Placement-mechanics tests
    (TestStormPriestUnlock et al.) go through the real ``place_building``
    seam instead."""
    b = create("storm_priest", col, row, BUILD, tier_idx)
    scene.spawn(b)
    return b


def frame(session, scene, tilemap_, dt):
    session.pre_sim(dt, scene)
    scene.update(dt)
    resolve_combat(scene, tilemap_, dt, BUILD, VFX,
                   on_base_hit=session.on_base_hit,
                   on_enemy_death=session.on_enemy_death)
    session.post_sim(scene)


# ---------------------------------------------------------------------------
# 1. Seed + cost math
# ---------------------------------------------------------------------------
class TestSeedAndCosts(unittest.TestCase):
    def test_parity_canary_against_fixture_values(self):
        # The pinned fixture core.json values (NOT the stale .py defaults).
        self.assertEqual(LS["cooldown"], [5, 3, 2])
        self.assertEqual(LS["damage"], [12, 18, 38])   # Storm Priest buff
        self.assertEqual(LS["radius"], [1, 2, 3])
        self.assertEqual(LS["max_level"], 3)

    def test_fresh_run_starts_at_level_0_locked(self):
        # Storm Priest wiring: lightning now boots LOCKED. A Storm Priest
        # placement (game.core.lightning.unlock_from_placement) is the ONLY
        # way to reach L1 — see TestStormPriestUnlock below. No RunState
        # cooldown field any more (feature-storm-acolyte-multi-build moved
        # it onto each caster) — an empty scene has no caster either way.
        st = RunState.from_balance(CORE, BUILD)
        self.assertEqual(st.lightning_level, 0)
        self.assertFalse(lt.can_strike(st, Scene()))


# ---------------------------------------------------------------------------
# 1b. Storm Priest placement unlock (game.ui.building_ui._do_place seam)
# ---------------------------------------------------------------------------
BUILDABLE_FIELD = ["bbb", "bbb", "bbb"]  # 'b' = BUILDABLE (not FIELD's 's' rows)


class TestStormPriestUnlock(unittest.TestCase):
    def test_placing_storm_priest_unlocks_lightning(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        self.assertEqual(st.lightning_level, 0)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        lt.unlock_from_placement(st, building)
        self.assertEqual(st.lightning_level, 1)

    def test_placing_a_non_source_building_leaves_it_locked(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "defence", 9999, BUILD, scene, occ)
        lt.unlock_from_placement(st, building)
        self.assertEqual(st.lightning_level, 0)

    def test_unlock_is_a_latch_not_a_reset(self):
        """A later Storm Priest placement (or any placement) never re-locks
        or lowers an already-upgraded run — the max() latch."""
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        st.lightning_level = 3
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        lt.unlock_from_placement(st, building)
        self.assertEqual(st.lightning_level, 3)


# ---------------------------------------------------------------------------
# 1c. Storm Priest tier -> lightning_level sync (game.ui.building_ui's
#     tier-advance branch: advance_tier() + sync_level_from_tier)
# ---------------------------------------------------------------------------
class TestStormPriestTierLeveling(unittest.TestCase):
    def test_advancing_tiers_raises_level_to_match(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        lt.unlock_from_placement(st, building)
        self.assertEqual(st.lightning_level, 1)
        self.assertEqual(building.tier_number(), 1)

        self.assertTrue(building.advance_tier())
        lt.sync_level_from_tier(st, building)
        self.assertEqual(building.tier_number(), 2)
        self.assertEqual(st.lightning_level, 2)

        self.assertTrue(building.advance_tier())
        lt.sync_level_from_tier(st, building)
        self.assertEqual(building.tier_number(), 3)
        self.assertEqual(st.lightning_level, 3)

    def test_sync_is_a_latch_not_a_reset(self):
        """A re-sync (or a batch call) never lowers an already-higher level."""
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        st.lightning_level = 3
        lt.sync_level_from_tier(st, building)   # building is still tier 1
        self.assertEqual(st.lightning_level, 3)

    def test_non_lightning_source_tier_advance_leaves_level_untouched(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "defence", 9999, BUILD, scene, occ)
        self.assertEqual(st.lightning_level, 0)
        building.advance_tier()
        lt.sync_level_from_tier(st, building)
        self.assertEqual(st.lightning_level, 0)


# ---------------------------------------------------------------------------
# 1d. Storm Priest is no longer a combatant (dropped the "combat" tag)
# ---------------------------------------------------------------------------
class TestStormPriestNotCombat(unittest.TestCase):
    def test_storm_priest_carries_no_combat_tag(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        self.assertNotIn("combat", building.tags)
        self.assertIn("lightning_source", building.tags)

    def test_placed_storm_priest_never_fires_even_with_enemy_in_range(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        e = spawn_enemy(scene, tm, 1, 2)   # adjacent — well within any range
        scene.update(0.0)
        hp0 = e.get_component(Health).hp
        for _ in range(20):
            scene.update(0.1)
            resolve_combat(scene, tm, 0.1, BUILD, VFX)
        self.assertEqual(e.get_component(Health).hp, hp0)   # never attacked
        self.assertEqual(scene.by_tag("projectile"), [])    # never fired


# ---------------------------------------------------------------------------
# 1e. strike() flashes the placed Storm Priest's attack pose
# ---------------------------------------------------------------------------
class TestStormPriestCasterFlash(unittest.TestCase):
    def test_strike_flips_to_attack_then_reverts_to_idle(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        tile = tm.get(1, 1)
        building, _cost = place_building(
            tm, tile, "storm_priest", 9999, BUILD, scene, occ)
        scene.update(0.0)
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, building)
        anim = building.get_component(SpriteAnimator)
        self.assertEqual(anim.animation, "idle")

        cs = make_cs()
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, 1.0, 1.0))  # whiff ok
        scene.update(0.0)
        self.assertEqual(anim.animation, "attack")

        scene.update(lt.CASTER_FLASH_DURATION + 0.1)
        self.assertEqual(anim.animation, "idle")


# ---------------------------------------------------------------------------
# 2. Cooldown gating
# ---------------------------------------------------------------------------
class TestCooldown(unittest.TestCase):
    """feature-storm-acolyte-multi-build: the cooldown lives on each fired
    caster's own ``LightningCaster.cooldown`` now, not a single ``RunState``
    field — every test here places (or bypass-spawns) a real Storm Priest."""

    def test_strike_spends_cooldown_on_the_firing_caster(self):
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene)          # tier0 -> level 1
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        cs = make_cs()
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, 3.0, 3.0))  # whiff ok
        caster = priest.get_component(lt.LightningCaster)
        self.assertEqual(caster.cooldown, LS["cooldown"][0])

    def test_strike_while_cooling_is_a_silent_noop(self):
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene)
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        cs = make_cs()                              # cooldown gate specifically
        e = spawn_enemy(scene, tm, 3, 3)
        scene.update(0.0)
        hp0 = e.get_component(Health).hp
        caster = priest.get_component(lt.LightningCaster)
        caster.cooldown = 2.0
        self.assertFalse(lt.can_strike(st, scene))
        self.assertFalse(lt.strike(st, CORE, VFX, scene, cs,
                                   *e.transform.world_pos))
        scene.update(0.0)
        self.assertEqual(e.get_component(Health).hp, hp0)   # no damage
        self.assertEqual(scene.by_tag("lightning_fx"), [])  # no FX
        self.assertEqual(caster.cooldown, 2.0)               # unchanged

    def test_whiff_still_spends_full_cooldown_and_plays_fx(self):
        tm, scene, occ = build_board(FIELD)   # no enemies at all
        priest = spawn_storm_priest(scene)
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        cs = make_cs()
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, 4.0, 4.0))
        scene.update(0.0)
        caster = priest.get_component(lt.LightningCaster)
        self.assertEqual(caster.cooldown, LS["cooldown"][0])
        self.assertEqual(len(scene.by_tag("lightning_fx")), 1)

    def test_tick_drains_linearly_and_clamps_at_zero(self):
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene)
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        st = RunState.from_balance(CORE, BUILD)
        caster = priest.get_component(lt.LightningCaster)
        caster.cooldown = 3.0
        lt.tick(st, 1.0, scene)
        self.assertAlmostEqual(caster.cooldown, 2.0)
        lt.tick(st, 10.0, scene)
        self.assertEqual(caster.cooldown, 0.0)
        lt.tick(st, 1.0, scene)                             # already 0: stable
        self.assertEqual(caster.cooldown, 0.0)

    def test_pre_sim_drains_only_in_enemy_phase(self):
        tm, scene, occ = build_board(["bb"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        st = session.state
        building, _c = place_building(tm, tm.get(1, 0), "storm_priest", 9999,
                                      BUILD, scene, occ)
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        caster = building.get_component(lt.LightningCaster)
        caster.cooldown = 3.0
        st.phase = GamePhase.ENEMY
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(caster.cooldown, 2.0)  # ENEMY: drains
        st.phase = GamePhase.BUILDING
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(caster.cooldown, 2.0)  # BUILDING: frozen
        st.phase = GamePhase.INCOME
        st.phase_timer = 99.0
        session.pre_sim(1.0, scene)
        self.assertAlmostEqual(caster.cooldown, 2.0)  # INCOME: frozen

    def test_fx_ages_and_self_despawns(self):
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene)
        scene.update(0.0)     # flush the spawn queue: by_tag needs it live
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        lt.strike(st, CORE, VFX, scene, make_cs(), 4.0, 4.0)
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

    def _board_with(self, deltas, zoom=1.0, tier_idx=0):
        """Enemies at world offsets ``deltas`` from the strike point (4, 4),
        plus a real Storm Priest caster at ``tier_idx`` (bypass-spawned —
        this class only cares about damage/radius geometry, not placement
        mechanics). Returns (scene, cs, strike point, [enemies], priest)."""
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene, tier_idx)
        enemies = []
        for dwx, dwy in deltas:
            e = spawn_enemy(scene, tm, 4, 4)
            enemies.append((e, dwx, dwy))
        scene.update(0.0)
        origin = enemies[0][0].transform.world_pos
        for e, dwx, dwy in enemies:
            e.transform.wx = origin[0] + dwx
            e.transform.wy = origin[1] + dwy
        return scene, make_cs(zoom), origin, [e for e, _, _ in enemies], priest

    def _strike(self, st, scene, cs, wx, wy):
        hp0 = {id(e): e.get_component(Health).hp
               for e in scene.by_tag("enemy")}
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, wx, wy))
        return {id(e): hp0[id(e)] - e.get_component(Health).hp
                for e in scene.by_tag("enemy")}

    def test_radius_1_boundary_hit_and_near_miss(self, zoom=1.0):
        scene, cs, (wx, wy), (center, diag, adj), priest = self._board_with(
            [(0, 0), (1, 1), (1, 0)], zoom=zoom)
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)          # tier0 -> radius 1
        dealt = self._strike(st, scene, cs, wx, wy)
        dmg = LS["damage"][0]
        self.assertEqual(dealt[id(center)], dmg)  # on the strike point
        self.assertEqual(dealt[id(diag)], dmg)    # d = 32 px: boundary <= HITS
        self.assertEqual(dealt[id(adj)], 0)       # d ≈ 35.78 px: MISS

    def test_zoom_invariance(self):
        # The same layout at zoom 2 produces the identical hit set.
        self.test_radius_1_boundary_hit_and_near_miss(zoom=2.0)

    def test_radius_2_and_3_widen_the_circle(self):
        scene, cs, (wx, wy), (center, adj, two), priest = self._board_with(
            [(0, 0), (1, 0), (2, 0)], tier_idx=1)     # tier1 -> radius 2, 64 px
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        dealt = self._strike(st, scene, cs, wx, wy)
        dmg2 = LS["damage"][1]
        self.assertEqual(dealt[id(adj)], dmg2)     # 35.78 <= 64: HIT
        self.assertEqual(dealt[id(two)], 0)        # 71.55 > 64: MISS

        priest.advance_tier()                      # tier2 -> radius 3, 96 px
        priest.get_component(lt.LightningCaster).cooldown = 0.0
        dealt = self._strike(st, scene, cs, wx, wy)
        self.assertEqual(dealt[id(two)], LS["damage"][2])  # 71.55 <= 96: HIT

    def test_all_in_radius_take_full_flat_damage(self):
        scene, cs, (wx, wy), (a, b), priest = self._board_with([(0, 0), (1, 1)])
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)          # unlocked via a Storm Priest
        dealt = self._strike(st, scene, cs, wx, wy)
        self.assertEqual(dealt[id(a)], LS["damage"][0])   # no falloff
        self.assertEqual(dealt[id(b)], LS["damage"][0])   # no target cap

    def test_lightning_kill_pays_xp_through_the_normal_sweep(self):
        tm, scene, occ = build_board(FIELD)
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        st = session.state
        priest = spawn_storm_priest(scene)         # unlocked via a Storm Priest
        lt.unlock_from_placement(st, priest)
        st.phase = GamePhase.ENEMY
        e = spawn_enemy(scene, tm, 4, 4)
        scene.update(0.0)
        e.get_component(Health).hp = LS["damage"][0]  # exactly lethal
        lt.strike(st, CORE, VFX, scene, make_cs(), *e.transform.world_pos)
        self.assertFalse(e.alive)
        frame(session, scene, tm, 0.0)                # the next combat sweep
        scene.update(0.0)                             # flush despawns
        self.assertEqual(scene.by_tag("enemy"), [])
        self.assertEqual(st.enemies_killed, 1)        # on_enemy_death fired
        self.assertGreater(st.player_xp, 0)           # XP paid


# ---------------------------------------------------------------------------
# 3b. feature-storm-acolyte-multi-build: escalating cost curve + multi-fire
# ---------------------------------------------------------------------------
class TestStormAcolyteEscalatingCost(unittest.TestCase):
    """The run-singleton ban is lifted: each fresh lightning_source-tagged
    placement costs the group's own ``repeat_cost_multiplier`` steeper than
    the last, tag-gated off ``count_tag`` (never a `storm_priest ==` type
    branch)."""

    def test_repeat_placement_escalates_by_the_group_multiplier(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        sp = BUILD["DefenceBuildings"]["StormPriest"]
        base_cost = sp["tiers"][0]["build_cost"]
        mult = sp["repeat_cost_multiplier"]
        tiles = [tm.get(0, 1), tm.get(1, 1), tm.get(2, 1)]
        costs = []
        for tile in tiles:
            _b, cost = place_building(tm, tile, "storm_priest", 999999,
                                      BUILD, scene, occ)
            costs.append(cost)
        self.assertEqual(costs, [
            base_cost,
            round(base_cost * mult),
            round(base_cost * mult ** 2),
        ])


class TestMultiAcolyteStrike(unittest.TestCase):
    """``strike()`` fires EVERY ready caster at the clicked point, each
    contributing its own tier's damage/radius/cooldown; a caster still
    cooling sits the strike out entirely."""

    def test_ready_casters_stack_damage_by_own_tier_cooling_one_sits_out(self):
        tm, scene, occ = build_board(BUILDABLE_FIELD)
        st = RunState.from_balance(CORE, BUILD)
        tier1, _c = place_building(tm, tm.get(0, 1), "storm_priest", 999999,
                                   BUILD, scene, occ)
        tier3, _c = place_building(tm, tm.get(1, 1), "storm_priest", 999999,
                                   BUILD, scene, occ)
        cooling, _c = place_building(tm, tm.get(2, 1), "storm_priest", 999999,
                                     BUILD, scene, occ)
        lt.unlock_from_placement(st, tier1)
        tier3.advance_tier()
        tier3.advance_tier()                        # tier index 2 -> level 3
        cooling.get_component(lt.LightningCaster).cooldown = 5.0

        cs = make_cs()
        e = spawn_enemy(scene, tm, 2, 2)
        scene.update(0.0)
        hp0 = e.get_component(Health).hp

        struck = lt.strike(st, CORE, VFX, scene, cs, *e.transform.world_pos)

        self.assertTrue(struck)
        dealt = hp0 - e.get_component(Health).hp
        self.assertEqual(dealt, LS["damage"][0] + LS["damage"][2])  # stacked
        self.assertEqual(tier1.get_component(lt.LightningCaster).cooldown,
                         LS["cooldown"][0])
        self.assertEqual(tier3.get_component(lt.LightningCaster).cooldown,
                         LS["cooldown"][2])
        self.assertEqual(cooling.get_component(lt.LightningCaster).cooldown,
                         5.0)      # untouched: never fired, never re-set
        scene.update(0.0)
        self.assertEqual(len(scene.by_tag("lightning_fx")), 2)  # one per firer


# ---------------------------------------------------------------------------
# 3c. Footprint-aware hit-test (the boss's "click above the model" bug)
# ---------------------------------------------------------------------------
class TestFootprintAwareHitTest(unittest.TestCase):
    """The boss's 2x2 block draws centred on the block's true CENTRE
    (renderer.py's ``block_center_offset``), not on ``transform.world_pos``
    (the anchor / MIN corner). ``strike()`` must hit-test against that same
    centre point — this is what previously made a click on the boss's
    visible lower body miss (you had to click ABOVE the model, at the
    anchor, to register a hit)."""

    def _footprint_2_boss(self, tm, col=10, row=10, era=0):
        enem = copy.deepcopy(ENEM)
        for row_ in enem["EnemyTypes"]["Boss"]["stats"]:
            row_["footprint"] = 2
        return create_enemy("boss", col, row, enem, tm, era)

    def test_click_near_the_far_corner_of_the_block_now_hits(self):
        tm, scene, occ = build_board(["b" * 20] * 20)
        boss = self._footprint_2_boss(tm)
        priest = spawn_storm_priest(scene)          # tier 0 -> radius 1 tile
        scene.spawn(boss)
        scene.update(0.0)
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        cs = make_cs()

        anchor_wx, anchor_wy = boss.transform.world_pos
        center_wx, center_wy = boss.center_world
        self.assertEqual((center_wx, center_wy),
                         (anchor_wx + 0.5, anchor_wy + 0.5))

        # A click near the block's FAR corner — comfortably inside the
        # visible sprite, past the radius from the OLD (anchor) hit-test
        # point but within it from the true (centre) point.
        click_wx, click_wy = anchor_wx + 1.2, anchor_wy + 1.2
        radius_px = LS["radius"][0] * cs.geometry.tile_w / 2 * cs.camera.zoom
        sx, sy = cs.world_to_screen(click_wx, click_wy)

        ax, ay = cs.world_to_screen(anchor_wx, anchor_wy)
        self.assertGreater((ax - sx) ** 2 + (ay - sy) ** 2, radius_px ** 2,
                           "fixture is wrong: this click should be a MISS "
                           "against the raw anchor point")
        cx, cy = cs.world_to_screen(center_wx, center_wy)
        self.assertLessEqual((cx - sx) ** 2 + (cy - sy) ** 2, radius_px ** 2,
                             "fixture is wrong: this click should be a HIT "
                             "against the true block centre")

        hp0 = boss.get_component(Health).hp
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, click_wx, click_wy))
        self.assertLess(boss.get_component(Health).hp, hp0)

    def test_footprint_1_enemy_is_byte_identical(self):
        """``center_world`` reduces to ``world_pos`` at footprint 1 — no
        behaviour change for every non-boss enemy type."""
        tm, scene, occ = build_board(FIELD)
        e = spawn_enemy(scene, tm, 4, 4)
        scene.update(0.0)
        self.assertEqual(e.center_world, e.transform.world_pos)

    def test_fx_marker_spawns_at_the_click_point_not_an_enemy(self):
        """Regression: the per-enemy hit-test loop must never reuse
        ``strike()``'s own ``wx``/``wy`` click-point parameter names for the
        enemy's world position — doing so once left the loop overwriting the
        click point with whichever enemy it last iterated, so the
        ``LightningFX`` marker built right after the loop (and everything a
        player visually reads as "where the bolt struck") landed on that
        enemy instead of the actual click."""
        tm, scene, occ = build_board(["b" * 20] * 20)
        boss = self._footprint_2_boss(tm)          # far from the click below
        priest = spawn_storm_priest(scene)
        scene.spawn(boss)
        scene.update(0.0)
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        cs = make_cs()

        click_wx, click_wy = 2.0, 2.0
        self.assertTrue(lt.strike(st, CORE, VFX, scene, cs, click_wx, click_wy))
        scene.update(0.0)
        fx = scene.by_tag("lightning_fx")[0]
        self.assertEqual(fx.transform.world_pos, (click_wx, click_wy))


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
        # Round 1 carries a designer-authored enemy-intro entry in the
        # fixture data (feature-enemy-intro-dialogue) — drain it exactly like
        # the host does before the round's real ENEMY phase begins.
        while st.phase == GamePhase.ENEMY_INTRO:
            session.resolve_enemy_intro()
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
        while st.phase == GamePhase.ENEMY_INTRO:
            session.resolve_enemy_intro()
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
        menu = CheatMenu(640, 360)
        menu.open()
        expected = ("add_love", "skip_round", "trigger_levelup", "inf_money",
                    "unlock_all")
        for (action, btn), want in zip(menu.buttons, expected):
            self.assertEqual(action, want)
            self.assertEqual(menu.hit(*self._center(btn.rect)), want)
        self.assertEqual(menu.hit(*self._center(menu.close_btn.rect)), "close")
        self.assertIsNone(menu.hit(0, 0))          # off-panel click swallowed

    def test_goto_round_field_digits_only_max_4_commit(self):
        menu = CheatMenu(640, 360)
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
        menu = CheatMenu(640, 360)
        menu.open()
        menu.hit(*self._center(menu.field_rect))
        self.assertIsNone(menu.handle_key("", "return"))   # empty field
        self.assertIsNone(menu.hit(*self._center(menu.go_btn.rect)))
        menu.round_text = "0"                              # n < 1
        self.assertIsNone(menu._commit())

    def test_reopen_resets_the_round_field(self):
        # Review finding: open() must clear the input state every time
        # (prototype clears _buf/_active on open).
        menu = CheatMenu(640, 360)
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
        menu = CheatMenu(640, 360)
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


# ---------------------------------------------------------------------------
# BossUpgradeTimelinePLAN BU-3 3.3 — #7 `stormpriest_slow` through the SEAM
# ---------------------------------------------------------------------------
#: Hand-pinned (BU-6): the magnitudes a designer edits in the new editor panel
#: must never decide whether this module is green (`data/CLAUDE.md`).
SLOW_PCT, SLOW_SECONDS = 20, 2.5
BOSS_UPGRADES = {
    "BossUpgrades": {
        "Catalog": {
            "stormpriest_slow": {
                "name": "Chilling Storm", "description": "",
                "params": {"slow_pct": SLOW_PCT,
                           "duration_seconds": SLOW_SECONDS}},
        },
        "Timeline": {"milestones": [
            {"slots": ["stormpriest_slow", None, None],
             "retaliation_bonus_love": 30},
        ] * 4},
    }
}


class TestStormpriestSlow(unittest.TestCase):
    """`game/core` imports NOTHING from `game/enemies`, so the applier arrives
    through `lightning.set_slow_hook` — the `components.set_damage_hook`
    precedent. Unset by default, installed once by the HOST at boot; with no
    hook installed the strike is as inert as an unpicked upgrade."""

    def setUp(self):
        self.addCleanup(lt.set_slow_hook, None)

    def _board(self, picks=0):
        tm, scene, occ = build_board(FIELD)
        priest = spawn_storm_priest(scene)
        enemy = spawn_enemy(scene, tm, 1, 1)
        scene.update(0.0)
        st = RunState.from_balance(CORE, BUILD)
        lt.unlock_from_placement(st, priest)
        if picks:
            st.boss_upgrade_stacks["stormpriest_slow"] = picks
        return tm, scene, st, enemy

    def _strike_at(self, st, scene, enemy, balance):
        wx, wy = enemy.transform.world_pos
        return lt.strike(st, CORE, VFX, scene, make_cs(), wx, wy,
                         boss_upgrades_balance=balance)

    def test_no_hook_installed_is_a_silent_no_op(self):
        _tm, scene, st, enemy = self._board(picks=1)
        self.assertTrue(self._strike_at(st, scene, enemy, BOSS_UPGRADES))
        self.assertEqual(buff_total(enemy, "move_speed"), 0.0)

    def test_no_balance_threaded_leaves_the_strike_byte_identical(self):
        calls = []
        lt.set_slow_hook(lambda *a: calls.append(a))
        _tm, scene, st, enemy = self._board(picks=1)
        self.assertTrue(self._strike_at(st, scene, enemy, None))
        self.assertEqual(calls, [])

    def test_an_unpicked_upgrade_slows_nothing(self):
        lt.set_slow_hook(apply_slow)
        _tm, scene, st, enemy = self._board(picks=0)
        self.assertTrue(self._strike_at(st, scene, enemy, BOSS_UPGRADES))
        self.assertEqual(buff_total(enemy, "move_speed"), 0.0)

    def test_a_damaged_enemy_is_slowed_by_the_authored_fraction(self):
        lt.set_slow_hook(apply_slow)
        _tm, scene, st, enemy = self._board(picks=1)
        self.assertTrue(self._strike_at(st, scene, enemy, BOSS_UPGRADES))
        self.assertAlmostEqual(buff_total(enemy, "move_speed"),
                               -SLOW_PCT / 100)

    def test_repeat_picks_deepen_the_slow(self):
        lt.set_slow_hook(apply_slow)
        _tm, scene, st, enemy = self._board(picks=2)
        self._strike_at(st, scene, enemy, BOSS_UPGRADES)
        self.assertAlmostEqual(buff_total(enemy, "move_speed"),
                               -2 * SLOW_PCT / 100)

    def test_several_casters_in_one_click_read_as_ONE_slow(self):
        """`STORMPRIEST_SLOW_SOURCE` is a module constant — one BuffState
        source key for the whole upgrade, never one per firing acolyte."""
        lt.set_slow_hook(apply_slow)
        tm, scene, st, enemy = self._board(picks=1)
        spawn_storm_priest(scene, col=2)
        spawn_storm_priest(scene, col=3)
        scene.update(0.0)
        self._strike_at(st, scene, enemy, BOSS_UPGRADES)
        self.assertAlmostEqual(buff_total(enemy, "move_speed"),
                               -SLOW_PCT / 100)

    def test_an_enemy_outside_the_blast_is_untouched(self):
        lt.set_slow_hook(apply_slow)
        tm, scene, st, enemy = self._board(picks=1)
        far = spawn_enemy(scene, tm, 5, 5)
        scene.update(0.0)
        self._strike_at(st, scene, enemy, BOSS_UPGRADES)
        self.assertLess(buff_total(enemy, "move_speed"), 0)
        self.assertEqual(buff_total(far, "move_speed"), 0.0)


if __name__ == "__main__":
    unittest.main()
