"""Phase 9C: 2×2 chunk unlock + spawn-zone recede (game/map/tile_map.py).

Ports and pins the prototype's src/map/tile_map.py:298-438 on the shipped
starter map (data/maps/first_light.json, prototype-exact layout). Unlock cost =
BASE + (manhattan_section_distance − 1) * MOD (direction-agnostic, adjacent
sections cost exactly BASE) with the live map.json values; adjacency requires a
chunk COMBAT tile edge-adjacent to an unlocked tile; a successful unlock
recedes the spawn band one 2×2 section outward on BOTH axes.
"""
import copy
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from game.map import load_map_balance
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAP = FIXTURE_DATA / "maps" / "first_light.json"
MAP_SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
BALANCE = load_map_balance(FIXTURE_DATA)


def make_tilemap():
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    return TileMap(doc, BALANCE)


def states(tm, coords):
    return [tm.get(c, r).state for c, r in coords]


class TestSeeding(unittest.TestCase):
    def test_zones_seed_from_terrain_codes(self):
        tm = make_tilemap()
        self.assertEqual(tm.get(1, 1).state, TileState.BUILT)      # base
        self.assertEqual(tm.get(2, 1).state, TileState.BUILDABLE)  # 'b'
        self.assertEqual(tm.get(3, 1).state, TileState.COMBAT)     # 'c'
        self.assertEqual(tm.get(10, 1).state, TileState.SPAWNING)  # 's'
        self.assertEqual(tm.get(0, 1).state, TileState.BACKGROUND)  # 'o'
        self.assertEqual(tm.get(1, 1).content_key, "base_building")


def expected_cost(manhattan):
    """The pinned formula: BASE for adjacent sections (distance 1), +MOD per
    further step; distance term clamped ≥ 0. Derived from the LIVE balancing
    values so a tuning pass never stales these tests again."""
    u = BALANCE["TileUnlocking"]
    return (u["base_unlock_cost"]
            + max(0, manhattan - 1) * u["unlock_cost_distance_mod"])


class TestUnlockCost(unittest.TestCase):
    def test_cost_scales_with_section_distance(self):
        tm = make_tilemap()
        # section (col_sec, row_sec) with the base (1,1) as the bottom-left tile
        # of section (0,0) — col origin 1, row origin 0. Cost is keyed to the
        # section's MANHATTAN distance from (0,0).
        cases = {
            (1, 1): 0,  # section (0,0) — starts owned, clamped to BASE
            (3, 1): 1,  # section (1,0)
            (1, 3): 1,  # section (0,1)
            (3, 3): 2,  # section (1,1)
            (7, 7): 6,  # section (3,3)
        }
        for (c, r), manhattan in cases.items():
            with self.subTest(tile=(c, r)):
                self.assertEqual(tm.unlock_cost(tm.get(c, r)),
                                 expected_cost(manhattan))

    def test_cost_is_direction_agnostic_and_never_below_base(self):
        # Base mid-map: sections LEFT/ABOVE the start have negative signed
        # offsets — the cost must mirror the positive directions exactly and
        # never dip below base_unlock_cost (the original bug made it negative).
        tm = TestFind2x2WindowedMatchesFullScan._build_big(40, 40, base=(20, 20))
        base_cost = BALANCE["TileUnlocking"]["base_unlock_cost"]
        # Section origins: col 20, row 19. Mirrored section pairs around (0,0):
        mirrors = [
            ((22, 20), (18, 20)),  # sections (+1,0) vs (-1,0)
            ((20, 21), (20, 17)),  # sections (0,+1) vs (0,-1)
            ((22, 21), (18, 17)),  # sections (+1,+1) vs (-1,-1)
            ((26, 25), (14, 13)),  # sections (+3,+3) vs (-3,-3)
        ]
        for right, left in mirrors:
            with self.subTest(pair=(right, left)):
                # exact mirrors share |sc|+|sr| — equal cost both directions
                sc_r, sr_r = tm._section_index(tm.get(*right))
                sc_l, sr_l = tm._section_index(tm.get(*left))
                self.assertEqual(abs(sc_r) + abs(sr_r), abs(sc_l) + abs(sr_l))
                self.assertEqual(tm.unlock_cost(tm.get(*right)),
                                 tm.unlock_cost(tm.get(*left)))
        # section offset (-2,-2) -> manhattan 4 -> base + 3*mod
        t = tm.get(16, 15)
        self.assertEqual(tm._section_index(t), (-2, -2))
        self.assertEqual(tm.unlock_cost(t), expected_cost(4))
        # sweep: no tile anywhere costs less than base
        for tile in tm.all_tiles():
            self.assertGreaterEqual(tm.unlock_cost(tile), base_cost)


