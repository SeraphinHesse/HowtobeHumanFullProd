"""Top-level shell state machine (Phase 9H).

Pure logic — the state machine that wraps the in-round gameplay in an
application shell (intro cutscene, main menu, settings, credits, add-a-name,
pause, game over). Owns ``state`` (a ``game.core.GameState``), the menu screen
instances, and the session-only ``SessionSettings``. It routes clicks/keys to
the active screen and applies the *pure* transitions itself; anything that
physically touches pygame or disk is returned to the host as an **intent
string** (the established ``hit() -> "end_turn"`` convention):

  ``"new_game"``          build a fresh run          (host builds the world)
  ``"new_game_debug"``    build a fresh run WITH a   (host builds the recorder
                          DebugRecorder armed        from ``shell.debug_settings``,
                                                     then the world)
  ``"quit_to_menu"``      tear the run down          (host drops the world)
  ``"quit_app"``          leave the game
  ``"set_display_mode"``  re-create the window       (host applies the mode)
  ``"add_name_commit"``   persist the typed name     (host writes + reports back)
  ``"open_highscores"``   the table just opened      (host RE-READS the scores
                                                     file so a just-finished run
                                                     shows, then calls
                                                     ``set_highscores``)

GAMEPLAY / GAME_OVER carry no shell screen (the host owns the HUD, building
panel, and game-over screen, which need the live world); the shell only tracks
that ``state`` so the host knows what to simulate/draw. CUTSCENE likewise has no
shell screen — the host blits the video frame.
"""
from game.core.phases import GameState

from .add_name import AddNameScreen
from .credits import CreditsScreen
from .debug_settings import DebugSettings, DebugSettingsScreen
from .highscores import HighscoresScreen
from .main_menu import MainMenu
from .pause import PauseScreen
from .player_intro import PlayerIntroScreen
from .settings import SessionSettings, SettingsScreen
from .skinning import ScreenSkinning

_MENU_STATES = (GameState.MAIN_MENU, GameState.SETTINGS, GameState.CREDITS,
                GameState.ADD_NAME, GameState.PAUSED, GameState.HIGHSCORES)


