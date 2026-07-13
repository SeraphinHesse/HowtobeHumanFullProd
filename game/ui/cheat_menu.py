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
"""
from engine.render import HudRect

from .widgets import (
    C_GOLD, C_PANEL_STONE, C_UI_BORDER, C_UI_TEXT, C_UI_TEXT_DIM, Button,
    contains, submit_centered, submit_panel, submit_text,
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


class CheatMenu:
    def __init__(self, view_w, view_h):
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

    def update(self, dt, mx, my):
        if not self.visible:
            return
        for btn in (self.close_btn, self.go_btn, *(b for _, b in self.buttons)):
            btn.hover(mx, my)
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
        swallowed by the host while the menu is open)."""
        if self.close_btn.hit(mx, my):
            return "close"
        for action, btn in self.buttons:
            if btn.hit(mx, my):
                return action
        if self.go_btn.hit(mx, my):
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
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        submit_panel(renderer, self.panel_rect)
        px, py, pw, _ph = self.panel_rect
        submit_centered(renderer, _TITLE, px + pw // 2, py + 8, "lg", C_GOLD)
        self.close_btn.submit(renderer)
        for _action, btn in self.buttons:
            btn.submit(renderer)
        renderer.submit_hud(
            HudRect((px + 10, self._divider_y, pw - 20, 1), C_UI_BORDER))
        submit_text(renderer, "Jump to round:", self._label_pos, "sm",
                    C_UI_TEXT_DIM)
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
        submit_text(renderer, shown, (fx + 6, fy + 4), "sm", tcol)
        self.go_btn.submit(renderer)
