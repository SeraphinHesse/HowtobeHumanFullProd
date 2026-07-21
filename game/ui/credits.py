"""Credits screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/credits_menu.py`` static two-column
list verbatim onto the ``game_over.py`` template: role (dim) on the left, name
(bright) on the right, blank tuples inserting a spacer, plus a BACK button.
Non-scrolling.

10L-B: ``ids`` names ``backdrop``, ``title`` ("CREDITS") + ``btn_back`` (the
credits ROWS are static content, not individually overridable — same "skip
dynamic content" rule as every other screen's list-shaped body).
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, submit_centered, submit_text
)
from . import widgets

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

SCREEN_ID = "credits"


class CreditsScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.back_btn = Button((0, 0, 200, 46), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD, label="CREDITS",
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        self.back_btn.rect = (view_w // 2 - 100, view_h - 90, 200, 46)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, 70, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_back": ("button", self.back_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.back_btn.enabled = True
        self.back_btn.hover(mx, my, mouse_down)
        self.back_btn.hovered = self.back_btn.hovered and is_visible(self.back_btn)
        self.back_btn.update(dt)

    def hit(self, mx, my):
        return ("back" if is_visible(self.back_btn) and self.back_btn.hit(mx, my)
               else None)

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        cx = view_w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        y = 150
        for role, name in _CREDITS:
            if not role and not name:
                y += _SPACER_H
                continue
            submit_text(renderer, role, (cx - 40, y), "sm", widgets.C_UI_TEXT_DIM,
                        align="right")
            submit_text(renderer, name, (cx + 40, y), "md", widgets.C_UI_TEXT)
            y += _LINE_H
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
