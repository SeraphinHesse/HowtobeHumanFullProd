"""Game over screen (Phase 9G).

Pure logic. Ports the prototype's ``src/ui/game_over_screen.py``: a full-screen
panel with the title, the run's stats, and a button. Since 9H the button returns
``"main_menu"`` (prototype-exact) — the host tears the dead run down and returns
to the shell's main menu, where START NEW GAME builds a fresh run.
"""
from engine.render import HudRect

from .widgets import C_RED, C_UI_TEXT, Button, anim_ms, submit_centered

_BG = (10, 5, 15)
_TITLE = "THE COLONY WAS DESTROYED"


class GameOverScreen:
    def __init__(self, view_w, view_h):
        self.button = Button((0, 0, 240, 46), "RETURN TO MENU", font_key="lg")
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        w, h = self.button.rect[2], self.button.rect[3]
        self.button.rect = (view_w // 2 - w // 2, view_h // 2 + 110, w, h)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.button.enabled = True
        self.button.hover(mx, my, mouse_down)
        self.button.update(dt)

    def hit(self, mx, my):
        return "main_menu" if self.button.hit(mx, my) else None

    def submit(self, renderer, state, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        cx = view_w // 2
        submit_centered(renderer, _TITLE, cx, view_h // 2 - 120, "xxl", C_RED)
        lines = [
            f"Round Reached: {state.round_num}",
            f"Buildings Placed: {state.buildings_placed}",
            f"Enemies Killed: {state.enemies_killed}",
        ]
        y = view_h // 2 - 30
        for line in lines:
            submit_centered(renderer, line, cx, y, "md", C_UI_TEXT)
            y += 28
        self.button.submit(renderer, anim_ms=t)
