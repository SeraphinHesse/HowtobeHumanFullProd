"""Per-widget `align` is designer-authorable (UL-1).

Two halves, one key:

* **Game side** — a `data/ui/screens/<id>.json` `widgets.<id>.align` reaches
  the drawn `HudText`. Nothing in `game/ui` changed to make that true:
  `ScreenSkinning.apply`'s generic setattr loop already threads any override
  key onto the widget, and `widgets.submit_label` already resolves
  `getattr(holder, "align", "left")`. The only thing that was missing is the
  schema key, so these tests are the pin that the two halves stay connected —
  an `_SPEC_TO_ATTR` entry or a `submit_label` refactor that broke the path
  would otherwise fail silently, with the text simply drawn left.
* **Editor side** — `_screen_primitives.resolve_align` prefers the designer's
  override over `screen_defaults.json`'s recorded measuring hint, so the
  editor's hit box for a re-aligned position-only anchor lands ON the glyphs.
  Measuring against the stale default is the `hud.round_label` failure
  (`game/ui/CLAUDE.md`), which authorable `align` would otherwise re-open for
  every anchor.

Disk-free and Qt-free: `ScreenSkinning.from_overrides` takes an in-memory
`{screen_id: doc}` map (the `test_construct_card.py` pattern), and
`editor.panels._screen_primitives` is pure stdlib + `engine.render`
(`editor/panels/__init__.py` is empty, so importing it pulls no PySide6).
"""
import unittest

from editor.panels._screen_primitives import interaction_rect, resolve_align
from engine.render import HudText
from engine.render.fonts import TextMetrics
from game.ui import widgets
from game.ui.skinning import ScreenSkinning

SCREEN = "some_screen"
ANCHOR = (100, 50, 0, 0)   # a position-only text anchor, the align-sensitive case
TEXT = "LOVE 12"


class RecordingRenderer:
    """Records every `submit_hud` call verbatim — the `test_ui_skinning.py`
    stand-in, restated here so this module needs none of that file's
    Session/TileMap fixture."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


def _drawn_label(override):
    """The one `HudText` an id'd label holder emits under `override` (the
    per-widget dict a screen doc would carry), through the real
    apply() -> submit_label() path."""
    holder = widgets.label_holder(rect=ANCHOR, label=TEXT)
    sk = ScreenSkinning.from_overrides(
        {SCREEN: {"widgets": {"love_text": override}}})
    sk.apply(SCREEN, {"love_text": ("label", holder)})
    renderer = RecordingRenderer()
    widgets.submit_label(renderer, holder)
    items = [i for i in renderer.items if isinstance(i, HudText)]
    assert len(items) == 1, items
    return items[0]


class TestAlignOverrideReachesTheDraw(unittest.TestCase):
    def test_each_value_is_drawn(self):
        for value in ("left", "center", "right"):
            with self.subTest(align=value):
                self.assertEqual(_drawn_label({"align": value}).align, value)

    def test_absent_align_is_left(self):
        """The pinned default: a screen doc that predates the key — i.e.
        every shipped one — draws exactly as it does today (`submit_label`'s
        own `"left"` fallback). This is the D5 golden-parity contract in
        miniature."""
        self.assertEqual(_drawn_label({}).align, "left")

    def test_align_rides_alongside_other_overrides(self):
        """`align` needs no `_SPEC_TO_ATTR` entry: it maps 1:1 onto the
        holder attribute, and does not disturb the keys that do get remapped
        (`font` -> `font_key`)."""
        item = _drawn_label({"align": "right", "font": "lg"})
        self.assertEqual(item.align, "right")
        self.assertEqual(item.font_key, "lg")


class TestResolveAlign(unittest.TestCase):
    def test_override_wins_over_the_default_hint(self):
        self.assertEqual(
            resolve_align({"align": "center"}, {"align": "right"}), "right")

    def test_falls_back_to_the_default_hint(self):
        self.assertEqual(resolve_align({"align": "center"}, {}), "center")

    def test_both_absent_is_left(self):
        self.assertEqual(resolve_align({}, {}), "left")

    def test_empty_inputs_are_tolerated(self):
        """`spec` is `{}`/None for an id the defaults don't know about; the
        editor must not crash mid-authoring on either."""
        self.assertEqual(resolve_align(None, None), "left")
        self.assertEqual(resolve_align(None, {"align": "center"}), "center")


class TestTheHitBoxFollowsTheOverride(unittest.TestCase):
    """`resolve_align` -> `interaction_rect`: the editor's box for an anchor
    shifts the same way the game's `HudText` align does."""

    def _box(self, spec, override):
        return interaction_rect(ANCHOR, text=TEXT, font_key="md",
                                align=resolve_align(spec, override))

    def test_each_value_shifts_x_the_documented_way(self):
        w = TextMetrics().size(TEXT, "md")[0]
        x = ANCHOR[0]
        for value, expected_x in (("left", x), ("center", x - w / 2),
                                  ("right", x - w)):
            with self.subTest(align=value):
                box = self._box({}, {"align": value})
                self.assertEqual(box[0], expected_x)
                self.assertEqual(box[2], w)

    def test_a_re_aligned_anchor_no_longer_measures_the_stale_default(self):
        """The regression this phase closes: the widget's recorded default is
        `left` (what the exporter read off the code holder), the designer has
        authored `right`, and the box must follow the DESIGNER — otherwise it
        sits a whole label to the right of the glyphs."""
        spec = {"align": "left"}
        self.assertNotEqual(self._box(spec, {"align": "right"}),
                            self._box(spec, {}))
        self.assertEqual(self._box(spec, {"align": "right"}),
                         self._box({"align": "right"}, {}))

    def test_a_sized_widget_is_returned_verbatim(self):
        """Only zero-extent axes grow, so `align` cannot move a widget that
        stores a real rect — it is an ANCHOR-only concern."""
        sized = (100, 50, 40, 12)
        for value in ("left", "center", "right"):
            with self.subTest(align=value):
                self.assertEqual(
                    interaction_rect(sized, text=TEXT, font_key="md",
                                     align=resolve_align({}, {"align": value})),
                    sized)


if __name__ == "__main__":
    unittest.main()
