"""Manifest v2 pure core (E-35/E-36/E-37) — no pygame, no Qt.

playback_order/parse_loop must be PROTOTYPE-EXACT (behavioral spec:
../HowToBeHuman/ClaudePrototype/HowToBeHuman src/core/sprite_manifest.py):
rows = animations, row 0 = idle (required), per-row fps, hidden frames
dropped AFTER loop expansion, loop = pre-roll + range*count + post-roll.
"""
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema.exceptions import ValidationError

from engine.assets import (
    Manifest,
    PLACEHOLDER,
    entry_from_dict,
    load_manifest,
    parse_loop,
    playback_order,
)
from engine.data_io import validate
from tools.tests.fixture_data import FIXTURE_DATA


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


class TestPlaybackOrder(unittest.TestCase):
    def test_no_loop_is_natural_order(self):
        self.assertEqual(playback_order(5, (), None), [0, 1, 2, 3, 4])

    def test_hidden_dropped(self):
        self.assertEqual(playback_order(5, {1, 3}, None), [0, 2, 4])

    def test_loop_expands_pre_range_post(self):
        # pre-roll [0], looped 1..2 x3, post-roll [3,4]
        self.assertEqual(playback_order(5, (), (1, 2, 3)),
                         [0, 1, 2, 1, 2, 1, 2, 3, 4])

    def test_hidden_dropped_after_expansion(self):
        # hidden index inside the looped range vanishes from EVERY repetition
        self.assertEqual(playback_order(5, {2}, (1, 2, 3)),
                         [0, 1, 1, 1, 3, 4])

    def test_degenerate_loop_start_after_end_is_natural_order(self):
        self.assertEqual(playback_order(5, (), (3, 1, 5)), [0, 1, 2, 3, 4])

    def test_loop_bounds_clamped(self):
        self.assertEqual(playback_order(3, (), (-2, 10, 2)),
                         [0, 1, 2, 0, 1, 2])

    def test_loop_count_clamped_to_one(self):
        self.assertEqual(playback_order(3, (), (0, 1, 0)), [0, 1, 2])

    def test_all_hidden_is_empty(self):
        self.assertEqual(playback_order(3, {0, 1, 2}, None), [])

    def test_out_of_range_hidden_ignored(self):
        self.assertEqual(playback_order(3, {7, -1}, None), [0, 1, 2])

    def test_hidden_none_means_none_hidden(self):
        self.assertEqual(playback_order(2, None, None), [0, 1])


class TestParseLoop(unittest.TestCase):
    def test_missing_fields_inactive(self):
        self.assertIsNone(parse_loop({}))
        self.assertIsNone(parse_loop({"loop_start": 0, "loop_count": 3}))
        self.assertIsNone(parse_loop({"loop_end": 2, "loop_count": 3}))

    def test_count_one_inactive(self):
        self.assertIsNone(parse_loop(row(loop=(0, 2, 1))))

    def test_active_loop(self):
        self.assertEqual(parse_loop(row(loop=(1, 3, 2))), (1, 3, 2))

    def test_start_after_end_inactive(self):
        self.assertIsNone(parse_loop(row(loop=(3, 1, 5))))

    def test_negative_start_inactive(self):
        self.assertIsNone(parse_loop(row(loop=(-1, 2, 2))))


