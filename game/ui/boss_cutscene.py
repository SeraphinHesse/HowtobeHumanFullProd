"""Boss cutscene window (Phase 10G) — the modal A/B story-choice screen.

Pure logic. Ports the prototype's ``src/ui/boss_cutscene.py``: a near-black
overlay, a win/loss headline, "How will we react?", and TWO option boxes
(``WinA``/``WinB`` or ``LossA``/``LossB``) whose descriptions come from
``game.core.boss_bonuses.BOSS_CHOICES`` (the choice SET cycles every 3 bosses).
**No cancel — the player must pick A or B**; the host swallows every other
click and all keys (``Session.frozen`` covers BOSS_CUTSCENE).

Since 10J the backdrop is the prototype's real alpha-210 dim (RGBA
``HudRect``) — the frozen board stays faintly visible behind the choice.
"""
from engine.render import HudRect

from game.core.boss_bonuses import choice_desc

from .widgets import (
    C_GOLD, C_UI_BORDER, C_UI_BTN_HOVER, C_UI_PANEL, C_UI_TEXT, C_UI_TEXT_DIM,
    contains, submit_centered, text_h,
)

_BG = (0, 0, 0, 210)           # prototype alpha dim (10J)
_WIN_GREEN = (100, 220, 100)
_LOSS_RED = (220, 100, 100)
_BOX_W, _BOX_H, _GAP = 180, 130, 20
_DOWN_SHIFT = 20               # boxes sit 20 px below true centre (prototype)


class BossCutscene:
    def __init__(self, view_w, view_h):
        self.view_w = view_w
        self.view_h = view_h
        self.boss_num = 0
        self.outcome = "win"
        self.rects = []
        self.hovered = -1
        self.visible = False

    def open(self, boss_num, outcome):
        self.boss_num = boss_num
        self.outcome = outcome
        self.visible = True
        self.hovered = -1
        # Lay out NOW: hover/hit run before the first submit (levelup pattern).
        self.layout(self.view_w, self.view_h)

    def close(self):
        self.visible = False
        self.hovered = -1

    def layout(self, view_w, view_h):
        self.view_w, self.view_h = view_w, view_h
        total = 2 * _BOX_W + _GAP
        x0 = view_w // 2 - total // 2
        y0 = view_h // 2 - _BOX_H // 2 + _DOWN_SHIFT
        self.rects = [(x0, y0, _BOX_W, _BOX_H),
                      (x0 + _BOX_W + _GAP, y0, _BOX_W, _BOX_H)]

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self.hovered = next(
            (i for i, r in enumerate(self.rects) if contains(r, mx, my)), -1)

    def hit(self, mx, my):
        """``"A"`` / ``"B"`` for a click on an option box, else None. There is
        NO dismiss path — the host swallows every other click."""
        for i, rect in enumerate(self.rects):
            if contains(rect, mx, my):
                return "A" if i == 0 else "B"
        return None

    # -- render -----------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        won = self.outcome == "win"
        headline = ("Cutscene: Round Won :)" if won
                    else "Cutscene: Round Lost :(")
        color = _WIN_GREEN if won else _LOSS_RED
        cx = view_w // 2
        top = self.rects[0][1]
        submit_centered(renderer, headline, cx,
                        top - text_h("xxl") - text_h("md") - 28, "xxl", color)
        submit_centered(renderer, "How will we react?", cx,
                        top - text_h("md") - 12, "md", C_UI_TEXT_DIM)
        prefix = "Win" if won else "Loss"
        set_idx = (self.boss_num - 1) % 3 if self.boss_num else 0
        for i, option in enumerate(("A", "B")):
            self._submit_box(renderer, self.rects[i], prefix + option,
                             choice_desc(set_idx, option), i == self.hovered)

    @staticmethod
    def _submit_box(renderer, rect, label, desc, hovered):
        x, y, w, h = rect
        renderer.submit_hud(HudRect(
            rect, C_UI_BTN_HOVER if hovered else C_UI_PANEL))
        renderer.submit_hud(HudRect(
            rect, C_GOLD if hovered else C_UI_BORDER, width=1))
        cx = x + w // 2
        cursor = y + 12
        submit_centered(renderer, label, cx, cursor, "lg",
                        C_GOLD if hovered else C_UI_TEXT)
        cursor += text_h("lg") + 10
        for line in desc.split("\n"):
            submit_centered(renderer, line, cx, cursor, "sm", C_UI_TEXT_DIM)
            cursor += text_h("sm") + 2
