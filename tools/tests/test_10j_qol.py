"""Phase 10J QOL: shift multi-select batch math (unlock chunk-dedup /
construct ×count / in-tier upgrade sums), the game log, the next-tier +
next-level previews, the income-source breakdown, and the FX spawn hooks.

Headless: real TileMap/Session/BuildingUI over the shipped starter map, no
pygame window (the UI layer is pure).
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings.components import Nameplate, TierState
from game.core import Session, load_balance
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.map.tiles import TileState
from game.ui.building_ui import BuildingUI
from game.ui.effects import FloaterManager
from game.ui.game_log import GameLog, LIFETIME, MAX_MESSAGES
from game.ui.hud import income_breakdown, income_sources

MAP = REPO / "data" / "maps" / "first_light.json"
MAP_SCHEMA = REPO / "data" / "schemas" / "map_file.schema.json"
MAP_BAL = load_balance(REPO / "data", "map")
BUILDINGS_BAL = load_balance(REPO / "data", "buildings")
ENEMIES_BAL = load_balance(REPO / "data", "enemies")
CORE_BAL = load_balance(REPO / "data", "core")
UI_BAL = load_balance(REPO / "data", "ui")
VIEW_W, VIEW_H = 1280, 720


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
        panel, b = self._place_defender()
        rows = dict(panel._next_level_rows(b))
        d = b.tier_data()
        self.assertEqual(rows["HP"], d["base_hp"] + d["hp_per_level"])
        self.assertEqual(rows["Damage"], d["base_dmg"] + d["dmg_per_level"])

    def test_next_tier_card_reads_tier_two(self):
        panel, b = self._place_defender()
        slot, header, rows = panel._next_tier_card(b)
        tier2 = b._tiers[1]
        self.assertEqual(header, f"Next: {tier2['name']}")
        self.assertEqual(dict(rows)["HP"], tier2["base_hp"])


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
    def test_building_vfx_presets_and_gold(self):
        fm = FloaterManager(UI_BAL, CORE_BAL)
        fm.spawn_building_vfx(3, 3, "place")
        self.assertEqual(len(fm._particles), 10)
        self.assertEqual(len(fm._gold), 1)
        fm.spawn_building_vfx(3, 3, "level1")
        self.assertEqual(len(fm._particles), 17)  # +7, no new highlight
        self.assertEqual(len(fm._gold), 1)
        fm.update(2.0)  # everything ages out
        self.assertEqual(len(fm._particles), 0)
        self.assertEqual(len(fm._gold), 0)

    def test_death_watcher_bursts_and_logs_named_only(self):
        tm, scene, occupancy, session = make_world()
        panel = make_panel()
        log = GameLog()
        fm = FloaterManager(UI_BAL, CORE_BAL)
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
        self.assertGreater(len(fm._particles), 0)
        self.assertEqual(log._messages[-1][0], "Rex has been killed")
        n = len(fm._particles)
        fm.watch_buildings(scene, log)      # no double burst
        self.assertEqual(len(fm._particles), n)

    def test_splatters_gated_and_cleared(self):
        fm = FloaterManager(UI_BAL, CORE_BAL)

        class _S:
            enemy_death_events = [(3.0, 4.0)]

        fm.spawn_death_events(_S, gore_on=False)   # settings toggle off
        self.assertEqual(fm._splatters, [])
        self.assertEqual(_S.enemy_death_events, [])  # ledger drains anyway
        _S.enemy_death_events = [(3.0, 4.0), (5.0, 6.0)]
        fm.spawn_death_events(_S, gore_on=True)
        self.assertEqual(len(fm._splatters), 2)
        fm.clear_splatters()
        self.assertEqual(fm._splatters, [])


if __name__ == "__main__":
    unittest.main()
