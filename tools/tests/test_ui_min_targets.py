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
playtest saying a specific control is hard to hit. **UL-10 widened that lint
to CLICKABLE LAYERS**, and deliberately not the hard floor: see
``_clickable_layers``.

**This module measures the REAL SHIPPED FONT, on purpose.** Every pixel
constant in ``game/ui`` was authored against ``SysFont("monospace")`` metrics,
but the game boots ``data/ui/active_font.json``'s face (``pixel_emulator``),
which is wider per glyph at the same nominal size. Measuring "whatever font
state this process happens to be in" is how twelve genuinely overhanging
labels stayed invisible for months: alone, this file got the SysFont fallback
and passed; only when a worker happened to run ``test_game_boot.py`` first
(which installed the real face and, until recently, leaked it) did the twelve
appear — and then they read as a flake, not a finding. ``setUpModule``
therefore installs the shipped face deliberately and ``tearDownModule``
restores the previous globals, so the measurement is the product's and the
leak rule (``test_theme_data.py``'s module docstring) still holds.
"""
import json
import unittest
from pathlib import Path

from engine import ui_layers
from engine.render import fonts as _fonts
from engine.render.fonts import configure_fonts, layout_h
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

#: The shipped font FILE is a binary, so it is not in the JSON-only fixture —
#: `data/fonts/` is read live for the face itself (allowlisted in
#: `test_fixture_guard.py`). Everything that decides WHICH face, and every
#: geometry number, still comes from the pin above.
_LIVE_FONT_DIR = Path(__file__).resolve().parents[2] / "data" / "fonts"


def _active_font_path():
    """The face `game/main.py` would install, resolved exactly as it does.

    `game/main.py` (~line 316-331): read `ui/active_font.json`'s `font_id`;
    `"default"` means no path (the SysFont fallback); any other id must name
    an entry in `fonts/font_manifest.json`, whose `file` is relative to
    `data/fonts/`. Kept as a small copy rather than an import because
    `game.main` does the resolution inline inside `main()`, mid-boot.
    """
    font_id = json.loads(
        (DATA / "ui" / "active_font.json").read_text(encoding="utf-8"))["font_id"]
    if font_id == "default":
        return None
    manifest = json.loads(
        (DATA / "fonts" / "font_manifest.json").read_text(encoding="utf-8"))
    entry = manifest["entries"][font_id]
    return (_LIVE_FONT_DIR / entry["file"]).resolve()


#: Saved by `setUpModule`, restored by `tearDownModule`. `_FONT_SPECS` is
#: mutated IN PLACE by `configure_fonts`, so it is restored clear+update
#: (never rebound); `_cache` holds already-built face objects and must be
#: cleared on the way in AND out.
_SAVED_FONT_STATE = {}


def setUpModule():
    _SAVED_FONT_STATE["path"] = _fonts._FONT_PATH
    _SAVED_FONT_STATE["bytes"] = _fonts._FONT_BYTES
    _SAVED_FONT_STATE["specs"] = dict(_fonts._FONT_SPECS)
    fonts_doc = json.loads(
        (DATA / "ui" / "fonts.json").read_text(encoding="utf-8"))
    configure_fonts(fonts_doc, font_path=_active_font_path())


def tearDownModule():
    if not _SAVED_FONT_STATE:
        return
    _fonts._FONT_PATH = _SAVED_FONT_STATE["path"]
    _fonts._FONT_BYTES = _SAVED_FONT_STATE["bytes"]
    _fonts._FONT_SPECS.clear()
    _fonts._FONT_SPECS.update(_SAVED_FONT_STATE["specs"])
    _fonts._cache.clear()
    _SAVED_FONT_STATE.clear()


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


def _clickable_layers():
    """``(screen_id, "<widget>.<layer>", rect)`` for every CLICKABLE layer
    authored in the pinned screen docs (UL-10).

    A layer is never an entry in a screen's ``ids`` — it is a sub-rect
    authored inside an EXISTING widget's ``layers`` array and only exists once
    ``engine.ui_layers.resolve`` has been applied to its owner's rect. So this
    walks the SAME captured ids for the owner geometry and the pinned screen
    doc for the layer array, and resolves the pair.

    Resolved in the ``idle`` state only: a state patch that shrinks a layer on
    hover is a transient, not a click target the designer aims at.

    **These join the NON-BLOCKING lint below, never ``TestButtonMinSize``.**
    A clickable layer is very often decorative art retargeted onto an existing
    button that already clears the floor, so a hard failure on the decal's own
    size would be a false positive on an already-accessible control — and
    ``game/ui/CLAUDE.md``'s standing rule forbids resizing designer art to
    silence a lint.
    """
    captured, _view_w, _view_h = _capture_screen_ids()
    screens_dir = DATA / "ui" / "screens"
    out = []
    for screen_id, ids in sorted(captured.items()):
        path = screens_dir / f"{screen_id}.json"
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            continue
        widgets_spec = doc.get("widgets") or {}
        for name, (_kind, widget) in sorted(ids.items()):
            layers = (widgets_spec.get(name) or {}).get("layers") or []
            owner_rect = getattr(widget, "rect", (0, 0, 0, 0))
            for index, entry in enumerate(layers):
                if not isinstance(entry, dict) or not entry.get("clickable"):
                    continue
                resolved = ui_layers.resolve(entry, owner_rect, "idle")
                out.append((screen_id,
                            f"{name}.{entry.get('id') or index}",
                            tuple(resolved["rect"])))
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
        """NON-BLOCKING lint: print the under-16 roster, assert nothing.

        UL-10 widened the roster to CLICKABLE LAYERS as well as buttons —
        same prefix, same never-fails contract, and deliberately NOT the hard
        floor above (see `_clickable_layers`). Layers report from 0px up,
        since they are not subject to `MIN_HARD` at all.
        """
        small = sorted(
            [(min(rect[2], rect[3]), f"{sid}.{name}", rect)
             for sid, name, rect, _label, _font in _buttons()
             if MIN_HARD <= min(rect[2], rect[3]) < MIN_LINT]
            + [(min(rect[2], rect[3]), f"{sid}.{name} (layer)", rect)
               for sid, name, rect in _clickable_layers()
               if min(rect[2], rect[3]) < MIN_LINT])
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

    def test_the_measured_font_is_the_shipped_one(self):
        """Bare-minimum guard on the premise of every assert in this class.

        Without it, a resolution bug that silently yielded ``None`` would
        drop the whole module back to the SysFont fallback and go green for
        exactly the reason this module exists to stop.
        """
        expected = _active_font_path()
        if expected is None:
            self.skipTest("active_font.json is 'default' — no face to install")
        self.assertTrue(expected.is_file(), f"{expected} is not on disk")
        self.assertEqual(str(expected), _fonts._FONT_PATH)
        self.assertIsNotNone(_fonts._FONT_BYTES)

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


class TestColorSwatchMinSize(unittest.TestCase):
    """MasterSheetColumnsPLAN B2: the construct modal's colour swatches.

    The walker above only sees ids that ``export_ui_layouts``'s builders
    produce, and the exporter's ``ConstructPreview`` is built with no
    capability map — so it has no swatches and cannot cover them. This
    constructs a colour-capable preview directly instead.
    """

    def test_every_swatch_clears_the_hard_floor(self):
        from game.buildings.registry import build_cost, create
        from game.core import load_balance
        from game.ui.building_ui import ConstructPreview

        build_bal, ui_bal = (load_balance(DATA, "buildings"),
                             load_balance(DATA, "ui"))
        view_w, view_h = export._logical_resolution(DATA)
        slot = create("defence", 0, 0, build_bal, 0).slot_key()
        preview = ConstructPreview(
            "defence", build_cost("defence", build_bal, 0), build_bal, ui_bal,
            view_w, view_h,
            building_colors={slot: ("pink", "red", "purple", "yellow")})
        swatches = preview.swatches
        self.assertTrue(swatches, "the fixture must actually build swatches")
        too_small = [f"preview_color_{i} {btn.rect}"
                     for i, btn in enumerate(swatches.buttons)
                     if min(btn.rect[2], btn.rect[3]) < MIN_HARD]
        self.assertEqual(
            [], too_small,
            f"swatch(es) under the {MIN_HARD}px logical click-target floor")


if __name__ == "__main__":
    unittest.main()