class TestStartAreaAnchoring(unittest.TestCase):
    """A placed start_area marker anchors the 2×2 section grid at its OWN min
    corner — the marker IS section (0,0) — instead of the base-derived
    fallback the other tests pin."""

    @staticmethod
    def _make(start=(12, 8), base=(1, 1)):
        tm = TestFind2x2WindowedMatchesFullScan._build_big(40, 40, base=base)
        # rebuild with the marker set (doc drives __init__ anchoring)
        doc = tm._doc
        doc.start_area = {"col": start[0], "row": start[1],
                          "slot": "start_area"}
        return TileMap(doc, BALANCE)

    def test_marker_is_section_0_0(self):
        tm = self._make()
        for c, r in ((12, 8), (13, 8), (12, 9), (13, 9)):
            self.assertEqual(tm._section_index(tm.get(c, r)), (0, 0))
        chunk = {(t.col, t.row) for t in tm.get_chunk_for_tile(tm.get(13, 9))}
        self.assertEqual(chunk, {(12, 8), (13, 8), (12, 9), (13, 9)})

    def test_adjacent_section_costs_exactly_base(self):
        tm = self._make()
        base_cost = BALANCE["TileUnlocking"]["base_unlock_cost"]
        for c, r in ((14, 8), (10, 8), (12, 6), (12, 10)):  # E/W/N/S sections
            with self.subTest(tile=(c, r)):
                self.assertEqual(tm.unlock_cost(tm.get(c, r)), base_cost)

    def test_null_marker_keeps_base_fallback(self):
        tm = TestFind2x2WindowedMatchesFullScan._build_big(40, 40, base=(1, 1))
        # legacy anchoring: col origin = base col, row origin = base row - 1
        self.assertEqual(tm._section_index(tm.get(1, 1)), (0, 0))
        self.assertEqual((tm._sec_col_origin, tm._sec_row_origin), (1, 0))


class TestAdjacency(unittest.TestCase):
    def test_adjacent_chunk_unlockable(self):
        tm = make_tilemap()
        # section (1,0) COMBAT tiles touch the buildable pocket at (2,1).
        self.assertTrue(tm.can_unlock(tm.get(3, 1)))

    def test_far_chunk_locked(self):
        tm = make_tilemap()
        # section (3,3): combat tiles surrounded by combat, no unlocked neighbour.
        self.assertFalse(tm.can_unlock(tm.get(7, 7)))

    def test_already_buildable_chunk_does_not_unlock(self):
        tm = make_tilemap()
        # The hole's section (0,0) chunk is cols[1,2]×rows[0,1] (base at its
        # bottom-left): only BUILT/BUILDABLE + background, no COMBAT to convert.
        self.assertFalse(tm.do_unlock(tm.get(2, 1)))


