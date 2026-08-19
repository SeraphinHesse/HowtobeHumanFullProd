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


def _emit_in_view(doc, view, band="under"):
    """`_emit`, for a screen whose `submit()` names which VIEW is showing."""
    renderer = RecordingRenderer()
    skinning = ScreenSkinning.from_overrides({SCREEN: doc})
    skinning.submit_layers(renderer, SCREEN, {}, band, skinning.state_of,
                           view=view)
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


class CustomWidgetViewTests(unittest.TestCase):
    """A `view` scopes a custom widget to ONE of the screen's views.

    Without it a screen ID is not a screen: `building_panel` is five modes
    plus two modals that all declare the same id, so a decoration authored
    for the build list also landed on the unlock and upgrade panels and on
    top of an open preview.
    """

    DOC = {
        "custom_widgets": {
            "scoped": {"band": "under", "kind": "panel", "rect": [0, 0, 4, 4],
                       "view": "construct"},
            "everywhere": {"band": "under", "kind": "panel",
                           "rect": [8, 0, 4, 4]},
        },
        "widgets": {"scoped": {"color": [255, 0, 0]},
                    "everywhere": {"color": [0, 255, 0]}},
    }

    def _colors(self, items):
        return {tuple(i.color) for i in items if isinstance(i, HudRect)}

    def test_a_scoped_widget_draws_only_in_its_own_view(self):
        self.assertEqual(self._colors(_emit_in_view(self.DOC, "construct")),
                         {(255, 0, 0), (0, 255, 0)})
        self.assertEqual(self._colors(_emit_in_view(self.DOC, "upgrade")),
                         {(0, 255, 0)})

    def test_no_view_from_the_caller_filters_nothing(self):
        """A single-view screen passes none, and must keep every widget —
        including one a hand-edited doc scoped to a view it does not have."""
        self.assertEqual(self._colors(_emit(self.DOC)),
                         {(255, 0, 0), (0, 255, 0)})


class CustomWidgetHiddenTests(unittest.TestCase):
    """`hidden_customs`: the CALLER drops a custom widget for this frame
    only — the live-state gate the doc cannot express (a plate sized to back
    N stat rows, on a building with fewer)."""

    DOC = {
        "custom_widgets": {
            "plate": {"kind": "panel", "rect": [0, 0, 4, 4]},
            "other": {"kind": "panel", "rect": [8, 0, 4, 4]},
        },
        "widgets": {"plate": {"color": [255, 0, 0]},
                    "other": {"color": [0, 255, 0]}},
    }

    def _emit_hidden(self, hidden):
        renderer = RecordingRenderer()
        skinning = ScreenSkinning.from_overrides({SCREEN: self.DOC})
        skinning.submit_layers(renderer, SCREEN, {}, "under",
                               skinning.state_of, hidden_customs=hidden)
        return {tuple(i.color) for i in renderer.items
                if isinstance(i, HudRect)}

    def test_a_hidden_name_drops_only_that_widget(self):
        self.assertEqual(self._emit_hidden({"plate"}), {(0, 255, 0)})

    def test_the_default_hides_nothing(self):
        self.assertEqual(self._emit_hidden(()), {(255, 0, 0), (0, 255, 0)})

    def test_hiding_a_parent_keeps_its_children(self):
        """`parent` is an EDIT-time relationship (`editor/widget_tree.py`:
        nothing in `game/` reads it), so dropping a plate must never take the
        widgets authored inside it with it — only the plate goes."""
        doc = {
            "custom_widgets": {
                "plate": {"kind": "panel", "rect": [0, 0, 40, 40]},
                "inner": {"kind": "panel", "rect": [4, 4, 8, 8]},
            },
            "widgets": {"plate": {"color": [255, 0, 0]},
                        "inner": {"color": [0, 0, 255], "parent": "plate"}},
        }
        renderer = RecordingRenderer()
        skinning = ScreenSkinning.from_overrides({SCREEN: doc})
        skinning.submit_layers(renderer, SCREEN, {}, "under",
                               skinning.state_of, hidden_customs={"plate"})
        self.assertEqual([i for i in renderer.items if isinstance(i, HudRect)],
                         [HudRect((4, 4, 8, 8), (0, 0, 255))])


class BuildingPanelStatBackdropTests(unittest.TestCase):
    """`BuildingUI._hidden_stat_backdrops` — the rule that feeds it: a plate
    cut for N stat rows is dropped on a building with fewer."""

    def test_threshold_per_plate(self):
        from game.ui import building_ui

        def hidden(rows):
            panel = building_ui.BuildingUI.__new__(building_ui.BuildingUI)
            panel.mode, panel._selected = "upgrade", object()
            with mock.patch.object(building_ui, "_building_stats",
                                   return_value=[("k", 0)] * rows):
                return panel._hidden_stat_backdrops()

        self.assertEqual(hidden(5), frozenset())
        self.assertEqual(hidden(4), frozenset({"custom_panel_19"}))
        self.assertEqual(hidden(3),
                         frozenset({"custom_panel_19", "custom_panel_16"}))
        self.assertEqual(hidden(2),
                         frozenset({"custom_panel_19", "custom_panel_16",
                                    "custom_panel_17"}))

    def test_no_selection_hides_nothing(self):
        from game.ui import building_ui

        panel = building_ui.BuildingUI.__new__(building_ui.BuildingUI)
        panel.mode, panel._selected = "construct", None
        self.assertEqual(panel._hidden_stat_backdrops(), frozenset())


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


class CustomWidgetAnimationTests(unittest.TestCase):
    """A custom widget rides the owning screen's clock (bugfix): it used to
    emit ``anim_time_ms=0`` unconditionally, so a multi-frame idle sheet
    froze on frame 0 while every code-owned panel on the same screen played."""

    def test_panel_skin_and_layer_carry_the_screens_anim_clock(self):
        doc = {
            "custom_widgets": {
                "deco_box": {"kind": "panel", "rect": [0, 0, 4, 4]},
            },
            "widgets": {
                "deco_box": {
                    "skin": "ui_panel",
                    "layers": [{"slot": "ui_panel_v2", "band": "under"}],
                },
            },
        }
        renderer = RecordingRenderer()
        skinning = ScreenSkinning.from_overrides({SCREEN: doc})
        skinning.submit_layers(renderer, SCREEN, {}, "under",
                               skinning.state_of, 1234)
        sprites = [i for i in renderer.items if isinstance(i, HudSprite)]
        self.assertEqual([s.slot_key for s in sprites],
                         ["ui_panel", "ui_panel_v2"])
        self.assertEqual([s.anim_time_ms for s in sprites], [1234, 1234])
        self.assertEqual([s.animation for s in sprites], ["idle", "idle"])


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
