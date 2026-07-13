"""Phase 9H: the pure top-level Shell state machine + game.ui purity.

Drives the shell with synthetic clicks (aimed at real button centres) and keys,
asserting the state transitions + emitted host intents. No pygame, no SDL — the
whole shell + its screens are rect math and enum transitions.
"""
import unittest
from pathlib import Path

from engine.assets.types import Frame
from engine.coords import Camera, CoordinateSystem, Geometry
from engine.render import DrawCall, HudRect, HudText, Renderer
from game.core import load_balance
from game.core.phases import GameState
from game.ui import Shell

REPO = Path(__file__).resolve().parents[2]
VW, VH = 1280, 720


class _FakeAssets:
    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        return Frame(surface=f"SURF:{slot_key}", frame_w=64, frame_h=64)


class _RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


def _renderer():
    geo = Geometry(tile_w=64, tile_h=32, map_cols=20, map_rows=20,
                   zoom_levels=(1.0,))
    cs = CoordinateSystem(geo, Camera())
    backend = _RecordingBackend()
    return Renderer(cs, _FakeAssets(), backend=backend), backend


def center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


def make_shell(start=GameState.MAIN_MENU):
    ui = load_balance(REPO / "data", "ui")
    return Shell(VW, VH, ui, start_state=start)


def click_action(shell, screen, action):
    """Click the button on ``screen`` whose action is ``action`` (main menu /
    pause list-of-(btn, action) shape)."""
    for btn, act in screen.buttons:
        if act == action:
            return shell.handle_click(*center(btn.rect))
    raise AssertionError(f"no button for {action}")


class TestMainMenu(unittest.TestCase):
    def test_new_game_intent(self):
        s = make_shell()
        self.assertEqual(click_action(s, s.main_menu, "new_game"), "new_game")
        self.assertEqual(s.state, GameState.MAIN_MENU)  # host drives the switch

    def test_quit_intent(self):
        s = make_shell()
        self.assertEqual(click_action(s, s.main_menu, "quit"), "quit_app")

    def test_open_settings_from_menu(self):
        s = make_shell()
        self.assertIsNone(click_action(s, s.main_menu, "settings"))
        self.assertEqual(s.state, GameState.SETTINGS)
        self.assertEqual(s.settings_caller, GameState.MAIN_MENU)

    def test_open_credits_and_back(self):
        s = make_shell()
        click_action(s, s.main_menu, "credits")
        self.assertEqual(s.state, GameState.CREDITS)
        s.handle_click(*center(s.credits.back_btn.rect))
        self.assertEqual(s.state, GameState.MAIN_MENU)

    def test_open_add_name_resets_field(self):
        s = make_shell()
        s.add_name_screen.name = "stale"
        click_action(s, s.main_menu, "add_name")
        self.assertEqual(s.state, GameState.ADD_NAME)
        self.assertEqual(s.add_name_screen.name, "")


class TestSettings(unittest.TestCase):
    def test_back_returns_to_caller(self):
        s = make_shell()
        s.open_settings(GameState.PAUSED)
        s.handle_click(*center(s.settings_screen.back_btn.rect))
        self.assertEqual(s.state, GameState.PAUSED)

    def test_display_mode_cycles_and_emits_intent(self):
        s = make_shell(GameState.SETTINGS)
        before = s.settings.display_mode
        intent = s.handle_click(*center(s.settings_screen.dm_right.rect))
        self.assertEqual(intent, "set_display_mode")
        self.assertNotEqual(s.settings.display_mode, before)

    def test_fx_toggle_flips_setting(self):
        s = make_shell(GameState.SETTINGS)
        before = s.settings.gore
        _attr, _label, btn = next(t for t in s.settings_screen.toggles
                                  if t[0] == "gore")
        self.assertIsNone(s.handle_click(*center(btn.rect)))
        self.assertEqual(s.settings.gore, not before)

    def test_escape_backs_out(self):
        s = make_shell()
        s.open_settings(GameState.MAIN_MENU)
        s.handle_key("", "escape")
        self.assertEqual(s.state, GameState.MAIN_MENU)


class TestAddName(unittest.TestCase):
    def test_typing_builds_name(self):
        s = make_shell(GameState.ADD_NAME)
        s.add_name_screen.reset(3)
        for ch in "Zoe":
            s.handle_key(ch, None)
        self.assertEqual(s.pending_name, "Zoe")

    def test_enter_emits_commit_intent(self):
        s = make_shell(GameState.ADD_NAME)
        s.add_name_screen.reset(3)
        self.assertEqual(s.handle_key("\r", "return"), "add_name_commit")

    def test_add_button_emits_commit(self):
        s = make_shell(GameState.ADD_NAME)
        self.assertEqual(s.handle_click(*center(s.add_name_screen.add_btn.rect)),
                         "add_name_commit")

    def test_report_added_clears_and_counts(self):
        s = make_shell(GameState.ADD_NAME)
        s.add_name_screen.name = "Zoe"
        s.set_pool_count(12)
        s.report_add_name(True, "Zoe")
        self.assertEqual(s.add_name_screen.name, "")
        self.assertEqual(s.add_name_screen.pool_count, 12)

    def test_back_button_to_menu(self):
        s = make_shell(GameState.ADD_NAME)
        s.handle_click(*center(s.add_name_screen.back_btn.rect))
        self.assertEqual(s.state, GameState.MAIN_MENU)

    def test_escape_backs_out(self):
        s = make_shell(GameState.ADD_NAME)
        self.assertIsNone(s.handle_key("", "escape"))
        self.assertEqual(s.state, GameState.MAIN_MENU)


