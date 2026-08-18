"""SD-3: the `x-widget: "sound_slot"` hook + SoundSlotWidget.

Driven by a PINNED fixture schema + doc written into the temp data/ copy, never
against live `data/` content (editor rule 2): the point is that the MARKER makes
the widget appear, so a fixture is both sufficient and drift-proof. No test
decodes audio and no test exec()s a dialog.
"""
import json
import unittest

from editor.panels.balancing import BalancingPanel
from editor.panels.sound_slot import SoundSlotWidget
from engine import data_io
from tools.tests.temp_data import TempDataCase

DOMAIN = "sndfix"
SLOT_PATH = "Group/attack"

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["Group"],
    "properties": {
        "Group": {
            "type": "object",
            "additionalProperties": False,
            "required": ["attack"],
            "properties": {"attack": {"$ref": "#/$defs/sound_slot"}},
        }
    },
    "$defs": {
        "sound_clip": {
            "type": "object",
            "additionalProperties": False,
            "required": ["end", "file", "start", "volume"],
            "properties": {
                "end": {"type": "number", "minimum": 0.0, "maximum": 3600.0},
                "file": {"type": "string"},
                "start": {"type": "number", "minimum": 0.0, "maximum": 3600.0},
                "volume": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "sound_slot": {
            "type": "object",
            "additionalProperties": False,
            "required": ["clips", "loop", "pick"],
            "x-widget": "sound_slot",
            "properties": {
                "clips": {"type": "array", "minItems": 0,
                          "items": {"$ref": "#/$defs/sound_clip"}},
                "loop": {"type": "boolean"},
                "pick": {"type": "string", "enum": ["random", "sequential"]},
            },
        },
    },
}

_DOC = {"Group": {"attack": {"clips": [], "loop": False, "pick": "random"}}}


class SoundSlotCase(TempDataCase):
    def setUp(self):
        super().setUp()
        (self.data_dir / "schemas" / f"{DOMAIN}.schema.json").write_text(
            json.dumps(_SCHEMA), encoding="utf-8")
        (self.data_dir / "balancing" / f"{DOMAIN}.json").write_text(
            json.dumps(_DOC), encoding="utf-8")

    def _panel(self):
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        panel.set_domain(DOMAIN)
        return panel

    def _widget(self, panel):
        return panel._widgets[SLOT_PATH]


class TestHook(SoundSlotCase):
    def test_marker_renders_a_sound_slot_widget(self):
        panel = self._panel()
        self.assertIsInstance(self._widget(panel), SoundSlotWidget)


class TestRoundTrip(SoundSlotCase):
    def test_loop_and_pick_stage_into_the_panel_doc(self):
        panel = self._panel()
        widget = self._widget(panel)
        widget._loop.setChecked(True)
        widget._pick.setCurrentIndex(widget._pick.findData("sequential"))
        staged = panel.staged_value(SLOT_PATH)
        self.assertTrue(staged["loop"])
        self.assertEqual(staged["pick"], "sequential")
        self.assertIn(SLOT_PATH, panel._dirty)

    def test_whole_slot_survives_set_widget_value(self):
        panel = self._panel()
        widget = self._widget(panel)
        restored = {"clips": [{"file": "imported/a.ogg", "volume": 0.5,
                               "start": 0.0, "end": 0.0}],
                    "loop": True, "pick": "sequential"}
        panel._set_widget_value(SLOT_PATH, widget, restored)
        self.assertEqual(widget.value(), restored)
        self.assertTrue(widget._loop.isChecked())

    def test_add_then_remove_clip_restructures_clips_and_validates(self):
        panel = self._panel()
        widget = self._widget(panel)
        widget.add_clip("imported/a.ogg")
        clips = panel.staged_value(SLOT_PATH)["clips"]
        self.assertEqual([c["file"] for c in clips], ["imported/a.ogg"])
        # The staged doc must still be schema-valid — the one write path.
        data_io.validate(panel._doc,
                         self.data_dir / "schemas" / f"{DOMAIN}.schema.json")
        widget.remove_clip(0)
        self.assertEqual(panel.staged_value(SLOT_PATH)["clips"], [])


class TestImportAndUsage(SoundSlotCase):
    def test_import_path_attaches_the_copied_clip(self):
        panel = self._panel()
        widget = self._widget(panel)
        src = self.data_dir / "src.ogg"
        src.write_bytes(b"\0" * 8)
        ref = widget.import_path(src)
        self.assertEqual(ref, "imported/src.ogg")
        self.assertEqual(
            panel.staged_value(SLOT_PATH)["clips"][0]["file"], ref)

    def test_sound_usage_docs_carries_the_live_staged_doc(self):
        panel = self._panel()
        self._widget(panel).add_clip("imported/a.ogg")
        docs = panel.sound_usage_docs()
        self.assertIs(docs[DOMAIN], panel._doc)
        from editor import sound_import
        users, _unknown = sound_import.clip_users(docs, "imported/a.ogg")
        self.assertIn(DOMAIN, users)


if __name__ == "__main__":
    unittest.main()
