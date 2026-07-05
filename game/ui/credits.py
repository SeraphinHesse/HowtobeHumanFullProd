"""Credits screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/credits_menu.py`` static two-column
list verbatim onto the ``game_over.py`` template: role (dim) on the left, name
(bright) on the right, blank tuples inserting a spacer, plus a BACK button.
Non-scrolling.
"""
from engine.render import HudRect

from .widgets import C_GOLD, C_UI_TEXT, C_UI_TEXT_DIM, Button, submit_centered, \
    submit_text

_BG = (12, 20, 14)

# (role, name) — verbatim from the prototype credits_menu.py; "" pair = spacer.
_CREDITS = [
    ("Producer", "Seraphin Hesse"),
    ("Game Design Lead", "Fabian Krüger"),
    ("Art Lead", "Hendrik Wagner"),
    ("Programming Lead", "Johann Heinrich"),
    ("", ""),
    ("UI Lead/2D Artist", "Alicia Jaison"),
    ("2D Artist", "Varvara Kozačuk"),
    ("2D Artist", "Jakob Dahlkar"),
    ("", ""),
    ("Game Designer", "Joel Hoch"),
    ("Game Designer", "Benjamin Riese"),
    ("", ""),
    ("Programmer", "Pantelis Charalambous"),
    ("Programmer", "Alfons Kavalic"),
]
_LINE_H = 30
_SPACER_H = 14


class CreditsScreen:
    def __init__(self, view_w, view_h):
        self.back_btn = Button((0, 0, 200, 46), "BACK")
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        self.back_btn.rect = (view_w // 2 - 100, view_h - 90, 200, 46)

    def update(self, dt, mx, my):
        self.back_btn.enabled = True
        self.back_btn.hover(mx, my)
        self.back_btn.update(dt)

    def hit(self, mx, my):
        return "back" if self.back_btn.hit(mx, my) else None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        cx = view_w // 2
        submit_centered(renderer, "CREDITS", cx, 70, "xxl", C_GOLD)
        y = 150
        for role, name in _CREDITS:
            if not role and not name:
                y += _SPACER_H
                continue
            submit_text(renderer, role, (cx - 40, y), "sm", C_UI_TEXT_DIM,
                        align="right")
            submit_text(renderer, name, (cx + 40, y), "md", C_UI_TEXT)
            y += _LINE_H
        self.back_btn.submit(renderer)
