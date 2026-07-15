"""Phase 10I: tile conditions + weight producers + overlays (map depth).

Pure-Python, headless — mirrors the 9C/9E fixtures: a synth ``TileMapDoc`` ->
``TileMap`` (with the new injectable condition-roll ``rng``), real balancing
via ``load_balance``, and component-level stubs where a full sim is overkill.
Covers the §4 plan of ``docs/briefs/phase-10i-map-depth.md``: seeded roll,
path-weight bonuses, pond routing (expensive, NOT impassable), defence /
economy / enemy stat modifiers, the damage-based weight discount (strict
round > 10 gate), defence-range coverage (+ mortar exclusion, raw range), the
overlay toggles/heatmap tracker, and the game/ui purity of ``overlays.py``.
"""
import copy
import random
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Movement, RangeSensor, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import BoostReceiver, RoundStats
from game.buildings.coverage import (
    defence_covered_tiles, wire_defence_coverage,
)
from game.core.balance import load_balance
from game.core.phases import GamePhase
from game.enemies import Enemy, SiegeCannon
from game.enemies.components import EnemyCombat, PathAgent
from game.map.pathfinder import find_path
from game.map.tile_map import TileMap
from game.map.tiles import TileCondition, TileState
from game.ui.overlays import MapOverlays, heat_color

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")

MODS = MAPBAL["TileConditions"]["modifiers"]
PW = MAPBAL["TileConditions"]["path_weights"]
LOVE = 10 ** 9


def synth(rows, base=(0, 0), rng=None):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL, rng=rng)


def place(tm, col, row, btype, cond=None):
    """Place a building via the ONE legal seam (snapshots the condition)."""
    tile = tm.get(col, row)
    if cond is not None:
        tile.condition = cond
    b, _ = place_building(tm, tile, btype, LOVE, BUILD,
                          Scene(), TileOccupancy())
    return b


# ---------------------------------------------------------------------------
# 1. Seeded condition roll: determinism, distribution, eligibility
# ---------------------------------------------------------------------------
class TestConditionRoll(unittest.TestCase):
    ROWS = (["bb" + "c" * 38] * 2            # pocket cols 0-1, combat beyond
            + ["c" * 40] * 37
            + ["f" * 40])                    # background border row

    @staticmethod
    def _grid(tm):
        return [[tm.get(c, r).condition for c in range(tm.cols)]
                for r in range(tm.rows)]

    def test_same_seed_same_grid_different_seed_differs(self):
        a = synth(self.ROWS, rng=random.Random(42))
        b = synth(self.ROWS, rng=random.Random(42))
        c = synth(self.ROWS, rng=random.Random(7))
        self.assertEqual(self._grid(a), self._grid(b))
        self.assertNotEqual(self._grid(a), self._grid(c))

    def test_distribution_matches_spawn_chances(self):
        tm = synth(self.ROWS, rng=random.Random(42))
        eligible = [t for t in tm.all_tiles()
                    if t.state in (TileState.COMBAT, TileState.SPAWNING)]
        n = len(eligible)
        self.assertGreater(n, 1000)
        chances = MAPBAL["TileConditions"]["spawn_chances"]
        for cond, key in ((TileCondition.GRASS, "grass"),
                          (TileCondition.MOUNTAIN, "mountain"),
                          (TileCondition.POND, "pond"),
                          (TileCondition.FOREST, "forest")):
            freq = sum(1 for t in eligible if t.condition == cond) / n
            self.assertAlmostEqual(freq, chances[key], delta=0.05,
                                   msg=f"{key} frequency {freq}")

    def test_pocket_base_and_background_stay_grass(self):
        tm = synth(self.ROWS, rng=random.Random(42))
        for col, row in ((0, 0), (1, 0), (0, 1), (1, 1)):  # pocket incl. base
            self.assertEqual(tm.get(col, row).condition, TileCondition.GRASS)
        for c in range(tm.cols):                            # background row
            self.assertEqual(tm.get(c, 39).condition, TileCondition.GRASS)

    def test_no_rng_keeps_the_all_grass_fixture_mode(self):
        tm = synth(self.ROWS)   # rng=None -> the pre-10I neutral grid
        self.assertTrue(all(t.condition == TileCondition.GRASS
                            for t in tm.all_tiles()))