class TestEntryFromDict(unittest.TestCase):
    def test_fps_to_duration(self):
        e = entry_dict([row(fps=12)])
        track = entry_from_dict("s", e).animations["idle"]
        self.assertEqual(track.timeline[0][1], 83)   # round(1000/12)
        self.assertEqual(track.total_ms, 3 * 83)

    def test_fps_missing_or_zero_defaults_to_eight(self):
        raw = entry_dict([row()])
        del raw["rows"][0]["fps"]
        self.assertEqual(entry_from_dict("s", raw).animations["idle"].timeline[0][1], 125)
        self.assertEqual(
            entry_from_dict("s", entry_dict([row(fps=0)])).animations["idle"].timeline[0][1],
            125)

    def test_row_index_is_sheet_band(self):
        e = entry_from_dict("s", entry_dict([row(), row("attack", frames=2)]))
        self.assertEqual(e.animations["idle"].row, 0)
        self.assertEqual(e.animations["attack"].row, 1)

    def test_tolerant_row_defaults(self):
        raw = entry_dict([{"animation": "idle", "frames": 2}])
        track = entry_from_dict("s", raw).animations["idle"]
        self.assertEqual([c for c, _ in track.timeline], [0, 1])

    def test_offsets_carried(self):
        e = entry_from_dict("s", entry_dict([row()], offset_x=3, offset_y=-8))
        self.assertEqual((e.offset_x, e.offset_y), (3, -8))

    def test_all_hidden_row_not_stored(self):
        e = entry_from_dict(
            "s", entry_dict([row(), row("attack", frames=2, hidden=(0, 1))]))
        self.assertNotIn("attack", e.animations)
        self.assertIn("idle", e.animations)

    def test_duplicate_animation_later_row_wins(self):
        e = entry_from_dict(
            "s", entry_dict([row(), row("attack", frames=2), row("attack", frames=4)]))
        self.assertEqual(e.animations["attack"].row, 2)
        self.assertEqual(len(e.animations["attack"].timeline), 4)

    def test_missing_frames_raises(self):
        raw = entry_dict([{"animation": "idle", "fps": 8}])
        with self.assertRaises(ValueError):
            entry_from_dict("s", raw)

    def test_row_zero_not_idle_raises(self):
        with self.assertRaises(ValueError):
            entry_from_dict("s", entry_dict([row("attack")]))

    def test_no_rows_raises(self):
        with self.assertRaises(ValueError):
            entry_from_dict("s", entry_dict([]))

    def test_missing_sheet_raises(self):
        raw = entry_dict([row()])
        del raw["sheet"]
        with self.assertRaises(ValueError):
            entry_from_dict("s", raw)

    def test_everything_hidden_raises(self):
        with self.assertRaises(ValueError):
            entry_from_dict("s", entry_dict([row(hidden=(0, 1, 2))]))

    def test_slice_parsed_as_int_tuple(self):
        raw = entry_dict([row()])
        raw["slice"] = [1, 2, 3, 4]
        self.assertEqual(entry_from_dict("s", raw).slice, (1, 2, 3, 4))

    def test_slice_absent_is_none(self):
        self.assertIsNone(entry_from_dict("s", entry_dict([row()])).slice)

    def test_bad_slice_raises(self):
        # wrong length, negative, non-numeric, and a bare string (which would
        # otherwise iterate into four plausible-looking margins)
        for bad in ([1, 2, 3], [1, 2, 3, 4, 5], [1, -2, 3, 4], ["a", "b", "c", "d"],
                    "1234", 4):
            raw = entry_dict([row()])
            raw["slice"] = bad
            with self.subTest(slice=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)

    def test_bad_slice_is_warn_and_skip_through_load_manifest(self):
        # entry_from_dict raises; load_manifest is the E-37 tolerance layer
        doc = {"version": 2, "entries": {"bad": entry_dict([row()])}}
        doc["entries"]["bad"]["slice"] = [1, 2, 3]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "asset_manifest.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)
        self.assertEqual(m.slots(), ())

    def test_row_start_absent_is_zero(self):
        self.assertEqual(entry_from_dict("s", entry_dict([row()])).row_start, 0)

    def test_row_start_parsed(self):
        raw = entry_dict([row()])
        raw["row_start"] = 3
        e = entry_from_dict("s", raw)
        self.assertEqual(e.row_start, 3)
        # the window is a SLICING concern: row indices above it are unchanged
        self.assertEqual(e.animations["idle"].row, 0)

    def test_bad_row_start_raises(self):
        # bool (an int subclass), float, numeric string, and negative — none
        # may be coerced into a row the designer never authored
        for bad in (True, 3.7, "3", -1, None, [3]):
            raw = entry_dict([row()])
            raw["row_start"] = bad
            with self.subTest(row_start=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)

    def test_column_keys_absent_default(self):
        e = entry_from_dict("s", entry_dict([row()]))
        self.assertEqual((e.column, e.column_mode, e.column_width),
                         (0, "manual", 0))

    def test_column_keys_parsed(self):
        raw = entry_dict([row()])
        raw["column"] = 2
        raw["column_mode"] = "season"
        raw["column_width"] = 4
        e = entry_from_dict("s", raw)
        self.assertEqual((e.column, e.column_mode, e.column_width),
                         (2, "season", 4))
        # the window is a SLICING concern: row indices above it are unchanged
        self.assertEqual(e.animations["idle"].row, 0)

    def test_bad_column_raises(self):
        for bad in (True, 3.7, "3", -1, None, [3]):
            raw = entry_dict([row()])
            raw["column"] = bad
            with self.subTest(column=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)

    def test_bad_column_width_raises(self):
        for bad in (True, 3.7, "3", -1, None, [3], 0):
            raw = entry_dict([row()])
            raw["column_width"] = bad
            with self.subTest(column_width=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)

    def test_bad_column_mode_raises(self):
        for bad in ("seasonal", 1, None):
            raw = entry_dict([row()])
            raw["column_mode"] = bad
            with self.subTest(column_mode=bad), self.assertRaises(ValueError):
                entry_from_dict("s", raw)


