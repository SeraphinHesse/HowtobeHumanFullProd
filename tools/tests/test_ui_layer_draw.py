"""``ScreenSkinning.submit_layers`` — the drawing half of layered widgets (UL-4).

UL-3 shipped the pure resolver (``engine/ui_layers.py``, covered by
``test_ui_layers.py``); this module covers the CALLER: which HUD primitive one
resolved layer becomes, in what order the two bands submit, and the D2
"a layer follows its owner" property once ``apply()`` has moved the owner.

The golden-parity half (D5 — no ``layers`` authored anywhere means ZERO
primitives, so ``test_ui_skinning.py``'s baselines stay byte-identical) is
pinned here by ``test_no_layers_emits_nothing`` and by that file itself.

Headless, no pygame, no disk: ``ScreenSkinning.from_overrides`` takes an
in-memory ``{screen_id: doc}`` map, the widgets are ``SimpleNamespace``s with a
``.rect`` (all ``submit_layers`` reads off a widget), and the renderer is the
``RecordingRenderer`` stand-in ``test_ui_skinning.py`` uses.
"""
import unittest
from types import SimpleNamespace

from engine.render import HudRect, HudSprite, HudText
from game.ui import strings
from game.ui.skinning import ScreenSkinning

SCREEN = "hud"
OWNER_RECT = (10, 20, 30, 40)


