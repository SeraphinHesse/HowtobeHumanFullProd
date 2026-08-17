"""Feature: tile-crowding visual offset — Standard/Walker and Raider.

Pure-Python, headless — the ``synth`` TileMap fixture + real (fixture)
balancing pattern ``test_enemies.py`` uses. See
``game/enemies/crowd_spacing.py``'s module docstring for the design (real
position offset, restore/apply split around ``scene.update``, the safety-bound
anchor table, per-type grouping via ``CrowdSpacing.<Type>``).
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Movement, Scene
from game.core.balance import load_balance
from game.enemies import (
    CrowdSpacing, apply_crowd_spacing, create_enemy, restore_crowd_positions,
)
from game.enemies.crowd_spacing import ANCHOR_TABLE, MAX_TABLE_SIZE
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
ENEM = load_balance(FIXTURE_DATA, "enemies")
CROWD = ENEM["CrowdSpacing"]
STD = CROWD["Standard"]
RDR = CROWD["Raider"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def _frozen_enemy(etype, tm, col, row, scene):
    """An enemy spawned and immediately frozen in place (no waypoints) so
    tests control its tile deterministically, the ``TestCombatLedger``
    "freeze: a pure target" precedent."""
    e = create_enemy(etype, col, row, ENEM, tm)
    scene.spawn(e)
    scene.update(0.0)  # apply spawn + on_spawn
    e.get_component(Movement).waypoints = []
    return e


def _frozen_walker(tm, col, row, scene):
    return _frozen_enemy("standard", tm, col, row, scene)


def _tick(scene, dt, n=1):
    for _ in range(n):
        restore_crowd_positions(scene)
        scene.update(dt)
        apply_crowd_spacing(scene, dt, CROWD)


class TestDwellGating(unittest.TestCase):
    def test_no_offset_below_dwell_threshold(self):
        tm = synth(["bbb"])
        scene = Scene()
        a = _frozen_walker(tm, 1, 0, scene)
        b = _frozen_walker(tm, 1, 0, scene)
        _tick(scene, STD["dwell_threshold_seconds"] * 0.5)
        self.assertEqual((a.get_component(CrowdSpacing).offset_dx,
                          a.get_component(CrowdSpacing).offset_dy), (0.0, 0.0))
        self.assertEqual((b.get_component(CrowdSpacing).offset_dx,
                          b.get_component(CrowdSpacing).offset_dy), (0.0, 0.0))

    def test_offset_appears_once_two_eligible_enemies_share_a_tile(self):
        tm = synth(["bbb"])
        scene = Scene()
        a = _frozen_walker(tm, 1, 0, scene)
        b = _frozen_walker(tm, 1, 0, scene)
        # Comfortably past the dwell threshold and past the ease window.
        _tick(scene, STD["dwell_threshold_seconds"] + STD["offset_ease_seconds"] * 5,
             n=10)
        off_a = (a.get_component(CrowdSpacing).offset_dx,
                 a.get_component(CrowdSpacing).offset_dy)
        off_b = (b.get_component(CrowdSpacing).offset_dx,
                 b.get_component(CrowdSpacing).offset_dy)
        self.assertNotEqual(off_a, (0.0, 0.0))
        self.assertNotEqual(off_b, (0.0, 0.0))
        self.assertNotEqual(off_a, off_b)

    def test_lone_occupant_never_offsets(self):
        tm = synth(["bbb"])
        scene = Scene()
        a = _frozen_walker(tm, 1, 0, scene)
        _tick(scene, 5.0, n=50)
        self.assertEqual((a.get_component(CrowdSpacing).offset_dx,
                          a.get_component(CrowdSpacing).offset_dy), (0.0, 0.0))


class TestPerTypeGrouping(unittest.TestCase):
    """A Raider and a Standard never share a slot layout, even on the same
    tile — each groups only with its own kind, off its own CrowdSpacing.<Type>
    tunables (feature request: separate system, separate slot cap)."""

    def test_one_of_each_type_on_a_tile_neither_offsets(self):
        """Each type is ALONE within its own group (1 Standard, 1 Raider) —
        no cross-type grouping, so neither gets an offset."""
        tm = synth(["bbb"])
        scene = Scene()
        walker = _frozen_walker(tm, 1, 0, scene)
        raider = _frozen_enemy("raider", tm, 1, 0, scene)
        _tick(scene, max(STD["dwell_threshold_seconds"],
                        RDR["dwell_threshold_seconds"]) + 1.0, n=10)
        self.assertEqual((walker.get_component(CrowdSpacing).offset_dx,
                          walker.get_component(CrowdSpacing).offset_dy), (0.0, 0.0))
        self.assertEqual((raider.get_component(CrowdSpacing).offset_dx,
                          raider.get_component(CrowdSpacing).offset_dy), (0.0, 0.0))

    def test_two_walkers_and_two_raiders_form_independent_pairs(self):
        tm = synth(["bbb"])
        scene = Scene()
        walkers = [_frozen_walker(tm, 1, 0, scene) for _ in range(2)]
        raiders = [_frozen_enemy("raider", tm, 1, 0, scene) for _ in range(2)]
        _tick(scene, max(STD["dwell_threshold_seconds"],
                        RDR["dwell_threshold_seconds"])
             + max(STD["offset_ease_seconds"], RDR["offset_ease_seconds"]) * 8,
             n=20)
        # Both types share the same normalized 2-slot layout shape; only the
        # magnitude (max_offset_tiles) differs per type.
        unit_fx, unit_fy = ANCHOR_TABLE[2][0]
        unit_mag = (unit_fx ** 2 + unit_fy ** 2) ** 0.5
        for w in walkers:
            cs = w.get_component(CrowdSpacing)
            mag = (cs.offset_dx ** 2 + cs.offset_dy ** 2) ** 0.5
            self.assertAlmostEqual(mag, unit_mag * STD["max_offset_tiles"], delta=1e-3)
        for r in raiders:
            cs = r.get_component(CrowdSpacing)
            mag = (cs.offset_dx ** 2 + cs.offset_dy ** 2) ** 0.5
            self.assertAlmostEqual(mag, unit_mag * RDR["max_offset_tiles"], delta=1e-3)

    def test_raider_slot_cap_is_five_not_six(self):
        tm = synth(["bbbbbbbbb"])
        scene = Scene()
        raiders = [_frozen_enemy("raider", tm, 4, 0, scene) for _ in range(7)]
        _tick(scene, RDR["dwell_threshold_seconds"] + RDR["offset_ease_seconds"] * 5,
             n=10)
        offsets = {(round(r.get_component(CrowdSpacing).offset_dx, 6),
                   round(r.get_component(CrowdSpacing).offset_dy, 6))
                  for r in raiders}
        self.assertLessEqual(len(offsets), RDR["max_slots"])
        self.assertEqual(RDR["max_slots"], 5)


class TestSafetyBound(unittest.TestCase):
    def test_anchor_table_never_exceeds_unit_magnitude_per_axis(self):
        """The schema's max_offset_tiles maximum (0.4) relies on every
        anchor-table entry staying within +/-1.0 per axis — re-derive it here
        so a future retune of the table can't silently break the guarantee."""
        for entries in ANCHOR_TABLE.values():
            for fx, fy in entries:
                self.assertLessEqual(abs(fx), 1.0)
                self.assertLessEqual(abs(fy), 1.0)

    def test_offset_never_crosses_a_tile_boundary_at_max_schema_value(self):
        tm = synth(["bbbbb"])
        scene = Scene()
        enemies = [_frozen_walker(tm, 2, 0, scene) for _ in range(6)]
        crowd = {"Standard": dict(STD), "Raider": dict(RDR)}
        crowd["Standard"]["max_offset_tiles"] = 0.4  # the schema's own hard ceiling
        for _ in range(50):
            restore_crowd_positions(scene)
            scene.update(crowd["Standard"]["offset_ease_seconds"])
            apply_crowd_spacing(scene, crowd["Standard"]["offset_ease_seconds"], crowd)
        for e in enemies:
            self.assertEqual(round(e.transform.wx), 2)
            self.assertEqual(round(e.transform.wy), 0)