class TestUnlockAndRecede(unittest.TestCase):
    def test_unlock_section_1_0_and_recede_on_both_axes(self):
        tm = make_tilemap()
        ok = tm.do_unlock(tm.get(3, 1))
        self.assertTrue(ok)

        # 1. get(3,1)'s chunk is cols[3,4]×rows[0,1] (grid offset one row up so
        #    the base is a section's bottom-left tile). Row 0 is background, so
        #    only the two COMBAT tiles in the chunk become BUILDABLE.
        unlocked = [(3, 1), (4, 1)]
        self.assertTrue(
            all(s == TileState.BUILDABLE for s in states(tm, unlocked)),
            states(tm, unlocked))

        # 2. X AXIS: nearest row-aligned SPAWNING 2×2 (cols10-11, rows1-2)
        #    recedes to COMBAT.
        receded_x = [(10, 1), (11, 1), (10, 2), (11, 2)]
        self.assertTrue(
            all(s == TileState.COMBAT for s in states(tm, receded_x)),
            states(tm, receded_x))

        # 3. Y AXIS: nearest col-aligned SPAWNING 2×2 in the southern band
        #    (cols3-4, rows10-11) recedes to COMBAT too.
        receded_y = [(3, 10), (4, 10), (3, 11), (4, 11)]
        self.assertTrue(
            all(s == TileState.COMBAT for s in states(tm, receded_y)),
            states(tm, receded_y))

        # 4. EACH converted block backfills: the nearest BACKGROUND 2×2
        #    strictly BEHIND it (same rows/cols, away from the chunk) becomes
        #    SPAWNING — cols14-15/rows1-2 for the x block, cols3-4/rows14-15
        #    for the y block.
        for new_spawn in ([(14, 1), (15, 1), (14, 2), (15, 2)],
                          [(3, 14), (4, 14), (3, 15), (4, 15)]):
            self.assertTrue(
                all(s == TileState.SPAWNING for s in states(tm, new_spawn)),
                (new_spawn, states(tm, new_spawn)))

    def test_recede_conserves_nothing_outside_the_converted_blocks(self):
        # A tile far from the action is untouched by the recede.
        tm = make_tilemap()
        before = tm.get(1, 12).state  # deep spawn band, unrelated
        tm.do_unlock(tm.get(3, 1))
        self.assertEqual(tm.get(1, 12).state, before)


