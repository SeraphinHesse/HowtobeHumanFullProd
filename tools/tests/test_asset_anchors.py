"""ESV-1: the optional manifest `anchors` block (schema + engine.assets parse/
store) and `game.anchors`' pure screen/world resolver.

Landing condition (phase-esv-1-anchors.md): a manifest with no `anchors` key
round-trips byte-identically and every resolver degrades to `(0.0, 0.0)`.
Mirrors the neighbouring `test_assets_manifest.py`'s `slice` tests — anchors
are parsed the same defensive way (reject a bare string, wrong length,
non-integers, an undeclared name) and warn-and-skip through `load_manifest`
(E-37), never raise.

Headless/pure: no pygame surfaces are ever loaded (frame_size/anchor are
metadata lookups only).
"""
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "data" / "schemas" / "asset_manifest.schema.json"

from tools.tests.fixture_data import FIXTURE_DATA

from engine.assets import Manifest, entry_from_dict, load_manifest
from engine.assets.manifest import ANCHOR_NAMES
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import GameObject, SpriteAnimator, Transform
from engine.data_io import write_validated
from game.anchors import screen_offset, world_offset


def row(animation="idle", frames=3, fps=8, hidden=(), loop=(0, 0, 1)):
    return {
        "animation": animation,
        "frames": frames,
        "fps": fps,
        "hidden": list(hidden),
        "loop_start": loop[0],
        "loop_end": loop[1],
        "loop_count": loop[2],
    }