class Shell:
    def __init__(self, view_w, view_h, ui_balance,
                 start_state=GameState.MAIN_MENU, skinning=None,
                 debug_balance=None):
        # 10L-B: shell owns ONE ScreenSkinning, shared by its five menu
        # screens; the host reads it back (``shell.skinning``) to thread the
        # same instance into the seven gameplay screens it builds itself
        # (Shell owns no world, so it cannot construct those).
        self.skinning = skinning or ScreenSkinning.empty()
        # player-identity: ``core.json``'s ``Debug`` group. LAST parameter,
        # defaulting to ``None``, so every existing caller (tests build
        # ``Shell(...)`` bare) is unaffected; ``{}`` reads every flag as its
        # permissive default.
        self.debug_balance = debug_balance or {}
        self.settings = SessionSettings.from_balance(ui_balance)
        self.main_menu = MainMenu(view_w, view_h, skinning=self.skinning,
                                  debug_balance=self.debug_balance)
        self.settings_screen = SettingsScreen(view_w, view_h, self.settings,
                                              skinning=self.skinning)
        self.credits = CreditsScreen(view_w, view_h, skinning=self.skinning)
        self.add_name_screen = AddNameScreen(view_w, view_h,
                                             skinning=self.skinning)
        self.pause = PauseScreen(view_w, view_h, skinning=self.skinning)
        # debug-mode-telemetry: the PLAY DEBUG gear's modal. It is a MAIN_MENU
        # OVERLAY, not its own ``GameState`` — a sixth menu state would have to
        # be declared in ``game/core/phases.py``, and this screen is reachable
        # from exactly one place, so a plain flag the screen lookup consults
        # first keeps the enum (and every consumer of it) untouched.
        self.debug_settings = self._debug_settings_from_balance()
        self.debug_settings_screen = DebugSettingsScreen(
            view_w, view_h, self.debug_settings, skinning=self.skinning)
        self.debug_settings_open = False
        # player-identity: the "who is playing?" prompt is a MAIN_MENU OVERLAY
        # too — the ``debug_settings_open`` shape exactly (a flag + a screen the
        # lookup consults first), not a sixth menu state.
        self.player_intro_screen = PlayerIntroScreen(view_w, view_h,
                                                     skinning=self.skinning)
        self.player_intro_open = False
        # The high-score table IS a real state (a full screen off the menu).
        self.highscores_screen = HighscoresScreen(view_w, view_h,
                                                  skinning=self.skinning)
        #: ``(name, skill)`` the host reads when it builds this run's recorder
        #: and, later, the high-score entry. ``(None, None)`` = not asked.
        self.player_identity = (None, None)
        self.state = start_state
        self.settings_caller = GameState.MAIN_MENU
        self._pool_count = 0

    def _debug_settings_from_balance(self):
        """Seed ``DebugSettings`` from ``core.json``'s ``Debug`` group, falling
        back to the dataclass default per key when the balance omits it (so an
        old/partial balance, and every bare ``Shell``, keeps today's values)."""
        b, d = self.debug_balance, DebugSettings()
        return DebugSettings(
            level=int(b.get("default_level", d.level)),
            jsonl=bool(b.get("default_output_jsonl", d.jsonl)),
            csv=bool(b.get("default_output_csv", d.csv)),
            md=bool(b.get("default_output_md", d.md)),
            html=bool(b.get("default_output_html", d.html)),
        )

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

    def set_highscores(self, doc):
        """Host hands the loaded scores document down (``game/ui`` does no disk
        I/O). Called right after the ``"open_highscores"`` intent, and at boot."""
        self.highscores_screen.set_doc(doc)

    def prefill_identity(self, name, skill):
        """Host pre-fills the identity prompt from the last recorded player."""
        self.player_intro_screen.reset(name, skill)

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
        if st == GameState.HIGHSCORES:
            if self.highscores_screen.hit(mx, my) == "back":
                self.state = GameState.MAIN_MENU
            return None
        return None

    def handle_key(self, char, key):
        st = self.state
        # player-identity: the intro modal is a TEXT FIELD — it must get every
        # key before the generic Esc branch below, exactly like ADD_NAME.
        if st == GameState.MAIN_MENU and self.player_intro_open:
            intent = self._player_intro_action(
                self.player_intro_screen.handle_key(char, key))
            if intent is not None:
                return intent
            # The screen only consumes Esc while its field is focused; if it
            # did not, Esc still closes the modal (the debug-settings branch).
            if self.player_intro_open and key == "escape":
                self.player_intro_open = False
            return None
        if st == GameState.ADD_NAME:
            return self._add_name_action(
                self.add_name_screen.handle_key(char, key))
        if st == GameState.HIGHSCORES:
            if self.highscores_screen.handle_key(char, key) == "back":
                self.state = GameState.MAIN_MENU
            return None
        if key == "escape":
            if st == GameState.MAIN_MENU and self.debug_settings_open:
                self.debug_settings_open = False  # debug-mode-telemetry
            elif st == GameState.SETTINGS:
                self.state = self.settings_caller
            elif st == GameState.CREDITS:
                self.state = GameState.MAIN_MENU
            elif st == GameState.PAUSED:
                self.state = GameState.GAMEPLAY
        return None

    def _main_menu_click(self, mx, my):
        # player-identity: the identity prompt sits ABOVE the gear's modal in
        # this ladder and consumes EVERY main-menu click while it is up.
        if self.player_intro_open:
            return self._player_intro_action(
                self.player_intro_screen.hit(mx, my))
        # debug-mode-telemetry: while the gear's modal is up it consumes EVERY
        # main-menu click (the in-round modal convention), so a click that
        # lands on a menu button behind it can never start a run.
        if self.debug_settings_open:
            if self.debug_settings_screen.hit(mx, my) == "back":
                self.debug_settings_open = False
            return None
        action = self.main_menu.hit(mx, my)
        if action == "new_game":
            self.player_identity = (None, None)   # a regular run is unstamped
            return "new_game"
        if action == "play_debug":
            if self.debug_balance.get("ask_player_identity", True):
                self.player_intro_open = True
                return None
            self.player_identity = (None, None)
            return "new_game_debug"
        if action == "play_debug_settings":
            self.debug_settings_open = True
            return None
        if action == "highscores":
            self.state = GameState.HIGHSCORES
            # The host re-reads the scores file (a run may have just finished)
            # and hands the fresh document back via ``set_highscores``.
            return "open_highscores"
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

    def _player_intro_action(self, action):
        """The ONE place the identity prompt's ``hit()``/``handle_key()``
        results are mapped, shared by the click and the key path."""
        if action == "start":
            screen = self.player_intro_screen
            self.player_identity = (screen.player_name, screen.skill)
            self.player_intro_open = False
            return "new_game_debug"
        if action == "back":
            self.player_intro_open = False
        return None

    def _add_name_action(self, action):
        if action == "back":
            self.state = GameState.MAIN_MENU
        elif action == "add":
            return "add_name_commit"
        return None

    # -- per-frame -------------------------------------------------------

    def _active_screen(self):
        # player-identity: checked BEFORE the gear's modal — it sits above it
        # in the click ladder, so it must be the drawn/updated screen too.
        if self.state == GameState.MAIN_MENU and self.player_intro_open:
            return self.player_intro_screen
        # debug-mode-telemetry: the gear's modal replaces the main menu while
        # it is open (it is opaque and consumes every click, so drawing the
        # menu under it would only cost fill rate).
        if self.state == GameState.MAIN_MENU and self.debug_settings_open:
            return self.debug_settings_screen
        return {
            GameState.MAIN_MENU: self.main_menu,
            GameState.SETTINGS: self.settings_screen,
            GameState.CREDITS: self.credits,
            GameState.ADD_NAME: self.add_name_screen,
            GameState.PAUSED: self.pause,
            GameState.HIGHSCORES: self.highscores_screen,
        }.get(self.state)

    def handle_scroll(self, dy):
        """Forward a mouse-wheel step to the active screen when it scrolls.

        Duck-typed on a CALLABLE ``scroll`` attribute (only the high-score
        table has one today), so every other screen — and every other state —
        is a silent no-op. Returns ``None``: scrolling is never a host intent.
        ``dy`` is in ROWS, positive = down the list; pygame's ``MOUSEWHEEL``
        ``event.y`` is positive when scrolling UP, so the host negates it."""
        fn = getattr(self._active_screen(), "scroll", None)
        if callable(fn):
            fn(dy)
        return None

    @property
    def in_menu(self):
        """True while a full-screen menu owns the frame (no world drawn)."""
        return self.state in (GameState.MAIN_MENU, GameState.SETTINGS,
                              GameState.CREDITS, GameState.ADD_NAME,
                              GameState.HIGHSCORES)

    def update(self, dt, mx, my, mouse_down=False):
        screen = self._active_screen()
        if screen is not None:
            screen.update(dt, mx, my, mouse_down)

    def submit(self, renderer, view_w, view_h):
        screen = self._active_screen()
        if screen is not None:
            screen.submit(renderer, view_w, view_h)
