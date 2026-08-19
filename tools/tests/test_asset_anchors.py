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
from game.anchors import anchor_world_point


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

    def test_with_every_declared_anchor_validates_parses_and_reserialises(self):
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
# game.anchors — the pure world-point resolver (fix-anchor-origin-parity;
# supersedes ESV-1's `screen_offset`/`world_offset` delta pair)
# ---------------------------------------------------------------------------
def _store_and_obj(anchor_xy=None, frame_w=64, frame_h=64, fit_tiles=1.0,
                   scale=1.0, wx=3.0, wy=2.0, offset_xy=(0, 0)):
    raw = entry_dict([row()], frame_w=frame_w, frame_h=frame_h,
                     offset_x=offset_xy[0], offset_y=offset_xy[1])
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
    """§2.4: every layer degrades to `None` (the caller's cue to fall back
    to its own pre-anchor point), never a special case."""

    def test_no_store_no_cs_no_obj_no_anchor_all_none(self):
        store, obj = _store_and_obj(anchor_xy=None)
        cs = load_coordinate_system(FIXTURE_DATA)
        self.assertIsNone(anchor_world_point(None, cs, obj, "muzzle"))
        self.assertIsNone(anchor_world_point(store, None, obj, "muzzle"))
        self.assertIsNone(anchor_world_point(store, cs, None, "muzzle"))
        self.assertIsNone(anchor_world_point(store, cs, obj, "muzzle"))

    def test_bare_object_with_no_sprite_animator_is_none(self):
        cs = load_coordinate_system(FIXTURE_DATA)
        obj = GameObject(transform=Transform(wx=1.0, wy=0.0))
        store, _ = _store_and_obj((18, -40))
        self.assertIsNone(anchor_world_point(store, cs, obj, "muzzle"))

    def test_explicit_zero_anchor_resolves_to_the_drawn_centre_not_none(self):
        """fix-anchor-origin-parity: a `[0, 0]` anchor is PRESENT data (the
        sprite's drawn centre), not absence — it must resolve to a real
        point, never `None` and never the object's raw `transform.world_pos`
        (the old, buggy short-circuit this replaced). At `fit_tiles=1.0`
        (no footprint fit) and no manifest offset, the drawn centre is
        exactly `(wx + 0.5, wy + 0.5)` — the tile-diamond-centre shift the
        old base point (`world_pos` itself) was missing — independently
        derivable from `world_to_screen`'s iso identity, not from
        `anchor_world_point` itself."""
        store, obj = _store_and_obj((0, 0), wx=3.0, wy=2.0)
        cs = load_coordinate_system(FIXTURE_DATA)
        point = anchor_world_point(store, cs, obj, "muzzle")
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 3.5, places=9)
        self.assertAlmostEqual(point[1], 2.5, places=9)


class TestAnchorWorldPointInvariance(unittest.TestCase):
    """D2, restated for the world-POINT resolver: `anchor_world_point`
    returns an absolute WORLD point, so — unlike the old delta pair — it is
    not merely invariant under zoom/pan, it is IDENTICAL: `world_to_screen`/
    `screen_to_world` are exact inverses at whatever zoom/pan `cs` currently
    carries, so the round trip lands back on the same world point regardless
    of the camera state it was resolved under."""

    def test_same_at_two_very_different_zoom_levels(self):
        store, obj = _store_and_obj((18, -40))
        cs = load_coordinate_system(FIXTURE_DATA)
        results = []
        for zoom in (1.0, 2.0):
            cs.camera.zoom = zoom
            results.append(anchor_world_point(store, cs, obj, "muzzle"))
        self.assertAlmostEqual(results[0][0], results[1][0], places=6)
        self.assertAlmostEqual(results[0][1], results[1][1], places=6)
        # and it is not the degenerate centre point — the anchor really
        # moved it off (wx + 0.5, wy + 0.5)
        self.assertNotAlmostEqual(results[0][0], 3.5, places=3)

    def test_same_under_pan(self):
        store, obj = _store_and_obj((18, -40))
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        before = anchor_world_point(store, cs, obj, "muzzle")
        cs.camera.pan_x, cs.camera.pan_y = 321.0, -654.0
        after = anchor_world_point(store, cs, obj, "muzzle")
        self.assertAlmostEqual(before[0], after[0], places=6)
        self.assertAlmostEqual(before[1], after[1], places=6)

    def test_anchor_scales_with_the_footprint_fit(self):
        """The muzzle anchor rides the SAME `fit_factor` the renderer uses
        (§1.3) — a downscaled unit's anchor shrinks with it, never the raw
        sheet-pixel value. Compared in SCREEN space (`cs.world_to_screen` of
        each resolved world point) against the `(0, 0)`-anchor (drawn
        centre) baseline, since the fit only ever scales a screen-pixel
        delta, never the raw world coordinate."""
        cs = load_coordinate_system(FIXTURE_DATA)
        # Pin the zoom: this asserts a hand-computed SCREEN delta, and
        # `Camera.zoom`'s dataclass default is a live tunable (it moved
        # 1.0 -> 2.0 with the camera-zoom balancing change), so inheriting
        # it would silently scale the expected 50.0 below.
        cs.set_zoom(1.0)
        # frame_w 128 on a 64-wide tile with fit_tiles=1 halves the draw.
        centre_store, centre_obj = _store_and_obj((0, 0), frame_w=128, fit_tiles=1.0)
        anchored_store, anchored_obj = _store_and_obj((100, 0), frame_w=128, fit_tiles=1.0)
        centre_sx, centre_sy = cs.world_to_screen(
            *anchor_world_point(centre_store, cs, centre_obj, "muzzle"))
        anchored_sx, anchored_sy = cs.world_to_screen(
            *anchor_world_point(anchored_store, cs, anchored_obj, "muzzle"))
        self.assertAlmostEqual(anchored_sx - centre_sx, 50.0)   # 100 * 0.5 fit * 1.0 scale * 1.0 zoom
        self.assertAlmostEqual(anchored_sy - centre_sy, 0.0)


