"""Designer-authored ``custom_widgets`` (UL-13): the runtime half.

Bare minimum by design — this proves the feature and the two guards the brief
names, nothing more. Every case runs on an IN-MEMORY override doc through
``ScreenSkinning.from_overrides``, so no ``data/`` tree is read or written at
all (the suite's data tripwire can never fire from here) and no fixture is
inherited from whatever the artists last imported.

The golden parity pin (``test_ui_skinning.py::test_all_screens_parity``) is the
other half of the contract: no ``custom_widgets`` key ⇒ zero extra primitives.
It is not restated here.
"""
import unittest
from unittest import mock

from engine.render import HudRect, HudSprite, HudText
from game.ui import skinning as skinning_module
from game.ui.skinning import ScreenSkinning

SCREEN = "pause"


class RecordingRenderer:
    """Records every ``submit_hud`` call verbatim — the stand-in
    ``test_ui_skinning.py``/``test_ui_layer_draw.py`` already use."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


def _emit(doc, band="under"):
    """The HUD primitives ``submit_layers`` emits for ``doc`` in ``band``.

    ``ids`` is deliberately EMPTY: a custom widget has no game-side widget
    object, so the real-widget loop has nothing to iterate and everything
    recorded here came from the custom-widget tail.
    """
    renderer = RecordingRenderer()
    skinning = ScreenSkinning.from_overrides({SCREEN: doc})
    skinning.submit_layers(renderer, SCREEN, {}, band, skinning.state_of)
    return renderer.items


class CustomWidgetDrawTests(unittest.TestCase):

    def test_panel_draws_box_and_caption_in_its_band_only(self):
        doc = {
            "custom_widgets": {
                "deco_box": {"kind": "panel", "rect": [10, 20, 100, 40]},
            },
            "widgets": {"deco_box": {"color": [1, 2, 3], "label": "Hi"}},
        }
        items = _emit(doc, "under")
        self.assertEqual([type(i) for i in items], [HudRect, HudText])
        self.assertEqual(items[0], HudRect((10, 20, 100, 40), (1, 2, 3)))
        self.assertEqual(items[1].text, "Hi")
        self.assertEqual(items[1].align, "center")
        # band defaults to "under" (NOT a layer's "over") — a custom widget
        # is decoration and must never default on top of the screen's own
        # readouts — so the over pass draws nothing at all.
        self.assertEqual(_emit(doc, "over"), [])

    def test_panel_skin_falls_back_to_screen_panel_default(self):
        doc = {
            "defaults": {"panel_skin": "ui_panel"},
            "custom_widgets": {
                "deco_box": {"kind": "panel", "rect": [0, 0, 8, 8]},
            },
        }
        items = _emit(doc)
        self.assertEqual(items, [HudSprite("ui_panel", (0, 0), (8, 8))])

    def test_label_draws_one_text_and_an_empty_string_draws_nothing(self):
        doc = {
            "custom_widgets": {
                "cap": {"kind": "label", "rect": [5, 6, 0, 0]},
            },
            "widgets": {"cap": {"text_id": "some_id"}},
        }
        with mock.patch.object(skinning_module.strings, "T",
                               return_value="Words"):
            items = _emit(doc)
        self.assertEqual([type(i) for i in items], [HudText])
        self.assertEqual((items[0].text, items[0].pos), ("Words", (5, 6)))
        # An empty resolved string draws NOTHING, never a blank HudText.
        with mock.patch.object(skinning_module.strings, "T", return_value=""):
            self.assertEqual(_emit(doc), [])


class CustomWidgetOverrideTests(unittest.TestCase):

    def test_override_rect_wins_and_visible_false_suppresses(self):
        doc = {
            "custom_widgets": {
                "deco_box": {"kind": "backdrop", "rect": [0, 0, 4, 4]},
            },
            "widgets": {"deco_box": {"rect": [50, 60, 70, 80],
                                     "color": [9, 9, 9]}},
        }
        self.assertEqual(_emit(doc),
                         [HudRect((50, 60, 70, 80), (9, 9, 9))])
        doc["widgets"]["deco_box"]["visible"] = False
        self.assertEqual(_emit(doc), [])


class CustomWidgetValidationTests(unittest.TestCase):

    def test_validate_ids_accepts_a_custom_widget_id(self):
        """A custom id has no ``screen_defaults.json`` record by construction,
        so without the guard every screen carrying one raises at load."""
        doc = {
            "custom_widgets": {
                "deco_box": {"kind": "panel", "rect": [0, 0, 4, 4]},
            },
            "widgets": {"deco_box": {"color": [1, 1, 1]}},
        }
        skinning = ScreenSkinning.from_overrides({SCREEN: doc})
        skinning._defaults = {SCREEN: {"widgets": {"btn_resume": {}}}}
        skinning.apply(SCREEN, {})   # must not raise
        doc["widgets"]["typo_id"] = {"color": [1, 1, 1]}
        skinning = ScreenSkinning.from_overrides({SCREEN: doc})
        skinning._defaults = {SCREEN: {"widgets": {"btn_resume": {}}}}
        with self.assertRaises(ValueError):
            skinning.apply(SCREEN, {})


if __name__ == "__main__":
    unittest.main()