class TestDualAxisRecede(unittest.TestCase):
    """The dual-axis recede on synthetic grids: both axes recede when both
    have an aligned spawn band; an axis with NO aligned spawning block is
    skipped (no nearest-overall fallback)."""

    @staticmethod
    def _build(paint, start=(2, 2)):
        """40×40 all-background map, base (1,1), start_area at `start`;
        `paint` is {(anchor_c, anchor_r): TileState} of 2×2 blocks to seed."""
        tm = TestFind2x2WindowedMatchesFullScan._build_big(40, 40, base=(1, 1))
        tm._doc.start_area = {"col": start[0], "row": start[1],
                              "slot": "start_area"}
        tm = TileMap(tm._doc, BALANCE)
        for (ac, ar), state in paint.items():
            for dc in range(2):
                for dr in range(2):
                    tm.set_tile_state(tm.get(ac + dc, ar + dr), state)
        return tm

    def test_both_axes_recede_with_backfill(self):
        tm = self._build({
            (2, 2): TileState.BUILDABLE,    # the starting pocket (section 0,0)
            (4, 2): TileState.COMBAT,       # the chunk we buy (section 1,0)
            (10, 2): TileState.SPAWNING,    # east band — row-aligned
            (4, 12): TileState.SPAWNING,    # south band — col-aligned
        })
        self.assertTrue(tm.do_unlock(tm.get(4, 2)))
        for c, r in ((4, 2), (5, 2), (4, 3), (5, 3)):
            self.assertEqual(tm.get(c, r).state, TileState.BUILDABLE)
        # both bands converted...
        for ac, ar in ((10, 2), (4, 12)):
            for dc in range(2):
                for dr in range(2):
                    self.assertEqual(tm.get(ac + dc, ar + dr).state,
                                     TileState.COMBAT, (ac, ar))
        # ...and each backfilled a background block: net spawning count is
        # conserved (8 tiles before, 8 after)
        self.assertEqual(len(tm.spawning_tiles()), 8)

    def test_axis_without_aligned_band_is_skipped(self):
        tm = self._build({
            (2, 2): TileState.BUILDABLE,
            (4, 2): TileState.COMBAT,
            (10, 2): TileState.SPAWNING,   # east band only — nothing southward
        })
        self.assertTrue(tm.do_unlock(tm.get(4, 2)))
        for dc in range(2):
            for dr in range(2):
                self.assertEqual(tm.get(10 + dc, 2 + dr).state,
                                 TileState.COMBAT)
        # exactly ONE conversion + ONE backfill — the y axis did nothing
        self.assertEqual(len(tm.spawning_tiles()), 4)

    def test_backfill_lands_strictly_behind_the_band(self):
        # The backfill is the background 2×2 directly BEHIND the converted
        # block — same rows, on the far side from the bought chunk — even
        # when a background block IN FRONT of the band is closer.
        # Layout per row: bb cc ff ss c fff — the front 'f' block (cols 4-5,
        # d²=4 from the band) is closer than the behind one (cols 9-10,
        # d²=9), but only the behind one may become SPAWNING.
        rows = ["bbccffsscfff"] * 4
        doc = tilemap.TileMapDoc(
            map_id="synthfront", display_name="Synth Front", cols=12, rows=4,
            legend={}, terrain=[list(r) for r in rows],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            start_area={"col": 0, "row": 0, "slot": "start_area"})
        tm = TileMap(doc, BALANCE)
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))
        for c, r in ((6, 0), (7, 0), (6, 1), (7, 1)):    # band → COMBAT
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT)
        for c, r in ((9, 0), (10, 0), (9, 1), (10, 1)):  # behind → SPAWNING
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING)
        for c, r in ((4, 0), (5, 0), (4, 1), (5, 1)):    # front stays bg
            self.assertEqual(tm.get(c, r).state, TileState.BACKGROUND)

    def test_backfill_skips_at_map_edge_band_shrinks(self):
        # Band flush against the map edge: nothing behind qualifies, so the
        # conversion happens but NO backfill — the band shrinks by one block
        # (never a wrong-side fallback anywhere else on the map).
        rows = ["bbccss"] * 4
        doc = tilemap.TileMapDoc(
            map_id="synthedge", display_name="Synth Edge", cols=6, rows=4,
            legend={}, terrain=[list(r) for r in rows],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            start_area={"col": 0, "row": 0, "slot": "start_area"})
        tm = TileMap(doc, BALANCE)
        self.assertEqual(len(tm.spawning_tiles()), 8)
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))
        for c, r in ((4, 0), (5, 0), (4, 1), (5, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT)
        self.assertEqual(len(tm.spawning_tiles()), 4)

    def test_leftward_recede_backfills_further_left(self):
        # Band WEST of the bought chunk (start area mid-map): the backfill
        # must land further WEST — behind the band, away from the chunk.
        # (Previously impossible twice over: plain-nearest picked a wrong-side
        # block, and the quarter-plane playfield window excluded every tile
        # left/above the start marker.)
        tm = self._build({
            (20, 20): TileState.BUILDABLE,  # the starting pocket
            (18, 20): TileState.COMBAT,     # the chunk we buy — WEST of start
            (12, 20): TileState.SPAWNING,   # west band — row-aligned
        }, start=(20, 20))
        self.assertTrue(tm.do_unlock(tm.get(18, 20)))
        for c, r in ((12, 20), (13, 20), (12, 21), (13, 21)):  # band → COMBAT
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT)
        for c, r in ((10, 20), (11, 20), (10, 21), (11, 21)):  # behind (west)
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING)

    def test_diagonal_band_recedes_once_when_aligned_both_ways(self):
        # ONE spawning block aligned with BOTH the chunk's row band and its
        # col band (any such block overlaps the chunk corner): the x pass
        # converts it; the y pass must NOT double-process it (COMBAT by then)
        # — exactly one backfill.
        tm = self._build({
            (2, 2): TileState.BUILDABLE,
            (4, 2): TileState.COMBAT,      # chunk; paints (5,3) too...
            (5, 3): TileState.SPAWNING,    # ...then this block claims it back
        })
        self.assertTrue(tm.do_unlock(tm.get(4, 2)))
        # the whole spawn block is COMBAT now (incl. the shared chunk tile)
        for c, r in ((5, 3), (6, 3), (5, 4), (6, 4)):
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT, (c, r))
        # one conversion → one backfill
        self.assertEqual(len(tm.spawning_tiles()), 4)


