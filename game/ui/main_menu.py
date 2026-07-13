"""Main menu screen (Phase 9H).

Pure logic — the top-level menu the shell shows between runs. Ports the
prototype's ``src/ui/main_menu.py`` button set (START NEW GAME / ADD A NAME /
SETTINGS / CREDITS / QUIT) onto the ``game_over.py`` full-screen template: a
solid ``HudRect`` backdrop, a centred title, and a vertical stack of
``widgets.Button`` click targets. ``hit`` returns the prototype's action strings.
The hand-painted background art draws as a full-view ``HudSprite`` from the
``main_menu_bg`` slot (10K, asset-pipeline sourced; letterbox-safe because the
host's SCALED logical surface is what gets letterboxed); the solid fill stays
beneath it as the missing-art fallback.
"""
from engine.render import HudRect, HudSprite

from .widgets import C_GOLD, C_UI_TEXT, Button, submit_centered

_BG = (18, 30, 20)
_BG_SLOT = "main_menu_bg"
_TITLE = "HOW TO BE HUMAN"

# (label, action) top-to-bottom
_ITEMS = [
    ("START NEW GAME", "new_game"),
    ("ADD A NAME", "add_name"),
    ("SETTINGS", "settings"),
    ("CREDITS", "credits"),
    ("QUIT", "quit"),
]
_BTN_W, _BTN_H, _GAP = 320, 52, 14


class MainMenu:
    def __init__(self, view_w, view_h):
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), action)
                        for label, action in _ITEMS]
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        x = view_w // 2 - _BTN_W // 2
        y = view_h // 2 - 60
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
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        renderer.submit_hud(HudSprite(_BG_SLOT, (0, 0), (view_w, view_h)))
        submit_centered(renderer, _TITLE, view_w // 2, view_h // 2 - 150,
                        "xxl", C_UI_TEXT)
        submit_centered(renderer, "defend the munckins",
                        view_w // 2, view_h // 2 - 110, "md", C_GOLD)
        for btn, _ in self.buttons:
            btn.submit(renderer)
