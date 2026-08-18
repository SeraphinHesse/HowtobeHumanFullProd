"""SaveGamePLAN SG-1: save-slot storage primitives.

Slot/index file mechanics only, against hand-built dicts — no RunState/
TileMap/Building serialization (SG-2/SG-3/SG-4). Mirrors
test_player_identity.py's TestHighscoreRoundTrip shape: a tempdir for the
disk half, FIXTURE_DATA for schema resolution (test_fixture_guard.py forbids
a new test from reading live data/).
"""
import tempfile
import unittest
from pathlib import Path

from tools.tests.fixture_data import FIXTURE_DATA

from game.core import savegame


def _slot_doc(slot_id="a", round_num=5, pinned=False, unlocked_tiles=None):
    return savegame.make_slot_doc(
        slot_id=slot_id,
        map_id="first_light",
        round_num=round_num,
        unlocked_tiles=unlocked_tiles or [[0, 0], [1, 0]],
        run_state={},
        session={},
        tile_map={"cols": 10, "rows": 10},
        buildings=[],
        pinned=pinned,
    )


class TestSlotRoundTrip(unittest.TestCase):
    """write_slot -> load_slot survives a reload, through the validating
    writer, in a tempdir."""

    def test_slot_survives_a_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = savegame.slot_path(tmp, "abc123")
            doc = _slot_doc(slot_id="abc123", round_num=15)
            savegame.write_slot(path, doc, FIXTURE_DATA)

            loaded = savegame.load_slot(path, FIXTURE_DATA)
        self.assertEqual(loaded["slot_id"], "abc123")
        self.assertEqual(loaded["round_num"], 15)
        self.assertEqual(loaded["map_id"], "first_light")
        self.assertEqual(loaded["unlocked_tiles"], [[0, 0], [1, 0]])

    def test_missing_slot_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = savegame.slot_path(tmp, "nope")
            self.assertIsNone(savegame.load_slot(path, FIXTURE_DATA))

    def test_corrupt_slot_returns_none_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = savegame.slot_path(tmp, "bad")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(savegame.load_slot(path, FIXTURE_DATA))


class TestIndexRoundTrip(unittest.TestCase):
    def test_missing_index_returns_empty_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = savegame.index_path(tmp)
            doc = savegame.load_index(path, FIXTURE_DATA)
        self.assertEqual(doc, {"version": 1, "slots": []})

    def test_index_survives_a_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = savegame.index_path(tmp)
            doc = {"version": 1, "slots": [savegame.make_summary(_slot_doc())]}
            savegame.write_index(path, doc, FIXTURE_DATA)

            loaded = savegame.load_index(path, FIXTURE_DATA)
        self.assertEqual(len(loaded["slots"]), 1)
        self.assertEqual(loaded["slots"][0]["slot_id"], "a")