class TestOverflowAndReflow(unittest.TestCase):
    def test_more_than_six_occupants_reuses_the_last_slot(self):
        tm = synth(["bbbbbbbbb"])
        scene = Scene()
        enemies = [_frozen_walker(tm, 4, 0, scene) for _ in range(8)]
        _tick(scene, STD["dwell_threshold_seconds"] + STD["offset_ease_seconds"] * 5,
             n=10)
        offsets = sorted(
            (e.get_component(CrowdSpacing).offset_dx,
             e.get_component(CrowdSpacing).offset_dy)
            for e in enemies)
        # At most this type's own max_slots distinct positions no matter how
        # many share the tile (the 7th/8th occupant, by sorted id, land on
        # the last slot).
        distinct = set(offsets)
        self.assertLessEqual(len(distinct), STD["max_slots"])
        self.assertLessEqual(len(distinct), MAX_TABLE_SIZE)

    def test_reflow_when_an_occupant_leaves(self):
        tm = synth(["bbb"])
        scene = Scene()
        a = _frozen_walker(tm, 1, 0, scene)
        b = _frozen_walker(tm, 1, 0, scene)
        c = _frozen_walker(tm, 1, 0, scene)
        _tick(scene, STD["dwell_threshold_seconds"] + STD["offset_ease_seconds"] * 5,
             n=10)
        three_way = (a.get_component(CrowdSpacing).offset_dx,
                    a.get_component(CrowdSpacing).offset_dy)
        scene.despawn(c)
        scene.update(0.0)
        _tick(scene, STD["offset_ease_seconds"] * 5, n=10)
        two_way = (a.get_component(CrowdSpacing).offset_dx,
                  a.get_component(CrowdSpacing).offset_dy)
        self.assertNotEqual(three_way, two_way)


class TestMovementComposition(unittest.TestCase):
    def test_path_position_advances_normally_while_drawn_position_is_offset(self):
        """restore_crowd_positions + Movement must compose correctly: the
        enemy's underlying PATH keeps advancing at its normal speed even
        while its DRAWN position carries a crowd offset — the whole point of
        the restore/apply split (see the module docstring's "why a naive
        nudge breaks movement" rationale)."""
        tm = synth(["bbbbbbbbbb"])
        scene = Scene()
        a = create_enemy("standard", 5, 0, ENEM, tm)
        b = create_enemy("standard", 5, 0, ENEM, tm)
        scene.spawn(a)
        scene.spawn(b)
        scene.update(0.0)
        cs_a = a.get_component(CrowdSpacing)
        # Captured BEFORE the crowd system's first cycle (which seeds
        # cs_a.base_wx from this same value) — not cs_a.base_wx itself,
        # which is still the -1.0 "not yet seeded" sentinel at this point.
        start_base = a.transform.wx
        for _ in range(40):
            restore_crowd_positions(scene)
            scene.update(0.05)
            apply_crowd_spacing(scene, 0.05, CROWD)
        # The clean path position (base_wx) must have moved toward the base —
        # a stuck/compounding offset would instead leave it near its start.
        self.assertLess(cs_a.base_wx, start_base - 0.5)
        # And the drawn position never drifted from the path position by more
        # than the configured max offset.
        self.assertLessEqual(abs(a.transform.wx - cs_a.base_wx),
                             STD["max_offset_tiles"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
