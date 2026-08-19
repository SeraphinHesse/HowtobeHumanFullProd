"""Level-up window (Phase 10A) — the modal "CHOOSE YOUR REWARD" screen.

Pure logic. Ports the prototype's ``src/ui/levelup_window.py``: three option
boxes, no cancel button (the player MUST pick), resolution on click. The whole
world is frozen behind it (``Session.frozen``), so nothing animates.

Since 10J the backdrop is the prototype's real ``(0, 0, 0, 185)`` alpha dim —
the frozen world stays visible behind the window (RGBA ``HudRect``).

10L-B named only ``backdrop`` in ``ids`` — the option boxes were a
dynamic-count list (1-3, driven by the roll), the "skip dynamic content" rule.
That is history twice over: the boxes became id'd slots (``option_box_0..2``),
and now so is everything INSIDE one — the title, the previous tier's name, the
sprite, the chevron, the cost line, the four explanation rows and the tier
footer each get a stable id and a stored rect (``option_box_1_title``, …), so a
designer can place, recolour, refont or hide any of them. See ``_new_parts``
for what is designer-owned and what stays code-owned; ``rects`` is still a
plain list of box tuples (test_levelup.py reads it directly). The boxes also
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
    anim_ms, contains, is_visible, label_holder, submit_label, submit_panel,
    wrap_text
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

# The roll offers 1-3 options. The COUNT is dynamic, but the SLOTS are not:
# there have always been exactly three possible positions, so each gets a
# stable id (`option_box_0..2`) and is individually overridable — rect, skin,
# tint, colour, visibility. This deliberately lifts the old "dynamic-count
# content is not individually overridable" rule for this screen (a designer
# asked for the buy options to be real editable widgets): the rule's real
# constraint was never "the count varies", it was "there is no stable id to
# attach an override to", and an index IS one here. The construct cards in
# building_ui.py get the same treatment keyed by building type.
_MAX_OPTIONS = 3
# The explanation is wrapped to at most four lines (`wrap_text(..., max_lines=
# 4)`), so the box holds exactly four explanation ROWS — a fixed count, hence
# four stable ids per slot. A roll whose text wraps to fewer simply leaves the
# tail holders undrawn; their stored rects stay put, which is what lets a
# designer place row 4 without knowing whether this particular reward uses it.
_EXPLANATION_LINES = 4

SCREEN_ID = "levelup"


def _new_parts():
    """The id'd widget group INSIDE one option box (feature: editable
    levelup text).

    Every text run and both graphics the box draws are individually
    overridable widgets now — rect, font, colour, family, alignment,
    visibility — the same treatment `building_ui.py`'s construct cards get
    (`card_<btype>_name` / `_price_text` / `_portrait`). What stays code-owned
    is the CONTENT: the title, the previous tier's name and the explanation
    come off the rolled option, so those three draw through `submit_label`'s
    `text=` bypass (its documented "authored at RUNTIME" case) and a `label`
    override on them is inert by construction rather than by editor policy.
    The cost line and the tier footer are templated instead — `text_id`s into
    `data/ui/strings.json` — so their wording IS designer-owned.

    `arrow` and `sprite` are `panel`-kind holders: they carry geometry (and,
    for the sprite, an optional `skin` override that replaces the rolled
    slot), not text.
    """
    return SimpleNamespace(
        prev_name=label_holder(font_key="sm", align="center"),
        arrow=SimpleNamespace(rect=(0, 0, 5, 4), visible=True),
        title=label_holder(font_key="md", align="center"),
        sprite=SimpleNamespace(rect=(0, 0, _SPRITE_PX, _SPRITE_PX), skin=None,
                               visible=True),
        cost=label_holder(font_key="sm", align="center",
                          text_id="levelup.cost_paid"),
        explanation=[label_holder(font_key="sm", align="center")
                     for _ in range(_EXPLANATION_LINES)],
        tier=label_holder(font_key="sm", align="center",
                          text_id="levelup.tier_progress"),
    )


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
        # One holder per option SLOT (see _MAX_OPTIONS): `rect` is the stored
        # geometry `layout()` computes and `skinning.apply()` may override,
        # `color`/`skin`/`tint` follow the usual "None means compute" holder
        # convention so an un-overridden box draws exactly as it always did.
        self._boxes = [SimpleNamespace(rect=(0, 0, _BOX_W, _BOX_H), skin=None,
                                       color=None, visible=True)
                       for _ in range(_MAX_OPTIONS)]
        # One id'd widget group per option SLOT — built once, re-laid-out per
        # roll, so a designer's override survives every reopen.
        self._parts = [_new_parts() for _ in range(_MAX_OPTIONS)]
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
        # DEFAULT geometry first — the centred row of however many boxes the
        # roll produced, exactly as before.
        defaults = []
        if n:
            total = n * _BOX_W + (n - 1) * _GAP
            x0 = view_w // 2 - total // 2
            y0 = view_h // 2 - _BOX_H // 2
            defaults = [(x0 + i * (_BOX_W + _GAP), y0, _BOX_W, _BOX_H)
                        for i in range(n)]
        for i, rect in enumerate(defaults):
            self._boxes[i].rect = rect
            self._layout_parts(i, rect, self.options[i])
        self._backdrop.rect = (0, 0, view_w, view_h)
        # layout_h: the heading anchor lands in the golden parity stream.
        top = defaults[0][1] if defaults else view_h // 2
        self._heading.rect = (view_w // 2, top - layout_h("xxl") - 8, 0, 0)
        self.ids = {"backdrop": ("backdrop", self._backdrop),
                    "heading": ("label", self._heading)}
        # Only the slots this roll actually offers are id'd — `apply()` walks
        # `ids`, so an override for a slot the roll didn't fill is simply not
        # applied this time. The exporter opens the window with a full three
        # so `screen_defaults.json` always records all three.
        for i in range(len(defaults)):
            self.ids[f"option_box_{i}"] = ("panel", self._boxes[i])
            self.ids.update(self._part_ids(i))
        self.skinning.apply(self.screen_id, self.ids)
        # AFTER apply, so an overridden rect drives hover/hit as well as the
        # draw — `self.rects` is the one geometry every consumer reads
        # (test_levelup.py included), and it must never disagree with what is
        # on screen.
        self.rects = [tuple(self._boxes[i].rect) for i in range(len(defaults))]

    def _part_ids(self, i):
        """`{id: (kind, holder)}` for option slot `i`'s inner widgets.

        Ids nest under the box's own (`option_box_1_title`), which is what
        gives them their parent in `data/ui/screen_defaults.json` and their
        branch in the editor's outliner. Every slot registers its FULL set
        every time, whatever the rolled option happens to contain — a reward
        with no previous tier still has an `option_box_i_prev_name` widget at
        the anchor that row would occupy, so the recorded defaults do not
        depend on which cards the mock roll produced.
        """
        p = self._parts[i]
        ids = {f"option_box_{i}_prev_name": ("label", p.prev_name),
               f"option_box_{i}_arrow": ("panel", p.arrow),
               f"option_box_{i}_title": ("label", p.title),
               f"option_box_{i}_sprite": ("panel", p.sprite),
               f"option_box_{i}_cost": ("label", p.cost)}
        for j, holder in enumerate(p.explanation):
            ids[f"option_box_{i}_explanation_{j}"] = ("label", holder)
        ids[f"option_box_{i}_tier"] = ("label", p.tier)
        return ids

    def _layout_parts(self, i, rect, option):
        """Store slot `i`'s inner geometry — the SAME cursor walk `_submit_box`
        used to do inline, moved up here so every position is a real stored
        rect an override can move (and the exporter can record).

        Two rules this walk keeps:
        * **It runs on the box's DEFAULT rect, before `skinning.apply()`.**
          Parenting is an authoring relationship, not a runtime one (the
          UiEditorParentingPLAN D2 rule every other screen follows): moving a
          box does NOT drag its children along. Each child is placed by its
          own override.
        * **A row the rolled option does not use is still placed**, at the
          anchor it *would* have had, without advancing the cursor — so the
          rows below it keep their pre-existing positions byte-for-byte
          (`prev_name`/`arrow` are the only two that can be absent, and they
          then share the title's anchor; neither is drawn, so nothing
          overlaps on screen).
        """
        x, y, w, h = rect
        p = self._parts[i]
        cx = x + w // 2
        cursor = y + 5
        prev_name = option.get("prev_name")
        p.prev_name.label = prev_name or ""
        p.prev_name.rect = (cx, cursor, 0, 0)
        # The chevron's own box: `_submit_up_arrow` draws (cx-2, y+3) ->
        # (cx, y) -> (cx+2, y+3), i.e. 5x4 anchored at its top-LEFT.
        p.arrow.rect = (cx - 2, cursor + layout_h("sm") + 2, 5, 4)
        if prev_name:
            cursor += layout_h("sm") + 2 + 5
        p.title.label = option["title"]
        p.title.rect = (cx, cursor, 0, 0)
        cursor += layout_h("md") + 3
        p.sprite.rect = (cx - _SPRITE_PX // 2, cursor, _SPRITE_PX, _SPRITE_PX)
        cursor += _SPRITE_PX + 2
        # FREE and "<label>  <cost>" are two different templates, so the
        # holder's `text_id` is picked per roll — both keys stay editable in
        # `data/ui/strings.json`.
        cost = option.get("display_cost", option["cost"])
        p.cost.text_id = ("levelup.cost_free" if cost <= 0
                          else "levelup.cost_paid")
        p.cost.rect = (cx, cursor, 0, 0)
        cursor += layout_h("sm") + 2
        for holder in p.explanation:
            holder.rect = (cx, cursor, 0, 0)
            cursor += layout_h("sm") + 1
        p.tier.rect = (cx, y + h - layout_h("sm") - 3, 0, 0)

    def update(self, dt, mx, my, mouse_down=False):
        # 10L-A: no widgets.Button here (plain option-box rects) — mouse_down
        # is accepted only so main.py's uniform threading call keeps working.
        self._clock += dt
        # A box hidden by a `visible: false` override is not hoverable — the
        # same rule every id'd button already follows (see game/ui/CLAUDE.md's
        # "visible=False skips BOTH submit AND hover/hit").
        self.hovered = next(
            (i for i, r in enumerate(self.rects)
             if self._box_visible(i) and contains(r, mx, my)), -1)

    def _box_visible(self, i):
        """Whether option slot `i` is drawn AND clickable.

        ANTI-SOFTLOCK: this modal has no dismiss path — the player MUST pick
        one — so if a `visible: false` override would hide EVERY offered box
        the overrides are ignored wholesale and all of them stay live. A
        designer hiding one or two boxes gets what they asked for; a designer
        hiding all of them gets a playable game instead of a frozen one."""
        if i >= len(self._boxes):
            return False
        if any(is_visible(self._boxes[j]) for j in range(len(self.rects))):
            return is_visible(self._boxes[i])
        return True

    def hit(self, mx, my):
        """The clicked option dict, or None. Clicks outside any box are
        swallowed by the host — there is no way to dismiss the window."""
        for i, rect in enumerate(self.rects):
            if (self._box_visible(i) and contains(rect, mx, my)
                    and i < len(self.options)):
                return self.options[i]
        return None

    # -- render -----------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        submit_label(renderer, self._heading, color=widgets.C_GOLD)
        default_skin = self.skinning.defaults(self.screen_id).get("panel_skin")
        for i, option in enumerate(self.options):
            if not self._box_visible(i):
                continue
            box = self._boxes[i]
            # Per-box `skin` wins over the screen-level `defaults.panel_skin`
            # — the same precedence every id'd widget already uses (an
            # override beats a kind-matched default).
            self._submit_box(renderer, self.rects[i], self._parts[i], option,
                             i == self.hovered,
                             getattr(box, "skin", None) or default_skin, t,
                             fill=getattr(box, "color", None),
                             tint=getattr(box, "tint", None))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)

    def _submit_box(self, renderer, rect, parts, option, hovered,
                    panel_skin=None, anim_ms_=0, fill=None, tint=None):
        x, y, w, h = rect
        if panel_skin:
            # 10L-B: a screen-level panel_skin default routes every option
            # box through the already-live skinned submit_panel (the
            # boss_cutscene box_a/box_b conditional-skin pattern, mirrored
            # for dynamic-count content via `defaults` instead of an id).
            submit_panel(renderer, rect, skin=panel_skin, anim_ms=anim_ms_,
                         tint=tint)
        else:
            # `fill` is the box's own `color` override; None keeps the
            # code-computed hover/idle pair ("None means compute").
            renderer.submit_hud(HudRect(
                rect,
                tuple(fill) if fill is not None
                else (widgets.C_UI_BTN_HOVER if hovered else widgets.C_UI_PANEL)))
            renderer.submit_hud(
                HudRect(rect, widgets.C_GOLD if hovered else widgets.C_UI_BORDER, width=1))

        # Every run below draws off a holder `_layout_parts` positioned and
        # `skinning.apply()` may since have rewritten — geometry, font, family,
        # colour and visibility are all the designer's. The CONTENT still comes
        # from the rolled option, hence `text=` on the three runtime-authored
        # runs (see `_new_parts`).
        prev_name = option.get("prev_name")
        if prev_name:
            submit_label(renderer, parts.prev_name, text=prev_name,
                         color=widgets.C_UI_TEXT_DIM)
            self._submit_up_arrow(renderer, parts.arrow)
        submit_label(renderer, parts.title, text=option["title"],
                     color=widgets.C_UI_TEXT)

        # A `skin` override on the sprite holder REPLACES the rolled slot —
        # the usual "an override wins" rule; with none set the option's own
        # sprite_key draws, and no sprite at all draws nothing.
        slot = getattr(parts.sprite, "skin", None) or option.get("sprite_key")
        if slot and is_visible(parts.sprite):
            sx, sy, sw, sh = parts.sprite.rect
            renderer.submit_hud(HudSprite(
                slot, (sx, sy), (sw, sh),
                tint=getattr(parts.sprite, "tint", None)))

        cost = option.get("display_cost", option["cost"])
        label = option.get("cost_label")
        if label:
            # Both templates take the same kwargs: `T` is `str.format`, which
            # ignores the surplus ones `levelup.cost_free` does not spend.
            submit_label(renderer, parts.cost, color=widgets.C_GOLD,
                         label=label, cost=cost)

        # The wrap is a LIVE font measurement, so it happens here and never in
        # `_layout_parts` — a stored rect must not depend on the platform's
        # text metrics (game/ui/CLAUDE.md). The holders are the rows; a
        # shorter wrap simply leaves the tail ones undrawn.
        lines = wrap_text(option["explanation"], "sm", w - 8,
                          max_lines=_EXPLANATION_LINES)
        for holder, line in zip(parts.explanation, lines):
            submit_label(renderer, holder, text=line,
                         color=widgets.C_UI_TEXT_DIM)

        if option["kind"] == "tier":
            submit_label(renderer, parts.tier, color=widgets.C_UI_TEXT_DIM,
                         tier_no=option["tier_no"], tier_max=option["tier_max"])

    @staticmethod
    def _submit_up_arrow(renderer, holder):
        """A small green chevron between the previous tier's name and this one.

        Drawn off its own id'd holder's rect (top-left + 5x4), so a designer
        can move or hide it independently of the name above it."""
        if not is_visible(holder):
            return
        x, y, w, h = holder.rect
        cx = x + w // 2
        renderer.submit_hud(HudLines(
            ((cx - 2, y + h - 1), (cx, y), (cx + 2, y + h - 1)),
            widgets.C_GREEN_STAT, width=2))