class TestCurrentFrame(unittest.TestCase):
    def manifest(self):
        e = entry_from_dict("tower", entry_dict(
            [row(frames=3, fps=8), row("attack", frames=2, fps=4)]))
        return Manifest({"tower": e})

    def test_time_walk(self):
        m = self.manifest()   # idle durs 125ms, total 375
        self.assertEqual(m.current_frame("tower", "idle", 0), (0, 0))
        self.assertEqual(m.current_frame("tower", "idle", 130), (0, 1))
        self.assertEqual(m.current_frame("tower", "idle", 380), (0, 0))  # wrap

    def test_phase_offsets_time(self):
        m = self.manifest()
        self.assertEqual(m.current_frame("tower", "idle", 0, phase_ms=130), (0, 1))

    def test_other_row_resolves_with_its_band(self):
        m = self.manifest()   # attack durs 250ms
        self.assertEqual(m.current_frame("tower", "attack", 0), (1, 0))
        self.assertEqual(m.current_frame("tower", "attack", 260), (1, 1))

    def test_single_frame_short_circuits(self):
        e = entry_from_dict("s", entry_dict([row(frames=1)]))
        m = Manifest({"s": e})
        self.assertEqual(m.current_frame("s", "idle", 99999), (0, 0))

    def test_loop_expanded_timeline_timing(self):
        e = entry_from_dict("s", entry_dict([row(frames=3, fps=8, loop=(0, 1, 2))]))
        m = Manifest({"s": e})
        # order [0,1,0,1,2] at 125ms each; t=300 sits in the third slot (col 0)
        self.assertEqual(m.current_frame("s", "idle", 300), (0, 0))
        self.assertEqual(m.current_frame("s", "idle", 550), (0, 2))

    def test_missing_animation_falls_back_to_idle(self):
        m = self.manifest()
        self.assertEqual(m.current_frame("tower", "death", 130), (0, 1))

    def test_missing_slot_is_placeholder_sentinel(self):
        m = self.manifest()
        self.assertIs(m.current_frame("nope", "idle", 0), PLACEHOLDER)

    def test_idle_missing_too_is_placeholder(self):
        # idle row fully hidden -> only attack stored; unknown anim -> idle ->
        # missing -> PLACEHOLDER (never raises)
        e = entry_from_dict("s", entry_dict(
            [row(hidden=(0, 1, 2)), row("attack", frames=2)]))
        m = Manifest({"s": e})
        self.assertIs(m.current_frame("s", "death", 0), PLACEHOLDER)
        self.assertEqual(m.current_frame("s", "attack", 0), (1, 0))


