"""Boss cutscene window (Phase 10G) — the modal A/B story-choice screen.

Pure logic. Ports the prototype's ``src/ui/boss_cutscene.py``: a near-black
overlay, a win/loss headline, "How will we react?", and TWO option boxes
(``WinA``/``WinB`` or ``LossA``/``LossB``) whose descriptions come from
``game.core.boss_bonuses.BOSS_CHOICES`` (the choice SET cycles every 3 bosses).
**No cancel — the player must pick A or B**; the host swallows every other
click and all keys (``Session.frozen`` covers BOSS_CUTSCENE).

Since 10J the backdrop is the prototype's real alpha-210 dim (RGBA
``HudRect``) — the frozen board stays faintly visible behind the choice.

10L-B: five ids (plan R3) — ``backdrop`` (color only), ``headline`` (font
only — its win/loss COLOR AND WHICH VARIANT stay logic-owned, a 2-variant
runtime pick, same "dynamic content" exclusion as HUD readouts; the variant
TEXT itself is Phase-C string-table content —
``boss_cutscene.headline_win``/``headline_loss``, ``game/ui/strings.py``),
``subtitle``
(font, text_color, **label** — a phase-B addition since its copy is fixed,
not game-state), ``box_a``/``box_b`` (rect — moves draw AND hit together; font;
text_color; **skin** via the already-live skinned ``submit_panel`` — a
CONDITIONAL path: with no skin the box keeps drawing its two raw hover-tinted
rects, byte-identical to pre-B2 (the golden parity pin); a skin present
switches that ONE box to ``submit_panel``, which needs a real anim clock —
this screen gains one here (10L-A explicitly left it clockless; that was
true only until a skinned path existed)."""
from types import SimpleNamespace

from engine.render import HudRect
from engine.render.fonts import layout_h

from game.core.boss_bonuses import choice_desc

from .skinning import ScreenSkinning, is_visible
from .widgets import (
    anim_ms, contains, submit_centered, submit_panel
)
from . import widgets
from .strings import T

_BG = (0, 0, 0, 210)           # prototype alpha dim (10J)
_WIN_GREEN = (100, 220, 100)
_LOSS_RED = (220, 100, 100)
_BOX_W, _BOX_H, _GAP = 180, 130, 20
_DOWN_SHIFT = 20               # boxes sit 20 px below true centre (prototype)

SCREEN_ID = "boss_cutscene"


