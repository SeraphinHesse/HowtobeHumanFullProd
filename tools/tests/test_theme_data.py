"""UH-6 (D5/D6): fonts + palette become schema-validated data, plus the
optional per-widget `tint`.

Every test that calls ``configure_fonts``/``configure_palette`` MUST
``addCleanup``-restore the module's unconfigured state — these mutate module
globals, and a leaked configure poisons every later parity test in the same
process (``test_ui_skinning.py``'s golden baseline, ``test_layout_h_
invariant.py``). Never read live ``data/ui/fonts.json``/``palette.json`` in
an assertion: the fixture dicts below pin TODAY'S values independently of the
live files (house rule, ``tools/tests/test_fixture_guard.py``).
"""
import unittest
from pathlib import Path

import jsonschema

from engine import data_io
from engine.render import fonts
from game.ui import widgets
from game.ui.skinning import ScreenSkinning
from game.ui.widgets import Button, submit_panel
from tools.export_ui_layouts import main as export_main
from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.test_ui_skinning import _BASELINE, _screen_captures

REPO = Path(__file__).resolve().parents[2]

# The stock values (D5) — verbatim from engine/render/fonts.py's _FONT_SPECS
# and game/ui/widgets.py's C_* block at the time data/ui/fonts.json and
# data/ui/palette.json were authored. Hardcoded here (not read from the live
# files) so this module never depends on data/ content, per house rule.
_FIXTURE_FONTS = {
    "sm": {"size": 9, "bold": False},
    "md": {"size": 11, "bold": False},
    "lg": {"size": 13, "bold": True},
    "xl": {"size": 18, "bold": True},
    "xxl": {"size": 26, "bold": True},
    "hud_phase": {"size": 14, "bold": False},
    "hud_lvl": {"size": 12, "bold": False},
}

_FIXTURE_PALETTE = {
    "gold": [255, 200, 50],
    "red": [210, 55, 55],
    "hp_green": [55, 195, 55],
    "hp_red": [200, 55, 55],
    "green_stat": [80, 210, 80],
    "ui_panel": [42, 34, 68],
    "ui_border": [80, 65, 120],
    "ui_btn": [75, 60, 115],
    "ui_btn_hover": [110, 90, 160],
    "ui_btn_active": [60, 140, 60],
    "ui_btn_disabled": [50, 45, 70],
    "ui_text": [235, 225, 195],
    "ui_text_dim": [150, 140, 120],
    # `highlight` / `highlight2` / `range_highlight` were HERE until
    # VfxAuthoringPLAN VA-5 moved them — with C_MOVE_HIGHLIGHT and
    # C_TUTORIAL_HIGHLIGHT, which were never palette keys — into
    # data/balancing/vfx.json's `procedural.highlights`, so each value has one
    # home (G-7/D8) and every tile highlight is editable and previewable in
    # the VFX editor. `tools/tests/test_highlight_data.py` pins them now, in
    # this module's exact shape.
    "panel_stone": [40, 32, 58],
    "panel_inset": [150, 135, 185],
    "purple": [168, 105, 222],
}


def _snapshot_fonts():
    return dict(fonts._FONT_SPECS)


def _restore_fonts(snapshot):
    fonts._FONT_SPECS.clear()
    fonts._FONT_SPECS.update(snapshot)
    fonts._cache.clear()


def _snapshot_font_family():
    """The UH-Font-A globals, guarded SEPARATELY from ``_FONT_SPECS`` so
    ``_snapshot_fonts``'s plain-dict shape (which callers below index and
    ``.items()``) stays intact. A test that configures a custom font family
    and does not restore these leaves every LATER test in the process
    rendering in that font — the same poison the module docstring warns
    about for the size presets, two globals over."""
    return (fonts._FONT_PATH, fonts._FONT_BYTES)


def _restore_font_family(snapshot):
    fonts._FONT_PATH, fonts._FONT_BYTES = snapshot
    fonts._cache.clear()


def _palette_attr_names():
    return tuple("C_" + key.upper() for key in widgets._PALETTE_KEYS)


def _snapshot_palette():
    return {name: getattr(widgets, name) for name in _palette_attr_names()}


def _restore_palette(snapshot):
    for name, value in snapshot.items():
        setattr(widgets, name, value)