class TestCurrentFrameExtraHidden(unittest.TestCase):
    """feature-enemy-intro-dialogue: a per-CALL frame-column narrowing on top
    of whatever the manifest row's own `hidden` already dropped."""

    def manifest(self):
        e = entry_from_dict("s", entry_dict([row(frames=4, fps=8)]))
        return Manifest({"s": e})

    def test_no_extra_hidden_is_unaffected(self):
        m = self.manifest()
        self.assertEqual(m.current_frame("s", "idle", 0, extra_hidden=None), (0, 0))
        self.assertEqual(m.current_frame("s", "idle", 0, extra_hidden=()), (0, 0))

    def test_extra_hidden_removes_a_column_from_the_walk(self):
        m = self.manifest()   # durs 125ms each; without extra_hidden: 0,1,2,3
        self.assertEqual(m.current_frame("s", "idle", 0, extra_hidden={1}),
                         (0, 0))
        self.assertEqual(m.current_frame("s", "idle", 130, extra_hidden={1}),
                         (0, 2))   # column 1 skipped, next up is column 2

    def test_extra_hidden_unions_with_baked_hidden_never_widens(self):
        # manifest already hides column 0; extra_hidden narrows further to {2,3}
        e = entry_from_dict("s", entry_dict([row(frames=4, fps=8, hidden=(0,))]))
        m = Manifest({"s": e})
        self.assertEqual(m.current_frame("s", "idle", 0, extra_hidden={1}),
                         (0, 2))
        # extra_hidden naming an ALREADY-hidden column changes nothing (union,
        # not an override) — column 0 was never coming back
        self.assertEqual(
            m.current_frame("s", "idle", 0, extra_hidden={0}),
            m.current_frame("s", "idle", 0, extra_hidden=None))

    def test_hiding_every_frame_degrades_to_unfiltered(self):
        m = self.manifest()
        # extra_hidden covering the whole timeline would leave nothing to
        # play — falls back to the unfiltered timeline rather than raising
        # or resolving to nothing.
        self.assertEqual(
            m.current_frame("s", "idle", 0, extra_hidden={0, 1, 2, 3}),
            m.current_frame("s", "idle", 0, extra_hidden=None))

    def test_single_remaining_frame_short_circuits(self):
        m = self.manifest()
        self.assertEqual(
            m.current_frame("s", "idle", 99999, extra_hidden={0, 1, 2}),
            (0, 3))


class TestManifestOverride(unittest.TestCase):
    def test_override_returns_new_manifest(self):
        base = Manifest()
        e = entry_from_dict("s", entry_dict([row()]))
        drafted = base.override("s", e)
        self.assertIsNone(base.entry("s"))
        self.assertIs(drafted.entry("s"), e)

    def test_override_with_none_removes(self):
        e = entry_from_dict("s", entry_dict([row()]))
        m = Manifest({"s": e}).override("s", None)
        self.assertIsNone(m.entry("s"))
        self.assertEqual(m.slots(), ())


class TestLoadManifestTolerance(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "asset_manifest.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_absent_file_is_empty_manifest(self):
        m = load_manifest(Path(tempfile.gettempdir()) / "does_not_exist_5x" / "m.json")
        self.assertEqual(m.slots(), ())

    def test_garbage_logs_and_returns_empty(self):
        path = self.write("{not json!!")
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)
        self.assertEqual(m.slots(), ())

    def test_wrong_version_logs_and_returns_empty(self):
        path = self.write(json.dumps({"version": 1, "entries": {}}))
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)
        self.assertEqual(m.slots(), ())

    def test_corrupt_entry_skipped_valid_kept(self):
        doc = {"version": 2, "entries": {
            "good": entry_dict([row()]),
            "bad": {"sheet": 5},
        }}
        path = self.write(json.dumps(doc))
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)
        self.assertEqual(m.slots(), ("good",))
        self.assertEqual(m.current_frame("good", "idle", 0), (0, 0))

    def test_valid_manifest_loads_silently(self):
        doc = {"version": 2, "entries": {"good": entry_dict([row()])}}
        m = load_manifest(self.write(json.dumps(doc)))
        self.assertEqual(m.slots(), ("good",))

    def test_corrupt_row_start_warns_and_skips_that_entry(self):
        bad = entry_dict([row()])
        bad["row_start"] = "3"
        doc = {"version": 2, "entries": {
            "good": entry_dict([row()]),
            "bad": bad,
        }}
        path = self.write(json.dumps(doc))
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)   # warn + skip, never raise (E-37)
        self.assertEqual(m.slots(), ("good",))

    def test_corrupt_column_mode_warns_and_skips_that_entry(self):
        bad = entry_dict([row()])
        bad["column_mode"] = "seasonal"
        doc = {"version": 2, "entries": {
            "good": entry_dict([row()]),
            "bad": bad,
        }}
        path = self.write(json.dumps(doc))
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            m = load_manifest(path)   # warn + skip, never raise (E-37)
        self.assertEqual(m.slots(), ("good",))


