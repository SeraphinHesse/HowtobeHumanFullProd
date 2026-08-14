"""Layer DRAW path tests (UiLayeredWidgetsPLAN UL-4) + per-state appearance
(UL-5).

**Merge note (UL-5):** this file is UL-4's; the phases were coded in parallel,
so this copy carries ONLY UL-5's per-state cases plus the minimal fixtures they
need. UL-4's own draw cases merge in alongside them — neither set restructures
the other.

Pure + headless: ``engine.ui_layers`` is pygame-free, and the widget cases use
the ``test_hud_panel.py`` recording-renderer fixture style (a stand-in renderer
that just collects the emitted HUD primitives).
"""
import unittest
from types import SimpleNamespace

from engine.render import HudRect, HudText
from engine.ui_layers import resolve
from game.ui import widgets
from game.ui.skinning import ScreenSkinning


class RecordingRenderer:
    """Collects everything submitted — ``test_hud_panel.py``'s fixture."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


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
    """``ScreenSkinning.state_of`` is the ONE normalizer (UL-5 §2d)."""

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