class _ConfigureMixin:
    """addCleanup-restores both module globals around any test that calls
    configure_fonts/configure_palette (mixed into every TestCase below that
    needs it, per the module docstring's standing order)."""

    def _protect_module_state(self):
        fonts_snapshot = _snapshot_fonts()
        palette_snapshot = _snapshot_palette()
        self.addCleanup(_restore_fonts, fonts_snapshot)
        self.addCleanup(_restore_palette, palette_snapshot)
        self.addCleanup(_restore_font_family, _snapshot_font_family())
        return fonts_snapshot, palette_snapshot


class TestStockParityPin(_ConfigureMixin, unittest.TestCase):
    """The crux (D5): configuring from the STOCK fixture docs must reproduce
    exactly today's rendering — the golden baseline never moves. Plan §5:
    "if this goes red, the phase is wrong, not the pin."."""

    def test_stock_docs_reproduce_golden_baseline(self):
        self._protect_module_state()
        fonts.configure_fonts(_FIXTURE_FONTS)
        widgets.configure_palette(_FIXTURE_PALETTE)
        captured = _screen_captures()
        self.assertEqual(set(captured), set(_BASELINE))
        for screen_id, items in captured.items():
            self.assertEqual(items, _BASELINE[screen_id],
                             f"{screen_id} drifted under stock theme data")


class TestFallbackEqualsStock(unittest.TestCase):
    """The unconfigured module defaults (bare test/tool construction, the
    ``ScreenSkinning.empty()`` precedent) must equal the fixture stock docs —
    kills silent dual-store drift between the Python literal and the JSON
    content it mirrors."""

    def test_font_specs_default_equals_fixture(self):
        for key, spec in _FIXTURE_FONTS.items():
            self.assertEqual(fonts._FONT_SPECS[key], (spec["size"], spec["bold"]),
                             f"font preset {key!r} drifted from its data fixture")

    def test_palette_defaults_equal_fixture(self):
        for key, rgb in _FIXTURE_PALETTE.items():
            attr = "C_" + key.upper()
            self.assertEqual(getattr(widgets, attr), tuple(rgb),
                             f"palette key {key!r} drifted from its data fixture")


class TestCustomFontFileIsNeverHeldOpen(_ConfigureMixin, unittest.TestCase):
    """UH-Font-A: ``configure_fonts(font_path=…)`` must SLURP the file, not
    hand its path to ``pygame.font.Font``.

    A path-built font makes SDL_ttf hold the file open for that object's
    whole life, and those objects sit in ``fonts._cache`` until the process
    exits — on Windows a hard lock that (a) leaves the editor sitting on the
    designer's font file for its whole run and (b) kills every
    ``TempDataCase`` teardown, since ``shutil.rmtree`` cannot unlink the
    copied ``.otf``. It went unnoticed until the first real font was made
    active, because the shipped pointer was ``"default"``.

    Deleting the file BEFORE building the fonts pins it on EVERY platform,
    not just the one with mandatory locking: on Windows the unlink itself
    fails while the handle is open, and on Linux/macOS the unlink succeeds
    but a path-built ``get_font`` then raises on the missing file. Only a
    genuinely read-once-into-memory implementation survives both."""

    def _font_file_copy(self):
        """A real ``.ttf`` from pygame's own package (``freesansbold.ttf``),
        copied into a tempdir. Deliberately NOT a font out of ``data/`` — the
        house rule is to pin the fixture rather than inherit whatever a
        designer last imported, and this test wants a font file it is free to
        delete."""
        import os
        import shutil
        import tempfile

        import pygame
        source = Path(pygame.__file__).parent / pygame.font.get_default_font()
        self.assertTrue(source.is_file(), f"pygame ships no {source.name}")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name) / "fixture_font.ttf"
        shutil.copyfile(source, target)
        return target, os.unlink

    def test_fonts_still_build_after_the_file_is_deleted(self):
        self._protect_module_state()
        font_file, unlink = self._font_file_copy()
        fonts.configure_fonts(_FIXTURE_FONTS, font_path=font_file)

        unlink(font_file)   # Windows: raises here if a handle is still open.
        self.assertFalse(font_file.exists())

        for key in _FIXTURE_FONTS:
            # Would raise FileNotFoundError if get_font resolved the path.
            self.assertGreater(fonts.get_font(key).size("Ag")[0], 0)

    def test_configure_rereads_the_file_rather_than_caching_a_path(self):
        """The bytes belong to the CONFIGURED font, so pointing the module
        back at ``None`` must drop them — otherwise a designer switching back
        to 'default' would keep rendering in the custom family."""
        self._protect_module_state()
        font_file, _ = self._font_file_copy()

        fonts.configure_fonts(_FIXTURE_FONTS, font_path=font_file)
        self.assertIsNotNone(fonts._FONT_BYTES)

        fonts.configure_fonts(_FIXTURE_FONTS)
        self.assertIsNone(fonts._FONT_BYTES)
        self.assertIsNone(fonts._FONT_PATH)