# ---------------------------------------------------------------------------
# fix-anchor-offset-and-bullet-sprites Fix 1: offset/anchor composition
# ---------------------------------------------------------------------------
class TestAssetStoreOffsetAccessor(unittest.TestCase):
    """`AssetStore.offset` mirrors `anchor()`'s degrade-never-raise shape."""

    def test_absent_slot_is_zero(self):
        store = AssetStore(manifest=Manifest({}), sprites_dir=None)
        self.assertEqual(store.offset("nope"), (0, 0))

    def test_present_entry_returns_ints(self):
        store, _obj = _store_and_obj(offset_xy=(3, -7))
        self.assertEqual(store.offset("thing"), (3, -7))

    def test_no_offset_authored_is_zero(self):
        store, _obj = _store_and_obj()
        self.assertEqual(store.offset("thing"), (0, 0))


class TestOffsetAnchorComposition(unittest.TestCase):
    """§1.2/§1.3: `offset_x`/`offset_y` fold into the anchor origin — the
    renderer already applies this nudge to the drawn art
    (`engine/render/renderer.py:138-139`), so the game-side anchor resolver
    must agree with it. Compared in SCREEN space (via `cs.world_to_screen`
    of the resolved world point) since the composed offset is authored in
    frame pixels, not world-fractional-tile units."""

    def test_composition_shifts_the_resolved_screen_point_exactly(self):
        """A fixture entry with `offset_y: 8` and `muzzle: [0, -20]` resolves
        8 frame-px lower (scaled) than the identical entry with no offset —
        the exact composed number, not just a direction."""
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        store_plain, obj_plain = _store_and_obj((0, -20), frame_w=64,
                                                 fit_tiles=1.0)
        store_nudged, obj_nudged = _store_and_obj((0, -20), frame_w=64,
                                                   fit_tiles=1.0,
                                                   offset_xy=(0, 8))
        sx0, sy0 = cs.world_to_screen(
            *anchor_world_point(store_plain, cs, obj_plain, "muzzle"))
        sx1, sy1 = cs.world_to_screen(
            *anchor_world_point(store_nudged, cs, obj_nudged, "muzzle"))
        # frame_w=64 on a 64-wide tile at fit_tiles=1.0 -> s == 1.0, so the
        # nudged result is exactly 8.0 lower (more positive screen y) than
        # the un-nudged one, and offset_x (0 in both) leaves x untouched.
        self.assertAlmostEqual(sy1 - sy0, 8.0)
        self.assertAlmostEqual(sx0, sx1)

    def test_nonzero_offset_with_no_anchors_is_still_none(self):
        """§1.2's byte-identity pin, restated for the `None`-degrade
        contract: an entry with a non-zero offset and NO `anchors` still
        resolves to `None` — the `anchor is None` early return fires before
        the offset is ever read, which is what keeps every un-anchored entry
        (181 of them) numerically untouched by this fix (its caller falls
        back to its own pre-anchor point, unchanged)."""
        cs = load_coordinate_system(FIXTURE_DATA)
        store, obj = _store_and_obj(anchor_xy=None, offset_xy=(0, 8))
        self.assertIsNone(anchor_world_point(store, cs, obj, "muzzle"))

    def test_zero_anchor_on_a_nudged_entry_is_the_offset_shifted_centre(self):
        """An anchor authored at `[0, 0]` on a NUDGED entry resolves to the
        drawn centre shifted by the composed offset ALONE — not the plain
        (un-nudged) drawn centre — matching the renderer's own nudge."""
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        plain_store, plain_obj = _store_and_obj((0, 0), frame_w=64,
                                                 fit_tiles=1.0)
        nudged_store, nudged_obj = _store_and_obj((0, 0), frame_w=64,
                                                   fit_tiles=1.0,
                                                   offset_xy=(0, 8))
        sx0, sy0 = cs.world_to_screen(
            *anchor_world_point(plain_store, cs, plain_obj, "muzzle"))
        sx1, sy1 = cs.world_to_screen(
            *anchor_world_point(nudged_store, cs, nudged_obj, "muzzle"))
        self.assertAlmostEqual(sx1, sx0)
        self.assertAlmostEqual(sy1 - sy0, 8.0)


if __name__ == "__main__":
    unittest.main()
