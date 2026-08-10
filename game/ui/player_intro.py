"""Player-identity prompt (player-identity feature).

The modal ``PLAY DEBUG`` puts up before a debug run starts: who is playing, and
how much have they played this game before. It is ``add_name.py``'s template
verbatim (construct -> ``layout()`` -> ``update()`` -> ``hit()`` ->
``handle_key()`` -> ``submit()``, a centred panel over a full-view backdrop,
one anim clock, an ``ids`` dict rebuilt in ``layout()`` with
``skinning.apply()`` called LAST) — including its text-entry state machine
(return/escape/backspace/printable, max 20 chars) and its click-to-focus
``editing`` behaviour.

This screen NEVER writes to disk (``game/ui`` is pygame- and IO-free): it just
exposes ``player_name`` / ``skill`` and returns action strings. The host reads
that pair off ``Shell.player_identity`` when it builds the run's
``DebugRecorder`` and, later, the high-score entry. ``game.core.highscores`` is
imported only for the pure ``SKILLS`` tuple (the sanctioned one-way
``game.ui -> game.core`` direction) — never for its load/append functions.

**Code-only, deliberately** (the ``debug_settings.py`` precedent): there is no
``data/ui/screens/player_intro.json`` and no ``data/ui/screen_defaults.json``
entry, and it is not in ``tools/export_ui_layouts.py``'s ``SCREEN_IDS``. An
absent override means "code defaults", so it still carries a full ``ids`` dict
and the panel -> button -> text submission order and is a drop-in the day
someone exports it.

The four experience options are RADIO buttons, not toggles: clicking one selects
it and deselects the rest, and exactly one is always selected. The selection is
drawn by setting the selected button's ``text_color`` to gold and every other's
to ``None`` (the "``None`` means compute" convention ``skinning.button_kwargs``
already honours) — no new draw path.
"""
from types import SimpleNamespace

from engine.render import HudRect

from game.core.highscores import SKILLS

from .highscores import skill_label
from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, contains, submit_centered, submit_panel, submit_text
)
from . import widgets

_MAX_CHARS = 20
_BG = (12, 14, 22)
_PW, _PH = 260, 238

#: skill value -> the id a designer picks that option by.
_SKILL_IDS = {value: f"btn_skill_{value}" for value in SKILLS}

_OPT_W, _OPT_H, _OPT_GAP = 140, 20, 5

SCREEN_ID = "player_intro"


class PlayerIntroScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        #: The public read surface the shell copies into ``player_identity``.
        self.player_name = ""
        self.skill = SKILLS[0]
        self.editing = True        # focused on open so typing works instantly
        #: ``[(skill_value, Button)]`` in ``SKILLS`` order.
        self.options = [(value, Button((0, 0, _OPT_W, _OPT_H),
                                       skill_label(value)))
                        for value in SKILLS]
        self.start_btn = Button((0, 0, 80, 20), "START")
        self.back_btn = Button((0, 0, 65, 20), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._panel = SimpleNamespace(rect=(0, 0, _PW, _PH), skin=None)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xl",
                                      text_color=widgets.C_GOLD,
                                      label="WHO IS PLAYING?", visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    # -- layout ------------------------------------------------------------

    def layout(self, view_w, view_h):
        x = view_w // 2 - _PW // 2
        y = view_h // 2 - _PH // 2
        self.rect = (x, y, _PW, _PH)
        self.name_rect = (x + 12, y + 48, _PW - 24, 18)
        self._prompt_y = y + 75
        oy = y + 90
        self._opt_x = x + _PW // 2 - _OPT_W // 2
        for _value, btn in self.options:
            btn.rect = (self._opt_x, oy, _OPT_W, _OPT_H)
            oy += _OPT_H + _OPT_GAP
        self.start_btn.rect = (x + 12, y + _PH - 28, 80, 20)
        self.back_btn.rect = (x + _PW - 12 - 65, y + _PH - 28, 65, 20)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._panel.rect = self.rect
        self._title.rect = (x + _PW // 2, y + 10, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "panel": ("panel", self._panel),
            "title": ("label", self._title),
            "btn_start": ("button", self.start_btn),
            "btn_back": ("button", self.back_btn),
        }
        for value, btn in self.options:
            self.ids[_SKILL_IDS[value]] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)
        self.rect = self._panel.rect  # coherent: a moved panel moves its hit-rect

    def reset(self, name="", skill=None):
        """Pre-fill both fields and clear focus state — called each time the
        screen is opened (the host passes the last recorded player). A ``None``
        or unknown skill falls back to the first option, so exactly one radio
        is always selected."""
        self.player_name = name or ""
        self.skill = skill if skill in SKILLS else SKILLS[0]
        self.editing = True

    # -- per-frame ---------------------------------------------------------

    def _buttons(self):
        for _value, btn in self.options:
            yield btn
        yield self.start_btn
        yield self.back_btn

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        # Radio selection reads as gold label text. ``None`` on the rest means
        # "compute" (skinning.button_kwargs' convention), i.e. the button's own
        # hover/flash logic, so this invents no new draw path.
        for value, btn in self.options:
            btn.text_color = widgets.C_GOLD if value == self.skill else None
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"start"`` / ``"back"`` / ``"name"`` (box focus) / ``None``.
        Clicking an option SELECTS it (and deselects the others) and returns
        ``None``. An invisible button is never hit (10L-B)."""
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        if is_visible(self.start_btn) and self.start_btn.hit(mx, my):
            return "start"
        for value, btn in self.options:
            if is_visible(btn) and btn.hit(mx, my):
                self.skill = value          # radio: exactly one stays selected
                return None
        self.editing = contains(self.name_rect, mx, my)  # click toggles focus
        return "name" if self.editing else None

    def handle_key(self, char, key):
        """Return ``"start"`` (Enter) / ``"back"`` (Esc) / ``None``. The
        ``add_name.py`` state machine verbatim."""
        if not self.editing:
            return None
        if key == "return":
            return "start"
        if key == "escape":
            return "back"
        if key == "backspace":
            self.player_name = self.player_name[:-1]
        elif char and char.isprintable() and len(self.player_name) < _MAX_CHARS:
            self.player_name += char
        return None

    # -- draw --------------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        x, y, w, h = self.rect
        if is_visible(self._panel):
            submit_panel(renderer, self.rect, fill=widgets.C_UI_PANEL,
                         border=widgets.C_UI_BORDER, skin=self._panel.skin,
                         tint=getattr(self._panel, "tint", None), anim_ms=t)
        for btn in self._buttons():
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))

        cx = x + w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        submit_centered(renderer,
                        "Stamped into this run's debug log filenames and reports.",
                        cx, y + 29, "sm", widgets.C_UI_TEXT_DIM)

        nx, ny, _nw, _nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect,
            widgets.C_GOLD if self.editing else widgets.C_UI_BORDER, width=1))
        if self.player_name or self.editing:
            shown = self.player_name + ("_" if self.editing else "")
            tcol = widgets.C_UI_TEXT
        else:
            shown = "type your name..."
            tcol = widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 4, ny + 4), "md", tcol)

        submit_centered(renderer, "How much have you played this game?", cx,
                        self._prompt_y, "sm", widgets.C_UI_TEXT)
