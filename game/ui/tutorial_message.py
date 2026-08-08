"""Tutorial message box (Phase TU-6) — the guided-chain's Continue/Skip modal.

Pure logic; copies ``game_over.py``'s construct -> layout -> update -> hit ->
submit template. Shown immediately on a fresh game, it consumes every click
while visible (the host's ``handle_world_click`` swallows the click
unconditionally once ``TutorialDirector.message_visible`` is true) so nothing
else can happen until the player dismisses or skips it.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import Button, anim_ms, submit_panel, submit_text, wrap_text
from . import widgets

SCREEN_ID = "tutorial_message"
_BG = (10, 5, 20, 200)
_PANEL_W, _PANEL_H = 260, 130


class TutorialMessageScreen:
    def __init__(self, view_w, view_h, skippable, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.skippable = skippable
        self.continue_btn = Button((0, 0, 100, 23), "CONTINUE", font_key="lg")
        self.skip_btn = Button((0, 0, 90, 20), "SKIP TUTORIAL", font_key="md")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG,
                                         visible=True)
        self._panel = SimpleNamespace(rect=(0, 0, _PANEL_W, _PANEL_H), skin=None)
        # The copy is NOT game-state (it comes from the director/script at
        # runtime, never a fixed literal) — per game/ui/CLAUDE.md's dynamic-
        # content convention this carries no ``label`` override field, only
        # rect/font/color/visible (the same shape game_over.py's dynamic
        # stat lines use).
        self._message_text = SimpleNamespace(rect=(0, 0, 0, 0), font_key="md",
                                             text_color=widgets.C_UI_TEXT,
                                             visible=True)
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.ids = {}
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        x = view_w // 2 - _PANEL_W // 2
        y = view_h // 2 - _PANEL_H // 2
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._panel.rect = (x, y, _PANEL_W, _PANEL_H)
        self._message_text.rect = (x + 10, y + 12, 0, 0)
        cbw, cbh = self.continue_btn.rect[2], self.continue_btn.rect[3]
        self.continue_btn.rect = (
            x + _PANEL_W - 8 - cbw, y + _PANEL_H - 8 - cbh, cbw, cbh)
        sbw, sbh = self.skip_btn.rect[2], self.skip_btn.rect[3]
        self.skip_btn.rect = (x + 8, y + _PANEL_H - 8 - sbh, sbw, sbh)
        # D7: the Skip button only shows when the script says `skippable` —
        # a screen-JSON override (if any) still wins, since apply() runs after.
        self.skip_btn.visible = self.skippable
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "message_text": ("label", self._message_text),
            "btn_continue": ("button", self.continue_btn),
            "btn_skip": ("button", self.skip_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn in (self.continue_btn, self.skip_btn):
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"continue"`` / ``"skip"`` / ``None``. The host treats
        this modal as consuming every click regardless of the result."""
        if is_visible(self.continue_btn) and self.continue_btn.hit(mx, my):
            return "continue"
        if is_visible(self.skip_btn) and self.skip_btn.hit(mx, my):
            return "skip"
        return None

    def submit(self, renderer, text, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        if is_visible(self._backdrop):
            renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        if is_visible(self._panel):
            submit_panel(renderer, self._panel.rect, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None), anim_ms=t)
        if is_visible(self._message_text) and text:
            tx, ty = self._message_text.rect[0], self._message_text.rect[1]
            for line in wrap_text(text, self._message_text.font_key,
                                  _PANEL_W - 20, max_lines=6):
                submit_text(renderer, line, (tx, ty), self._message_text.font_key,
                           self._message_text.text_color)
                ty += 11
        if is_visible(self.continue_btn):
            self.continue_btn.submit(renderer, anim_ms=t,
                                     **button_kwargs(self.continue_btn))
        if is_visible(self.skip_btn):
            self.skip_btn.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.skip_btn))
