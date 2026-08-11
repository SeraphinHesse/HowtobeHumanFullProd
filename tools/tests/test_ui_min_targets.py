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

from engine.render.fonts import layout_h
from game.ui import widgets
from tools import export_ui_layouts as export
from tools.tests.fixture_data import FIXTURE_DATA

#: The PINNED snapshot, never live ``data/`` — the root CLAUDE.md rule, and
#: what ``test_fixture_guard.py`` enforces. This test asserts committed
#: LAYOUT geometry, so it must read the pin: a designer resizing a widget in
#: live data is their business, not a gate failure.
DATA = FIXTURE_DATA

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


#: Id families whose LABEL is composed at build time from live game state, so
#: the static-fit assert below does not apply to them (the class's own stated
#: scope). `building_panel.card_<building_type>` is the only member: a card's
#: label is `T("building.construct.card", name=, cost=)` — the name comes from
#: `buildings.json` and the cost is a live, escalating price, so neither the
#: text nor its width is knowable from code. They became visible to this test
#: only when the cards gained ids (editable buy options); they are NOT newly
#: overflowing, they were simply never measured before. The lint below reports
#: them so the overhang stays visible rather than silently excluded.
DYNAMIC_LABEL_PREFIXES = ("card_",)


def _has_dynamic_label(name):
    return name.startswith(DYNAMIC_LABEL_PREFIXES)


def _label_overflow(buttons):
    """``[(overflow_px, description), ...]`` for every button whose label is
    wider than its box, worst first."""
    out = []
    for sid, name, rect, label, font in buttons:
        if not label:
            continue
        text_w = widgets.text_size(label, font)[0]
        if text_w > rect[2] - LABEL_MARGIN:
            need = text_w + LABEL_MARGIN
            out.append((need - rect[2],
                        f"{sid}.{name} {label!r}@{font} needs "
                        f"{need}px, has {rect[2]}px"))
    return sorted(out, reverse=True)


class TestStaticLabelFit(unittest.TestCase):
    """UR-5 §1(b): every STATIC button label fits its button.

    Static only. Dynamic labels (building display names, player names,
    high-score rows) stay eyeball-only — see the brief's playtest script.
    They used never to reach an ``ids`` widget at export time at all; the
    construct cards now do (they are individually overridable widgets), so
    the exclusion is an explicit list (``DYNAMIC_LABEL_PREFIXES``) rather
    than an accident of what happens to be id'd.
    """

    def test_labels_fit_their_button_width(self):
        overflowing = [
            desc for _over, desc in
            _label_overflow(b for b in _buttons() if not _has_dynamic_label(b[1]))
        ]
        self.assertEqual([], overflowing,
                         "static button label(s) overhang their button")

    def test_report_dynamic_label_overflow(self):
        """NON-BLOCKING lint: the dynamic-label roster that overhangs.

        A real UR-5-class finding rather than test bookkeeping — a construct
        card is 118px wide and several of its labels measure past 150px at
        ``md``, i.e. they overhang their card on BOTH sides in game today.
        The fix is a design call (narrower copy, a smaller font, or a wider
        panel column), so this prints instead of failing.
        """
        over = _label_overflow(b for b in _buttons() if _has_dynamic_label(b[1]))
        if over:
            print(f"\n[dynamic-label lint] {len(over)} button(s) whose "
                  f"live-composed label overhangs its box — a design call, "
                  f"not auto-fixable:")
            for overflow_px, desc in over:
                print(f"    +{overflow_px:>3}px  {desc}")

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
