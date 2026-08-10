"""Level-up window (Phase 10A) — the modal "CHOOSE YOUR REWARD" screen.

Pure logic. Ports the prototype's ``src/ui/levelup_window.py``: three option
boxes, no cancel button (the player MUST pick), resolution on click. The whole
world is frozen behind it (``Session.frozen``), so nothing animates.

Since 10J the backdrop is the prototype's real ``(0, 0, 0, 185)`` alpha dim —
the frozen world stays visible behind the window (RGBA ``HudRect``).

10L-B: ``ids`` names only ``backdrop`` — the option boxes are a dynamic-count
list (1-3, driven by the roll), the same "skip dynamic content" rule as every
other screen's list-shaped body; ``rects`` therefore stays a plain list of
tuples (test_levelup.py reads it directly). No per-widget id, but they DO
inherit the screen's ``defaults.panel_skin`` (B3): the boss_cutscene
``box_a``/``box_b`` CONDITIONAL-skin pattern, mirrored here — with no
``panel_skin`` set the boxes keep drawing their two raw hover-tinted rects,
byte-identical to pre-B2/B3 (the golden parity pin); a ``panel_skin`` present
routes every box through the skinned ``submit_panel`` instead, which needs a
real anim clock — this screen gains one here (10L-A explicitly left it
clockless; that was true only until a skinned path existed).
"""
from types import SimpleNamespace

from engine.render import HudLines, HudRect, HudSprite
from engine.render.fonts import layout_h

from .skinning import ScreenSkinning
from .widgets import (
    anim_ms, contains, label_holder, submit_centered, submit_label,
    submit_panel, wrap_text
)
from . import widgets
from .strings import T

_BG = (0, 0, 0, 185)  # prototype levelup_window.py alpha dim (10J)
# UR-5 fix (triage Step 1): the option box is a CONTAINER, but everything
# inside it is font-sized and fonts.json did not halve — so UR-2's 200x220 ->
# 100x110 left the box smaller than its own contents. Two measurements:
#   * width — ``wrap_text`` gets ``_BOX_W - 8``; at 92px, 5 of the 41 shipped
#     explanations wrap past ``max_lines=4`` and were SILENTLY TRUNCATED (at
#     the pre-UR-2 184px, the worst case was 3 lines). 122px is the measured
#     minimum that keeps all 41 within 4 lines -> _BOX_W = 130.
#   * height — the content stack in ``_submit_box`` measures 138px from the
#     box top (5 pad + 13 prev_name + 5 arrow + 16 title + 38 sprite + 13 cost
#     + 4x12 explanation), and the tier-progress footer needs another 14 below
#     it, so the box must be >= 154. At 110 the last two explanation lines and
#     the footer fell outside the box entirely.
# Three boxes: 3*130 + 2*4 = 398 of 640 wide, 154 of 360 tall.
_BOX_W, _BOX_H, _GAP = 130, 154, 4
# NOT module constants (UH-6): widgets.C_UI_PANEL/C_UI_BTN_HOVER are read at
# the _submit_box call site instead of copied here — a module-level `= widgets
# .C_UI_PANEL` would capture today's value at IMPORT time and never see a
# later configure_palette() rebind (the same "default arg" trap fonts.py's
# module docstring calls out, just at module scope instead of a def line).
# Same reasoning applies to the heading below (Phase C): read via T() at the
# submit() call site, never cached into a module constant.
_SPRITE_PX = 36

SCREEN_ID = "levelup"


