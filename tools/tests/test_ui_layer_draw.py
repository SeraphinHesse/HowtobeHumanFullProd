"""Layer DRAW path tests (UiLayeredWidgetsPLAN UL-4) + per-state appearance
(UL-5).

UL-3 shipped the pure resolver (``engine/ui_layers.py``, covered by
``test_ui_layers.py``); this module covers the CALLER: which HUD primitive one
resolved layer becomes, in what order the two bands submit, the D2 "a layer
follows its owner" property once ``apply()`` has moved the owner, and (UL-5)
per-state appearance resolution on both a layer entry (``resolve()``) and an
owner widget itself (``Button``/label-holder ``states`` patches).

The golden-parity half (D5 — no ``layers`` authored anywhere means ZERO
primitives, so ``test_ui_skinning.py``'s baselines stay byte-identical) is
pinned here by ``test_no_layers_emits_nothing`` and by that file itself.

Headless, no pygame, no disk: ``ScreenSkinning.from_overrides`` takes an
in-memory ``{screen_id: doc}`` map, the widgets are ``SimpleNamespace``s with a
``.rect`` (all ``submit_layers`` reads off a widget), and the renderer is the
``RecordingRenderer`` stand-in ``test_ui_skinning.py``/``test_hud_panel.py``
use.
"""
import unittest
from types import SimpleNamespace

from engine.render import HudRect, HudSprite, HudText
from engine.ui_layers import resolve
from game.ui import strings, widgets
from game.ui.skinning import ScreenSkinning

SCREEN = "hud"
OWNER_RECT = (10, 20, 30, 40)


class RecordingRenderer:
    """Records every ``submit_hud`` call verbatim (the same stand-in
    ``tools/tests/test_ui_skinning.py``/``test_hud_panel.py`` use)."""

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


# A layer entry whose four states each recolour it and nudge it differently —
# one fixture, so the four per-state cases below cannot drift apart.
FOUR_STATE_LAYER = {
    "offset": [0, 0, 20, 10],
    "color": [10, 10, 10],
    "text_color": [1, 2, 3],
    "states": {
        "idle": {"color": [11, 11, 11], "offset": [0, 0, 20, 10]},
        "hover": {"color": [22, 22, 22], "offset": [1, -1, 20, 10]},
        "pressed": {"color": [33, 33, 33], "offset": [0, 2, 20, 10]},
        "disabled": {"color": [44, 44, 44], "text_color": [9, 9, 9],
                     "offset": [0, 0, 20, 6]},
    },
}
OWNER = (100, 200, 50, 60)


class TestResolveStates(unittest.TestCase):
    def test_idle(self):
        out = resolve(FOUR_STATE_LAYER, OWNER, "idle")
        self.assertEqual(out["color"], (11, 11, 11))
        self.assertEqual(out["rect"], (100, 200, 20, 10))
        self.assertEqual(out["text_color"], (1, 2, 3))   # base key stands

    def test_hover(self):
        out = resolve(FOUR_STATE_LAYER, OWNER, "hover")
        self.assertEqual(out["color"], (22, 22, 22))
        self.assertEqual(out["rect"], (101, 199, 20, 10))

    def test_pressed(self):
        out = resolve(FOUR_STATE_LAYER, OWNER, "pressed")
        self.assertEqual(out["color"], (33, 33, 33))
        self.assertEqual(out["rect"], (100, 202, 20, 10))

    def test_disabled(self):
        out = resolve(FOUR_STATE_LAYER, OWNER, "disabled")
        self.assertEqual(out["color"], (44, 44, 44))
        self.assertEqual(out["text_color"], (9, 9, 9))
        self.assertEqual(out["rect"], (100, 200, 20, 6))

    def test_absent_state_falls_back_to_idle(self):
        layer = {"offset": [0, 0, 5, 5], "color": [1, 1, 1],
                 "states": {"idle": {"color": [7, 7, 7]}}}
        self.assertEqual(resolve(layer, OWNER, "hover")["color"], (7, 7, 7))

    def test_no_matching_state_and_no_idle_falls_back_to_base(self):
        layer = {"offset": [1, 1, 5, 5], "color": [1, 1, 1],
                 "states": {"pressed": {"color": [7, 7, 7]}}}
        out = resolve(layer, OWNER, "hover")
        self.assertEqual(out["color"], (1, 1, 1))
        self.assertEqual(out["rect"], (101, 201, 5, 5))

    def test_present_but_empty_state_does_not_fall_through_to_idle(self):
        """PRESENCE of the key drives the fallback, not truthiness — an
        authored ``"hover": {}`` means "hover looks like the base", so
        collapsing this back to ``.get(state) or .get("idle")`` is a
        behaviour change, not a simplification."""
        layer = {"offset": [0, 0, 5, 5], "color": [1, 1, 1],
                 "states": {"hover": {}, "idle": {"color": [9, 9, 9]}}}
        self.assertEqual(resolve(layer, OWNER, "hover")["color"], (1, 1, 1))
        self.assertEqual(resolve(layer, OWNER, "pressed")["color"], (9, 9, 9))

    def test_two_length_patch_offset_moves_without_resizing(self):
        layer = {"offset": [0, 0, 20, 10],
                 "states": {"hover": {"offset": [3, -4]}}}
        self.assertEqual(resolve(layer, OWNER, "hover")["rect"],
                         (103, 196, 20, 10))

    def test_no_states_key_resolves_identically_for_every_state(self):
        """D5 parity: an un-authored entry cannot notice this phase."""
        layer = {"offset": [1, 2, 3, 4], "slot": "s", "color": [5, 6, 7],
                 "visible": False}
        base = resolve(layer, OWNER, "idle")
        for state in ("hover", "pressed", "disabled"):
            self.assertEqual(resolve(layer, OWNER, state), base)

    def test_resolve_never_mutates_the_spec(self):
        layer = {"offset": [0, 0, 4, 4], "color": [1, 1, 1],
                 "states": {"hover": {"color": [2, 2, 2], "offset": [9, 9]}}}
        before = repr(layer)
        resolve(layer, OWNER, "hover")
        self.assertEqual(repr(layer), before)