# ---------------------------------------------------------------------------
# 2. Condition path-weight bonuses (+2/+9/+1, gated 0 < base < 999)
# ---------------------------------------------------------------------------
class TestPathWeightBonuses(unittest.TestCase):
    def test_condition_adds_on_a_combat_tile(self):
        for cond, key in ((TileCondition.MOUNTAIN, "mountain"),
                          (TileCondition.POND, "pond"),
                          (TileCondition.FOREST, "forest")):
            with self.subTest(cond=cond):
                tm = synth(["bcsf"])
                t = tm.get(1, 0)            # combat, base weight 1
                t.condition = cond
                self.assertEqual(tm.weight(t), 1 + PW[key])

    def test_grass_adds_nothing(self):
        tm = synth(["bcsf"])
        self.assertEqual(tm.weight(tm.get(1, 0)), 1)

    def test_base_and_impassable_are_exempt(self):
        tm = synth(["bcsf"])
        base = tm.get(0, 0)                 # base_building -> weight 0
        base.condition = TileCondition.POND
        self.assertEqual(tm.weight(base), 0)
        bg = tm.get(3, 0)                   # background -> 999
        bg.condition = TileCondition.POND
        self.assertEqual(tm.weight(bg), 999)


# ---------------------------------------------------------------------------
# 3. Pond routing: expensive (+9) but NOT impassable
# ---------------------------------------------------------------------------
class TestPondRouting(unittest.TestCase):
    ROWS = ["ccccc",
            "bfffs",
            "ccccc"]

    def test_path_prefers_the_grass_lane(self):
        tm = synth(self.ROWS, base=(0, 1))
        for c in range(5):
            tm.get(c, 2).condition = TileCondition.POND   # bottom lane ponds
        path = find_path(tm, 4, 1)
        self.assertTrue(path)
        self.assertTrue(all(r != 2 for _, r in path),
                        f"path crossed the pond lane: {path}")

    def test_pond_only_route_is_still_crossed(self):
        tm = synth(self.ROWS, base=(0, 1))
        for c in range(5):
            tm.get(c, 0).condition = TileCondition.POND
            tm.get(c, 2).condition = TileCondition.POND
        path = find_path(tm, 4, 1)
        self.assertTrue(path, "pond must be expensive, NOT impassable")
        self.assertEqual(path[-1], (0, 1))


