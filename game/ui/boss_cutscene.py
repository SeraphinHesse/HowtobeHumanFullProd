"""Boss cutscene window (Phase 10G; BossUpgradeTimelinePLAN BU-4) — the modal
boss-upgrade picker.

Pure logic. A near-black overlay, a win/loss headline, "How will we react?",
and **THREE option boxes** — one per slot of this bossfight's milestone
(``game.core.boss_upgrades.milestone_slots``, the ``(boss_num - 1) % 4`` cycle,
D1/D2). Each box shows that catalog upgrade's designer-authored ``name`` and
``description``, the description ``.format()``-ed with its own live ``params``
so a card can never advertise a magnitude the math no longer uses (the same
rule 10G's ``choice_desc`` followed for the retired A/B narrative pick, which
BU-4 DELETED along with ``game/core/boss_bonuses.py``).
**No cancel — the player must pick one card**; the host swallows every other
click and all keys (``Session.frozen`` covers BOSS_CUTSCENE). Both outcomes
show the picker: a LOSS shows the retaliation-love headline *and* the same 3
cards (D7).

An EMPTY slot (a designer left it unassigned, or no ``boss_upgrades`` balance
is wired at all — the headless exporter/preview) still draws its box frame, so
the screen's geometry is stable and a designer can see the hole, but it carries
no text and is not hoverable or clickable.

Since 10J the backdrop is the prototype's real alpha-210 dim (RGBA
``HudRect``) — the frozen board stays faintly visible behind the choice.

10L-B: five ids (plan R3) — ``backdrop`` (color only), ``headline`` (font
only — its win/loss COLOR AND WHICH VARIANT stay logic-owned, a 2-variant
runtime pick, same "dynamic content" exclusion as HUD readouts; the variant
TEXT itself is Phase-C string-table content —
``boss_cutscene.headline_win``/``headline_loss``, ``game/ui/strings.py``),
``subtitle``
(font, text_color, **label** — a phase-B addition since its copy is fixed,
not game-state), ``box_a``/``box_b``/``box_c`` (rect — moves draw AND hit
together; font;
text_color; **skin** via the already-live skinned ``submit_panel`` — a
CONDITIONAL path: with no skin the box keeps drawing its two raw hover-tinted
rects, byte-identical to pre-B2 (the golden parity pin); a skin present
switches that ONE box to ``submit_panel``, which needs a real anim clock —
this screen gains one here (10L-A explicitly left it clockless; that was
true only until a skinned path existed)). ``box_c`` is BU-4's third slot,
APPENDED — the two existing ids keep their names and their meaning, which is
the on-disk contract ``data/ui/screens/boss_cutscene.json`` and
``screen_defaults.json`` are written against."""
from types import SimpleNamespace

from engine.render import HudRect
from engine.render.fonts import layout_h

from game.core import boss_upgrades

from .skinning import ScreenSkinning, is_visible
from .widgets import (
    anim_ms, contains, submit_centered, submit_label, submit_panel, wrap_text
)
from . import widgets
from .strings import T

_BG = (0, 0, 0, 210)           # prototype alpha dim (10J)
_WIN_GREEN = (100, 220, 100)
_LOSS_RED = (220, 100, 100)
#: BU-4: three columns, and each card now carries a full prose description
#: (the catalog's ``description``, wrapped) instead of 10G's pre-broken
#: two-liner — so the box grew from 90x65 to hold it. 3 * 200 + 2 * 12 = 624
#: of the 640-logical surface (UR-2), leaving an 8px margin a side; the height
#: holds a name row plus the worst-case 5-line wrap the shipped catalog
#: measures at under the SHIPPED face, with one line of slack (measured, not
#: guessed — and `_submit_box` clamps to the height regardless).
_BOX_W, _BOX_H, _GAP = 200, 104, 12
_BOX_PAD = 5                   # inner text inset, left/right/top/bottom
_DOWN_SHIFT = 10               # boxes sit 10 px below true centre (prototype)

SCREEN_ID = "boss_cutscene"


