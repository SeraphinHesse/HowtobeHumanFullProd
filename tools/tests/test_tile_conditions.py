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
from game.buildings import (
    BaseBuilding, PlacementError, attach_base, place_building,
)
from game.buildings.components import RoundStats
from game.buildings.coverage import (
    defence_covered_tiles, wire_defence_coverage,
)
from game.core.balance import load_balance
from game.core.phases import GamePhase
from game.enemies import Enemy
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


def synth(rows, base=(0, 0), rng=None, tile_conditions=None):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[],
        tile_conditions=tile_conditions)
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
                    if t.state == TileState.COMBAT]
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


class TestSpawnTilesAreConditionFreeUntilTheyConvert(unittest.TestCase):
    """A spawn tile is a staging area, not a gameplay tile: it carries NO
    condition at map construction and decides one only when it converts to
    COMBAT. That covers `s -> c` and `f -> s -> c` alike, since both go
    through the one `set_tile_state` seam."""

    #: pocket, combat, a painted spawn band, background behind it
    ROWS = ["bbcccc" + "s" * 6 + "f" * 8] * 12

    def _map(self, seed=13, **kw):
        return synth(self.ROWS, rng=random.Random(seed), **kw)

    def test_the_init_roll_skips_the_spawn_band(self):
        tm = self._map()
        band = [t for t in tm.all_tiles() if t.state == TileState.SPAWNING]
        self.assertGreater(len(band), 50)
        for t in band:
            self.assertEqual(t.condition, TileCondition.GRASS,
                             (t.col, t.row))
            self.assertFalse(t.condition_rolled, (t.col, t.row))

    def test_converting_to_combat_rolls_the_condition(self):
        tm = self._map()
        band = [t for t in tm.all_tiles() if t.state == TileState.SPAWNING]
        for t in band:
            tm.set_tile_state(t, TileState.COMBAT)
        for t in band:
            self.assertTrue(t.condition_rolled, (t.col, t.row))
        # a whole band's worth of draws cannot plausibly all come up grass
        self.assertGreater(
            len({t.condition for t in band}), 1,
            "the deferred roll produced a single condition for the band")

    def test_a_background_tile_rolls_on_the_f_to_s_to_c_route(self):
        """The bug this replaces: a tile that entered play late used to stay
        GRASS forever, because the init roll skipped it and never returned."""
        tm = self._map()
        tile = tm.get(15, 5)
        self.assertEqual(tile.state, TileState.BACKGROUND)
        tm.set_tile_state(tile, TileState.SPAWNING)
        self.assertEqual(tile.condition, TileCondition.GRASS)
        self.assertFalse(tile.condition_rolled)
        tm.set_tile_state(tile, TileState.COMBAT)
        self.assertTrue(tile.condition_rolled)

    def test_the_roll_fires_once_and_survives_later_transitions(self):
        tm = self._map()
        tile = tm.get(6, 0)                       # spawn band
        tm.set_tile_state(tile, TileState.COMBAT)
        rolled = tile.condition
        for state in (TileState.BUILDABLE, TileState.BUILT,
                      TileState.COMBAT):
            tm.set_tile_state(tile, state)
            self.assertEqual(tile.condition, rolled, state)

    def test_a_painted_spawn_tile_keeps_its_mark_through_the_conversion(self):
        """A designer's mark still wins everywhere: it applies to the spawn
        band immediately AND is never overwritten by the deferred roll."""
        tm = self._map(tile_conditions={(6, 0): "pond", (7, 0): "mountain"})
        for (col, row), cond in (((6, 0), TileCondition.POND),
                                 ((7, 0), TileCondition.MOUNTAIN)):
            tile = tm.get(col, row)
            self.assertEqual(tile.state, TileState.SPAWNING)
            self.assertEqual(tile.condition, cond)      # visible immediately
            tm.set_tile_state(tile, TileState.COMBAT)
            self.assertEqual(tile.condition, cond)      # never re-rolled

    def test_no_rng_defers_nothing(self):
        """`rng=None` is the all-GRASS headless-fixture mode for the deferred
        roll exactly as it is for the init roll."""
        tm = synth(self.ROWS)
        tile = tm.get(6, 0)
        tm.set_tile_state(tile, TileState.COMBAT)
        self.assertEqual(tile.condition, TileCondition.GRASS)
        self.assertFalse(tile.condition_rolled)

    def test_the_conversion_roll_is_seed_deterministic(self):
        def band_conditions(seed):
            tm = self._map(seed=seed)
            band = [t for t in tm.all_tiles()
                    if t.state == TileState.SPAWNING]
            for t in band:
                tm.set_tile_state(t, TileState.COMBAT)
            return [t.condition for t in band]

        self.assertEqual(band_conditions(3), band_conditions(3))
        self.assertNotEqual(band_conditions(3), band_conditions(4))