# ---------------------------------------------------------------------------
# 4. Defence stat modifiers (snapshot at placement; prototype order)
# ---------------------------------------------------------------------------
class TestDefenceModifiers(unittest.TestCase):
    T0 = BUILD["DefenceBuildings"]["BasicDefence"]["tiers"][0]

    def test_forest_cuts_damage(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence", TileCondition.FOREST)
        pen = MODS["Forest"]["def_dmg_penalty"]
        self.assertEqual(b.damage(),
                         max(1, int(self.T0["base_dmg"] * (1.0 - pen))))
        self.assertEqual(b._tile_condition, TileCondition.FOREST)

    def test_forest_cut_composes_after_the_boost_multiply(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence", TileCondition.FOREST)
        b.get_component(BoostReceiver).damage_pct = 0.5
        pen = MODS["Forest"]["def_dmg_penalty"]
        expected = int(int(self.T0["base_dmg"] * 1.5) * (1.0 - pen))
        self.assertEqual(b.damage(), max(1, expected))

    def test_pond_slows_attacks_after_the_boost_multiply(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence", TileCondition.POND)
        pen = MODS["Pond"]["def_attack_speed_penalty"]
        self.assertAlmostEqual(b.attack_speed(),
                               self.T0["attack_speed"] * (1.0 + pen))
        b.get_component(BoostReceiver).speed_pct = 0.2
        self.assertAlmostEqual(
            b.attack_speed(),
            self.T0["attack_speed"] * 0.8 * (1.0 + pen))

    def test_mountain_range_bonus_keeps_raw_range_raw(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence", TileCondition.MOUNTAIN)
        bonus = MODS["Mountain"]["def_range_bonus"]
        self.assertEqual(b.range_tiles(), self.T0["range_tiles"])   # RAW
        self.assertEqual(b.effective_range_tiles(),
                         self.T0["range_tiles"] + bonus)
        # basic defence TARGETS with the effective value; the sensor mirrors it
        self.assertEqual(b.targeting_range_tiles(),
                         self.T0["range_tiles"] + bonus)
        self.assertEqual(b.get_component(RangeSensor).range_tiles,
                         self.T0["range_tiles"] + bonus)

    def test_grass_is_neutral(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence")
        self.assertEqual(b.damage(), self.T0["base_dmg"])
        self.assertAlmostEqual(b.attack_speed(), self.T0["attack_speed"])
        self.assertEqual(b.effective_range_tiles(), b.range_tiles())

    def test_aoe_leaf_takes_pond_and_mountain(self):
        a0 = BUILD["DefenceBuildings"]["AOEDefence"]["tiers"][0]
        b = place(synth(["bbbbb"]), 2, 0, "aoe_defence", TileCondition.POND)
        self.assertAlmostEqual(
            b.attack_speed(),
            a0["attack_speed"] * (1 + MODS["Pond"]["def_attack_speed_penalty"]))
        b2 = place(synth(["bbbbb"]), 2, 0, "aoe_defence",
                   TileCondition.MOUNTAIN)
        self.assertEqual(b2.range_tiles(), a0["range_tiles"])
        self.assertEqual(b2.effective_range_tiles(),
                         a0["range_tiles"] + MODS["Mountain"]["def_range_bonus"])
        # PROTOTYPE INCONSISTENCY kept for parity: the mortar TARGETS with its
        # RAW range (aoe_defence_building.py:308) — the mountain bonus only
        # ever shows in its panel row; the sensor mirrors the targeting value.
        self.assertEqual(b2.targeting_range_tiles(), a0["range_tiles"])
        self.assertEqual(b2.get_component(RangeSensor).range_tiles,
                         a0["range_tiles"])

    def test_beam_leaf_takes_the_pond_interval(self):
        s0 = BUILD["DefenceBuildings"]["BeamDefence"]["tiers"][0]
        b = place(synth(["bbbbb"]), 2, 0, "sun_scorcher", TileCondition.POND)
        self.assertAlmostEqual(
            b.attack_speed(),
            s0["attack_speed"] * (1 + MODS["Pond"]["def_attack_speed_penalty"]))

    def test_unplaced_preview_building_is_neutral(self):
        from game.buildings.registry import create
        b = create("defence", 0, 0, BUILD)
        self.assertEqual(b.damage(), self.T0["base_dmg"])
        self.assertEqual(b.effective_range_tiles(), b.range_tiles())


# ---------------------------------------------------------------------------
# 5. Economy modifiers (Musician only; Meditator/Painter untouched)
# ---------------------------------------------------------------------------
class TestEconomyModifiers(unittest.TestCase):
    Y0 = BUILD["EconomyBuildings"]["Musicians"]["tiers"][0]["base_yield"]

    def test_musician_mountain_pond_forest(self):
        pen = MODS["Mountain"]["eco_yield_penalty"]
        b = place(synth(["bbbbb"]), 2, 0, "economic", TileCondition.MOUNTAIN)
        self.assertEqual(b.yield_amount(), max(0, int(self.Y0 * (1.0 - pen))))
        for cond, key in ((TileCondition.POND, "Pond"),
                          (TileCondition.FOREST, "Forest")):
            with self.subTest(cond=cond):
                b = place(synth(["bbbbb"]), 2, 0, "economic", cond)
                bonus = MODS[key]["eco_yield_bonus"]
                self.assertEqual(b.yield_amount(),
                                 int(self.Y0 * (1.0 + bonus)))

    def test_musician_grass_neutral(self):
        b = place(synth(["bbbbb"]), 2, 0, "economic")
        self.assertEqual(b.yield_amount(), self.Y0)

    def test_meditator_and_painter_yields_unchanged(self):
        grass = place(synth(["bbbbb"]), 2, 0, "meditator")
        forest = place(synth(["bbbbb"]), 2, 0, "meditator",
                       TileCondition.FOREST)
        mountain = place(synth(["bbbbb"]), 2, 0, "meditator",
                         TileCondition.MOUNTAIN)
        self.assertEqual(forest.yield_amount(), grass.yield_amount())
        self.assertEqual(mountain.yield_amount(), grass.yield_amount())
        painter = place(synth(["bbbbb"]), 2, 0, "painter",
                        TileCondition.FOREST)
        self.assertEqual(painter.yield_amount(), 0)


# ---------------------------------------------------------------------------
# 6. Enemy modifiers (last-ARRIVED tile; spawn tile never applies)
# ---------------------------------------------------------------------------
class TestEnemyModifiers(unittest.TestCase):
    SPEED_PEN = MODS["Mountain"]["enemy_speed_penalty"]
    DMG_BONUS = MODS["Mountain"]["enemy_dmg_bonus"]
    MIN_FRACTION = MAPBAL["TileConditions"]["min_speed_fraction"]

    @staticmethod
    def _walk_until(scene, mv, index, limit=400, dt=0.05):
        for _ in range(limit):
            if mv.index >= index:
                scene.update(dt)    # one more tick: PathAgent sees the index
                return True
            scene.update(dt)
        return False

    def test_mountain_slows_after_arrival_not_at_spawn(self):
        tm = synth(["bbccs"])
        tm.get(4, 0).condition = TileCondition.FOREST   # spawn tile: ignored
        tm.get(3, 0).condition = TileCondition.MOUNTAIN
        scene = Scene()
        e = Enemy(4, 0, ENEM, tm)
        base_speed = e.get_component(Movement).speed
        scene.spawn(e)
        scene.update(0.0)          # flush spawn queue -> on_spawn -> path
        mv = e.get_component(Movement)
        scene.update(0.01)
        # waypoint 0 is the spawn tile itself — its condition never applies
        self.assertLessEqual(mv.index, 1)
        self.assertAlmostEqual(mv.speed, base_speed)
        # arrive at (3,0): waypoints[1] -> index 2 -> mountain slow
        self.assertTrue(self._walk_until(scene, mv, 2))
        pa = e.get_component(PathAgent)
        self.assertEqual(pa._current_condition, TileCondition.MOUNTAIN)
        self.assertAlmostEqual(mv.speed,
                               max(0.0, base_speed - self.SPEED_PEN))

    def test_speed_is_floored_at_a_fraction_of_the_units_own_speed(self):
        """BP-1: the penalty subtracts, but never below
        ``move_speed × min_speed_fraction``. It used to clamp at 0 instead,
        which welded any unit slower than the flat penalty to the floor for
        good (only the boss is — see ``test_boss.TestConditionSpeedFloor``).
        Siege is the closest of the normal types to that line and still clears
        it: 1.0 − 0.4 = 0.6 beats its 0.5 floor, so its number is unmoved."""
        tm = synth(["bbccs"])
        real = ENEM["EnemyTypes"]["SiegeCannon"]["move_speed"]
        s = SiegeCannon(4, 0, ENEM, tm)
        pa = s.get_component(PathAgent)
        pa._current_condition = TileCondition.MOUNTAIN
        self.assertAlmostEqual(pa._condition_speed(), real - self.SPEED_PEN)
        self.assertGreater(pa._condition_speed(), real * self.MIN_FRACTION)

    def test_pond_applies_neither_modifier(self):
        tm = synth(["bbccs"])
        e = Enemy(4, 0, ENEM, tm)
        pa = e.get_component(PathAgent)
        ec = e.get_component(EnemyCombat)
        pa._current_condition = TileCondition.POND
        self.assertAlmostEqual(pa._condition_speed(), pa._real_speed)
        self.assertEqual(ec._effective_dmg(pa), ec.dmg)

    def test_mountain_boosts_blocking_building_damage(self):
        tm = synth(["bbccs"])
        blocker = place(tm, 1, 0, "defence")          # blocks the lane
        tm.get(2, 0).condition = TileCondition.MOUNTAIN
        scene = Scene()
        e = Enemy(4, 0, ENEM, tm)
        scene.spawn(e)
        scene.update(0.0)
        mv = e.get_component(Movement)
        pa = e.get_component(PathAgent)
        hp0 = blocker.get_component(Health).hp
        # walk to (2,0) (mountain), then block on (1,0) and land >= 1 hit
        for _ in range(600):
            scene.update(0.05)
            if blocker.get_component(Health).hp < hp0:
                break
        self.assertTrue(pa.blocked)
        self.assertEqual(pa._current_condition, TileCondition.MOUNTAIN)
        expected = max(1, int(e.dmg * (1.0 + self.DMG_BONUS)))
        dealt = hp0 - blocker.get_component(Health).hp
        self.assertEqual(dealt % expected, 0)
        self.assertGreaterEqual(dealt, expected)
        self.assertEqual(
            blocker.get_component(RoundStats).dmg_taken_this_round, dealt)

    def test_wall_attack_uses_the_effective_damage_too(self):
        tm = synth(["bbccs"])
        e = Enemy(4, 0, ENEM, tm)
        pa = e.get_component(PathAgent)
        ec = e.get_component(EnemyCombat)
        pa._current_condition = TileCondition.MOUNTAIN
        expected = max(1, int(ec.dmg * (1.0 + self.DMG_BONUS)))
        self.assertEqual(ec._effective_dmg(pa), expected)


# ---------------------------------------------------------------------------
# 7. Damage-based weight reduction (top-3, strict round > 10 gate)
# ---------------------------------------------------------------------------
class TestDamageReduction(unittest.TestCase):
    CFG = MAPBAL["Pathfinding"]["damage_reduction"]

    def _map_with_defenders(self):
        tm = synth(["bbbbb", "ccccs"])
        occupancy = TileOccupancy()
        attach_base(tm, BaseBuilding(0, 0, CORE), Scene(), occupancy)
        buildings = []
        for col, dmg in ((1, 100), (2, 50), (3, 30), (4, 10)):
            b = place(tm, col, 0, "defence")
            b.get_component(RoundStats).dmg_dealt_last_round = dmg
            buildings.append(b)
        return tm, buildings

    def _flags(self, tm):
        return {(t.col, t.row) for t in tm.built_tiles()
                if t.damage_weight_reduced}

    def test_top_three_flagged_and_discounted_at_round_11(self):
        tm, _ = self._map_with_defenders()
        tm.set_round(self.CFG["min_round"] + 1)
        find_path(tm, 4, 1)     # pre-query refresh recomputes the flags
        self.assertEqual(self._flags(tm), {(1, 0), (2, 0), (3, 0)})
        w = tm.get(1, 0).pathfinding_weight(MAPBAL)
        # defence_building base weight 2 -> max(1, int(round(2*0.5))) == 1
        self.assertEqual(w, max(1, int(round(2 * self.CFG["reduction"]))))
        self.assertEqual(tm.weight(tm.get(4, 0)), 2)   # unflagged stays 2

    def test_round_gate_is_strict(self):
        tm, _ = self._map_with_defenders()
        tm.set_round(self.CFG["min_round"])    # round 10: NOT yet
        find_path(tm, 4, 1)
        self.assertEqual(self._flags(tm), set())

    def test_dead_occupant_and_base_are_excluded(self):
        tm, buildings = self._map_with_defenders()
        base_tile = tm.get(0, 0)
        base_tile.occupant.get_component(RoundStats).dmg_dealt_last_round = 999
        buildings[0].get_component(Health).damage(10 ** 6)   # kill the top
        tm.set_round(self.CFG["min_round"] + 1)
        find_path(tm, 4, 1)
        self.assertEqual(self._flags(tm), {(2, 0), (3, 0), (4, 0)})
        self.assertEqual(tm.weight(base_tile), 0)

    def test_flags_recompute_when_stats_change(self):
        tm, buildings = self._map_with_defenders()
        tm.set_round(self.CFG["min_round"] + 1)
        find_path(tm, 4, 1)
        self.assertIn((1, 0), self._flags(tm))
        buildings[3].get_component(RoundStats).dmg_dealt_last_round = 200
        buildings[0].get_component(RoundStats).dmg_dealt_last_round = 5
        find_path(tm, 4, 1)
        self.assertEqual(self._flags(tm), {(2, 0), (3, 0), (4, 0)})


# ---------------------------------------------------------------------------
# 8. Defence-range coverage -> +1 path weight (mortar excluded, raw range)
# ---------------------------------------------------------------------------
class TestDefenceRangeCoverage(unittest.TestCase):
    ADD = BUILD["BuildingsGlobal"]["defence_range_pathfinding"][
        "path_weight_add"]

    def test_covered_tiles_gain_the_add_after_a_query(self):
        tm = synth(["bbbbbbbb", "cccccccs"])
        b = place(tm, 2, 0, "defence")
        r = int(b.range_tiles())
        wire_defence_coverage(tm, BUILD)
        find_path(tm, 7, 1)      # pre-query refresh applies the coverage
        inside = tm.get(2, 1)    # Chebyshev 1 from the defender
        self.assertEqual(tm.weight(inside), 1 + self.ADD)
        outside = tm.get(2 + r + 1, 1)   # beyond raw range
        self.assertEqual(tm.weight(outside), 1)

    def test_mountain_bonus_does_not_extend_coverage(self):
        tm = synth(["bbbbbbbb", "cccccccs"])
        b = place(tm, 2, 0, "defence", TileCondition.MOUNTAIN)
        r = int(b.range_tiles())
        self.assertEqual(b.effective_range_tiles(), r + 1)
        wire_defence_coverage(tm, BUILD)
        find_path(tm, 7, 1)
        edge = tm.get(2 + r, 1)          # raw-range edge: covered
        self.assertEqual(tm.weight(edge), 1 + self.ADD)
        beyond = tm.get(2 + r + 1, 1)    # effective-range ring: NOT covered
        self.assertEqual(tm.weight(beyond), 1)

    def test_mortar_produces_no_coverage(self):
        tm = synth(["bbbbbbbb", "cccccccs"])
        place(tm, 2, 0, "aoe_defence")
        self.assertEqual(defence_covered_tiles(tm, BUILD), set())
        wire_defence_coverage(tm, BUILD)
        find_path(tm, 7, 1)
        self.assertEqual(tm.weight(tm.get(2, 1)), 1)

    def test_disabled_toggle_yields_empty_coverage(self):
        tm = synth(["bbbbbbbb", "cccccccs"])
        place(tm, 2, 0, "defence")
        build = copy.deepcopy(BUILD)
        build["BuildingsGlobal"]["defence_range_pathfinding"]["enabled"] = \
            False
        self.assertEqual(defence_covered_tiles(tm, build), set())
        wire_defence_coverage(tm, build)
        find_path(tm, 7, 1)
        self.assertEqual(tm.weight(tm.get(2, 1)), 1)

    def test_booster_adds_a_3x3_coverage_square(self):
        # Prototype boosters carry range_tiles = 1 (boost_building.py:51) and
        # game.py:601 includes them -> every alive "boost"-tagged occupant
        # adds a full r=1 Chebyshev square (the repo booster has NO
        # range_tiles() method — the tag drives the square).
        tm = synth(["bbbbbbbb", "cccccccs"])
        place(tm, 2, 0, "boost_speed")
        expected = {(2 + dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
        self.assertEqual(defence_covered_tiles(tm, BUILD), expected)
        wire_defence_coverage(tm, BUILD)
        find_path(tm, 7, 1)
        self.assertEqual(tm.weight(tm.get(2, 1)), 1 + self.ADD)   # covered
        self.assertEqual(tm.weight(tm.get(4, 1)), 1)              # outside

    def test_base_tile_is_exempt(self):
        tm = synth(["bbbbbbbb", "cccccccs"])
        place(tm, 1, 0, "defence")       # base (0,0) is inside its square
        wire_defence_coverage(tm, BUILD)
        find_path(tm, 7, 1)
        self.assertTrue(tm.get(0, 0).defence_range_covered)
        self.assertEqual(tm.weight(tm.get(0, 0)), 0)


# ---------------------------------------------------------------------------
# 9. Overlays: toggles, heatmap tracker, RANGE coverage set, colour ramp
# ---------------------------------------------------------------------------
class _StubEnemy:
    def __init__(self, wx, wy, alive=True):
        self.alive = alive
        self.transform = types.SimpleNamespace(world_pos=(wx, wy))


class _StubScene:
    def __init__(self, enemies):
        self.enemies = enemies

    def by_tag(self, tag):
        return list(self.enemies)


class TestOverlays(unittest.TestCase):
    def _mo(self):
        return MapOverlays(800, 600)

    def test_hit_flips_and_consumes(self):
        mo = self._mo()
        rx, ry = mo.range_btn.rect[0] + 5, mo.range_btn.rect[1] + 5
        hx, hy = mo.heatmap_btn.rect[0] + 5, mo.heatmap_btn.rect[1] + 5
        self.assertTrue(mo.hit(rx, ry))
        self.assertTrue(mo.show_range)
        self.assertTrue(mo.hit(rx, ry))
        self.assertFalse(mo.show_range)
        self.assertTrue(mo.hit(hx, hy))
        self.assertTrue(mo.show_heatmap)
        self.assertFalse(mo.hit(400, 300))      # empty space: not consumed
        self.assertTrue(mo.over(rx, ry))
        self.assertFalse(mo.over(400, 300))

    def test_track_counts_distinct_enemies_and_snapshots_on_edge(self):
        mo = self._mo()
        e1, e2 = _StubEnemy(2.2, 3.4), _StubEnemy(1.9, 3.1)
        scene = _StubScene([e1, e2])
        for _ in range(3):                       # frames accumulate, not add
            mo.track(GamePhase.ENEMY, GamePhase.ENEMY, scene)
        self.assertEqual(mo.path_heatmap, {})    # nothing before the edge
        mo.track(GamePhase.ROUND_END, GamePhase.ENEMY, scene)
        self.assertEqual(mo.path_heatmap, {(2, 3): 2})
        # next round resets: one enemy only -> count 1 replaces the 2
        mo.track(GamePhase.ENEMY, GamePhase.BUILDING, _StubScene([e1]))
        mo.track(GamePhase.ROUND_END, GamePhase.ENEMY, scene)
        self.assertEqual(mo.path_heatmap, {(2, 3): 1})

    def test_dead_enemies_are_not_tracked(self):
        mo = self._mo()
        scene = _StubScene([_StubEnemy(2, 3, alive=False)])
        mo.track(GamePhase.ENEMY, GamePhase.ENEMY, scene)
        mo.track(GamePhase.ROUND_END, GamePhase.ENEMY, scene)
        self.assertEqual(mo.path_heatmap, {})

    def test_range_coverage_includes_mortar_square_and_boost_plus(self):
        tm = synth(["bbbbbb"])
        mortar = place(tm, 1, 0, "aoe_defence")
        place(tm, 4, 0, "boost_speed")
        cov = MapOverlays.range_coverage(tm)
        r = int(mortar.range_tiles())
        self.assertIn((1 + r, 0), cov)           # mortar IS in the overlay
        self.assertIn((1, r), cov)
        for pos in ((3, 0), (5, 0), (4, -1), (4, 1)):   # boost plus-shape
            self.assertIn(pos, cov)
        self.assertNotIn((4 + 2, 0 + 2), cov)    # boosts add no square

    def test_heat_ramp_endpoints(self):
        # 10J: the ramp carries the prototype's alpha (50 + 130*t) again
        self.assertEqual(heat_color(0.0), (0, 100, 200, 50))
        self.assertEqual(heat_color(0.5), (255, 255, 0, 115))
        self.assertEqual(heat_color(1.0), (255, 0, 0, 180))


# ---------------------------------------------------------------------------
# 10. Purity: overlays.py never imports pygame directly
# ---------------------------------------------------------------------------
class TestPurity(unittest.TestCase):
    def test_overlays_has_no_direct_pygame_import(self):
        src = (REPO / "game" / "ui" / "overlays.py").read_text(
            encoding="utf-8")
        for line in src.splitlines():
            s = line.strip()
            self.assertFalse(
                s.startswith(("import pygame", "from pygame")),
                f"game/ui/overlays.py imports pygame directly: {s}")


if __name__ == "__main__":
    unittest.main()