class TestMasterSheetSchemas(unittest.TestCase):
    """M1 (GpuAndMasterSheetsPLAN): the master-sheet registry + row_start.

    Schemas come from the PINNED snapshot, never live ``data/`` — this module
    is not on ``test_fixture_guard``'s live-data allowlist. Validation is
    read-only, so nothing here writes anywhere. Every assertion is about a
    document this test itself builds; no live/fixture CONTENT is asserted on.
    """

    MASTER = FIXTURE_DATA / "schemas" / "master_sheets.schema.json"
    MANIFEST = FIXTURE_DATA / "schemas" / "asset_manifest.schema.json"

    @staticmethod
    def registry(entries):
        return {"version": 1, "entries": entries}

    @staticmethod
    def sheet_entry(**over):
        e = {"file": "master/characters.png", "display_name": "Characters",
             "frame_w": 64, "frame_h": 96, "column_width": 4}
        e.update(over)
        return e

    # --- registry ---------------------------------------------------------
    def test_seeded_registry_validates(self):
        validate({"version": 1, "entries": {}}, self.MASTER)

    def test_bad_file_path_rejected(self):
        for bad in ("imported/characters.png", "master/Characters.png",
                    "characters.png"):
            with self.subTest(file=bad), self.assertRaises(ValidationError):
                validate(self.registry({"characters": self.sheet_entry(file=bad)}),
                         self.MASTER)

    def test_bad_sheet_id_rejected(self):
        for bad in ("1bad", "Bad-Id", "_lead"):
            with self.subTest(sheet_id=bad), self.assertRaises(ValidationError):
                validate(self.registry({bad: self.sheet_entry()}), self.MASTER)

    def test_missing_frame_w_rejected(self):
        entry = self.sheet_entry()
        del entry["frame_w"]
        with self.assertRaises(ValidationError):
            validate(self.registry({"characters": entry}), self.MASTER)

    # --- registry columns (C1) -------------------------------------------
    def test_column_width_without_names_validates(self):
        # D1/D4: the width is required, the per-column names are not.
        validate(self.registry({"characters": self.sheet_entry()}), self.MASTER)

    def test_missing_column_width_rejected(self):
        entry = self.sheet_entry()
        del entry["column_width"]
        with self.assertRaises(ValidationError):
            validate(self.registry({"characters": entry}), self.MASTER)

    def test_out_of_range_column_width_rejected(self):
        for bad in (0, 257):
            with self.subTest(column_width=bad), self.assertRaises(ValidationError):
                validate(self.registry(
                    {"characters": self.sheet_entry(column_width=bad)}), self.MASTER)

    def test_bad_column_names_rejected(self):
        for bad in (["red", "red"], ["Red"]):
            with self.subTest(columns=bad), self.assertRaises(ValidationError):
                validate(self.registry(
                    {"characters": self.sheet_entry(columns=bad)}), self.MASTER)

    # --- manifest ---------------------------------------------------------
    def test_entry_without_row_start_and_master_sheet_both_validate(self):
        doc = {"version": 2, "entries": {
            "legacy": entry_dict([row()]),          # no row_start, no column keys
            "windowed": dict(entry_dict([row()], sheet="master/characters.png"),
                             row_start=4),
        }}
        validate(doc, self.MANIFEST)

    def test_negative_row_start_rejected(self):
        entry = dict(entry_dict([row()], sheet="master/characters.png"),
                     row_start=-1)
        with self.assertRaises(ValidationError):
            validate({"version": 2, "entries": {"windowed": entry}}, self.MANIFEST)

    def test_bad_column_keys_rejected(self):
        for bad in ({"column": -1}, {"column_mode": "seasonal"},
                    {"column_width": 0}):
            entry = dict(entry_dict([row()], sheet="master/characters.png"), **bad)
            with self.subTest(**bad), self.assertRaises(ValidationError):
                validate({"version": 2, "entries": {"windowed": entry}},
                         self.MANIFEST)


if __name__ == "__main__":
    unittest.main()
