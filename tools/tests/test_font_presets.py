"""UL-2 (D6): designer-defined font presets — extra keys in
``data/ui/fonts.json`` beyond the 7 shipped ones.

Three claims, in one place: the schema ACCEPTS a well-named extra key (and
still refuses a badly-named one), ``configure_fonts`` accepts it while staying
LOUD about a missing required key, and its ``layout_h`` entry is DERIVED once
at configure time without ever touching the 7 pinned entries.

Every test that calls ``configure_fonts`` ``addCleanup``-restores the module
globals, per ``test_theme_data.py``'s standing order — **extended here to
cover ``fonts._LAYOUT_H``**, which this phase is the first thing ever to
mutate at runtime. A leaked custom entry there would poison whichever layout
test runs next in the same process (``test_ui_skinning.py``'s golden
baseline, ``test_layout_h_invariant.py``), exactly the way a leaked
``_FONT_SPECS`` entry already can.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import jsonschema

from editor import theme_ops
from engine import data_io
from engine.render import fonts

REPO = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = REPO / "data" / "schemas" / "fonts.schema.json"

# The 7 shipped presets, hardcoded (never read from the live data/ tree —
# house rule, same as test_theme_data._FIXTURE_FONTS).
_STOCK = {
    "sm": {"size": 9, "bold": False},
    "md": {"size": 11, "bold": False},
    "lg": {"size": 13, "bold": True},
    "xl": {"size": 18, "bold": True},
    "xxl": {"size": 26, "bold": True},
    "hud_phase": {"size": 14, "bold": False},
    "hud_lvl": {"size": 12, "bold": False},
}

_CUSTOM_KEY = "title_big"
_CUSTOM_SPEC = {"size": 34, "bold": True}


def _doc(**extra):
    doc = {key: dict(spec) for key, spec in _STOCK.items()}
    doc.update(extra)
    return doc


def _schema():
    return data_io.load_json(_SCHEMA_PATH)


class _FontsStateMixin:
    """Restores ``_FONT_SPECS``, ``_LAYOUT_H``, the font-family globals and
    the cache. ``_LAYOUT_H`` is the addition over ``test_theme_data.py``'s
    ``_snapshot_fonts``/``_restore_fonts`` — see the module docstring."""

    def _protect_fonts(self):
        specs = dict(fonts._FONT_SPECS)
        layout = dict(fonts._LAYOUT_H)
        family = (fonts._FONT_PATH, fonts._FONT_BYTES)

        def restore():
            fonts._FONT_SPECS.clear()
            fonts._FONT_SPECS.update(specs)
            fonts._LAYOUT_H.clear()
            fonts._LAYOUT_H.update(layout)
            fonts._FONT_PATH, fonts._FONT_BYTES = family
            fonts._cache.clear()

        self.addCleanup(restore)
        return layout


class TestSchemaAcceptsExtraPresets(unittest.TestCase):
    """``patternProperties`` opens the doc to designer keys — but only ones
    shaped like a key, and only with the same ``{size, bold}`` body."""

    def test_stock_seven_still_validate(self):
        jsonschema.validate(_doc(), _schema())

    def test_a_well_named_extra_preset_validates(self):
        jsonschema.validate(_doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)}), _schema())

    def test_a_badly_named_extra_preset_is_rejected(self):
        for bad in ("Title_Big", "1title", "title big", "title-big", ""):
            with self.subTest(name=bad):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(_doc(**{bad: dict(_CUSTOM_SPEC)}), _schema())

    def test_an_extra_preset_still_obeys_the_font_spec_shape(self):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(_doc(title_big={"size": 999, "bold": True}), _schema())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(_doc(title_big={"size": 12}), _schema())

    def test_a_missing_shipped_preset_is_still_rejected(self):
        doc = _doc()
        doc.pop("xxl")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, _schema())


class TestConfigureFontsAcceptsExtras(_FontsStateMixin, unittest.TestCase):

    def test_custom_key_reaches_font_specs(self):
        self._protect_fonts()
        fonts.configure_fonts(_doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)}))
        self.assertEqual(fonts._FONT_SPECS[_CUSTOM_KEY], (34, True))

    def test_a_missing_shipped_key_still_raises(self):
        """The relaxation drops the UNKNOWN-key half only: dropping one of
        the 7 must stay loud, or a screen naming it would silently draw at
        the 'md' fallback."""
        self._protect_fonts()
        doc = _doc()
        doc.pop("lg")
        with self.assertRaises(ValueError):
            fonts.configure_fonts(doc)

    def test_required_key_check_survives_an_earlier_custom_configure(self):
        """``_REQUIRED_KEYS`` is a frozen import-time snapshot, not a live
        read of ``_FONT_SPECS`` — otherwise the custom key written by the
        FIRST call would count as required in the second."""
        self._protect_fonts()
        fonts.configure_fonts(_doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)}))
        fonts.configure_fonts(_doc())   # no custom key: must NOT raise
        self.assertEqual(fonts._REQUIRED_KEYS, frozenset(_STOCK))


class TestDerivedLayoutHeight(_FontsStateMixin, unittest.TestCase):
    """The custom key gets a REAL derived height, once, at configure time —
    and the 7 pinned entries never move."""

    def test_custom_key_gets_a_derived_height(self):
        self._protect_fonts()
        fonts.configure_fonts(_doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)}))
        height = fonts.layout_h(_CUSTOM_KEY)
        self.assertIsInstance(height, int)
        self.assertIn(_CUSTOM_KEY, fonts._LAYOUT_H)
        # A 34pt preset cannot legitimately measure at or below the 11pt
        # 'md' fallback — so this is the derivation actually running, not
        # layout_h falling through to _FALLBACK_KEY.
        self.assertGreater(height, fonts.layout_h("md"))

    def test_reconfigure_keeps_the_custom_height(self):
        self._protect_fonts()
        doc = _doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)})
        fonts.configure_fonts(doc)
        first = fonts.layout_h(_CUSTOM_KEY)
        fonts.configure_fonts(doc)
        self.assertEqual(fonts.layout_h(_CUSTOM_KEY), first)

    def test_the_seven_pinned_heights_are_never_rederived(self):
        pinned = self._protect_fonts()
        bumped = {key: {"size": spec["size"] + 6, "bold": spec["bold"]}
                  for key, spec in _STOCK.items()}
        bumped[_CUSTOM_KEY] = dict(_CUSTOM_SPEC)
        fonts.configure_fonts(bumped)
        for key in _STOCK:
            with self.subTest(key=key):
                self.assertEqual(fonts._LAYOUT_H[key], pinned[key])

    def test_an_unconfigured_key_still_falls_back_to_md(self):
        self._protect_fonts()
        fonts.configure_fonts(_doc())
        self.assertEqual(fonts.layout_h("never_defined"), fonts.layout_h("md"))


class TestPresetNameRules(unittest.TestCase):
    """``theme_ops``'s pure helpers — ONE home for the rule the schema's
    ``patternProperties`` also encodes."""

    def test_valid_names(self):
        for name in ("title_big", "a", "h2", "menu_title_2"):
            with self.subTest(name=name):
                self.assertTrue(theme_ops.is_valid_preset_name(name, _STOCK))

    def test_invalid_names(self):
        for name in ("Title", "1big", "big title", "big-title", "", None):
            with self.subTest(name=name):
                self.assertFalse(theme_ops.is_valid_preset_name(name, _STOCK))

    def test_a_name_that_already_exists_is_refused(self):
        self.assertFalse(theme_ops.is_valid_preset_name("md", _STOCK))
        self.assertFalse(
            theme_ops.is_valid_preset_name("title_big", ("title_big",)))

    def test_the_seven_shipped_presets_are_pinned(self):
        for key in _STOCK:
            with self.subTest(key=key):
                self.assertTrue(theme_ops.is_pinned_preset(key))
        self.assertFalse(theme_ops.is_pinned_preset(_CUSTOM_KEY))


class TestFontKeysSeeCustomPresets(unittest.TestCase):
    """``theme_ops.font_keys`` is the single source both of
    ``screen_details.py``'s font combos (``_populate_font_combo`` feeds
    ``font_combo`` AND ``default_font_combo`` from it), so a custom preset
    written to fonts.json is assignable per widget with no combo change."""

    def _temp_tree(self, doc):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "schemas").mkdir()
        (tmp / "ui").mkdir()
        shutil.copy(_SCHEMA_PATH, tmp / "schemas" / "fonts.schema.json")
        theme_ops.write_fonts(doc, tmp)
        return tmp

    def test_a_custom_preset_survives_write_validated_and_shows_up(self):
        tmp = self._temp_tree(_doc(**{_CUSTOM_KEY: dict(_CUSTOM_SPEC)}))
        self.assertIn(_CUSTOM_KEY, theme_ops.font_keys(tmp))
        on_disk = json.loads(
            theme_ops.fonts_path(tmp).read_text(encoding="utf-8"))
        self.assertEqual(on_disk[_CUSTOM_KEY], _CUSTOM_SPEC)

    def test_a_badly_named_preset_cannot_be_written(self):
        tmp = self._temp_tree(_doc())
        with self.assertRaises(Exception):
            theme_ops.write_fonts(_doc(**{"Title": dict(_CUSTOM_SPEC)}), tmp)


if __name__ == "__main__":
    unittest.main()