class LevelupWindow:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.options = []
        self.rects = []
        self.hovered = -1
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        # UT-5: the heading is a FIXED line above the option row, so it earns
        # an id (unlike the 1-3 boxes below it). Its anchor is stored in
        # layout(), the text-label convention — the exporter reads a real
        # position and a rect override moves it.
        self._heading = label_holder(text_id="levelup.heading", font_key="xxl",
                                     text_color=None, align="center")
        self.ids = {}
        self._clock = 0.0  # 10L-B: only the skinned box path uses this

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
        else:
            total = n * _BOX_W + (n - 1) * _GAP
            x0 = view_w // 2 - total // 2
            y0 = view_h // 2 - _BOX_H // 2
            self.rects = [(x0 + i * (_BOX_W + _GAP), y0, _BOX_W, _BOX_H)
                          for i in range(n)]
        self._backdrop.rect = (0, 0, view_w, view_h)
        # layout_h: the heading anchor lands in the golden parity stream.
        top = self.rects[0][1] if self.rects else view_h // 2
        self._heading.rect = (view_w // 2, top - layout_h("xxl") - 8, 0, 0)
        self.ids = {"backdrop": ("backdrop", self._backdrop),
                    "heading": ("label", self._heading)}
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self._clock += dt
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
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        submit_label(renderer, self._heading, color=widgets.C_GOLD)
        panel_skin = self.skinning.defaults(self.screen_id).get("panel_skin")
        for i, option in enumerate(self.options):
            self._submit_box(renderer, self.rects[i], option, i == self.hovered,
                             panel_skin, t)

    def _submit_box(self, renderer, rect, option, hovered, panel_skin=None,
                    anim_ms_=0):
        x, y, w, h = rect
        if panel_skin:
            # 10L-B: a screen-level panel_skin default routes every option
            # box through the already-live skinned submit_panel (the
            # boss_cutscene box_a/box_b conditional-skin pattern, mirrored
            # for dynamic-count content via `defaults` instead of an id).
            submit_panel(renderer, rect, skin=panel_skin, anim_ms=anim_ms_)
        else:
            renderer.submit_hud(HudRect(
                rect,
                widgets.C_UI_BTN_HOVER if hovered else widgets.C_UI_PANEL))
            renderer.submit_hud(
                HudRect(rect, widgets.C_GOLD if hovered else widgets.C_UI_BORDER, width=1))
        cx = x + w // 2
        cursor = y + 5

        # layout_h throughout _submit_box: every cursor position below lands
        # directly in the golden parity stream's HudText.pos entries.
        prev_name = option.get("prev_name")
        if prev_name:
            submit_centered(renderer, prev_name, cx, cursor, "sm", widgets.C_UI_TEXT_DIM)
            cursor += layout_h("sm") + 2
            self._submit_up_arrow(renderer, cx, cursor)
            cursor += 5
        submit_centered(renderer, option["title"], cx, cursor, "md", widgets.C_UI_TEXT)
        cursor += layout_h("md") + 3

        slot = option.get("sprite_key")
        if slot:
            renderer.submit_hud(HudSprite(
                slot, (cx - _SPRITE_PX // 2, cursor), (_SPRITE_PX, _SPRITE_PX)))
        cursor += _SPRITE_PX + 2

        cost = option.get("display_cost", option["cost"])
        label = option.get("cost_label")
        if label:
            text = (T("levelup.cost_free") if cost <= 0
                    else T("levelup.cost_paid", label=label, cost=cost))
            submit_centered(renderer, text, cx, cursor, "sm", widgets.C_GOLD)
        cursor += layout_h("sm") + 2

        for line in wrap_text(option["explanation"], "sm", w - 8, max_lines=4):
            submit_centered(renderer, line, cx, cursor, "sm", widgets.C_UI_TEXT_DIM)
            cursor += layout_h("sm") + 1

        if option["kind"] == "tier":
            submit_centered(
                renderer, T("levelup.tier_progress", tier_no=option["tier_no"],
                           tier_max=option["tier_max"]),
                cx, y + h - layout_h("sm") - 3, "sm", widgets.C_UI_TEXT_DIM)

    @staticmethod
    def _submit_up_arrow(renderer, cx, y):
        """A small green chevron between the previous tier's name and this one."""
        renderer.submit_hud(HudLines(
            ((cx - 2, y + 3), (cx, y), (cx + 2, y + 3)), widgets.C_GREEN_STAT, width=2))
