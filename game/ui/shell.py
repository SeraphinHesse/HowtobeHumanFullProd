"""Top-level shell state machine (Phase 9H).

Pure logic — the state machine that wraps the in-round gameplay in an
application shell (intro cutscene, main menu, settings, credits, add-a-name,
pause, game over). Owns ``state`` (a ``game.core.GameState``), the menu screen
instances, and the session-only ``SessionSettings``. It routes clicks/keys to
the active screen and applies the *pure* transitions itself; anything that
physically touches pygame or disk is returned to the host as an **intent
string** (the established ``hit() -> "end_turn"`` convention):

  ``"new_game"``          build a fresh run          (host builds the world)
  ``"quit_to_menu"``      tear the run down          (host drops the world)
  ``"quit_app"``          leave the game
  ``"set_display_mode"``  re-create the window       (host applies the mode)
  ``"add_name_commit"``   persist the typed name     (host writes + reports back)

GAMEPLAY / GAME_OVER carry no shell screen (the host owns the HUD, building
panel, and game-over screen, which need the live world); the shell only tracks
that ``state`` so the host knows what to simulate/draw. CUTSCENE likewise has no
shell screen — the host blits the video frame.
"""
from game.core.phases import GameState

from .add_name import AddNameScreen
from .credits import CreditsScreen
from .main_menu import MainMenu
from .pause import PauseScreen
from .settings import SessionSettings, SettingsScreen
from .skinning import ScreenSkinning

_MENU_STATES = (GameState.MAIN_MENU, GameState.SETTINGS, GameState.CREDITS,
                GameState.ADD_NAME, GameState.PAUSED)


class Shell:
    def __init__(self, view_w, view_h, ui_balance,
                 start_state=GameState.MAIN_MENU, skinning=None):
        # 10L-B: shell owns ONE ScreenSkinning, shared by its five menu
        # screens; the host reads it back (``shell.skinning``) to thread the
        # same instance into the seven gameplay screens it builds itself
        # (Shell owns no world, so it cannot construct those).
        self.skinning = skinning or ScreenSkinning.empty()
        self.settings = SessionSettings.from_balance(ui_balance)
        self.main_menu = MainMenu(view_w, view_h, skinning=self.skinning)
        self.settings_screen = SettingsScreen(view_w, view_h, self.settings,
                                              skinning=self.skinning)
        self.credits = CreditsScreen(view_w, view_h, skinning=self.skinning)
        self.add_name_screen = AddNameScreen(view_w, view_h,
                                             skinning=self.skinning)
        self.pause = PauseScreen(view_w, view_h, skinning=self.skinning)
        self.state = start_state
        self.settings_caller = GameState.MAIN_MENU
        self._pool_count = 0

    # -- host-facing state helpers ---------------------------------------

    def enter_gameplay(self):
        """Host calls after a run's world is built (or on resume)."""
        self.state = GameState.GAMEPLAY

    def enter_game_over(self):
        """Host mirrors the session's GAME_OVER up to the shell."""
        self.state = GameState.GAME_OVER

    def to_main_menu(self):
        """Host calls after tearing a run down (game over -> menu)."""
        self.state = GameState.MAIN_MENU

    def open_settings(self, caller):
        self.settings_caller = caller
        self.state = GameState.SETTINGS

    def open_add_name(self):
        self.add_name_screen.reset(self._pool_count)
        self.state = GameState.ADD_NAME

    def set_pool_count(self, count):
        """Host keeps the shell's random-name pool count fresh (boot + commits)."""
        self._pool_count = count
        self.add_name_screen.pool_count = count

    def report_add_name(self, added, name):
        """Host reports a commit outcome so the add-name screen shows feedback."""
        self.add_name_screen.set_result(added, name, self._pool_count)

    @property
    def pending_name(self):
        """The name currently typed in the add-name screen (host reads on commit)."""
        return self.add_name_screen.name

    # -- input routing ---------------------------------------------------

    def handle_click(self, mx, my):
        st = self.state
        if st == GameState.MAIN_MENU:
            return self._main_menu_click(mx, my)
        if st == GameState.SETTINGS:
            return self._settings_click(mx, my)
        if st == GameState.CREDITS:
            if self.credits.hit(mx, my) == "back":
                self.state = GameState.MAIN_MENU
            return None
        if st == GameState.ADD_NAME:
            return self._add_name_action(self.add_name_screen.hit(mx, my))
        if st == GameState.PAUSED:
            return self._pause_click(mx, my)
        return None

    def handle_key(self, char, key):
        st = self.state
        if st == GameState.ADD_NAME:
            return self._add_name_action(
                self.add_name_screen.handle_key(char, key))
        if key == "escape":
            if st == GameState.SETTINGS:
                self.state = self.settings_caller
            elif st == GameState.CREDITS:
                self.state = GameState.MAIN_MENU
            elif st == GameState.PAUSED:
                self.state = GameState.GAMEPLAY
        return None

    def _main_menu_click(self, mx, my):
        action = self.main_menu.hit(mx, my)
        if action == "new_game":
            return "new_game"
        if action == "quit":
            return "quit_app"
        if action == "settings":
            self.open_settings(GameState.MAIN_MENU)
        elif action == "credits":
            self.state = GameState.CREDITS
        elif action == "add_name":
            self.open_add_name()
        return None

    def _settings_click(self, mx, my):
        action = self.settings_screen.hit(mx, my)
        if action == "back":
            self.state = self.settings_caller
            return None
        if action == "set_display_mode":
            return "set_display_mode"
        return None

    def _pause_click(self, mx, my):
        action = self.pause.hit(mx, my)
        if action == "resume":
            self.state = GameState.GAMEPLAY
        elif action == "settings":
            self.open_settings(GameState.PAUSED)
        elif action == "quit_to_menu":
            self.state = GameState.MAIN_MENU
            return "quit_to_menu"
        elif action == "quit":
            return "quit_app"
        return None

    def _add_name_action(self, action):
        if action == "back":
            self.state = GameState.MAIN_MENU
        elif action == "add":
            return "add_name_commit"
        return None

    # -- per-frame -------------------------------------------------------

    def _active_screen(self):
        return {
            GameState.MAIN_MENU: self.main_menu,
            GameState.SETTINGS: self.settings_screen,
            GameState.CREDITS: self.credits,
            GameState.ADD_NAME: self.add_name_screen,
            GameState.PAUSED: self.pause,
        }.get(self.state)

    @property
    def in_menu(self):
        """True while a full-screen menu owns the frame (no world drawn)."""
        return self.state in (GameState.MAIN_MENU, GameState.SETTINGS,
                              GameState.CREDITS, GameState.ADD_NAME)

    def update(self, dt, mx, my, mouse_down=False):
        screen = self._active_screen()
        if screen is not None:
            screen.update(dt, mx, my, mouse_down)

    def submit(self, renderer, view_w, view_h):
        screen = self._active_screen()
        if screen is not None:
            screen.submit(renderer, view_w, view_h)