class TestAddSlotAndEviction(unittest.TestCase):
    """add_slot's FIFO-with-pin eviction, exercised end-to-end on disk."""

    def test_new_slots_accumulate_below_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                doc = _slot_doc(slot_id=f"s{i}", round_num=5 * (i + 1))
                index_doc, evicted = savegame.add_slot(tmp, doc, FIXTURE_DATA,
                                                        keep=10)
                self.assertIsNone(evicted)
            self.assertEqual(len(index_doc["slots"]), 5)
            self.assertEqual([s["slot_id"] for s in index_doc["slots"]],
                             [f"s{i}" for i in range(5)])

    def test_oldest_unpinned_slot_is_evicted_when_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(10):
                savegame.add_slot(tmp, _slot_doc(slot_id=f"s{i}"),
                                  FIXTURE_DATA, keep=10)
            # 11th save should evict s0 (oldest, unpinned).
            index_doc, evicted = savegame.add_slot(
                tmp, _slot_doc(slot_id="s10"), FIXTURE_DATA, keep=10)
            self.assertEqual(evicted, "s0")
            self.assertEqual(len(index_doc["slots"]), 10)
            ids = [s["slot_id"] for s in index_doc["slots"]]
            self.assertNotIn("s0", ids)
            self.assertIn("s10", ids)
            # The evicted slot's body is actually gone from disk.
            self.assertIsNone(savegame.load_slot(
                savegame.slot_path(tmp, "s0"), FIXTURE_DATA))

    def test_pinned_slots_are_skipped_by_eviction(self):
        with tempfile.TemporaryDirectory() as tmp:
            savegame.add_slot(tmp, _slot_doc(slot_id="s0", pinned=True),
                              FIXTURE_DATA, keep=10)
            for i in range(1, 10):
                savegame.add_slot(tmp, _slot_doc(slot_id=f"s{i}"),
                                  FIXTURE_DATA, keep=10)
            index_doc, evicted = savegame.add_slot(
                tmp, _slot_doc(slot_id="s10"), FIXTURE_DATA, keep=10)
            self.assertEqual(evicted, "s1")   # s0 is pinned, s1 is next-oldest
            ids = [s["slot_id"] for s in index_doc["slots"]]
            self.assertIn("s0", ids)
            self.assertNotIn("s1", ids)

    def test_all_pinned_skips_the_new_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(10):
                savegame.add_slot(tmp, _slot_doc(slot_id=f"s{i}", pinned=True),
                                  FIXTURE_DATA, keep=10)
            index_doc, evicted = savegame.add_slot(
                tmp, _slot_doc(slot_id="s10"), FIXTURE_DATA, keep=10)
            self.assertIsNone(evicted)
            ids = [s["slot_id"] for s in index_doc["slots"]]
            self.assertEqual(len(ids), 10)
            self.assertNotIn("s10", ids)      # the new save was skipped
            self.assertIsNone(savegame.load_slot(
                savegame.slot_path(tmp, "s10"), FIXTURE_DATA))


class TestPinAndDelete(unittest.TestCase):
    def test_set_pinned_updates_index_and_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            savegame.add_slot(tmp, _slot_doc(slot_id="s0"), FIXTURE_DATA)
            index_doc = savegame.set_pinned(tmp, "s0", True, FIXTURE_DATA)
            self.assertTrue(index_doc["slots"][0]["pinned"])
            body = savegame.load_slot(savegame.slot_path(tmp, "s0"),
                                      FIXTURE_DATA)
            self.assertTrue(body["pinned"])

    def test_set_pinned_on_unknown_slot_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_doc = savegame.set_pinned(tmp, "ghost", True, FIXTURE_DATA)
            self.assertEqual(index_doc["slots"], [])

    def test_remove_slot_deletes_body_and_index_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            savegame.add_slot(tmp, _slot_doc(slot_id="s0"), FIXTURE_DATA)
            index_doc = savegame.remove_slot(tmp, "s0", FIXTURE_DATA)
            self.assertEqual(index_doc["slots"], [])
            self.assertIsNone(savegame.load_slot(
                savegame.slot_path(tmp, "s0"), FIXTURE_DATA))

    def test_remove_unknown_slot_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            savegame.add_slot(tmp, _slot_doc(slot_id="s0"), FIXTURE_DATA)
            index_doc = savegame.remove_slot(tmp, "ghost", FIXTURE_DATA)
            self.assertEqual(len(index_doc["slots"]), 1)


class TestMostRecentSlot(unittest.TestCase):
    def test_empty_index_has_no_most_recent(self):
        self.assertIsNone(savegame.most_recent_slot({"version": 1, "slots": []}))

    def test_most_recent_is_the_last_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                index_doc, _ = savegame.add_slot(
                    tmp, _slot_doc(slot_id=f"s{i}"), FIXTURE_DATA)
        self.assertEqual(savegame.most_recent_slot(index_doc), "s2")


if __name__ == "__main__":
    unittest.main()
