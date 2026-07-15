"""Game over screen (Phase 9G).

Pure logic. Ports the prototype's ``src/ui/game_over_screen.py``: a full-screen
panel with the title, the run's stats, and a button. Since 9H the button returns
``"main_menu"`` (prototype-exact) — the host tears the dead run down and returns
to the shell's main menu, where START NEW GAME builds a fresh run.

10L-B: ``ids`` names ``backdrop``, ``title`` ("THE COLONY WAS DESTROYED") +
``btn_return_to_menu`` (the run-stats lines are dynamic content, not
individually overridable). An invisible button is neither drawn nor
hit-tested.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import C_RED, C_UI_TEXT, Button, anim_ms, submit_centered

_BG = (10, 5, 15)
_TITLE = "THE COLONY WAS DESTROYED"

SCREEN_ID = "game_over"


class GameOverScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.button = Button((0, 0, 240, 46), "RETURN TO MENU", font_key="lg")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=C_RED, label=_TITLE,
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        w, h = self.button.rect[2], self.button.rect[3]
        self.button.rect = (view_w // 2 - w // 2, view_h // 2 + 110, w, h)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, view_h // 2 - 120, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_return_to_menu": ("button", self.button),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.button.enabled = True
        self.button.hover(mx, my, mouse_down)
        self.button.hovered = self.button.hovered and is_visible(self.button)
        self.button.update(dt)

    def hit(self, mx, my):
        return ("main_menu" if is_visible(self.button) and self.button.hit(mx, my)
               else None)

    def submit(self, renderer, state, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        cx = view_w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        lines = [
            f"Round Reached: {state.round_num}",
            f"Buildings Placed: {state.buildings_placed}",
            f"Enemies Killed: {state.enemies_killed}",
        ]
        y = view_h // 2 - 30
        for line in lines:
            submit_centered(renderer, line, cx, y, "md", C_UI_TEXT)
            y += 28
        if is_visible(self.button):
            self.button.submit(renderer, anim_ms=t, **button_kwargs(self.button))