class TestLayoutHAuthority(_ConfigureMixin, unittest.TestCase):
    """``layout_h``/``_LAYOUT_H`` stay authoritative (plan §5): a
    ``configure_fonts`` call that changes every drawn size must NOT change
    the exporter's stored-layout output one bit. Mirrors
    ``test_layout_h_invariant.py``'s exporter-output test, with a real size
    bump standing in for that module's simulated font-metric drift."""

    def test_configure_fonts_does_not_move_exported_layouts(self):
        import tempfile

        snapshot, _ = self._protect_module_state()
        with tempfile.TemporaryDirectory() as tmp_a, \
                tempfile.TemporaryDirectory() as tmp_b:
            tmp_a, tmp_b = Path(tmp_a), Path(tmp_b)
            export_main(data_root=REPO / "data", output_dir=tmp_a)
            bumped = {key: {"size": size + 6, "bold": bold}
                     for key, (size, bold) in snapshot.items()}
            fonts.configure_fonts(bumped)
            export_main(data_root=REPO / "data", output_dir=tmp_b)
            bytes_a = (tmp_a / "ui" / "screen_defaults.json").read_bytes()
            bytes_b = (tmp_b / "ui" / "screen_defaults.json").read_bytes()
        self.assertEqual(bytes_a, bytes_b)


class TestTintSchemaAndFlow(unittest.TestCase):
    """The `tint` widget key (D6): schema-accepted at the color shape, and
    ``ScreenSkinning.apply``'s generic setattr loop threads a JSON list onto
    the widget as a tuple — no special-casing needed, same as `skin`."""

    def test_schema_accepts_tint(self):
        schema = data_io.load_json(REPO / "data" / "schemas" / "ui_screen.schema.json")
        jsonschema.validate(
            {"widgets": {"my_button": {"tint": [10, 20, 30]}}}, schema)

    def test_schema_rejects_short_tint(self):
        schema = data_io.load_json(REPO / "data" / "schemas" / "ui_screen.schema.json")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(
                {"widgets": {"my_button": {"tint": [10, 20]}}}, schema)

    def test_screen_skinning_apply_flows_tint_as_tuple(self):
        sk = ScreenSkinning.empty()
        sk._overrides = {"my_screen": {"widgets": {"btn": {"tint": [1, 2, 3]}}}}

        class _Holder:
            pass

        holder = _Holder()
        sk.apply("my_screen", {"btn": ("button", holder)})
        self.assertEqual(holder.tint, (1, 2, 3))
        self.assertIsInstance(holder.tint, tuple)


class TestPaletteRebindReachesConsumers(_ConfigureMixin, unittest.TestCase):
    """Proves the attribute-access re-point (game/ui/*.py) + the
    submit_panel default-arg sentinel fix actually work end to end: after
    ``configure_palette``, a screen submit emits the NEW color, not the
    stale one a leftover early-bound import would freeze."""

    def test_configured_gold_reaches_a_button_label(self):
        self._protect_module_state()
        widgets.configure_palette({**_FIXTURE_PALETTE, "gold": [1, 2, 3]})

        class _Rec:
            def __init__(self):
                self.calls = []

            def submit_hud(self, item):
                self.calls.append(item)

        # pause.py's title label is submitted in widgets.C_GOLD (module
        # attribute access, UH-6) — proves the re-point without importing
        # a whole screen module's dependency graph.
        rec = _Rec()
        from game.ui.widgets import submit_centered
        submit_centered(rec, "TEST", 10, 10, "md", widgets.C_GOLD)
        self.assertEqual(rec.calls[0].color, (1, 2, 3))

    def test_configured_panel_color_reaches_submit_panel_default(self):
        self._protect_module_state()
        widgets.configure_palette({**_FIXTURE_PALETTE, "ui_panel": [7, 8, 9]})

        class _Rec:
            def __init__(self):
                self.calls = []

            def submit_hud(self, item):
                self.calls.append(item)

        rec = _Rec()
        submit_panel(rec, (0, 0, 10, 10))   # no fill= override -> the default
        self.assertEqual(rec.calls[0].color, (7, 8, 9))


if __name__ == "__main__":
    unittest.main()
