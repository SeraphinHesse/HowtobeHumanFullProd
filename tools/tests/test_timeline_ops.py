"""``editor/timeline_ops.py`` tests (TimelinePLAN T5). Pure Python — no Qt,
no pygame — copies ``data/`` into a tempdir so writes never touch the repo
(the ``TempDataCase`` pattern, without the Qt base class this module has no
need of).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from editor import timeline_ops

REPO = Path(__file__).resolve().parents[2]


class TimelineOpsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)

    def empty_doc(self):
        return {"Timeline": {"levels": []}}


class TestLevelAndSlotOps(TimelineOpsCase):
    def test_add_level_is_idempotent(self):
        doc = self.empty_doc()
        timeline_ops.add_level(doc, 3)
        timeline_ops.add_level(doc, 3)
        self.assertEqual(len(doc["Timeline"]["levels"]), 1)

    def test_add_level_keeps_levels_sorted(self):
        doc = self.empty_doc()
        timeline_ops.add_level(doc, 5)
        timeline_ops.add_level(doc, 1)
        timeline_ops.add_level(doc, 3)
        village_levels = [lvl["village_level"] for lvl in doc["Timeline"]["levels"]]
        self.assertEqual(village_levels, [1, 3, 5])

    def test_remove_level_drops_its_slots_too(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 2, 0, "unlock", "blocker", 0)
        timeline_ops.remove_level(doc, 2)
        self.assertEqual(doc["Timeline"]["levels"], [])

    def test_remove_level_missing_is_a_no_op(self):
        doc = self.empty_doc()
        timeline_ops.remove_level(doc, 9)  # must not raise
        self.assertEqual(doc["Timeline"]["levels"], [])

    def test_add_slot_creates_level_and_appends_empty_slot(self):
        doc = self.empty_doc()
        timeline_ops.add_slot(doc, 1)
        timeline_ops.add_slot(doc, 1)
        level = doc["Timeline"]["levels"][0]
        self.assertEqual(len(level["offer_slots"]), 2)
        self.assertTrue(all(s["assignment"] is None for s in level["offer_slots"]))

    def test_remove_slot_out_of_range_is_a_no_op(self):
        doc = self.empty_doc()
        timeline_ops.add_slot(doc, 1)
        timeline_ops.remove_slot(doc, 1, 5)  # must not raise
        self.assertEqual(len(doc["Timeline"]["levels"][0]["offer_slots"]), 1)


class TestAssignAndClear(TimelineOpsCase):
    def test_assign_slot_creates_level_and_pads_slots(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 4, 2, "unlock", "storm_priest", 0)
        level = doc["Timeline"]["levels"][0]
        self.assertEqual(level["village_level"], 4)
        self.assertEqual(len(level["offer_slots"]), 3)
        self.assertIsNone(level["offer_slots"][0]["assignment"])
        self.assertIsNone(level["offer_slots"][1]["assignment"])
        self.assertEqual(
            level["offer_slots"][2]["assignment"],
            {"kind": "unlock", "building_type": "storm_priest", "tier_index": 0})

    def test_assign_slot_replaces_an_occupied_slot_unconditionally(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "wall_builder", 0)
        assignment = doc["Timeline"]["levels"][0]["offer_slots"][0]["assignment"]
        self.assertEqual(assignment["building_type"], "wall_builder")

    def test_clear_slot_empties_without_removing_it(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.clear_slot(doc, 1, 0)
        level = doc["Timeline"]["levels"][0]
        self.assertEqual(len(level["offer_slots"]), 1)
        self.assertIsNone(level["offer_slots"][0]["assignment"])


class TestPlacementsAndUniqueness(TimelineOpsCase):
    def test_placements_indexes_every_non_null_assignment(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.assign_slot(doc, 4, 0, "tier", "defence", 1)
        self.assertEqual(
            timeline_ops.placements(doc),
            {("blocker", 0): 1, ("defence", 1): 4})

    def test_validate_uniqueness_passes_on_a_clean_doc(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.validate_uniqueness(doc)  # must not raise

    def test_validate_uniqueness_rejects_duplicate_village_level(self):
        doc = self.empty_doc()
        doc["Timeline"]["levels"] = [
            {"village_level": 1, "offer_slots": []},
            {"village_level": 1, "offer_slots": []},
        ]
        with self.assertRaises(ValueError):
            timeline_ops.validate_uniqueness(doc)

    def test_validate_uniqueness_rejects_duplicate_placement(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.assign_slot(doc, 2, 0, "unlock", "blocker", 0)
        with self.assertRaises(ValueError):
            timeline_ops.validate_uniqueness(doc)


class TestSaveAndLoad(TimelineOpsCase):
    def test_save_then_load_round_trips(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.save_progression(doc, self.data_dir)
        reloaded = timeline_ops.load_progression(self.data_dir)
        self.assertEqual(reloaded, doc)

    def test_save_raises_before_touching_disk_on_uniqueness_violation(self):
        doc = self.empty_doc()
        timeline_ops.assign_slot(doc, 1, 0, "unlock", "blocker", 0)
        timeline_ops.assign_slot(doc, 2, 0, "unlock", "blocker", 0)
        path = timeline_ops.progression_path(self.data_dir)
        before = path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            timeline_ops.save_progression(doc, self.data_dir)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_load_building_catalog_reads_every_type(self):
        # Structural assertions only (never pin a live display name/value,
        # per data/CLAUDE.md's "never assert against live data/ content"
        # rule) — building_type/card_slots existing and well-shaped is what
        # T1 already pins in test_balancing_data.py::TestBuildingTypeAndCardSlots.
        catalog = timeline_ops.load_building_catalog(self.data_dir)
        self.assertGreater(len(catalog), 0)
        for entry in catalog:
            self.assertTrue(entry["building_type"])
            self.assertTrue(entry["label"])
            self.assertEqual(len(entry["tiers"]), 3)
            for tier in entry["tiers"]:
                self.assertTrue(tier["name"])
                self.assertTrue(tier["slot"])


if __name__ == "__main__":
    unittest.main()