class TestPaintedConditions(unittest.TestCase):
    """The map doc's `tile_conditions` marks: applied unconditionally (even at
    rng=None), locking their cell out of the roll and overriding EVERY
    eligibility rule the roll applies (background, starting pocket, base)."""

    ROWS = TestConditionRoll.ROWS
    PAINT = {(5, 5): "pond",        # eligible combat tile
             (0, 0): "mountain",    # the base, inside the starting pocket
             (3, 39): "forest"}     # a BACKGROUND tile

    def test_paint_wins_everywhere_and_locks_the_cell(self):
        tm = synth(self.ROWS, rng=random.Random(42), tile_conditions=self.PAINT)
        self.assertEqual(tm.get(5, 5).condition, TileCondition.POND)
        self.assertEqual(tm.get(0, 0).condition, TileCondition.MOUNTAIN)
        self.assertEqual(tm.get(3, 39).condition, TileCondition.FOREST)
        # ... while unpainted eligible tiles still roll.
        rolled = [t.condition for t in tm.all_tiles()
                  if t.state == TileState.COMBAT and (t.col, t.row) != (5, 5)]
        self.assertTrue(any(c != TileCondition.GRASS for c in rolled))

    def test_paint_applies_without_an_rng(self):
        tm = synth(self.ROWS, tile_conditions=self.PAINT)   # rng=None
        self.assertEqual(tm.get(5, 5).condition, TileCondition.POND)
        self.assertEqual(tm.get(0, 0).condition, TileCondition.MOUNTAIN)
        self.assertEqual(tm.get(3, 39).condition, TileCondition.FOREST)
        painted = set(self.PAINT)
        self.assertTrue(all(t.condition == TileCondition.GRASS
                            for t in tm.all_tiles()
                            if (t.col, t.row) not in painted))


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
# 3b. Tile Condition Rework: a pond blocks building placement outright
# ---------------------------------------------------------------------------
class TestPondBlocksPlacement(unittest.TestCase):
    def test_pond_condition_rejects_placement_even_on_a_buildable_tile(self):
        tm = synth(["bbbbb"])
        tile = tm.get(2, 0)
        tile.condition = TileCondition.POND
        with self.assertRaises(PlacementError):
            place_building(tm, tile, "defence", LOVE, BUILD, Scene(),
                           TileOccupancy())
        self.assertIsNone(tile.occupant)

    def test_a_non_pond_buildable_tile_still_places(self):
        tm = synth(["bbbbb"])
        tile = tm.get(2, 0)
        tile.condition = TileCondition.MOUNTAIN
        b, _ = place_building(tm, tile, "defence", LOVE, BUILD, Scene(),
                              TileOccupancy())
        self.assertIsNotNone(b)
        self.assertIs(tile.occupant, b)


