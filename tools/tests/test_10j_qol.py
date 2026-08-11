"""Phase 10J QOL: shift multi-select batch math (unlock chunk-dedup /
construct ×count / in-tier upgrade sums), the game log, the next-tier +
next-level previews, the income-source breakdown, and the FX spawn hooks.

Headless: real TileMap/Session/BuildingUI over the shipped starter map, no
pygame window (the UI layer is pure).
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings.components import Nameplate, TierState
from game.core import Session, load_balance
from game.core import levelup as lv
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.map.tiles import TileState
from game.ui.building_ui import BuildingUI
from game.ui.effects import FloaterManager
from game.ui.game_log import GameLog, LIFETIME, MAX_MESSAGES
from game.ui.hud import income_breakdown, income_sources

MAP = FIXTURE_DATA / "maps" / "first_light.json"
MAP_SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
MAP_BAL = load_balance(FIXTURE_DATA, "map")
BUILDINGS_BAL = load_balance(FIXTURE_DATA, "buildings")
ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")  # ESV-3a: FloaterManager's 3rd arg
PROGRESSION_BAL = load_balance(FIXTURE_DATA, "progression")
VIEW_W, VIEW_H = 640, 360
# Slinger (defence tier index 1)'s Timeline placement -- the village_level a
# batch-advance test must reach for `tier_offerable` to allow it, since the
# Timeline is the SOLE source of tier eligibility (progression_balance=None
# on a bare Session, as `make_world()` builds, always reads "not offerable").
DEF_T2_LEVEL = lv.timeline_level_for("defence", 1, PROGRESSION_BAL)


def make_world():
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    tm = TileMap(doc, MAP_BAL)
    scene = Scene()
    occupancy = TileOccupancy()
    session = Session.create(Spawner(), tm, ENEMIES_BAL, CORE_BAL,
                             BUILDINGS_BAL, occupancy=occupancy)
    return tm, scene, occupancy, session


def make_panel():
    return BuildingUI(VIEW_W, VIEW_H, UI_BAL)


def click(btn):
    """Centre coordinates of a widgets.Button."""
    x, y, w, h = btn.rect
    return x + w // 2, y + h // 2


class TestGameLog(unittest.TestCase):
    def test_post_caps_and_ages_out(self):
        log = GameLog()
        for i in range(MAX_MESSAGES + 3):
            log.post(f"m{i}")
        self.assertEqual(len(log._messages), MAX_MESSAGES)
        self.assertEqual(log._messages[0][0], "m3")  # oldest dropped
        log.update(LIFETIME + 0.01)
        self.assertEqual(log._messages, [])

    def test_drain_consumes_state_ledger(self):
        log = GameLog()

        class _S:
            log_events = ["a", "b"]

        log.drain(_S)
        self.assertEqual([m[0] for m in log._messages], ["a", "b"])
        self.assertEqual(_S.log_events, [])


class TestBatchUnlock(unittest.TestCase):
    def test_chunk_dedup_and_batch_spend(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        # Two tiles in the SAME 2x2 chunk + one in another chunk -> 2 chunks.
        t_a1, t_a2 = tm.get(3, 1), tm.get(4, 1)
        t_b = tm.get(1, 3)
        self.assertEqual(
            {(t.col, t.row) for t in tm.get_chunk_for_tile(t_a1)},
            {(t.col, t.row) for t in tm.get_chunk_for_tile(t_a2)})
        expected = tm.unlock_cost(t_a1) + tm.unlock_cost(t_b)
        panel.open_for_tile(t_a1, session, BUILDINGS_BAL,
                            selected_tiles=[t_a1, t_a2, t_b])
        self.assertEqual(panel.mode, "unlock")
        self.assertEqual(panel._action_cost, expected)
        self.assertIn("UNLOCK 2 AREAS", panel.action_btn.label)
        session.state.love = expected + 5
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, 5)
        for t in (t_a1, t_a2, t_b):
            self.assertEqual(t.state, TileState.BUILDABLE)


class TestBatchConstructAndUpgrade(unittest.TestCase):
    def _open_construct(self, panel, session, tiles):
        panel.open_for_tile(tiles[0], session, BUILDINGS_BAL,
                            selected_tiles=tiles)
        self.assertEqual(panel.mode, "construct")
        btype, btn = next(
            (bt, b) for bt, b in panel.cards if bt == "defence")
        panel.handle_click(*click(btn), session, BUILDINGS_BAL, None, None)
        return btype

    def test_batch_construct_names_first_only(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        p = panel.preview
        self.assertIsNotNone(p)
        self.assertEqual(p.count, 2)
        self.assertEqual(p.total_cost, p.cost * 2)
        p.name = "Rex"
        love_before = session.state.love
        panel.handle_click(*click(p.confirm_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - p.cost * 2)
        b1, b2 = tiles[0].occupant, tiles[1].occupant
        self.assertIsNotNone(b1)
        self.assertIsNotNone(b2)
        self.assertEqual(b1.get_component(Nameplate).custom_name, "Rex")
        self.assertEqual(b2.get_component(Nameplate).custom_name, "")

    def test_batch_in_tier_upgrade_spends_sum(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        # panel reopened in upgrade mode for the batch's primary
        self.assertEqual(panel.mode, "upgrade")
        targets = panel._batch_upgrade_targets()
        self.assertEqual(len(targets), 2)
        total = sum(c for _, c in targets)
        self.assertEqual(panel._action_cost, total)
        love_before = session.state.love
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - total)
        for t in tiles:
            lvl = t.occupant.get_component(TierState).current_level_in_tier
            self.assertEqual(lvl, 2)

    def test_batch_catches_up_to_level_3_then_advances_together(self):
        """Catch-up-then-advance rework: a multi-selection where one building
        is already at tier max and another is still mid-tier does NOT
        combine catch-up + advance into one click any more. Stage A first
        levels the laggard up to level 3 (one step per click, the maxed
        building untouched); only once BOTH are at level 3 does Stage B
        (ADVANCE) appear and advance them together."""
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        b_ready, b_catchup = (t.occupant for t in tiles)
        b_ready.get_component(TierState).current_level_in_tier = 3  # tier max
        # b_catchup stays at level 1 -- needs 2 more in-tier levels first
        session.state.tiers_unlocked["defence"] = 2  # Slinger researched
        session.progression_balance = PROGRESSION_BAL  # Slinger offerable...
        session.state.village_level = DEF_T2_LEVEL     # ...at this level

        tier0 = BUILDINGS_BAL["DefenceBuildings"]["BasicDefence"]["tiers"][0]
        tier1_cost = (BUILDINGS_BAL["DefenceBuildings"]["BasicDefence"]
                      ["tiers"][1]["build_cost"])
        base, incr = tier0["upgrade_cost_base"], tier0["upgrade_cost_increment"]
        step_cost = lambda lvl: base + (lvl - 1) * incr  # noqa: E731

        panel.open_for_tile(tiles[0], session, BUILDINGS_BAL,
                            selected_tiles=tiles)
        self.assertEqual(panel.mode, "upgrade")

        # Stage A, click 1: only the laggard is in the batch (level 1 -> 2);
        # the already-maxed building is untouched.
        targets = panel._batch_upgrade_targets()
        self.assertEqual([t[0] for t in targets], [b_catchup])
        self.assertIn("UPGRADE", panel.action_btn.label)
        self.assertEqual(panel._action_cost, step_cost(1))
        love_before = session.state.love
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - step_cost(1))
        self.assertEqual(b_catchup.get_component(TierState).current_level_in_tier, 2)
        self.assertEqual(b_ready.get_component(TierState).current_level_in_tier, 3)

        # Stage A, click 2: level 2 -> 3, still just the laggard.
        self.assertIn("UPGRADE", panel.action_btn.label)
        self.assertEqual(panel._action_cost, step_cost(2))
        love_before = session.state.love
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - step_cost(2))
        self.assertEqual(b_catchup.get_component(TierState).current_level_in_tier, 3)

        # Both buildings are now at level 3 -- Stage A's sweep is empty, so
        # Stage B (ADVANCE) takes over, covering BOTH together.
        self.assertEqual(panel._batch_upgrade_targets(), [])
        targets = panel._batch_advance_targets()
        self.assertEqual({t[0] for t in targets}, {b_ready, b_catchup})
        self.assertIn("ADVANCE", panel.action_btn.label)
        expected_advance = tier1_cost * 2
        self.assertEqual(panel._action_cost, expected_advance)

        love_before = session.state.love
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - expected_advance)
        for b in (b_ready, b_catchup):
            ts = b.get_component(TierState)
            self.assertEqual(ts.current_tier, 1)
            self.assertEqual(ts.current_level_in_tier, 1)

    def test_batch_advance_excludes_buildings_that_cannot_reach_next_tier(self):
        """A building already at its FINAL tier can't advance no matter what
        -- Stage A still catches it up to level 3 like any other selected
        building (it just never gets a next tier to advance into), and
        Stage B then silently excludes it from the ADVANCE batch, leaving it
        at level 3 while the eligible building in the same selection still
        advances."""
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        b_eligible, b_stuck = (t.occupant for t in tiles)
        b_eligible.get_component(TierState).current_level_in_tier = 3
        b_stuck.get_component(TierState).current_tier = 2  # Pistoleer (final tier)
        # b_stuck stays at level 1 of its final tier -- still needs catch-up
        session.state.tiers_unlocked["defence"] = 2
        session.progression_balance = PROGRESSION_BAL
        session.state.village_level = DEF_T2_LEVEL

        panel.open_for_tile(tiles[0], session, BUILDINGS_BAL,
                            selected_tiles=tiles)
        # Stage A: b_stuck still needs catching up within its own (final)
        # tier, even though it can never advance beyond it.
        targets = panel._batch_upgrade_targets()
        self.assertEqual([t[0] for t in targets], [b_stuck])
        for _ in range(2):  # level 1 -> 2 -> 3
            panel.handle_click(*click(panel.action_btn), session,
                               BUILDINGS_BAL, scene, occupancy)
        self.assertEqual(b_stuck.get_component(TierState).current_level_in_tier, 3)

        # Stage B: only b_eligible is advance-eligible now; b_stuck is
        # excluded (no next tier exists) and left untouched.
        targets = panel._batch_advance_targets()
        self.assertEqual([t[0] for t in targets], [b_eligible])

        tier1_cost = (BUILDINGS_BAL["DefenceBuildings"]["BasicDefence"]
                      ["tiers"][1]["build_cost"])
        love_before = session.state.love
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, love_before - tier1_cost)
        self.assertEqual(b_eligible.get_component(TierState).current_tier, 1)
        self.assertEqual(b_stuck.get_component(TierState).current_tier, 2)
        self.assertEqual(b_stuck.get_component(TierState).current_level_in_tier, 3)

    def test_batch_upgrade_not_blocked_by_blocked_primary(self):
        """Regression for the grey-out bug: the PRIMARY selected building
        being blocked (tier maxed, next tier not yet researched) must not
        disable a batch that a non-primary selected building could still
        take. `_batch_upgrade_targets` sweeps the whole selection, not just
        the primary."""
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        primary, other = (t.occupant for t in tiles)
        primary.get_component(TierState).current_level_in_tier = 3  # tier max
        # Next tier is NOT researched (tiers_unlocked left at its default),
        # so primary's own mode is neither "in_tier" nor "tier_upgrade" --
        # under the old primary-gated logic this alone disabled the button.
        # `other` stays at level 1 (plain "in_tier").

        panel.open_for_tile(tiles[0], session, BUILDINGS_BAL,
                            selected_tiles=tiles)
        self.assertEqual(panel.mode, "upgrade")
        self.assertTrue(panel.action_btn.enabled)
        self.assertIn("UPGRADE", panel.action_btn.label)
        targets = panel._batch_upgrade_targets()
        self.assertEqual([t[0] for t in targets], [other])

    def test_batch_advance_all_or_nothing_when_unaffordable(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1), tm.get(2, 2)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        for t in tiles:
            t.occupant.get_component(TierState).current_level_in_tier = 3
        session.state.tiers_unlocked["defence"] = 2
        session.progression_balance = PROGRESSION_BAL
        session.state.village_level = DEF_T2_LEVEL

        panel.open_for_tile(tiles[0], session, BUILDINGS_BAL,
                            selected_tiles=tiles)
        total = panel._action_cost
        self.assertGreater(total, 0)
        session.state.love = total - 1
        panel.handle_click(*click(panel.action_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        self.assertEqual(session.state.love, total - 1)  # nothing spent
        for t in tiles:
            self.assertEqual(t.occupant.get_component(TierState).current_tier, 0)

    def test_dice_and_rename_preserve_rebirth_chain(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        tiles = [tm.get(2, 1)]
        session.state.love = 999
        self._open_construct(panel, session, tiles)
        p = panel.preview
        # dice always replaces the buffer with a pool name
        p.handle_click(*click(p.dice_btn))
        self.assertIn(p.name, BUILDINGS_BAL["BuildingsGlobal"]["random_names"])
        panel.handle_click(*click(p.confirm_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        b = tiles[0].occupant
        np = b.get_component(Nameplate)
        named = np.custom_name
        # upgrade-panel rename: committing the SAME name must not reset the
        # rebirth chain (prototype _commit_upgrade_name)
        np.rebirth_gen = 2
        panel._name_buf = named
        panel._name_editing = True
        panel._commit_rename()
        self.assertEqual(np.rebirth_gen, 2)
        panel._name_buf = "Other"
        panel._name_editing = True
        panel._commit_rename()
        self.assertEqual(np.custom_name, "Other")
        self.assertEqual(np.rebirth_gen, 0)


class TestConstructAtResearchedTier(unittest.TestCase):
    """Once a tier is researched, the construct panel offers -- and places --
    that tier directly, not the type's tier 0 (the placement-follows-research
    change)."""

    def test_card_preview_and_placement_all_show_the_researched_tier(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        session.state.tiers_unlocked["defence"] = 2  # Slinger (tier index 1)
        tier1 = BUILDINGS_BAL["DefenceBuildings"]["BasicDefence"]["tiers"][1]
        tier0_cost = BUILDINGS_BAL["DefenceBuildings"]["BasicDefence"]["tiers"][0]["build_cost"]
        session.state.love = tier1["build_cost"] + 5

        tile = tm.get(2, 1)
        panel.open_for_tile(tile, session, BUILDINGS_BAL)
        self.assertEqual(panel.mode, "construct")
        btype, btn = next(
            (bt, b) for bt, b in panel.cards if bt == "defence")
        self.assertIn(tier1["name"], btn.label)   # "Slinger", not "Stone Thrower"
        self.assertIn(str(tier1["build_cost"]), btn.label)

        panel.handle_click(*click(btn), session, BUILDINGS_BAL, None, None)
        p = panel.preview
        self.assertIsNotNone(p)
        self.assertEqual(p.cost, tier1["build_cost"])
        self.assertNotEqual(p.cost, tier0_cost)
        self.assertIn(tier1["name"], p.title)

        panel.handle_click(*click(p.confirm_btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        building = tile.occupant
        self.assertIsNotNone(building)
        self.assertEqual(building.get_component(TierState).current_tier, 1)


class TestPreviews(unittest.TestCase):
    def _place_defender(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        session.state.love = 999
        tile = tm.get(2, 1)
        panel.open_for_tile(tile, session, BUILDINGS_BAL)
        btype, btn = next((bt, b) for bt, b in panel.cards
                          if bt == "defence")
        panel.handle_click(*click(btn), session, BUILDINGS_BAL, scene,
                           occupancy)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        return panel, tile.occupant

    def test_next_level_rows_show_upgraded_stats(self):
        # UT-3: stat rows are keyed by STAT KEY, not by display label — the
        # hover preview matches on the key now, so renaming a stat in
        # strings.json can no longer silently break the green highlight.
        panel, b = self._place_defender()
        rows = dict(panel._next_level_rows(b))
        d = b.tier_data()
        self.assertEqual(rows["hp"], d["base_hp"] + d["hp_per_level"])
        self.assertEqual(rows["damage"], d["base_dmg"] + d["dmg_per_level"])

    def test_next_tier_card_reads_tier_two(self):
        # UT-3: the card returns the bare tier NAME; the "Next: {name}"
        # wrapper is the id'd header widget's own string template.
        panel, b = self._place_defender()
        slot, next_name, rows = panel._next_tier_card(b)
        tier2 = b._tiers[1]
        self.assertEqual(next_name, tier2["name"])
        self.assertEqual(dict(rows)["hp"], tier2["base_hp"])


class TestIncomeSources(unittest.TestCase):
    def test_sources_split_and_sum_to_breakdown(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        session.state.love = 999
        for tile, btype in ((tm.get(2, 1), "economic"),
                            (tm.get(2, 2), "defence")):
            panel.open_for_tile(tile, session, BUILDINGS_BAL)
            btn = next(b for bt, b in panel.cards if bt == btype)
            panel.handle_click(*click(btn), session, BUILDINGS_BAL, scene,
                               occupancy)
            panel.handle_click(*click(panel.preview.confirm_btn), session,
                               BUILDINGS_BAL, scene, occupancy)
        sources = dict(income_sources(session))
        self.assertIn("Base", sources)
        self.assertGreater(sources["Musicians"], 0)   # the musician's yield
        self.assertNotIn("Meditators", sources)
        income, upkeep = income_breakdown(session)
        self.assertEqual(income, sum(v for v in sources.values() if v > 0))
        self.assertEqual(upkeep, -sources.get("Upkeep", 0))


class TestFxHooks(unittest.TestCase):
    """ESV-3a moved the particle/gold/splatter LISTS onto the FloaterManager's
    VfxSystem (``fm._vfx``) — these tests peek one level deeper
    (``fm._vfx._particles`` etc.) than before ESV-3a, but assert the exact
    same counts (the port is a byte-identical no-op)."""

    def test_building_vfx_presets_and_gold(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.spawn_building_vfx(3, 3, "place")
        self.assertEqual(len(fm._vfx._particles), 10)
        self.assertEqual(len(fm._vfx._gold), 1)
        fm.spawn_building_vfx(3, 3, "level1")
        self.assertEqual(len(fm._vfx._particles), 17)  # +7, no new highlight
        self.assertEqual(len(fm._vfx._gold), 1)
        fm.update(2.0)  # everything ages out
        self.assertEqual(len(fm._vfx._particles), 0)
        self.assertEqual(len(fm._vfx._gold), 0)

    def test_death_watcher_bursts_and_logs_named_only(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        log = GameLog()
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        session.state.love = 999
        tile = tm.get(2, 1)
        panel.open_for_tile(tile, session, BUILDINGS_BAL)
        btn = next(b for bt, b in panel.cards if bt == "defence")
        panel.handle_click(*click(btn), session, BUILDINGS_BAL, scene,
                           occupancy)
        panel.preview.name = "Rex"
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        b = tile.occupant
        scene.update(0.0)                   # apply the queued spawn (E-13)
        fm.watch_buildings(scene, log)      # registers alive
        from engine.core import Health
        b.get_component(Health).damage(10 ** 6)
        fm.watch_buildings(scene, log)      # sees the death once
        self.assertGreater(len(fm._vfx._particles), 0)
        self.assertEqual(log._messages[-1][0], "Rex has been killed")
        n = len(fm._vfx._particles)
        fm.watch_buildings(scene, log)      # no double burst
        self.assertEqual(len(fm._vfx._particles), n)

    def test_splatters_gated_and_cleared(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)

        class _S:
            enemy_death_events = [(3.0, 4.0)]

        fm.spawn_death_events(_S, gore_on=False)   # settings toggle off
        self.assertEqual(fm._vfx._splatters, [])
        self.assertEqual(_S.enemy_death_events, [])  # ledger drains anyway
        _S.enemy_death_events = [(3.0, 4.0), (5.0, 6.0)]
        fm.spawn_death_events(_S, gore_on=True)
        self.assertEqual(len(fm._vfx._splatters), 2)
        fm.clear_splatters()
        self.assertEqual(fm._vfx._splatters, [])


class TestStormPriestLightningSeam(unittest.TestCase):
    """The placement -> lightning-unlock WIRING, driven through the REAL
    ``BuildingUI._do_place`` seam (card click -> construct preview -> confirm),
    with NO manual ``lightning.unlock_from_placement`` call. This is the
    regression guard for the ``unlock_from_placement`` call site in
    ``building_ui._do_place``: delete that line and this test fails (the pure
    unit tests in ``test_lightning.py`` would not — they call the helper
    directly). Lightning boots LOCKED (level 0); only a Storm Priest unlocks it.
    """

    def test_placing_storm_priest_via_panel_unlocks_lightning(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        st = session.state
        st.unlocked_buildings["storm_priest"] = True   # earned the type
        st.love = 100000
        self.assertEqual(st.lightning_level, 0)         # locked at boot
        tile = tm.get(2, 1)
        panel.open_for_tile(tile, session, BUILDINGS_BAL)
        self.assertEqual(panel.mode, "construct")
        btype, btn = next(
            (bt, b) for bt, b in panel.cards if bt == "storm_priest")
        panel.handle_click(*click(btn), session, BUILDINGS_BAL,
                           scene, occupancy)            # -> construct preview
        self.assertIsNotNone(panel.preview)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)  # -> _do_place
        self.assertEqual(st.lightning_level, 1)         # unlocked BY placement

    def test_placing_defence_via_panel_leaves_lightning_locked(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        st = session.state
        st.love = 100000                                 # defence starts unlocked
        tile = tm.get(2, 1)
        panel.open_for_tile(tile, session, BUILDINGS_BAL)
        btype, btn = next(
            (bt, b) for bt, b in panel.cards if bt == "defence")
        panel.handle_click(*click(btn), session, BUILDINGS_BAL,
                           scene, occupancy)
        panel.handle_click(*click(panel.preview.confirm_btn), session,
                           BUILDINGS_BAL, scene, occupancy)
        self.assertEqual(st.lightning_level, 0)         # non-source: still locked


class TestLifeLostBanner(unittest.TestCase):
    """The "YOU / LOST 1 LIFE" centre-screen banner: ``Session.on_base_hit``
    fills the ``life_lost_events`` ledger, ``FloaterManager`` drains it (off
    the same per-frame ``spawn_boss_events`` call the boss announcement uses)
    and ``submit_announce`` draws it on the boss-announce timings."""

    class _Recorder:
        def __init__(self):
            self.items = []

        def submit_hud(self, item):
            self.items.append(item)

    def test_base_hit_appends_one_marker_per_charged_life(self):
        tm, scene, occupancy, session = make_world()
        st = session.state
        lives = st.base_lives

        class _Enemy:
            ETYPE = "standard"

        session.on_base_hit(_Enemy())
        self.assertEqual(st.base_lives, lives - 1)
        self.assertEqual(st.life_lost_events, [st.round_num])

    def test_drain_arms_the_banner_and_submit_draws_two_lines(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)

        class _S:
            boss_events = []
            life_lost_events = [3]

        fm.spawn_boss_events(_S)             # the shared per-frame drain hook
        self.assertEqual(_S.life_lost_events, [])
        self.assertIsNotNone(fm._life_lost_age)
        rec = self._Recorder()
        fm.submit_announce(rec, VIEW_W, VIEW_H)
        texts = [i.text for i in rec.items if hasattr(i, "text")]
        self.assertEqual(texts, ["YOU", "LOST 1 LIFE"])   # no boss banner
        fm.update(10.0)                                   # ages out
        self.assertIsNone(fm._life_lost_age)
        rec2 = self._Recorder()
        fm.submit_announce(rec2, VIEW_W, VIEW_H)
        self.assertEqual(rec2.items, [])

    def test_empty_ledger_never_arms_the_banner(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)

        class _S:
            boss_events = []
            life_lost_events = []

        fm.spawn_boss_events(_S)
        self.assertIsNone(fm._life_lost_age)


if __name__ == "__main__":
    unittest.main()