class BossCutscene:
    def __init__(self, view_w, view_h, core_balance, skinning=None,
                 boss_upgrades_balance=None):
        self.screen_id = SCREEN_ID
        # `core_balance` is the screen's UNCHANGED third positional (every call
        # site — the host, tools/screen_preview.py, tools/export_ui_layouts.py,
        # the golden pin — passes it there). It is no longer READ: BU-4
        # retired `boss_bonuses.choice_desc`, whose live `BossBonuses`
        # magnitudes were the only reason this screen ever held it. Kept
        # rather than dropped so the positional contract cannot be silently
        # mis-filled by a caller that was not updated.
        self.core_balance = core_balance
        # BU-4: the card copy + magnitudes (`["BossUpgrades"]["Catalog"]`) and
        # the milestone this bossfight offers. `None` is tolerated everywhere
        # (`game/core/boss_upgrades.py`'s "host-set optional" rule) — it simply
        # offers three empty slots.
        self.boss_upgrades_balance = boss_upgrades_balance
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.boss_num = 0
        self.outcome = "win"
        # Consolation love the LOST boss round already paid (session
        # `_begin_round_end`). 0 on a win, and on a loss whose era authored
        # `loss_love_reward: 0` — both keep the plain headline.
        self.love_reward = 0
        # The 3 catalog upgrade ids this milestone offers, resolved once in
        # `open()` (never per frame — the answer cannot change while the modal
        # is up). A slot may be None: an empty, still-drawn, unpickable box.
        self.slots = [None, None, None]
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
        # UT-5: both go out through ``submit_label`` now, so a ``visible``
        # override is honoured. ``headline`` keeps ``text_id=None`` on purpose
        # — it picks ONE OF TWO string ids from the runtime outcome, the same
        # ``text=`` escape hatch ``hud.py``'s phase banner uses.
        self._headline = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                         text_id=None, align="center",
                                         visible=True)
        self._subtitle = SimpleNamespace(rect=(0, 0, 0, 0), font_key="md",
                                         text_color=widgets.C_UI_TEXT_DIM,
                                         align="center", visible=True,
                                         text_id=None,
                                         label="How will we react?")
        self.box_a = SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                     font_key="lg", text_color=None)
        self.box_b = SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                     font_key="lg", text_color=None)
        self.box_c = SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                     font_key="lg", text_color=None)
        self.ids = {}

    @property
    def boxes(self):
        """The three option boxes in slot order — the ONE iteration order
        layout/hover/hit/submit all share, so they cannot drift apart."""
        return (self.box_a, self.box_b, self.box_c)

    def open(self, boss_num, outcome, love_reward=0):
        self.boss_num = boss_num
        self.outcome = outcome
        self.love_reward = int(love_reward or 0)
        self.slots = boss_upgrades.milestone_slots(self.boss_upgrades_balance,
                                                   boss_num)
        self.visible = True
        self.hovered = -1
        # Lay out NOW: hover/hit run before the first submit (levelup pattern).
        self.layout(self.view_w, self.view_h)

    def close(self):
        self.visible = False
        self.hovered = -1

    def layout(self, view_w, view_h):
        self.view_w, self.view_h = view_w, view_h
        boxes = self.boxes
        total = len(boxes) * _BOX_W + (len(boxes) - 1) * _GAP
        x0 = view_w // 2 - total // 2
        y0 = view_h // 2 - _BOX_H // 2 + _DOWN_SHIFT
        for i, box in enumerate(boxes):
            box.rect = (x0 + i * (_BOX_W + _GAP), y0, _BOX_W, _BOX_H)
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
            - layout_h(self._subtitle.font_key) - 14, 0, 0)
        self._subtitle.rect = (cx, top - layout_h(self._subtitle.font_key) - 6,
                              0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "headline": ("label", self._headline),
            "subtitle": ("label", self._subtitle),
            "box_a": ("panel", self.box_a),
            "box_b": ("panel", self.box_b),
            "box_c": ("panel", self.box_c),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self._clock += dt
        self.hovered = next(
            (i for i in self._pickable_indices()
             if contains(self.boxes[i].rect, mx, my)), -1)

    def _pickable_indices(self):
        """Box indices a click can actually resolve: visible AND carrying a
        real catalog id. An empty slot still DRAWS (stable geometry, and a
        designer sees the hole) but can never be picked or hovered."""
        return [i for i, box in enumerate(self.boxes)
                if is_visible(box) and self._slot(i) is not None]

    def _slot(self, i):
        """The catalog upgrade id in box ``i``, or None. Tolerates a short
        ``slots`` list (a hand-built screen that never called ``open``)."""
        return self.slots[i] if i < len(self.slots) else None

    def hit(self, mx, my):
        """The picked **upgrade id** (a catalog key string) for a click on a
        filled option box, else None — BU-4 replaced 10G's ``"A"``/``"B"``.
        There is NO dismiss path — the host swallows every other click."""
        for i in self._pickable_indices():
            if contains(self.boxes[i].rect, mx, my):
                return self._slot(i)
        return None

    # -- card copy ---------------------------------------------------------

    def _card(self, upgrade_id):
        """``(name, description)`` for one catalog id, the description
        ``.format()``-ed with that upgrade's own live ``params`` so the card
        always quotes the magnitude the hook site actually uses.

        Never raises: a designer-authored description naming a placeholder the
        params dict does not carry falls back to the raw text (a cosmetic
        string must not take down a fully modal screen).
        """
        catalog = {}
        if self.boss_upgrades_balance is not None:
            catalog = self.boss_upgrades_balance["BossUpgrades"]["Catalog"]
        entry = catalog.get(upgrade_id) or {}
        name = entry.get("name", upgrade_id)
        desc = entry.get("description", "")
        try:
            desc = desc.format(**entry.get("params", {}))
        except (KeyError, IndexError, ValueError):
            pass
        return name, desc

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
        # A loss that paid consolation love says so in the headline — the
        # same 2-variant runtime pick, with a third id for the templated case
        # (the plain loss id stays for a 0 reward).
        if won:
            headline = T("boss_cutscene.headline_win")
        elif self.love_reward > 0:
            headline = T("boss_cutscene.headline_loss_reward",
                         love=self.love_reward)
        else:
            headline = T("boss_cutscene.headline_loss")
        color = _WIN_GREEN if won else _LOSS_RED
        submit_label(renderer, self._headline, text=headline, color=color)
        submit_label(renderer, self._subtitle)
        for i, box in enumerate(self.boxes):
            if not is_visible(box):
                continue
            upgrade_id = self._slot(i)
            # An empty slot draws its frame and nothing else (see the module
            # docstring) — no label, no desc, never hovered.
            label, desc = (self._card(upgrade_id) if upgrade_id is not None
                           else ("", ""))
            self._submit_box(renderer, box, label, desc, i == self.hovered, t)

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
        if not label and not desc:
            return  # empty slot: the frame above is the whole card
        cx = x + w // 2
        cursor = y + _BOX_PAD
        label_color = (box.text_color if box.text_color is not None
                       else (widgets.C_GOLD if hovered else widgets.C_UI_TEXT))
        submit_centered(renderer, label, cx, cursor, box.font_key, label_color)
        # layout_h: this cursor position lands directly in HudText.pos
        # entries the golden parity stream captures.
        cursor += layout_h(box.font_key) + 5
        # BU-4: the catalog description is designer-authored PROSE, so it is
        # wrapped to the box rather than pre-broken at "\n", and clamped to
        # however many lines the box's remaining height actually holds — the
        # box can never overflow, whatever a designer types (or however wide
        # the shipped face is; `game/ui/CLAUDE.md`'s shipped-font rule).
        step = layout_h("sm") + 2
        max_lines = max(1, (y + h - _BOX_PAD - cursor) // step)
        for line in wrap_text(desc, "sm", w - 2 * _BOX_PAD, max_lines):
            submit_centered(renderer, line, cx, cursor, "sm", widgets.C_UI_TEXT_DIM)
            cursor += step