# ---------------------------------------------------------------------------
# 4. Defence stat modifiers (snapshot at placement; prototype order)
# ---------------------------------------------------------------------------
class TestDefenceModifiers(unittest.TestCase):
    T0 = BUILD["DefenceBuildings"]["BasicDefence"]["tiers"][0]

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

    def test_forest_is_now_neutral_for_defence(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence", TileCondition.FOREST)
        self.assertEqual(b.damage(), self.T0["base_dmg"])
        self.assertAlmostEqual(b.attack_speed(), self.T0["attack_speed"])

    def test_grass_is_neutral(self):
        b = place(synth(["bbbbb"]), 2, 0, "defence")
        self.assertEqual(b.damage(), self.T0["base_dmg"])
        self.assertAlmostEqual(b.attack_speed(), self.T0["attack_speed"])
        self.assertEqual(b.effective_range_tiles(), b.range_tiles())

    def test_aoe_leaf_takes_the_mountain_range_bonus(self):
        a0 = BUILD["DefenceBuildings"]["AOEDefence"]["tiers"][0]
        b = place(synth(["bbbbb"]), 2, 0, "aoe_defence",
                  TileCondition.MOUNTAIN)
        self.assertEqual(b.range_tiles(), a0["range_tiles"])
        self.assertEqual(b.effective_range_tiles(),
                         a0["range_tiles"] + MODS["Mountain"]["def_range_bonus"])
        # PROTOTYPE INCONSISTENCY kept for parity: the mortar TARGETS with its
        # RAW range (aoe_defence_building.py:308) — the mountain bonus only
        # ever shows in its panel row; the sensor mirrors the targeting value.
        self.assertEqual(b.targeting_range_tiles(), a0["range_tiles"])
        self.assertEqual(b.get_component(RangeSensor).range_tiles,
                         a0["range_tiles"])

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

    def test_musician_mountain_is_now_neutral(self):
        b = place(synth(["bbbbb"]), 2, 0, "economic", TileCondition.MOUNTAIN)
        self.assertEqual(b.yield_amount(), self.Y0)

    def test_musician_forest_bonus(self):
        b = place(synth(["bbbbb"]), 2, 0, "economic", TileCondition.FOREST)
        bonus = MODS["Forest"]["eco_yield_bonus"]
        self.assertEqual(b.yield_amount(), int(self.Y0 * (1.0 + bonus)))

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
    """Tile Condition Rework: Forest/Mountain no longer carry enemy-facing
    modifiers (each condition keeps exactly one player-facing headline
    effect). Pond never carried them either — this class pins that
    neutrality across the board. The generic enemy_dmg_bonus/
    enemy_speed_penalty plumbing in game/enemies/components.py is left in
    place, unused by any condition today, available again if a future
    condition wants it."""

    @staticmethod
    def _walk_until(scene, mv, index, limit=400, dt=0.05):
        for _ in range(limit):
            if mv.index >= index:
                scene.update(dt)    # one more tick: PathAgent sees the index
                return True
            scene.update(dt)
        return False

    def test_mountain_no_longer_slows_enemies(self):
        tm = synth(["bbccs"])
        tm.get(4, 0).condition = TileCondition.FOREST   # spawn tile: ignored
        tm.get(3, 0).condition = TileCondition.MOUNTAIN
        scene = Scene()
        e = Enemy(4, 0, ENEM, tm)
        base_speed = e.get_component(Movement).speed
        scene.spawn(e)
        scene.update(0.0)          # flush spawn queue -> on_spawn -> path
        mv = e.get_component(Movement)
        # arrive at (3,0): waypoints[1] -> index 2
        self.assertTrue(self._walk_until(scene, mv, 2))
        pa = e.get_component(PathAgent)
        self.assertEqual(pa._current_condition, TileCondition.MOUNTAIN)
        self.assertAlmostEqual(mv.speed, base_speed)

    def test_pond_applies_neither_modifier(self):
        tm = synth(["bbccs"])
        e = Enemy(4, 0, ENEM, tm)
        pa = e.get_component(PathAgent)
        ec = e.get_component(EnemyCombat)
        pa._current_condition = TileCondition.POND
        self.assertAlmostEqual(pa._condition_speed(), pa._real_speed)
        self.assertEqual(ec._effective_dmg(pa), ec.dmg)


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
# 7b. buildings-overwrite-tileweights: a building's death must bump the
#     shared flow field, or a stale field serves a pre-death route/cost.
# ---------------------------------------------------------------------------
class TestBuildingOverwriteFlowFieldInvalidation(unittest.TestCase):
    def test_building_death_bumps_path_version(self):
        tm = synth(["bbbbb"])
        place(tm, 2, 0, "defence", TileCondition.MOUNTAIN)
        find_path(tm, 4, 0)   # pre-query refresh populates _overwrite_prev
        v0 = tm._path_version
        tm.get(2, 0).occupant.get_component(Health).damage(10 ** 6)
        find_path(tm, 4, 0)   # must detect the flag-set change and bump
        self.assertGreater(tm._path_version, v0)


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
