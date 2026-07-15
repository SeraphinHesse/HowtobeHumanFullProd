"""Pause screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/pause_menu.py`` four-button panel
(RESUME / SETTINGS / QUIT TO MENU / QUIT GAME). Drawn OVER the frozen gameplay
(the host freezes the sim in PAUSED). Since 10J the full-screen
``(0, 0, 0, 150)`` alpha dim from the prototype draws behind the panel (the
9H deferral), so the still board reads as paused-in-place.
"""
from engine.render import HudRect

from .widgets import C_GOLD, Button, anim_ms, submit_centered

# (label, action) top-to-bottom
_ITEMS = [
    ("RESUME", "resume"),
    ("SETTINGS", "settings"),
    ("QUIT TO MENU", "quit_to_menu"),
    ("QUIT GAME", "quit"),
]
_PW, _PH = 300, 320
_BTN_W, _BTN_H, _GAP = 240, 46, 12


class PauseScreen:
    def __init__(self, view_w, view_h):
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), action)
                        for label, action in _ITEMS]
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        px = view_w // 2 - _PW // 2
        py = view_h // 2 - _PH // 2
        self.rect = (px, py, _PW, _PH)
        x = view_w // 2 - _BTN_W // 2
        y = py + 84
        for btn, _ in self.buttons:
            btn.rect = (x, y, _BTN_W, _BTN_H)
            y += _BTN_H + _GAP

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn, _ in self.buttons:
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.update(dt)

    def hit(self, mx, my):
        for btn, action in self.buttons:
            if btn.hit(mx, my):
                return action
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        px, py, pw, ph = self.rect
        # 10J: the prototype's (0,0,0,150) pause dim over the frozen world
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), (0, 0, 0, 150)))
        renderer.submit_hud(HudRect(self.rect, (24, 20, 40), border_radius=6))
        renderer.submit_hud(HudRect(self.rect, (80, 65, 120), border_radius=6,
                                    width=2))
        submit_centered(renderer, "PAUSED", view_w // 2, py + 32, "xl", C_GOLD)
        for btn, _ in self.buttons:
            btn.submit(renderer, anim_ms=t)