class RecordingRenderer:
    """Records every ``submit_hud`` call verbatim (the same stand-in
    ``tools/tests/test_ui_skinning.py`` uses)."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


def _skinning(widget_spec):
    return ScreenSkinning.from_overrides(
        {SCREEN: {"widgets": {"love_text": widget_spec}}})


def _ids(rect=OWNER_RECT):
    widget = SimpleNamespace(rect=rect)
    return {"love_text": ("label", widget)}, widget


def _idle(_widget):
    return "idle"


class TestBandsAndOrder(unittest.TestCase):
    """One call per band; ``z`` orders WITHIN a band (D4)."""

    def setUp(self):
        self.skinning = _skinning({"layers": [
            {"id": "over_top", "band": "over", "z": 5,
             "offset": [0, 0, 0, 0], "color": [1, 1, 1]},
            {"id": "under_late", "band": "under", "z": 2,
             "offset": [1, 1, 0, 0], "color": [2, 2, 2]},
            {"id": "under_early", "band": "under", "z": 0,
             "offset": [2, 2, 0, 0], "color": [3, 3, 3]},
        ]})
        self.ids, _ = _ids()

    def test_under_then_over_in_z_order(self):
        r = RecordingRenderer()
        self.skinning.submit_layers(r, SCREEN, self.ids, "under", _idle)
        self.skinning.submit_layers(r, SCREEN, self.ids, "over", _idle)
        self.assertEqual([item.color for item in r.items],
                         [(3, 3, 3), (2, 2, 2), (1, 1, 1)])

    def test_a_band_only_draws_its_own_layers(self):
        r = RecordingRenderer()
        self.skinning.submit_layers(r, SCREEN, self.ids, "over", _idle)
        self.assertEqual(len(r.items), 1)


class TestPrimitivePrecedence(unittest.TestCase):
    """slot -> text -> color, first match wins; no match draws nothing."""

    def _one(self, layer):
        skinning = _skinning({"layers": [dict(layer, band="over")]})
        ids, _ = _ids()
        r = RecordingRenderer()
        skinning.submit_layers(r, SCREEN, ids, "over", _idle)
        return r.items

    def test_slot_wins(self):
        items = self._one({"slot": "ui_frame", "label": "ignored",
                           "color": [9, 9, 9], "tint": [1, 2, 3],
                           "offset": [1, 2, 0, 0]})
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], HudSprite)
        self.assertEqual(items[0].slot_key, "ui_frame")
        self.assertEqual(items[0].dest, (11, 22))
        self.assertEqual(items[0].size, (30, 40))
        self.assertEqual(items[0].tint, (1, 2, 3))

    def test_text_id_beats_color(self):
        items = self._one({"text_id": "hud.love_unaffordable",
                           "color": [9, 9, 9], "offset": [0, 0, 0, 0]})
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], HudText)
        self.assertEqual(items[0].text, strings.T("hud.love_unaffordable"))
        self.assertEqual(items[0].pos, (10, 20))
        self.assertEqual(items[0].font_key, "md")      # label-holder default
        self.assertEqual(items[0].color, (235, 225, 195))  # C_UI_TEXT
        self.assertEqual(items[0].align, "left")

    def test_label_fallback_with_authored_font_and_color(self):
        items = self._one({"label": "HI", "font": "sm", "align": "center",
                           "text_color": [1, 2, 3], "offset": [0, 0, 0, 0]})
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].text, items[0].font_key, items[0].color,
                          items[0].align), ("HI", "sm", (1, 2, 3), "center"))

    def test_empty_label_draws_nothing(self):
        self.assertEqual(self._one({"label": "", "offset": [0, 0, 0, 0]}), [])

    def test_color_only_is_a_rect(self):
        items = self._one({"color": [4, 5, 6], "offset": [1, 1, 5, 6]})
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], HudRect)
        self.assertEqual((items[0].rect, items[0].color), ((11, 21, 5, 6),
                                                           (4, 5, 6)))

    def test_no_role_draws_nothing(self):
        self.assertEqual(self._one({"offset": [0, 0, 0, 0]}), [])

    def test_invisible_layer_draws_nothing(self):
        self.assertEqual(
            self._one({"color": [4, 5, 6], "visible": False,
                       "offset": [0, 0, 0, 0]}), [])


class TestParity(unittest.TestCase):
    """D5: nothing authored, nothing drawn — the overwhelmingly common path."""

    def test_no_layers_emits_nothing(self):
        skinning = _skinning({"rect": [1, 2, 3, 4]})
        ids, _ = _ids()
        r = RecordingRenderer()
        skinning.submit_layers(r, SCREEN, ids, "under", _idle)
        skinning.submit_layers(r, SCREEN, ids, "over", _idle)
        self.assertEqual(r.items, [])

    def test_no_override_at_all_emits_nothing(self):
        ids, _ = _ids()
        r = RecordingRenderer()
        ScreenSkinning.empty().submit_layers(r, SCREEN, ids, "over", _idle)
        self.assertEqual(r.items, [])


class TestFollowsItsOwner(unittest.TestCase):
    """D2: the offset is relative to the POST-OVERRIDE rect, resolved fresh
    every frame — so a ``rect`` override that moves the owner moves the layer
    with it, no re-authoring of the layer."""

    def test_rect_override_moves_the_layer(self):
        skinning = ScreenSkinning.from_overrides({SCREEN: {"widgets": {
            "love_text": {
                "rect": [100, 200, 30, 40],
                "layers": [{"band": "under", "offset": [-2, -3, 0, 0],
                            "color": [7, 7, 7]}],
            }}}})
        ids, widget = _ids()

        before = RecordingRenderer()
        skinning.submit_layers(before, SCREEN, ids, "under", _idle)
        self.assertEqual(before.items[0].rect, (8, 17, 30, 40))

        skinning.apply(SCREEN, ids)          # the override moves the owner
        self.assertEqual(widget.rect, (100, 200, 30, 40))

        after = RecordingRenderer()
        skinning.submit_layers(after, SCREEN, ids, "under", _idle)
        self.assertEqual(after.items[0].rect, (98, 197, 30, 40))


class TestStateOf(unittest.TestCase):
    """UL-4 ships the placeholder; UL-5 replaces only this method's body."""

    def test_state_of_is_a_bound_method_returning_idle(self):
        skinning = ScreenSkinning.empty()
        widget = SimpleNamespace(rect=OWNER_RECT)
        self.assertEqual(skinning.state_of(widget), "idle")

    def test_submit_layers_calls_state_of_per_widget(self):
        skinning = _skinning({"layers": [
            {"band": "over", "color": [1, 1, 1], "offset": [0, 0, 0, 0]}]})
        ids, widget = _ids()
        seen = []

        def spy(w):
            seen.append(w)
            return "idle"

        skinning.submit_layers(RecordingRenderer(), SCREEN, ids, "over", spy)
        self.assertEqual(seen, [widget])


if __name__ == "__main__":
    unittest.main()
