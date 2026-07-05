"""Pause screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/pause_menu.py`` four-button panel
(RESUME / SETTINGS / QUIT TO MENU / QUIT GAME). Drawn OVER the frozen gameplay
(the host freezes the sim in PAUSED), so this is an opaque centred panel rather
than a full-screen fill — the still board stays visible around it (the HUD pass
has no per-pixel alpha, so a translucent dim isn't available; a solid panel over
the frozen world reads as paused-in-place).
"""
from engine.render import HudRect

from .widgets import C_GOLD, Button, submit_centered

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

    def update(self, dt, mx, my):
        for btn, _ in self.buttons:
            btn.enabled = True
            btn.hover(mx, my)
            btn.update(dt)

    def hit(self, mx, my):
        for btn, action in self.buttons:
            if btn.hit(mx, my):
                return action
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        px, py, pw, ph = self.rect
        renderer.submit_hud(HudRect(self.rect, (24, 20, 40), border_radius=6))
        renderer.submit_hud(HudRect(self.rect, (80, 65, 120), border_radius=6,
                                    width=2))
        submit_centered(renderer, "PAUSED", view_w // 2, py + 32, "xl", C_GOLD)
        for btn, _ in self.buttons:
            btn.submit(renderer)
