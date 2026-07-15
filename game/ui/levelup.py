"""Level-up window (Phase 10A) — the modal "CHOOSE YOUR REWARD" screen.

Pure logic. Ports the prototype's ``src/ui/levelup_window.py``: three option
boxes, no cancel button (the player MUST pick), resolution on click. The whole
world is frozen behind it (``Session.frozen``), so nothing animates.

Since 10J the backdrop is the prototype's real ``(0, 0, 0, 185)`` alpha dim —
the frozen world stays visible behind the window (RGBA ``HudRect``).
"""
from engine.render import HudLines, HudRect, HudSprite

from .widgets import (
    C_GOLD, C_GREEN_STAT, C_UI_BORDER, C_UI_BTN_HOVER, C_UI_PANEL, C_UI_TEXT,
    C_UI_TEXT_DIM, HEART, contains, submit_centered, text_h, wrap_text,
)

_BG = (0, 0, 0, 185)  # prototype levelup_window.py alpha dim (10J)
_BOX_W, _BOX_H, _GAP = 200, 220, 8
_BOX_BG = C_UI_PANEL
_BOX_HOVER = C_UI_BTN_HOVER
_SPRITE_PX = 72
_HEADING = "CHOOSE YOUR REWARD"


class LevelupWindow:
    def __init__(self, view_w, view_h):
        self.view_w = view_w
        self.view_h = view_h
        self.options = []
        self.rects = []
        self.hovered = -1

    @property
    def visible(self):
        return bool(self.options)

    def open(self, options):
        self.options = list(options)
        self.hovered = -1
        # Lay out NOW: hover/hit run before the first submit, and the box count
        # decides the layout.
        self.layout(self.view_w, self.view_h)

    def close(self):
        self.options = []
        self.hovered = -1

    def layout(self, view_w, view_h):
        self.view_w, self.view_h = view_w, view_h
        n = len(self.options)
        if not n:
            self.rects = []
            return
        total = n * _BOX_W + (n - 1) * _GAP
        x0 = view_w // 2 - total // 2
        y0 = view_h // 2 - _BOX_H // 2
        self.rects = [(x0 + i * (_BOX_W + _GAP), y0, _BOX_W, _BOX_H)
                      for i in range(n)]

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self.hovered = next(
            (i for i, r in enumerate(self.rects) if contains(r, mx, my)), -1)

    def hit(self, mx, my):
        """The clicked option dict, or None. Clicks outside any box are
        swallowed by the host — there is no way to dismiss the window."""
        for i, rect in enumerate(self.rects):
            if contains(rect, mx, my) and i < len(self.options):
                return self.options[i]
        return None

    # -- render -----------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        top = self.rects[0][1] if self.rects else view_h // 2
        submit_centered(renderer, _HEADING, view_w // 2,
                        top - text_h("xxl") - 16, "xxl", C_GOLD)
        for i, option in enumerate(self.options):
            self._submit_box(renderer, self.rects[i], option, i == self.hovered)

    def _submit_box(self, renderer, rect, option, hovered):
        x, y, w, h = rect
        renderer.submit_hud(HudRect(rect, _BOX_HOVER if hovered else _BOX_BG))
        renderer.submit_hud(
            HudRect(rect, C_GOLD if hovered else C_UI_BORDER, width=1))
        cx = x + w // 2
        cursor = y + 10

        prev_name = option.get("prev_name")
        if prev_name:
            submit_centered(renderer, prev_name, cx, cursor, "sm", C_UI_TEXT_DIM)
            cursor += text_h("sm") + 2
            self._submit_up_arrow(renderer, cx, cursor)
            cursor += 10
        submit_centered(renderer, option["title"], cx, cursor, "md", C_UI_TEXT)
        cursor += text_h("md") + 6

        slot = option.get("sprite_key")
        if slot:
            renderer.submit_hud(HudSprite(
                slot, (cx - _SPRITE_PX // 2, cursor), (_SPRITE_PX, _SPRITE_PX)))
        cursor += _SPRITE_PX + 4

        cost = option.get("display_cost", option["cost"])
        label = option.get("cost_label")
        if label:
            text = "FREE" if cost <= 0 else f"{label}  {HEART}{cost}"
            submit_centered(renderer, text, cx, cursor, "sm", C_GOLD)
        cursor += text_h("sm") + 4

        for line in wrap_text(option["explanation"], "sm", w - 16, max_lines=4):
            submit_centered(renderer, line, cx, cursor, "sm", C_UI_TEXT_DIM)
            cursor += text_h("sm") + 1

        if option["kind"] == "tier":
            submit_centered(
                renderer, f"Tier {option['tier_no']} of {option['tier_max']}",
                cx, y + h - text_h("sm") - 6, "sm", C_UI_TEXT_DIM)

    @staticmethod
    def _submit_up_arrow(renderer, cx, y):
        """A small green chevron between the previous tier's name and this one."""
        renderer.submit_hud(HudLines(
            ((cx - 5, y + 6), (cx, y), (cx + 5, y + 6)), C_GREEN_STAT, width=2))