def entry_dict(rows, sheet="imported/x.png", frame_w=64, frame_h=96,
               offset_x=0, offset_y=0):
    return {
        "sheet": sheet,
        "frame_w": frame_w,
        "frame_h": frame_h,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 1/2. Round-trip through the validating writer
# ---------------------------------------------------------------------------
class TestRoundTrip(unittest.TestCase):
    def test_without_anchors_is_byte_identical(self):
        """The whole phase's regression pin: adding the schema/parser support
        for `anchors` must not perturb a manifest that never authors one."""
        doc = {"version": 2, "entries": {"tower": entry_dict([row()])}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset_manifest.json"
            write_validated(doc, path, SCHEMA)
            text1 = path.read_text(encoding="utf-8")
            self.assertNotIn('"anchors"', text1)
            write_validated(doc, path, SCHEMA)   # re-write the identical doc
            self.assertEqual(text1, path.read_text(encoding="utf-8"))
            m = load_manifest(path)
            self.assertIsNone(m.entry("tower").anchors)

    def test_with_all_six_anchors_validates_parses_and_reserialises(self):
        anchors = {name: [10 + i, -20 - i] for i, name in enumerate(ANCHOR_NAMES)}
        doc = {"version": 2, "entries": {"tower": entry_dict([row()])}}
        doc["entries"]["tower"]["anchors"] = anchors
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset_manifest.json"
            write_validated(doc, path, SCHEMA)   # schema accepts it
            text1 = path.read_text(encoding="utf-8")
            write_validated(doc, path, SCHEMA)
            self.assertEqual(text1, path.read_text(encoding="utf-8"))
            entry = load_manifest(path).entry("tower")
            for i, name in enumerate(ANCHOR_NAMES):
                self.assertEqual(entry.anchor(name), (10 + i, -20 - i))
            self.assertIsNone(entry.anchor("not_a_real_name"))


# ---------------------------------------------------------------------------
# entry_from_dict: direct raise (mirrors TestEntryFromDict's slice tests)
# ---------------------------------------------------------------------------
class TestEntryFromDictAnchors(unittest.TestCase):
    def test_anchors_absent_is_none(self):
        self.assertIsNone(entry_from_dict("s", entry_dict([row()])).anchors)

    def test_one_declared_name_parsed(self):
        raw = entry_dict([row()])
        raw["anchors"] = {"muzzle": [18, -40]}
        e = entry_from_dict("s", raw)
        self.assertEqual(e.anchor("muzzle"), (18, -40))
        self.assertIsNone(e.anchor("impact"))

    def test_bad_anchor_raises(self):
        # a bare string (iterates into two valid-looking ints), wrong length,
        # non-integer, and an undeclared name.
        bad_cases = [
            {"muzzle": "12"},
            {"muzzle": [1, 2, 3]},
            {"muzzle": ["a", "b"]},
            {"not_a_real_anchor": [1, 2]},
        ]
        for bad in bad_cases:
            raw = entry_dict([row()])
            raw["anchors"] = bad
            with self.subTest(anchors=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)

    def test_anchors_not_an_object_raises(self):
        raw = entry_dict([row()])
        raw["anchors"] = "12"
        with self.assertRaises(ValueError):
            entry_from_dict("s", raw)


# ---------------------------------------------------------------------------
# 3. Malformed anchors: warn-and-skip THAT ENTRY, never raise (E-37)
# ---------------------------------------------------------------------------
class TestMalformedAnchorsWarnAndSkip(unittest.TestCase):
    def _load(self, doc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "asset_manifest.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)
        return m

    def test_bare_string_value(self):
        doc = {"version": 2, "entries": {"bad": entry_dict([row()])}}
        doc["entries"]["bad"]["anchors"] = {"muzzle": "12"}
        self.assertEqual(self._load(doc).slots(), ())

    def test_three_item_array(self):
        doc = {"version": 2, "entries": {"bad": entry_dict([row()])}}
        doc["entries"]["bad"]["anchors"] = {"muzzle": [1, 2, 3]}
        self.assertEqual(self._load(doc).slots(), ())

    def test_non_integer_values(self):
        doc = {"version": 2, "entries": {"bad": entry_dict([row()])}}
        doc["entries"]["bad"]["anchors"] = {"muzzle": ["a", "b"]}
        self.assertEqual(self._load(doc).slots(), ())

    def test_undeclared_name(self):
        doc = {"version": 2, "entries": {"bad": entry_dict([row()])}}
        doc["entries"]["bad"]["anchors"] = {"not_a_real_anchor": [1, 2]}
        self.assertEqual(self._load(doc).slots(), ())

    def test_only_the_bad_entry_is_dropped(self):
        doc = {"version": 2, "entries": {
            "good": entry_dict([row()]),
            "bad": entry_dict([row()]),
        }}
        doc["entries"]["bad"]["anchors"] = {"muzzle": "12"}
        self.assertEqual(self._load(doc).slots(), ("good",))


# ---------------------------------------------------------------------------
# game.anchors — the pure screen/world resolver
# ---------------------------------------------------------------------------
def _store_and_obj(anchor_xy=None, frame_w=64, frame_h=64, fit_tiles=1.0,
                   scale=1.0, wx=3.0, wy=2.0):
    raw = entry_dict([row()], frame_w=frame_w, frame_h=frame_h)
    if anchor_xy is not None:
        raw["anchors"] = {"muzzle": list(anchor_xy)}
    entry = entry_from_dict("thing", raw)
    manifest = Manifest({"thing": entry})
    store = AssetStore(manifest=manifest, sprites_dir=None,
                       frame_sizes={"thing": (frame_w, frame_h)})
    obj = GameObject(
        transform=Transform(wx=wx, wy=wy),
        components=[SpriteAnimator(slot_key="thing", fit_tiles=fit_tiles,
                                   scale=scale)])
    return store, obj


class TestResolverAbsence(unittest.TestCase):
    """§2.4: every layer degrades to today's number, never a special case."""

    def test_no_store_no_cs_no_animator_no_anchor_all_zero(self):
        store, obj = _store_and_obj(anchor_xy=None)
        cs = load_coordinate_system(FIXTURE_DATA)
        self.assertEqual(screen_offset(None, cs, obj, "muzzle", 1.0), (0.0, 0.0))
        self.assertEqual(screen_offset(store, None, obj, "muzzle", 1.0), (0.0, 0.0))
        self.assertEqual(screen_offset(store, cs, None, "muzzle", 1.0), (0.0, 0.0))
        self.assertEqual(screen_offset(store, cs, obj, "muzzle", 1.0), (0.0, 0.0))
        self.assertEqual(world_offset(None, cs, obj, "muzzle"), (0.0, 0.0))
        self.assertEqual(world_offset(store, None, obj, "muzzle"), (0.0, 0.0))
        self.assertEqual(world_offset(store, cs, obj, "muzzle"), (0.0, 0.0))

    def test_bare_object_with_no_sprite_animator_is_zero(self):
        cs = load_coordinate_system(FIXTURE_DATA)
        obj = GameObject(transform=Transform(wx=1.0, wy=0.0))
        store, _ = _store_and_obj((18, -40))
        self.assertEqual(world_offset(store, cs, obj, "muzzle"), (0.0, 0.0))

    def test_explicit_zero_anchor_is_exactly_zero(self):
        store, obj = _store_and_obj((0, 0))
        cs = load_coordinate_system(FIXTURE_DATA)
        self.assertEqual(world_offset(store, cs, obj, "muzzle"), (0.0, 0.0))


class TestWorldOffsetInvariance(unittest.TestCase):
    """D2: `world_offset` runs the screen delta back through
    `cs.screen_to_world` twice, so zoom and pan cancel in the difference —
    never a hand-derived closed form."""

    def test_same_at_two_very_different_zoom_levels(self):
        store, obj = _store_and_obj((18, -40))
        cs = load_coordinate_system(FIXTURE_DATA)
        results = []
        for zoom in (1.0, 2.0):
            cs.camera.zoom = zoom
            results.append(world_offset(store, cs, obj, "muzzle"))
        self.assertAlmostEqual(results[0][0], results[1][0], places=6)
        self.assertAlmostEqual(results[0][1], results[1][1], places=6)
        # and it is not the degenerate zero — the anchor really moved it
        self.assertGreater(abs(results[0][0]) + abs(results[0][1]), 0.0)

    def test_same_under_pan(self):
        store, obj = _store_and_obj((18, -40))
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        before = world_offset(store, cs, obj, "muzzle")
        cs.camera.pan_x, cs.camera.pan_y = 321.0, -654.0
        after = world_offset(store, cs, obj, "muzzle")
        self.assertAlmostEqual(before[0], after[0], places=6)
        self.assertAlmostEqual(before[1], after[1], places=6)

    def test_screen_offset_scales_with_the_footprint_fit(self):
        """The muzzle offset rides the SAME `fit_factor` the renderer uses
        (§1.3) — a downscaled unit's anchor shrinks with it, never the raw
        sheet-pixel value."""
        # frame_w 128 on a 64-wide tile with fit_tiles=1 halves the draw.
        store, obj = _store_and_obj((100, 0), frame_w=128, fit_tiles=1.0)
        dsx, _dsy = screen_offset(store, load_coordinate_system(FIXTURE_DATA),
                                  obj, "muzzle", zoom=1.0)
        self.assertAlmostEqual(dsx, 50.0)   # 100 * 0.5 fit * 1.0 scale * 1.0 zoom


if __name__ == "__main__":
    unittest.main()