class TestSpawnableBackgroundReserve(unittest.TestCase):
    """The designer-painted spawn reserve: mark batch `n` flips BACKGROUND →
    SPAWNING on the nth successful purchase, and the implicit recede is
    suppressed until the reserve is exhausted.

    Pinned synthetic 8×4 map (never live `data/`): per row
    ``bb cc ss oo`` — buildable pocket, the chunks we buy, the spawn band,
    then background for the marks/backfill. Section grid anchored at (0, 0),
    so the two purchasable chunks are cols2-3 × rows0-1 and cols2-3 × rows2-3.
    """

    ROWS = ["bbccssoo"] * 4

    @staticmethod
    def _make(marks, balance=BALANCE):
        doc = tilemap.TileMapDoc(
            map_id="synthreserve", display_name="Synth Reserve",
            cols=8, rows=4, legend={},
            terrain=[list(r) for r in TestSpawnableBackgroundReserve.ROWS],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            spawnable_background=dict(marks),
            start_area={"col": 0, "row": 0, "slot": "start_area"})
        return TileMap(doc, balance)

    def test_batch_one_releases_on_the_first_purchase_and_not_before(self):
        tm = self._make({(6, 0): 1, (7, 0): 1, (6, 2): 2})
        for c, r in ((6, 0), (7, 0), (6, 2)):
            self.assertEqual(tm.get(c, r).state, TileState.BACKGROUND)
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))
        for c, r in ((6, 0), (7, 0)):
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING, (c, r))
        # batch 2 waits for the second purchase
        self.assertEqual(tm.get(6, 2).state, TileState.BACKGROUND)

    def test_retire_stage_outranks_the_implicit_recede(self):
        tm = self._make({(6, 0): 1})
        # purchase 1 releases the LAST batch -> nothing implicit runs: the
        # painted band (cols4-5 rows0-1) is untouched.
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))
        self.assertEqual(tm.get(6, 0).state, TileState.SPAWNING)
        for c, r in ((4, 0), (5, 0), (4, 1), (5, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING, (c, r))
        # purchase 2 is past the marks -> the RETIRE stage (despawnable-spawn's
        # third stage) claims it, not the implicit recede: the released cell
        # dies and the painted band is still exactly where the designer left it.
        self.assertTrue(tm.do_unlock(tm.get(2, 2)))
        self.assertEqual(tm.get(6, 0).state, TileState.COMBAT)
        self.assertEqual(
            {(t.col, t.row) for t in tm.spawning_tiles()},
            {(c, r) for c in (4, 5) for r in range(4)})

    def test_spawn_recede_enabled_false_suppresses_the_old_system(self):
        balance = copy.deepcopy(BALANCE)
        balance["TileUnlocking"]["spawn_recede_enabled"] = False
        tm = self._make({}, balance=balance)   # no marks at all
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))
        self.assertTrue(tm.do_unlock(tm.get(2, 2)))
        # every painted spawn tile is exactly where the designer left it
        self.assertEqual(
            {(t.col, t.row) for t in tm.spawning_tiles()},
            {(c, r) for c in (4, 5) for r in range(4)})