class TestPause(unittest.TestCase):
    def test_resume(self):
        s = make_shell(GameState.PAUSED)
        self.assertIsNone(click_action(s, s.pause, "resume"))
        self.assertEqual(s.state, GameState.GAMEPLAY)

    def test_settings_from_pause_and_back(self):
        s = make_shell(GameState.PAUSED)
        click_action(s, s.pause, "settings")
        self.assertEqual(s.state, GameState.SETTINGS)
        self.assertEqual(s.settings_caller, GameState.PAUSED)
        s.handle_click(*center(s.settings_screen.back_btn.rect))
        self.assertEqual(s.state, GameState.PAUSED)

    def test_quit_to_menu_intent(self):
        s = make_shell(GameState.PAUSED)
        self.assertEqual(click_action(s, s.pause, "quit_to_menu"), "quit_to_menu")
        self.assertEqual(s.state, GameState.MAIN_MENU)

    def test_quit_app_intent(self):
        s = make_shell(GameState.PAUSED)
        self.assertEqual(click_action(s, s.pause, "quit"), "quit_app")

    def test_escape_resumes(self):
        s = make_shell(GameState.PAUSED)
        s.handle_key("", "escape")
        self.assertEqual(s.state, GameState.GAMEPLAY)


class TestHostHelpers(unittest.TestCase):
    def test_gameplay_and_game_over_and_menu(self):
        s = make_shell()
        s.enter_gameplay()
        self.assertEqual(s.state, GameState.GAMEPLAY)
        s.enter_game_over()
        self.assertEqual(s.state, GameState.GAME_OVER)
        s.to_main_menu()
        self.assertEqual(s.state, GameState.MAIN_MENU)

    def test_no_screen_for_world_states(self):
        s = make_shell(GameState.GAMEPLAY)
        self.assertIsNone(s._active_screen())  # host owns HUD/game-over
        self.assertFalse(s.in_menu)


class TestScreenRender(unittest.TestCase):
    """Every shell screen's submit() emits HUD primitives without crashing —
    headless render coverage for the paths a live click can't reach in CI."""

    def _submit(self, state):
        s = make_shell(state)
        if state == GameState.ADD_NAME:
            s.add_name_screen.reset(5)
        r, _ = _renderer()
        s.submit(r, VW, VH)
        n = r.flush(target=None)
        self.assertGreater(n, 0, f"{state} rendered nothing")

    def test_main_menu_renders(self):
        self._submit(GameState.MAIN_MENU)

    def test_settings_renders(self):
        self._submit(GameState.SETTINGS)

    def test_credits_renders(self):
        self._submit(GameState.CREDITS)

    def test_add_name_renders(self):
        self._submit(GameState.ADD_NAME)

    def test_pause_renders(self):
        self._submit(GameState.PAUSED)

    def test_world_states_render_nothing_from_shell(self):
        # GAMEPLAY/GAME_OVER: the host owns the HUD; the shell draws nothing.
        s = make_shell(GameState.GAMEPLAY)
        r, _ = _renderer()
        s.submit(r, VW, VH)
        self.assertEqual(r.flush(target=None), 0)

    def test_main_menu_bg_art_between_fill_and_text(self):
        # 10K: the full-view main_menu_bg DrawCall sits over the solid
        # fallback fill and under every text/button primitive
        s = make_shell(GameState.MAIN_MENU)
        r, backend = _renderer()
        s.submit(r, VW, VH)
        r.flush(target=None)
        calls = backend.calls
        bg_i = next(i for i, c in enumerate(calls)
                    if isinstance(c, DrawCall)
                    and c.surface == "SURF:main_menu_bg")
        self.assertEqual(calls[bg_i].dest, (0, 0))
        self.assertEqual(calls[bg_i].size, (VW, VH))
        fill_i = next(i for i, c in enumerate(calls)
                      if isinstance(c, HudRect) and c.rect == (0, 0, VW, VH))
        first_text_i = next(i for i, c in enumerate(calls)
                            if isinstance(c, HudText))
        self.assertLess(fill_i, bg_i)
        self.assertLess(bg_i, first_text_i)


class TestPurity(unittest.TestCase):
    """game.ui (incl. the 9H shell) never imports pygame DIRECTLY — it emits
    engine HUD primitives and measures via engine.render.fonts.TextMetrics
    (which is a sanctioned pygame-touching module, so game.ui imports pygame
    only transitively). A source scan enforces the stated 'no pygame' invariant
    without tripping over that legitimate transitive edge."""

    def test_game_ui_has_no_direct_pygame_import(self):
        offenders = []
        for path in (REPO / "game" / "ui").glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith(("import pygame", "from pygame")):
                    offenders.append(path.name)
        self.assertEqual(offenders, [],
                         f"game/ui imports pygame directly: {offenders}")


if __name__ == "__main__":
    unittest.main()
