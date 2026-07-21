"""Phase A5' (10L-A): skinned ``widgets.Button`` / ``submit_panel`` + the R2
pixel-perfect hit seam.

Pure + headless: ``game/ui`` never imports pygame, so a 5-line recording fake
renderer is enough — no SDL, no ``Renderer``. The crux of the phase is
``test_unskinned_button_parity``: with ``skin=None`` the emitted primitive
stream must be byte-identical to pre-10L, field for field.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine.render import HudRect, HudSprite, HudText
from game.core import load_balance
from game.ui import Shell
from game.ui import widgets
from game.ui.widgets import (
    C_RED, C_UI_BORDER, C_UI_BTN, C_UI_BTN_DISABLED, C_UI_BTN_HOVER,
    C_UI_PANEL, C_UI_TEXT, C_UI_TEXT_DIM, Button, anim_ms, submit_panel,
    text_h,
)

UI = load_balance(FIXTURE_DATA, "ui")
RECT = (10, 20, 100, 30)


class _Rec:
    """Records every ``submit_hud(item)`` call, in order — no pygame."""

    def __init__(self):
        self.calls = []

    def submit_hud(self, item):
        self.calls.append(item)


def _center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


class TestUnskinnedButtonParity(unittest.TestCase):
    """The crux of the phase: skin=None must emit exactly what pre-10L did."""

    def _submit(self, btn, **kw):
        rec = _Rec()
        btn.submit(rec, **kw)
        return rec.calls

    def _expected(self, fill, tcol, label, font_key="md"):
        ty = 20 + (30 - text_h(font_key)) // 2
        return [
            HudRect(RECT, fill, border_radius=3),
            HudRect(RECT, C_UI_BORDER, border_radius=3, width=1),
            HudText(label, (60, ty), font_key, tcol, align="center"),
        ]

    def test_unskinned_button_parity(self):
        cases = {}

        normal = Button(RECT, "GO", font_key="md")
        cases["normal"] = (normal, self._expected(C_UI_BTN, C_UI_TEXT, "GO"))

        hovered = Button(RECT, "GO", font_key="md")
        hovered.hover(*_center(RECT))
        cases["hovered"] = (
            hovered, self._expected(C_UI_BTN_HOVER, C_UI_TEXT, "GO"))

        disabled = Button(RECT, "GO", font_key="md", enabled=False)
        disabled.hover(*_center(RECT))
        cases["disabled"] = (
            disabled, self._expected(C_UI_BTN_DISABLED, C_UI_TEXT_DIM, "GO"))

        flashing = Button(RECT, "GO", font_key="md")
        flashing.start_flash(1.0)
        cases["flashing"] = (
            flashing, self._expected(C_RED, C_UI_TEXT, "GO"))

        # Row 3/4 collapse (Sec 1.4): hovered+pressed renders like plain hover.
        pressed = Button(RECT, "GO", font_key="md")
        pressed.hover(*_center(RECT), mouse_down=True)
        self.assertTrue(pressed.pressed)
        cases["pressed_renders_as_hovered"] = (
            pressed, self._expected(C_UI_BTN_HOVER, C_UI_TEXT, "GO"))

        for name, (btn, expected) in cases.items():
            with self.subTest(state=name):
                calls = self._submit(btn)
                self.assertEqual(calls, expected)
                self.assertFalse(any(isinstance(c, HudSprite) for c in calls))

    def test_color_and_text_color_overrides_still_work(self):
        """``overlays.py``'s ``btn.submit(renderer, color=..., text_color=...)``
        active-toggle call form (normal branch only)."""
        btn = Button(RECT, "GO", font_key="md")
        calls = self._submit(btn, color=(1, 2, 3), text_color=(4, 5, 6))
        self.assertEqual(calls, self._expected((1, 2, 3), (4, 5, 6), "GO"))


class TestUnskinnedPanelParity(unittest.TestCase):
    def test_unskinned_panel_parity(self):
        rec = _Rec()
        submit_panel(rec, (0, 0, 40, 50))
        self.assertEqual(rec.calls, [
            HudRect((0, 0, 40, 50), C_UI_PANEL),
            HudRect((0, 0, 40, 50), C_UI_BORDER, width=1),
        ])
        self.assertFalse(any(isinstance(c, HudSprite) for c in rec.calls))

    def test_custom_fill_and_border_still_honoured(self):
        rec = _Rec()
        submit_panel(rec, (0, 0, 40, 50), fill=(9, 9, 9), border=(1, 1, 1))
        self.assertEqual(rec.calls, [
            HudRect((0, 0, 40, 50), (9, 9, 9)),
            HudRect((0, 0, 40, 50), (1, 1, 1), width=1),
        ])


class TestSkinnedButton(unittest.TestCase):
    def test_skinned_button_emits_sprite_plus_label(self):
        unskinned = Button(RECT, "GO", font_key="md")
        rec_u = _Rec()
        unskinned.submit(rec_u)
        expected_label = rec_u.calls[-1]
        self.assertIsInstance(expected_label, HudText)

        skinned = Button(RECT, "GO", font_key="md", skin="ui_button")
        rec = _Rec()
        skinned.submit(rec, anim_ms=1234)
        self.assertEqual(len(rec.calls), 2)
        sprite, label = rec.calls
        self.assertEqual(sprite, HudSprite(
            "ui_button", (10, 20), (100, 30), animation="idle",
            anim_time_ms=1234))
        self.assertEqual(label, expected_label)
        self.assertFalse(any(isinstance(c, HudRect) for c in rec.calls))

    def test_skinned_state_rows(self):
        # idle
        idle = Button(RECT, "GO", skin="ui_button")
        self.assertEqual(idle._state(), "idle")

        # hovered -> "hover"
        hovered = Button(RECT, "GO", skin="ui_button")
        hovered.hover(*_center(RECT))
        self.assertEqual(hovered._state(), "hover")

        # hovered + mouse_down -> "pressed"
        pressed = Button(RECT, "GO", skin="ui_button")
        pressed.hover(*_center(RECT), mouse_down=True)
        self.assertEqual(pressed._state(), "pressed")

        # disabled -> "disabled"
        disabled = Button(RECT, "GO", skin="ui_button", enabled=False)
        disabled.hover(*_center(RECT), mouse_down=True)
        self.assertEqual(disabled._state(), "disabled")

        # flash beats disabled -> "pressed", flash_label overlay unchanged
        flashing = Button(RECT, "GO", skin="ui_button", enabled=False)
        flashing.start_flash(0.5, label="NOT ENOUGH LOVE")
        self.assertEqual(flashing._state(), "pressed")
        rec = _Rec()
        flashing.submit(rec)
        sprite, label = rec.calls
        self.assertEqual(sprite.animation, "pressed")
        self.assertEqual(label.text, "NOT ENOUGH LOVE")

    def test_skinned_panel(self):
        rec = _Rec()
        submit_panel(rec, RECT, skin="ui_panel", anim_ms=99)
        self.assertEqual(rec.calls, [
            HudSprite("ui_panel", (10, 20), (100, 30), animation="idle",
                     anim_time_ms=99),
        ])
        self.assertFalse(any(isinstance(c, HudRect) for c in rec.calls))

    def test_pressed_property(self):
        cx, cy = _center(RECT)
        outside = (RECT[0] - 50, RECT[1] - 50)

        default_call = Button(RECT, "GO")
        default_call.hover(cx, cy)  # no mouse_down arg
        self.assertFalse(default_call.pressed)

        inside_down = Button(RECT, "GO")
        inside_down.hover(cx, cy, mouse_down=True)
        self.assertTrue(inside_down.pressed)

        outside_down = Button(RECT, "GO")
        outside_down.hover(*outside, mouse_down=True)
        self.assertFalse(outside_down.pressed)

        disabled_down = Button(RECT, "GO", enabled=False)
        disabled_down.hover(cx, cy, mouse_down=True)
        self.assertFalse(disabled_down.pressed)


class TestScreenThreading(unittest.TestCase):
    def test_screen_threads_mouse_down_and_clock(self):
        shell = Shell(1280, 720, UI)
        mm = shell.main_menu
        btn = mm.buttons[0][0]
        cx, cy = _center(btn.rect)

        shell.update(0.1, cx, cy, True)
        self.assertTrue(btn.pressed)

        for _ in range(9):
            shell.update(0.1, cx, cy, True)
        self.assertEqual(anim_ms(mm._clock), 1000)


class TestR2HitSeam(unittest.TestCase):
    """The host-injected per-pixel alpha hit test. Every test that wires a fake
    seam MUST clean it up — an unset seam is the module-level default that
    every other test in the suite silently relies on."""

    def setUp(self):
        widgets.set_skin_hit_test(None)

    def tearDown(self):
        widgets.set_skin_hit_test(None)

    def test_no_seam_or_no_skin_is_rect_only(self):
        plain = Button(RECT, "GO")
        plain.hover(15, 25)
        self.assertTrue(plain.hovered)
        plain.hover(5, 5)
        self.assertFalse(plain.hovered)

        skinned = Button(RECT, "GO", skin="ui_button")
        skinned.hover(15, 25)
        self.assertTrue(skinned.hovered)  # still rect: seam unset
        skinned.hover(5, 5)
        self.assertFalse(skinned.hovered)

    def test_hover_and_hit_respect_the_injected_hit_test(self):
        cx, cy = _center(RECT)

        widgets.set_skin_hit_test(lambda *_: False)
        self.addCleanup(widgets.set_skin_hit_test, None)
        refused_hover = Button(RECT, "GO", skin="ui_button")
        refused_hover.hover(cx, cy)
        self.assertFalse(refused_hover.hovered)  # fake refused
        refused_hit = Button(RECT, "GO", skin="ui_button")
        self.assertFalse(refused_hit.hit(cx, cy))  # fake refused

        widgets.set_skin_hit_test(lambda *_: True)
        accepted_hover = Button(RECT, "GO", skin="ui_button")
        accepted_hover.hover(cx, cy)
        self.assertTrue(accepted_hover.hovered)
        accepted_hit = Button(RECT, "GO", skin="ui_button")
        self.assertTrue(accepted_hit.hit(cx, cy))

    def test_hit_seam_receives_canonical_silhouette(self):
        calls = []

        def _spy(*args):
            calls.append(args)
            return True

        widgets.set_skin_hit_test(_spy)
        self.addCleanup(widgets.set_skin_hit_test, None)

        x, y = 50, 30  # inside RECT = (10, 20, 100, 30)
        btn = Button(RECT, "GO", skin="ui_button")
        btn.hover(x, y)

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0], ("ui_button", "idle", 0, (100, 30), (40, 10)))

    def test_panels_have_no_hit_test(self):
        calls = []

        def _spy(*args):
            calls.append(args)
            return True

        widgets.set_skin_hit_test(_spy)
        self.addCleanup(widgets.set_skin_hit_test, None)

        rec = _Rec()
        submit_panel(rec, RECT, skin="ui_panel", anim_ms=50)
        self.assertEqual(len(calls), 0)
        self.assertTrue(any(isinstance(c, HudSprite) for c in rec.calls))


class TestTint(unittest.TestCase):
    """D6/UH-6: an optional per-widget `tint` (a sheet-multiply color) rides
    the same HudSprite a skin already emits. Omitted = ``None`` = today's
    rendering — the two parity tests above (``test_skinned_button_emits_
    sprite_plus_label`` / ``test_skinned_panel``) already pin that byte-for-
    byte; these add the "present" half."""

    def test_skinned_button_with_tint_emits_it_on_the_sprite(self):
        btn = Button(RECT, "GO", skin="ui_button")
        btn.tint = (10, 20, 30)   # the override setattrs this (ScreenSkinning.apply)
        rec = _Rec()
        btn.submit(rec, anim_ms=5)
        sprite, _label = rec.calls
        self.assertEqual(sprite.tint, (10, 20, 30))

    def test_skinned_button_without_tint_attr_is_none(self):
        # A dynamic (non-id'd) button never gains a `.tint` attribute at
        # all — getattr(..., None) must not raise.
        btn = Button(RECT, "GO", skin="ui_button")
        rec = _Rec()
        btn.submit(rec)
        sprite, _label = rec.calls
        self.assertIsNone(sprite.tint)

    def test_submit_panel_with_tint(self):
        rec = _Rec()
        submit_panel(rec, RECT, skin="ui_panel", tint=(40, 50, 60), anim_ms=1)
        self.assertEqual(rec.calls, [
            HudSprite("ui_panel", (10, 20), (100, 30), tint=(40, 50, 60),
                     animation="idle", anim_time_ms=1),
        ])

    def test_submit_panel_without_tint_is_none(self):
        rec = _Rec()
        submit_panel(rec, RECT, skin="ui_panel", anim_ms=1)
        sprite = rec.calls[0]
        self.assertIsNone(sprite.tint)


if __name__ == "__main__":
    unittest.main()