class TestDespawnableSpawn(unittest.TestCase):
    """The designer-painted despawn schedule and the retire stage behind it.

    Pinned synthetic 10×4 map (never live `data/`): per row
    ``bb cccc ss oo`` — buildable pocket, the four chunks we buy, the painted
    spawn band, then background for the reserve marks. Section grid anchored at
    (0, 0), so the purchasable chunks are cols2-3/cols4-5 × rows0-1/rows2-3.

    The signed-off timeline (spawn marks n=1,2 + despawn marks n=1,2):
    purchase 1 releases spawn-bg 1 then despawns 1; purchase 2 the same for 2;
    purchase 3 retires spawn-bg batch 1; purchase 4 retires batch 2; only after
    that does the old implicit recede resume.
    """

    ROWS = ["bbccccssoo"] * 4
    #: buy order that keeps every chunk edge-adjacent to unlocked ground
    BUYS = [(2, 0), (2, 2), (4, 0), (4, 2)]

    @staticmethod
    def _make(reserve, despawn, balance=BALANCE):
        doc = tilemap.TileMapDoc(
            map_id="synthdespawn", display_name="Synth Despawn",
            cols=10, rows=4, legend={},
            terrain=[list(r) for r in TestDespawnableSpawn.ROWS],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            spawnable_background=dict(reserve),
            despawnable_spawn=dict(despawn),
            start_area={"col": 0, "row": 0, "slot": "start_area"})
        return TileMap(doc, balance)

    def _buy(self, tm, i):
        c, r = self.BUYS[i]
        self.assertTrue(tm.do_unlock(tm.get(c, r)), f"purchase {i + 1}")

    def test_despawn_batch_fires_on_its_own_purchase(self):
        tm = self._make({}, {(6, 0): 1, (7, 0): 1, (6, 2): 2})
        self._buy(tm, 0)
        for c, r in ((6, 0), (7, 0)):
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT, (c, r))
        # batch 2 waits for the second purchase
        self.assertEqual(tm.get(6, 2).state, TileState.SPAWNING)
        self._buy(tm, 1)
        self.assertEqual(tm.get(6, 2).state, TileState.COMBAT)

    def test_reserve_batches_retire_ascending_once_marks_are_exhausted(self):
        tm = self._make({(8, 0): 1, (8, 2): 2}, {(6, 0): 1, (6, 2): 2})
        self._buy(tm, 0)          # release spawn-bg 1, despawn 1
        self.assertEqual(tm.get(8, 0).state, TileState.SPAWNING)
        self.assertEqual(tm.get(6, 0).state, TileState.COMBAT)
        self._buy(tm, 1)          # release spawn-bg 2, despawn 2
        self.assertEqual(tm.get(8, 2).state, TileState.SPAWNING)
        self.assertEqual(tm.get(6, 2).state, TileState.COMBAT)
        self._buy(tm, 2)          # both mark sets spent -> retire batch 1
        self.assertEqual(tm.get(8, 0).state, TileState.COMBAT)
        self.assertEqual(tm.get(8, 2).state, TileState.SPAWNING)
        self._buy(tm, 3)          # -> retire batch 2
        self.assertEqual(tm.get(8, 2).state, TileState.COMBAT)
        # the retire stage only ever touches reserve-released cells: the
        # legend-painted band's untouched rows are exactly where they started
        for c, r in ((7, 0), (7, 2), (6, 1), (7, 1), (6, 3), (7, 3)):
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING, (c, r))

    def test_implicit_recede_resumes_once_the_retire_batches_are_spent(self):
        tm = self._make({(8, 0): 1}, {})   # one reserve batch, no despawn marks
        self._buy(tm, 0)                   # release it
        self._buy(tm, 1)                   # retire it (still no implicit move)
        self.assertEqual(tm.get(8, 0).state, TileState.COMBAT)
        for c, r in ((6, 0), (7, 0), (6, 1), (7, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING, (c, r))
        self._buy(tm, 2)                   # everything spent -> old rule back
        for c, r in ((6, 0), (7, 0), (6, 1), (7, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT, (c, r))

    def test_no_marks_of_either_kind_recedes_on_the_first_purchase(self):
        tm = self._make({}, {})
        self._buy(tm, 0)
        # row-aligned band recedes to COMBAT and backfills strictly behind it
        for c, r in ((6, 0), (7, 0), (6, 1), (7, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.COMBAT, (c, r))
        for c, r in ((8, 0), (9, 0), (8, 1), (9, 1)):
            self.assertEqual(tm.get(c, r).state, TileState.SPAWNING, (c, r))


class TestZoneVisualOverrides(unittest.TestCase):
    """Runtime zone changes must show on the ground: `set_tile_state` records
    the tile's new zone code in `terrain_overrides` (consumed by the host's
    `band_render_items(code_overrides=…)`) and fires `on_zone_change` — while
    the shared map doc stays pristine for the next fresh game."""

    def test_fresh_map_has_no_overrides(self):
        tm = make_tilemap()
        self.assertEqual(tm.terrain_overrides, {})

    def test_unlock_and_recede_record_all_zone_codes(self):
        tm = make_tilemap()
        fired = []
        tm.on_zone_change = lambda: fired.append(True)
        doc_terrain_before = ["".join(r) for r in tm._doc.terrain]
        tm.do_unlock(tm.get(3, 1))
        expected = {}
        for pos in ((3, 1), (4, 1)):                              # unlocked
            expected[pos] = "b"
        for pos in ((10, 1), (11, 1), (10, 2), (11, 2),           # x recede
                    (3, 10), (4, 10), (3, 11), (4, 11)):          # y recede
            expected[pos] = "c"
        for pos in ((14, 1), (15, 1), (14, 2), (15, 2),           # x backfill
                    (3, 14), (4, 14), (3, 15), (4, 15)):          # y backfill
            expected[pos] = "s"
        self.assertEqual(tm.terrain_overrides, expected)
        self.assertEqual(len(fired), len(expected))   # one ping per write
        # the doc itself is untouched — a fresh TileMap starts pristine
        self.assertEqual(["".join(r) for r in tm._doc.terrain],
                         doc_terrain_before)

    def test_built_state_never_writes_an_override(self):
        tm = make_tilemap()
        tm.set_tile_state(tm.get(2, 1), TileState.BUILT)  # place on buildable
        self.assertEqual(tm.terrain_overrides, {})

    def test_revert_to_painted_code_drops_the_override(self):
        tm = make_tilemap()
        t = tm.get(3, 1)   # painted 'c'
        tm.set_tile_state(t, TileState.BUILDABLE)
        self.assertEqual(tm.terrain_overrides[(3, 1)], "b")
        tm.set_tile_state(t, TileState.COMBAT)
        self.assertNotIn((3, 1), tm.terrain_overrides)


class TestStateIndexConsistency(unittest.TestCase):
    """The `_by_state` index (perf: O(result) state queries — it removed the
    per-frame full-map HUD scans that dropped large maps to ~2 fps) must always
    agree with a brute-force scan of `all_tiles()`, through every state change."""

    def _assert_consistent(self, tm):
        for state in TileState:
            indexed = {(t.col, t.row) for t in tm._by_state[state]}
            scanned = {(t.col, t.row) for t in tm.all_tiles()
                       if t.state == state}
            self.assertEqual(indexed, scanned, f"index desync for {state.name}")

    def test_query_methods_match_scan_at_seed(self):
        tm = make_tilemap()
        self._assert_consistent(tm)
        # the three queries return exactly the indexed sets
        self.assertEqual({(t.col, t.row) for t in tm.built_tiles()},
                         {(t.col, t.row) for t in tm.all_tiles()
                          if t.state == TileState.BUILT})
        self.assertEqual({(t.col, t.row) for t in tm.spawning_tiles()},
                         {(t.col, t.row) for t in tm.all_tiles()
                          if t.state == TileState.SPAWNING})

    def test_index_survives_unlock_and_recede(self):
        tm = make_tilemap()
        tm.do_unlock(tm.get(3, 1))  # converts + recedes across all three states
        self._assert_consistent(tm)

    def test_set_tile_state_moves_between_buckets(self):
        tm = make_tilemap()
        t = tm.get(2, 1)  # BUILDABLE at seed
        self.assertIn(t, tm._by_state[TileState.BUILDABLE])
        tm.set_tile_state(t, TileState.BUILT)
        self.assertIn(t, tm._by_state[TileState.BUILT])
        self.assertNotIn(t, tm._by_state[TileState.BUILDABLE])
        self.assertEqual(t.state, TileState.BUILT)
        # a no-op state write leaves the index untouched
        tm.set_tile_state(t, TileState.BUILT)
        self._assert_consistent(tm)


class TestFind2x2WindowedMatchesFullScan(unittest.TestCase):
    """`_find_2x2` uses an expanding-window search (perf: O(local), not a full
    ~1M-anchor scan per unlock on a large map). It must return the SAME block a
    brute-force whole-map scan would — same nearest-by-squared-distance pick,
    same first-row-major tie-break, same `min_ring` handling."""

    @staticmethod
    def _build_big(cols, rows, base=(1, 1)):
        # A large synth map (mostly background 'o' so predicates find sparse
        # matches far from the reference — the case the window must expand for),
        # exercised without any real art (TileMap reads dims/base/terrain only).
        terrain = [["o"] * cols for _ in range(rows)]
        doc = tilemap.TileMapDoc(
            map_id="synth", display_name="Synth", cols=cols, rows=rows,
            legend={}, terrain=terrain,
            base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
        return TileMap(doc, BALANCE)

    @staticmethod
    def _full_scan(tm, predicate, ref_col, ref_row,
                   c_bounds=None, r_bounds=None):
        """The pre-optimisation whole-map scan, inlined here as the oracle."""
        best, best_d = None, float("inf")
        for r in range(tm.rows - 1):
            for c in range(tm.cols - 1):
                if c_bounds is not None and not c_bounds[0] <= c <= c_bounds[1]:
                    continue
                if r_bounds is not None and not r_bounds[0] <= r <= r_bounds[1]:
                    continue
                block = [tm.get(c, r), tm.get(c + 1, r),
                         tm.get(c, r + 1), tm.get(c + 1, r + 1)]
                if any(t is None or not predicate(t) for t in block):
                    continue
                cc, rr = c + 0.5, r + 0.5
                d = (cc - ref_col) ** 2 + (rr - ref_row) ** 2
                if d < best_d:
                    best_d, best = d, block
        return best

    @staticmethod
    def _coords(block):
        return None if block is None else [(t.col, t.row) for t in block]

    def _paint_block(self, tm, anchor_c, anchor_r, state):
        for dc in range(2):
            for dr in range(2):
                tm.set_tile_state(tm.get(anchor_c + dc, anchor_r + dr), state)

    def test_matches_full_scan_across_refs(self):
        tm = self._build_big(40, 40)
        # A few sparse SPAWNING 2×2 blocks scattered across the map, including
        # near-far and equal-distance candidates around a couple of references.
        for ac, ar in [(4, 4), (30, 6), (6, 30), (34, 34), (18, 18), (20, 18)]:
            self._paint_block(tm, ac, ar, TileState.SPAWNING)
        pred = lambda t: t.state == TileState.SPAWNING
        cases = [(5, 5), (19, 18), (33, 33), (19, 5), (2, 2), (18, 19)]
        for ref_c, ref_r in cases:
            with self.subTest(ref=(ref_c, ref_r)):
                got = tm._find_2x2(pred, ref_c, ref_r)
                want = self._full_scan(tm, pred, ref_c, ref_r)
                self.assertEqual(self._coords(got), self._coords(want))

    def test_matches_full_scan_when_no_block_qualifies(self):
        tm = self._build_big(40, 40)  # no SPAWNING blocks painted
        pred = lambda t: t.state == TileState.SPAWNING
        self.assertIsNone(tm._find_2x2(pred, 20, 20))

    def test_matches_full_scan_with_anchor_clamp_bounds(self):
        # the dual-axis recede's axis strips: anchor col/row clamped to an
        # inclusive range must give the oracle's answer, including when the
        # clamp excludes every block (None, without scanning the whole map)
        tm = self._build_big(40, 40)
        for ac, ar in [(4, 4), (30, 6), (6, 30), (34, 34), (18, 18), (20, 18)]:
            self._paint_block(tm, ac, ar, TileState.SPAWNING)
        pred = lambda t: t.state == TileState.SPAWNING
        cases = [
            {"r_bounds": (3, 6)},          # x-axis strip holding two blocks
            {"c_bounds": (17, 21)},        # y-axis strip holding two blocks
            {"r_bounds": (10, 12)},        # strip with NO qualifying block
            {"c_bounds": (0, 39)},         # clamp covering everything
            {"c_bounds": (17, 21), "r_bounds": (3, 20)},   # both axes
        ]
        for bounds in cases:
            for ref_c, ref_r in ((5, 5), (19, 18), (2, 35)):
                with self.subTest(bounds=bounds, ref=(ref_c, ref_r)):
                    got = tm._find_2x2(pred, ref_c, ref_r, **bounds)
                    want = self._full_scan(tm, pred, ref_c, ref_r, **bounds)
                    self.assertEqual(self._coords(got), self._coords(want))

    def test_equal_distance_picks_row_major_first(self):
        # Two qualifying blocks equidistant from the reference: the full scan
        # (and so the window search) must pick the row-major-earlier one.
        tm = self._build_big(40, 40)
        # Anchors 8 and 23 on row 20 have centres 8.5 / 23.5 — both exactly 7.5
        # from ref col 16 (8 + 23 = 31 = 2*16 - 1), so a true distance tie.
        self._paint_block(tm, 8, 20, TileState.SPAWNING)   # earlier in row-major
        self._paint_block(tm, 23, 20, TileState.SPAWNING)  # same row, later col
        pred = lambda t: t.state == TileState.SPAWNING
        got = tm._find_2x2(pred, 16, 20)
        want = self._full_scan(tm, pred, 16, 20)
        self.assertEqual(self._coords(got), self._coords(want))
        self.assertEqual(got[0].col, 8)  # the row-major-earlier block wins


if __name__ == "__main__":
    unittest.main()