class BossCutscene:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.boss_num = 0
        self.outcome = "win"
        self.hovered = -1
        self.visible = False
        self._clock = 0.0  # 10L-B: only the skinned box_a/box_b path uses this
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        # ``rect`` on a label id is the anchor point submit_centered draws
        # from — W/H nominal 0 (position-only text, no fill/box implied),
        # same convention every other label id in game/ui uses (review fix:
        # every ids target needs a stored, readable, override-respecting
        # rect, not just font/colour).
        # headline is a win/loss 2-variant string built from runtime outcome
        # (like its color) — stays logic-owned, no `label` default (out of
        # scope per the "dynamic/enum-varying text" rule). subtitle is a
        # fixed, non-varying string, so — like every other screen's static
        # title — `label` is a legitimate override field for it.
        self._headline = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl")
        self._subtitle = SimpleNamespace(rect=(0, 0, 0, 0), font_key="md",
                                         text_color=widgets.C_UI_TEXT_DIM,
                                         label="How will we react?")
        self.box_a = SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                     font_key="lg", text_color=None)
        self.box_b = SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                     font_key="lg", text_color=None)
        self.ids = {}

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
        self.box_a.rect = (x0, y0, _BOX_W, _BOX_H)
        self.box_b.rect = (x0 + _BOX_W + _GAP, y0, _BOX_W, _BOX_H)
        self._backdrop.rect = (0, 0, view_w, view_h)
        # headline/subtitle sit above box_a's (default, pre-override) top —
        # the same "no cascade" convention every other container-relative
        # label in game/ui uses (a box_a rect OVERRIDE does not retarget
        # these; they'd need their own rect override to follow it).
        cx = view_w // 2
        top = y0
        # layout_h: headline/subtitle are stored/id'd rects (screen_defaults.
        # json + the golden parity stream).
        self._headline.rect = (
            cx, top - layout_h(self._headline.font_key)
            - layout_h(self._subtitle.font_key) - 28, 0, 0)
        self._subtitle.rect = (cx, top - layout_h(self._subtitle.font_key) - 12,
                              0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "headline": ("label", self._headline),
            "subtitle": ("label", self._subtitle),
            "box_a": ("panel", self.box_a),
            "box_b": ("panel", self.box_b),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self._clock += dt
        self.hovered = next(
            (i for i, box in enumerate((self.box_a, self.box_b))
             if is_visible(box) and contains(box.rect, mx, my)), -1)

    def hit(self, mx, my):
        """``"A"`` / ``"B"`` for a click on an option box, else None. There is
        NO dismiss path — the host swallows every other click."""
        for i, box in enumerate((self.box_a, self.box_b)):
            if is_visible(box) and contains(box.rect, mx, my):
                return "A" if i == 0 else "B"
        return None

    # -- render -----------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        won = self.outcome == "win"
        # Phase C: the TEXT is now string-table content (boss_cutscene.
        # headline_win/headline_loss) — the win/loss PICK stays logic-owned
        # (a 2-variant runtime string, same as the colour below), just like
        # the module docstring's "dynamic content" exclusion always meant.
        headline = T("boss_cutscene.headline_win" if won
                     else "boss_cutscene.headline_loss")
        color = _WIN_GREEN if won else _LOSS_RED
        submit_centered(renderer, headline, self._headline.rect[0],
                        self._headline.rect[1], self._headline.font_key, color)
        submit_centered(renderer, self._subtitle.label, self._subtitle.rect[0],
                        self._subtitle.rect[1], self._subtitle.font_key,
                        self._subtitle.text_color)
        prefix = "Win" if won else "Loss"
        set_idx = (self.boss_num - 1) % 3 if self.boss_num else 0
        for i, (option, box) in enumerate(
                (("A", self.box_a), ("B", self.box_b))):
            if not is_visible(box):
                continue
            self._submit_box(renderer, box, prefix + option,
                             choice_desc(set_idx, option), i == self.hovered, t)

    @staticmethod
    def _submit_box(renderer, box, label, desc, hovered, anim_ms_):
        rect = box.rect
        x, y, w, h = rect
        if box.skin:
            # 10L-B: a skin present routes through the already-live skinned
            # submit_panel — the same conditional Button/submit_panel already
            # use for skinned-vs-flat (fill/border become irrelevant, exactly
            # like submit_panel's own contract).
            submit_panel(renderer, rect, skin=box.skin,
                        tint=getattr(box, "tint", None), anim_ms=anim_ms_)
        else:
            renderer.submit_hud(HudRect(
                rect, widgets.C_UI_BTN_HOVER if hovered else widgets.C_UI_PANEL))
            renderer.submit_hud(HudRect(
                rect, widgets.C_GOLD if hovered else widgets.C_UI_BORDER, width=1))
        cx = x + w // 2
        cursor = y + 12
        label_color = (box.text_color if box.text_color is not None
                       else (widgets.C_GOLD if hovered else widgets.C_UI_TEXT))
        submit_centered(renderer, label, cx, cursor, box.font_key, label_color)
        # layout_h: this cursor position lands directly in HudText.pos
        # entries the golden parity stream captures.
        cursor += layout_h(box.font_key) + 10
        for line in desc.split("\n"):
            submit_centered(renderer, line, cx, cursor, "sm", widgets.C_UI_TEXT_DIM)
            cursor += layout_h("sm") + 2
