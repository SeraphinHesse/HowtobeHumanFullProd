"""UL-10: a CLICKABLE layer routes a click, and never changes anything else.

Four behaviours, one per class:

1. a retargeting layer produces the TARGET widget's own action;
2. ``Hud.hit()`` called twice returns the same answer and mutates nothing
   (D8 — ``main.py`` calls it once for the MOUSEBUTTONDOWN pan-arming probe
   and again for real on MOUSEBUTTONUP);
3. a screen with no clickable layers routes exactly as it did before UL-10;
4. **Ruling 1** — a layer whose ``target`` names neither a widget in this
   screen nor a reserved token SWALLOWS the click; it does not fall through
   to the widget underneath it.

Fixture style is ``test_ui_layers.py``'s: in-memory
``ScreenSkinning.from_overrides`` docs, never live ``data/`` and never a
staged temp tree — nothing here reads or writes a file.
"""
import unittest
from types import SimpleNamespace

from game.ui.hud import Hud
from game.ui.skinning import ScreenSkinning, hit_layer

VIEW_W, VIEW_H = 640, 360


def idle(_widget):
    return "idle"


def hud_with(layers_by_widget):
    """A laid-out ``Hud`` whose override doc authors `layers_by_widget`."""
    doc = {"widgets": {name: {"layers": layers}
                       for name, layers in layers_by_widget.items()}}
    hud = Hud(VIEW_W, VIEW_H, ScreenSkinning.from_overrides({"hud": doc}))
    hud.layout(VIEW_W, VIEW_H)
    return hud


def centre(rect):
    x, y, w, h = rect
    return x + w // 2, y + h // 2


class TestRetarget(unittest.TestCase):
    """A clickable layer on one widget fires ANOTHER widget's action."""

    def test_layer_returns_the_target_widgets_action(self):
        ids = {"btn_a": ("button", SimpleNamespace(rect=(0, 0, 50, 20))),
               "btn_b": ("button", SimpleNamespace(rect=(0, 40, 50, 20)))}
        spec = {"btn_a": {"layers": [{"id": "decal", "offset": [0, 0, 10, 10],
                                      "clickable": True, "target": "btn_b"}]}}
        self.assertEqual(
            "beta",
            hit_layer(ids, spec, 5, 5, idle, {"btn_a": "alpha",
                                              "btn_b": "beta"}))

    def test_reserved_tokens_come_back_verbatim(self):
        ids = {"btn_a": ("button", SimpleNamespace(rect=(0, 0, 50, 20)))}
        for token in ("close_window", "back", "noop"):
            spec = {"btn_a": {"layers": [{"offset": [0, 0, 10, 10],
                                          "clickable": True,
                                          "target": token}]}}
            self.assertEqual(token, hit_layer(ids, spec, 5, 5, idle,
                                              {"btn_a": "alpha"}))

    def test_non_clickable_layer_is_transparent(self):
        """The decorative case — every shipped screen today. The click must
        fall through (``None``) so the widget's own hit path runs."""
        ids = {"btn_a": ("button", SimpleNamespace(rect=(0, 0, 50, 20)))}
        spec = {"btn_a": {"layers": [{"offset": [0, 0, 10, 10],
                                      "target": "btn_a"}]}}
        self.assertIsNone(hit_layer(ids, spec, 5, 5, idle, {"btn_a": "alpha"}))

    def test_hud_layer_retargets_pause_onto_end_turn(self):
        """The Quick Test's shape, in a unit: art on the pause button fires
        End Turn instead."""
        hud = hud_with({"btn_pause": [{"id": "munchkin",
                                       "offset": [0, 0, 0, 0],
                                       "clickable": True,
                                       "target": "btn_end_turn"}]})
        self.assertEqual("end_turn", hud.hit(*centre(hud.pause.rect)))
        # …and a click nowhere near the layer still ends the turn on its own
        # button, i.e. nothing else about the screen moved.
        self.assertEqual("end_turn", hud.hit(*centre(hud.end_turn.rect)))


class TestHudHitIsPure(unittest.TestCase):
    """D8: ``main.py`` calls ``Hud.hit()`` twice per click."""

    def _snapshot(self, hud):
        return (hud._panel_open,
                tuple(sorted((name, tuple(getattr(w, "rect", ())),
                              getattr(w, "hovered", None),
                              getattr(w, "enabled", None))
                             for name, (_kind, w) in hud.ids.items())))

    def test_two_identical_calls_agree_and_change_nothing(self):
        hud = hud_with({"btn_pause": [{"id": "munchkin",
                                       "offset": [0, 0, 0, 0],
                                       "clickable": True,
                                       "target": "btn_end_turn"}]})
        point = centre(hud.pause.rect)
        before = self._snapshot(hud)
        first = hud.hit(*point)
        mid = self._snapshot(hud)
        second = hud.hit(*point)
        after = self._snapshot(hud)
        self.assertEqual(first, second)
        self.assertEqual(before, mid)
        self.assertEqual(before, after)

    def test_purity_holds_on_the_unlayered_screen_too(self):
        hud = hud_with({})
        point = centre(hud.pause.rect)
        before = self._snapshot(hud)
        self.assertEqual(hud.hit(*point), hud.hit(*point))
        self.assertEqual(before, self._snapshot(hud))


class TestNoClickableLayersRoutesAsBefore(unittest.TestCase):
    """D5 parity: UL-10's insertion is a no-op on every shipped screen."""

    def test_pause_button_still_returns_pause(self):
        for hud in (hud_with({}),
                    # a layer that exists but is NOT clickable, right on top
                    # of the pause button
                    hud_with({"btn_pause": [{"id": "decal",
                                             "offset": [0, 0, 0, 0],
                                             "color": [1, 2, 3]}]})):
            self.assertEqual("pause", hud.hit(*centre(hud.pause.rect)))
            self.assertEqual("end_turn", hud.hit(*centre(hud.end_turn.rect)))

    def test_a_miss_is_still_a_miss(self):
        hud = hud_with({"btn_pause": [{"id": "decal", "offset": [0, 0, 4, 4],
                                       "clickable": True,
                                       "target": "btn_end_turn"}]})
        self.assertIsNone(hud.hit(VIEW_W // 2, VIEW_H // 2))


class TestDeadTargetSwallows(unittest.TestCase):
    """Ruling 1: an unroutable target stops the click, it does not leak it."""

    def test_unroutable_target_returns_noop_not_the_widget_under_it(self):
        hud = hud_with({"btn_pause": [{"id": "typo", "offset": [0, 0, 0, 0],
                                       "clickable": True,
                                       "target": "no_such_widget"}]})
        # The layer covers btn_pause exactly, so a fall-through would be a
        # real, distinguishable action.
        self.assertEqual("pause", hud_with({}).hit(*centre(hud.pause.rect)),
                         "premise: this point IS the pause button")
        self.assertEqual("noop", hud.hit(*centre(hud.pause.rect)))

    def test_a_missing_target_swallows_the_same_way(self):
        hud = hud_with({"btn_pause": [{"id": "bare", "offset": [0, 0, 0, 0],
                                       "clickable": True}]})
        self.assertEqual("noop", hud.hit(*centre(hud.pause.rect)))


if __name__ == "__main__":
    unittest.main()