class TestStateOf(unittest.TestCase):
    """``ScreenSkinning.state_of`` is the ONE normalizer (UL-4's seam,
    UL-5 §2d's real body). A ``Button`` answers through its own ``_state()``;
    every other widget (a plain ``SimpleNamespace``/label holder with no state
    machine) resolves to ``"idle"``, always."""

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

    def test_button_answers_through_its_own_state(self):
        skinning = ScreenSkinning.empty()
        btn = widgets.Button((0, 0, 40, 20), "GO")
        self.assertEqual(skinning.state_of(btn), "idle")
        btn.hovered = True
        self.assertEqual(skinning.state_of(btn), "hover")
        btn.mouse_down = True
        self.assertEqual(skinning.state_of(btn), "pressed")
        btn.enabled = False
        btn.hovered = False
        self.assertEqual(skinning.state_of(btn), "disabled")

    def test_stateless_holder_is_always_idle(self):
        holder = widgets.label_holder((5, 6, 0, 0), label="Hi")
        self.assertEqual(ScreenSkinning.empty().state_of(holder), "idle")


class TestWidgetStatePatch(unittest.TestCase):
    def test_button_hover_patch_recolours_and_nudges_the_draw(self):
        btn = widgets.Button((10, 20, 40, 20), "GO")
        btn.states = {"hover": {"text_color": [1, 2, 3], "offset": [2, -3]}}
        btn.hovered = True
        r = RecordingRenderer()
        btn.submit(r)
        rects = [i for i in r.items if isinstance(i, HudRect)]
        text = [i for i in r.items if isinstance(i, HudText)][0]
        self.assertEqual(rects[0].rect, (12, 17, 40, 20))
        self.assertEqual(text.color, (1, 2, 3))
        self.assertEqual(btn.rect, (10, 20, 40, 20))     # NOT mutated

    def test_button_without_states_is_untouched(self):
        plain, patched = widgets.Button((10, 20, 40, 20), "GO"), \
            widgets.Button((10, 20, 40, 20), "GO")
        patched.states = {"pressed": {"offset": [5, 5]}}   # unreachable: idle
        a, b = RecordingRenderer(), RecordingRenderer()
        plain.submit(a)
        patched.submit(b)
        self.assertEqual([repr(i) for i in a.items], [repr(i) for i in b.items])

    def test_present_but_empty_state_does_not_fall_through_to_idle(self):
        """``widgets._state_patch`` is a second copy of the same ladder as
        ``engine.ui_layers``' — pin its empty-vs-absent branch too."""
        btn = widgets.Button((10, 20, 40, 20), "GO")
        btn.states = {"hover": {}, "idle": {"offset": [7, 7]}}
        btn.hovered = True
        r = RecordingRenderer()
        btn.submit(r)
        drawn = [i for i in r.items if isinstance(i, HudRect)][0]
        self.assertEqual(drawn.rect, (10, 20, 40, 20))   # base, not idle's

    def test_explicit_call_site_color_beats_the_patch(self):
        """A caller's computed semantic colour is MORE specific than the
        screen doc — the same precedence ``Button.submit`` gives an explicit
        ``text_color=`` kwarg."""
        holder = widgets.label_holder((30, 40, 0, 0), label="Hi")
        holder.states = {"idle": {"text_color": [4, 5, 6]}}
        r = RecordingRenderer()
        widgets.submit_label(r, holder, color=widgets.C_GOLD)
        self.assertEqual(r.items[0].color, widgets.C_GOLD)

    def test_label_holder_uses_its_idle_patch_only(self):
        holder = widgets.label_holder((30, 40, 0, 0), label="Hi")
        holder.states = {"idle": {"color": [4, 5, 6], "offset": [1, 2]},
                         "hover": {"color": [7, 7, 7], "offset": [50, 50]}}
        r = RecordingRenderer()
        widgets.submit_label(r, holder)
        text = r.items[0]
        self.assertEqual(text.pos, (31, 42))
        self.assertEqual(text.color, (4, 5, 6))
        self.assertEqual(holder.rect, (30, 40, 0, 0))     # NOT mutated


if __name__ == "__main__":
    unittest.main()
