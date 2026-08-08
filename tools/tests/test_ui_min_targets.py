"""UR-5 §1(b)/§1(c): the two mechanical checks the eyeball pass cannot do.

Both walk EVERY shipped screen's ``ids`` — the ``{name: (kind, widget)}``
B2/B3 contract — captured straight out of ``tools/export_ui_layouts.py``'s own
per-screen builders, so a screen added to ``SCREEN_IDS`` is covered here for
free and the mock state is exactly the one the golden export pins.

Why the ids and not the exported JSON: ``screen_defaults.json`` carries
``{rect, kind, label}`` but NOT ``font_key``, and the label-fit check needs the
font. Capturing the raw ids gives both checks one source.

Filter on the ``kind`` from the ids PAIR, never on ``type(widget)`` — panels
and labels are not click targets (``widgets.submit_panel``'s docstring) and a
``bar``/``backdrop`` has no label to fit.

**MIN_HARD is a floor, MIN_LINT is not.** ``SCALED`` preserves physical screen
area (12 logical px == 24 physical px at the 2x reference monitor), so a small
control does not actually shrink under the pointer; the risk is sub-pixel
rounding in the mouse remap at non-integer monitor scales
(``planning/UiResolutionPLAN.md`` §5). So only the 12px floor fails the build.
``test_report_small_click_targets`` prints the under-16 roster as an eyeball
worklist and never fails — do NOT convert it into an assertion without a
playtest saying a specific control is hard to hit.
"""
import unittest
from pathlib import Path

from engine.render.fonts import layout_h
from game.ui import widgets
from tools import export_ui_layouts as export

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"

#: Hard floor for a click target's smaller dimension, in LOGICAL pixels.
MIN_HARD = 12
#: Comfort threshold — reported, never asserted (see the module docstring).
MIN_LINT = 16
#: Horizontal breathing room a static label must leave inside its button
#: (2px a side). ``Button.submit`` centres the label and does no fitting or
#: truncation, so a label wider than this silently overhangs both edges.
LABEL_MARGIN = 4


def _capture_screen_ids():
    """``{screen_id: {name: (kind, widget)}}`` for every shipped screen.

    ``_widgets_from_ids`` is the single funnel every builder pushes its ids
    through on the way to JSON, so wrapping it captures the live widget
    objects without duplicating the builder roster (or its mock states) here.
    ``building_panel`` calls it once per view — first-wins, matching the
    exporter's own union rule for ids shared across modes.
    """
    captured = {}
    current = [None]
    original = export._widgets_from_ids

    def capturing(ids):
        bucket = captured.setdefault(current[0], {})
        for name, pair in ids.items():
            bucket.setdefault(name, pair)
        return original(ids)

    export._widgets_from_ids = capturing
    try:
        view_w, view_h = export._logical_resolution(DATA)
        for screen_id in export.SCREEN_IDS:
            current[0] = screen_id
            export.build_screen_defaults(screen_id, view_w, view_h, DATA)
    finally:
        export._widgets_from_ids = original
    return captured, view_w, view_h


def _buttons():
    """``(screen_id, name, rect, label, font_key)`` for every ``button`` id."""
    captured, _view_w, _view_h = _capture_screen_ids()
    out = []
    for screen_id, ids in sorted(captured.items()):
        for name, (kind, widget) in sorted(ids.items()):
            if kind != "button":
                continue
            out.append((screen_id, name, getattr(widget, "rect", (0, 0, 0, 0)),
                        getattr(widget, "label", "") or "",
                        getattr(widget, "font_key", "lg")))
    return out


class TestButtonMinSize(unittest.TestCase):
    """UR-5 §1(c): no click target below the logical-pixel floor."""

    def test_every_button_clears_the_hard_floor(self):
        too_small = [
            f"{sid}.{name} {rect}"
            for sid, name, rect, _label, _font in _buttons()
            if min(rect[2], rect[3]) < MIN_HARD
        ]
        self.assertEqual(
            [], too_small,
            f"button(s) under the {MIN_HARD}px logical click-target floor")

    def test_report_small_click_targets(self):
        """NON-BLOCKING lint: print the under-16 roster, assert nothing."""
        small = sorted(
            (min(rect[2], rect[3]), f"{sid}.{name}", rect)
            for sid, name, rect, _label, _font in _buttons()
            if MIN_HARD <= min(rect[2], rect[3]) < MIN_LINT)
        if small:
            print(f"\n[UR-5 lint] {len(small)} click target(s) between "
                  f"{MIN_HARD} and {MIN_LINT} logical px — eyeball, do not "
                  f"auto-resize:")
            for smallest, where, rect in small:
                print(f"    {where:<28} {rect}  min={smallest}")


class TestStaticLabelFit(unittest.TestCase):
    """UR-5 §1(b): every STATIC button label fits its button.

    Static only. Dynamic labels (building display names, player names,
    high-score rows) never reach an ``ids`` widget at export time and stay
    eyeball-only — see the brief's playtest script.
    """

    def test_labels_fit_their_button_width(self):
        overflowing = []
        for sid, name, rect, label, font in _buttons():
            if not label:
                continue
            text_w = widgets.text_size(label, font)[0]
            if text_w > rect[2] - LABEL_MARGIN:
                overflowing.append(
                    f"{sid}.{name} {label!r}@{font} needs "
                    f"{text_w + LABEL_MARGIN}px, has {rect[2]}px")
        self.assertEqual([], overflowing,
                         "static button label(s) overhang their button")

    def test_labels_fit_their_button_height(self):
        """The vertical half: ``Button.submit`` centres on ``layout_h``, so a
        button shorter than its font's line height overhangs top AND bottom."""
        too_short = []
        for sid, name, rect, label, font in _buttons():
            if not label:
                continue
            if rect[3] < layout_h(font):
                too_short.append(
                    f"{sid}.{name} {label!r}@{font} needs "
                    f"{layout_h(font)}px, has {rect[3]}px")
        self.assertEqual([], too_short,
                         "static button label(s) are taller than their button")


if __name__ == "__main__":
    unittest.main()
