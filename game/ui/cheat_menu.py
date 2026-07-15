"""Cheat menu (Phase 10H) — the Ctrl+L debug overlay.

Pure logic, the ``game_over.py``/``levelup.py`` modal template. Ports the
prototype's ``src/ui/cheat_menu.py`` + the host glue at ``game.py:293-318``.

**Hotkey divergence (deliberate, coordination ruling #4):** the toggle is
**Ctrl+L** per MIGRATION_PLAN.md 10H, not the prototype's Ctrl+P — bare ``P``
is already this repo's quick-skip key (10F), so a mistimed Ctrl+P would
silently throw away a whole wave.

The menu NEVER mutates game state (uniform, unlike the prototype's two
in-menu appliers): every click/key returns an ACTION the host maps onto
``Session`` cheat methods — ``"close"`` / ``"add_love"`` / ``"skip_round"`` /
``"trigger_levelup"`` / ``"inf_money"`` / ``"unlock_all"`` /
``("goto_round", n)`` / None (swallowed). The stays-open rule (prototype
``cheat_menu.py:49-56``) lives in the host: it closes the menu only on
``close``, ``trigger_levelup`` and a committed ``goto_round`` — the other
four leave it open for repeat presses.

Since 10J the backdrop is the prototype's real ``(0, 0, 0, 150)`` alpha dim
(RGBA ``HudRect``).

10L-B (plan R3, PINNED): eleven ids — ``panel``, ``title``, ``btn_close``,
``btn_add_love``, ``btn_skip_round``, ``btn_trigger_levelup``,
``btn_inf_money``, ``btn_unlock_all``, ``round_field``, ``btn_goto``,
``jump_label``. ``submit()`` calls ``layout()`` EVERY FRAME (the menu can be
left open across many frames), so ``skinning.apply()`` must be — and is — a
cached-dict setattr loop with zero disk reads per call (pinned by
``test_ui_skinning.py``'s "loads once" test). ``field_rect``/``round_text``/
``field_focused``/``panel_rect`` stay real, directly-readable attributes
(``test_lightning.py`` reads ``field_rect``/``close_btn``/``go_btn``
directly) — the ids-only shadow holders (``_round_field``, ``_panel``,
``_title``, ``_jump_label``) are synced from/to them each ``layout()``.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    C_GOLD, C_PANEL_STONE, C_UI_BORDER, C_UI_TEXT, C_UI_TEXT_DIM, Button,
    anim_ms, contains, submit_centered, submit_panel, submit_text,
)

_BG = (0, 0, 0, 150)  # prototype alpha dim (10J)
_PANEL_W, _PANEL_H = 220, 258
_TITLE = "CHEATS"
_MAX_DIGITS = 4  # prototype round-field cap

# (action, label) in prototype stacking order (cheat_menu.py:16-46).
_BUTTONS = (
    ("add_love", "+10 Love"),
    ("skip_round", "Skip Round"),
    ("trigger_levelup", "LEVEL UP"),
    ("inf_money", "Infinite Money"),
    ("unlock_all", "Unlock All Tech"),
)
# action -> the ids name a designer picks it by (10L-B, PINNED)
_ACTION_IDS = {
    "add_love": "btn_add_love", "skip_round": "btn_skip_round",
    "trigger_levelup": "btn_trigger_levelup", "inf_money": "btn_inf_money",
    "unlock_all": "btn_unlock_all",
}

SCREEN_ID = "cheat_menu"


class CheatMenu:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.visible = False
        self.round_text = ""
        self.field_focused = False
        self.close_btn = Button((0, 0, 20, 18), "X", "md")
        self.buttons = [(action, Button((0, 0, 0, 0), label, "md"))
                        for action, label in _BUTTONS]
        self.go_btn = Button((0, 0, 0, 0), "Go to Round", "sm")
        self.panel_rect = (0, 0, _PANEL_W, _PANEL_H)
        self.field_rect = (0, 0, 0, 0)
        self._label_pos = (0, 0)
        self._divider_y = 0
        self._clock = 0.0  # 10L-A: one anim clock per screen
        # -- 10L-B: shadow holders for the four non-Button ids --
        self._panel = SimpleNamespace(rect=self.panel_rect, skin=None)
        self._title = SimpleNamespace(font_key="lg", text_color=C_GOLD)
        self._round_field = SimpleNamespace(rect=self.field_rect,
                                            font_key="sm", text_color=None)
        self._jump_label = SimpleNamespace(font_key="sm",
                                           text_color=C_UI_TEXT_DIM)
        self.ids = {}
        # -- /10L-B --
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    # -- open / close -------------------------------------------------------

    def open(self):
        self.visible = True
        # Fresh input state on every open (prototype clears _buf/_active).
        self.round_text = ""
        self.field_focused = False

    def close(self):
        self.visible = False
        self.field_focused = False

    def toggle(self):
        if self.visible:
            self.close()
        else:
            self.open()

    # -- layout / update ----------------------------------------------------

    def layout(self, view_w, view_h):
        self.view_w, self.view_h = view_w, view_h
        px = view_w // 2 - _PANEL_W // 2
        py = view_h // 2 - _PANEL_H // 2
        self.panel_rect = (px, py, _PANEL_W, _PANEL_H)
        self.close_btn.rect = (px + _PANEL_W - 26, py + 6, 20, 18)
        y = py + 32
        for _action, btn in self.buttons:
            btn.rect = (px + 10, y, _PANEL_W - 20, 26)
            y += 30
        self._divider_y = y + 2
        self._label_pos = (px + 10, y + 8)
        self.field_rect = (px + 10, y + 26, 96, 22)
        self.go_btn.rect = (px + 112, y + 26, _PANEL_W - 122, 22)
        # -- 10L-B: cached-dict setattr loop, zero disk I/O per call (the
        # menu's submit() calls layout() every frame it stays open) --
        self._panel.rect = self.panel_rect
        self._round_field.rect = self.field_rect
        self.ids = {
            "panel": ("panel", self._panel),
            "title": ("label", self._title),
            "btn_close": ("button", self.close_btn),
            "round_field": ("field", self._round_field),
            "btn_goto": ("button", self.go_btn),
            "jump_label": ("label", self._jump_label),
        }
        for action, btn in self.buttons:
            self.ids[_ACTION_IDS[action]] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)
        self.panel_rect = self._panel.rect
        self.field_rect = self._round_field.rect

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        if not self.visible:
            return
        for btn in (self.close_btn, self.go_btn, *(b for _, b in self.buttons)):
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    # -- input --------------------------------------------------------------

    def handle_key(self, char, key):
        """Every key is consumed while the menu is open. Esc closes; the rest
        edits the click-to-focus round field (digits only, max 4, backspace
        edits, Enter commits — prototype cheat_menu.py:130-138)."""
        if key == "escape":
            return "close"
        if not self.field_focused:
            return None
        if key == "backspace":
            self.round_text = self.round_text[:-1]
        elif key == "return":
            return self._commit()
        elif char and char.isdigit() and len(self.round_text) < _MAX_DIGITS:
            self.round_text += char
        return None

    def hit(self, mx, my):
        """The clicked action, or None (every click on/off the panel is
        swallowed by the host while the menu is open). An invisible button
        is never hit (10L-B)."""
        if is_visible(self.close_btn) and self.close_btn.hit(mx, my):
            return "close"
        for action, btn in self.buttons:
            if is_visible(btn) and btn.hit(mx, my):
                return action
        if is_visible(self.go_btn) and self.go_btn.hit(mx, my):
            return self._commit()
        if contains(self.field_rect, mx, my):
            self.field_focused = True
            return None
        self.field_focused = False
        return None

    def _commit(self):
        """A ``("goto_round", n)`` action for a valid int >= 1; empty/invalid
        input is a no-op and the menu stays open (prototype ``_commit``)."""
        try:
            n = int(self.round_text)
        except ValueError:
            return None
        if n < 1:
            return None
        return ("goto_round", n)

    # -- render ---------------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        submit_panel(renderer, self.panel_rect, skin=self._panel.skin, anim_ms=t)
        px, py, pw, _ph = self.panel_rect
        submit_centered(renderer, _TITLE, px + pw // 2, py + 8,
                        self._title.font_key, self._title.text_color)
        if is_visible(self.close_btn):
            self.close_btn.submit(renderer, anim_ms=t, **button_kwargs(self.close_btn))
        for _action, btn in self.buttons:
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
        renderer.submit_hud(
            HudRect((px + 10, self._divider_y, pw - 20, 1), C_UI_BORDER))
        submit_text(renderer, "Jump to round:", self._label_pos,
                   self._jump_label.font_key, self._jump_label.text_color)
        renderer.submit_hud(HudRect(self.field_rect, C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.field_rect, C_GOLD if self.field_focused else C_UI_BORDER,
            width=1))
        fx, fy = self.field_rect[0], self.field_rect[1]
        if self.round_text or self.field_focused:
            shown = self.round_text + ("_" if self.field_focused else "")
            tcol = C_UI_TEXT
        else:
            shown = "round"
            tcol = C_UI_TEXT_DIM
        submit_text(renderer, shown, (fx + 6, fy + 4), self._round_field.font_key,
                   tcol)
        if is_visible(self.go_btn):
            self.go_btn.submit(renderer, anim_ms=t, **button_kwargs(self.go_btn))
