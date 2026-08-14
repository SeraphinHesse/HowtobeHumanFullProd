"""Main HUD (Phase 9G): love/income panel, XP bar, lives, tile counter, the
bottom-right Building/Defending phase readout, End Turn button.

Pure logic (no pygame): reads the ``Session``/``RunState`` and the tile grid,
emits screen-space HUD primitives via ``renderer.submit_hud``. Ports the
prototype's ``src/ui/hud.py`` core (the speed controls, boss readouts
and map-overlay toggles are their own later phases — 10F/10G/10I). The hole
is lives-based (HP mode was removed), so the base readout is a life count, never
an HP bar.

The 10A XP bar drops the prototype's mascot face: it needs an ``xp_icon`` slot
that ``data/slots.json`` does not carry (revisit at 10L / the 11 parity audit).
10J added ``income_sources`` + the hover breakdown tooltip on the income line.
"""
import math
from types import SimpleNamespace

from engine.render.fonts import layout_h

from game.core.boss_bonuses import love_bonus_income
from game.core.lightning import LightningCaster
from game.core.phases import GamePhase, GameState
from game.core.xp import scaled_base_income

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, contains, label_holder, submit_bar, submit_centered,
    submit_label, submit_panel, submit_text, text_h, text_size
)
from . import widgets
from .strings import T

# -- 10H: lightning + cheat menu --
_LIGHTNING_READY = (255, 240, 80)    # prototype ready-label colour
_LIGHTNING_COOLING = (120, 120, 140)
# -- /10H --

# The phase readout's two-state copy. It used to be a six-way GamePhase ->
# string-id map (``_PHASE_LABEL_ID``) resolved through the Phase C string
# table; the readout moved bottom-right (above End Turn) and now says only
# which HALF of the round the player is in, so the map is gone. These two are
# CODE-OWNED module constants (the ``effects.py`` ``_ANNOUNCE_L1``/
# ``_ANNOUNCE_L2`` precedent), deliberately NOT new `strings.json` ids:
# `configure_strings` fails loud on a key-set mismatch, so adding ids would be
# a coupled `data/ui/strings.json` + `game/ui/strings.py` +
# `test_strings_data.py` change for two literals. A follow-up string-table
# pass is the place to migrate them (game/ui/CLAUDE.md "Not yet migrated").
# The six `hud.phase.*` ids stay in the string table, currently unreferenced.
_PHASE_PANEL_BUILDING = "Building Phase"
_PHASE_PANEL_DEFENDING = "Defending Phase"


def _phase_panel_text(phase):
    """The phase readout's TEXT: the player is either building or defending.
    A FUNCTION, not a dict of resolved text, for the same reason
    ``_phase_color`` below is one. Every phase that is not BUILDING (ENEMY /
    ROUND_END / INCOME / LEVELUP / BOSS_CUTSCENE) is the defending half of
    the round."""
    return (_PHASE_PANEL_BUILDING if phase == GamePhase.BUILDING
            else _PHASE_PANEL_DEFENDING)


def _phase_color(phase, default):
    """The phase banner's color, keyed by GamePhase (UH-6: a FUNCTION, not a
    module dict — a dict literal built from `widgets.C_RED`/`C_GOLD` at
    import time would freeze today's values and never see a later
    configure_palette() rebind; this looks the attribute up fresh on every
    call, same as every other palette read in this module)."""
    return {
        GamePhase.ENEMY: widgets.C_RED,
        GamePhase.LEVELUP: widgets.C_GOLD,
        GamePhase.INCOME: widgets.C_GOLD,
        GamePhase.BOSS_CUTSCENE: widgets.C_GOLD,      # -- 10G boss --
    }.get(phase, default)


_INCOME_PINK = (214, 96, 136)
_XP_PURPLE = (168, 105, 222)
_XP_TRACK = (48, 34, 66)
# -- 10L wave-3 phase 4: baked icon slots beside the readouts --
# UR-5 review: UR-2 HALVED these (18 -> 9, 4 -> 2) against
# planning/UiResolutionPLAN.md §2, which cites the 18x18 icons as its
# canonical "already 640-scale, LEAVE" example. The override is deliberate:
# these icons are sized against the HUD rows they sit in (the love pill is
# 34px tall today and halves to 17), so an unhalved 18px icon overflows a
# 17px pill. Physically neutral under SDL SCALED (18 logical px at 1x ==
# 9 logical px at 2x == the same 18 physical px). If the UR-5 eyeball pass
# disagrees with the bucket call, THIS is the first site it revisits.
# UR-5 verdict: KEPT at 9. Measured — the love pill is 17px tall and an 18px
# icon does not fit inside it; 9px clears the 13px "md" rows it sits beside.
_ICON_SIZE = 9   # fits the ~8-10px HUD rows without crowding the text
_ICON_GAP = 2
# -- /10L wave-3 --
# -- UR-5: the income/lives/tiles readout column. Its ROW STEP is font-scale
# (see _readout_step) — never halve it with the surface. Both the readout pill
# and the speed-button row below derive their geometry from these, so the two
# cannot drift back into the 2px overlap UR-2 left behind. --
_READOUT_TOP = 25    # first readout row, just under the 17px love pill
_READOUT_PAD = 2     # readout pill padding above the first / below the last row
_READOUT_CLEAR = 4   # readout pill bottom -> speed-button row top


def _readout_step():
    """Vertical step between the income / lives / tiles rows — ``layout_h`` of
    their font plus leading, NOT a pixel literal. A row step is a 640-scale
    (font) quantity per planning/UiResolutionPLAN.md §2; UR-2 halved it to 8px
    against a 13px line height and the three rows overlapped. A FUNCTION, not a
    module constant: a constant evaluated at import would freeze the
    pre-``configure_fonts`` fallback metrics (the same trap this module's
    palette/strings notes describe)."""
    return layout_h("md") + 3


def _readout_bottom():
    """Y one pixel past the readout pill (last row + padding) — the anchor the
    speed-button row sits below."""
    return _READOUT_TOP + 2 * _readout_step() + layout_h("md") + _READOUT_PAD
# -- 10J income tooltip (prototype hud.py:519-554 colours) --
_TOOLTIP_BG = (20, 15, 35)
_TOOLTIP_RED = (180, 80, 80)
_TOOLTIP_GOLD = (220, 180, 80)


def income_sources(session):
    """Ordered ``[(label, amount)]`` this HUD would pay next payday — the 10J
    income-tooltip breakdown (prototype ``game.py:1998-2006`` ``_income_sources``):
    ``Base`` always, then ``Musicians`` / ``Meditators`` / ``Story`` when
    nonzero, then a NEGATIVE ``Upkeep`` when nonzero. Mirrors the payday sweep
    so the readout can't drift; ``income_breakdown`` sums it, keeping the pill
    and the tooltip in lockstep."""
    musicians = meditators = upkeep = 0
    for t in session.tilemap.built_tiles():
        b = t.occupant
        if b is None or not getattr(b, "alive", False):
            continue
        yfn = getattr(b, "yield_amount", None)
        if yfn is not None:
            if getattr(b, "building_type", None) == "meditator":
                meditators += yfn()
            else:
                musicians += yfn()
        ufn = getattr(b, "upkeep", None)
        if ufn is not None:
            upkeep += ufn()
    # Boss-bonus story income: the SAME whole-board slot-3 sum payday pays
    # (Boss2A/2B), so the HUD net can't drift from the next payday.
    st = session.state
    story = love_bonus_income(st, session.tilemap, session.core_balance)
    sources = [(T("hud.income.base"), scaled_base_income(st, session.core_balance))]
    if musicians:
        sources.append((T("hud.income.musicians"), musicians))
    if meditators:
        sources.append((T("hud.income.meditators"), meditators))
    if story:
        sources.append((T("hud.income.story"), story))
    if upkeep:
        sources.append((T("hud.income.upkeep"), -upkeep))
    return sources


def income_breakdown(session):
    """(gross_income, total_upkeep) — summed off ``income_sources`` so the net
    pill and the 10J tooltip can never disagree."""
    sources = income_sources(session)
    income = sum(v for _, v in sources if v > 0)
    upkeep = -sum(v for _, v in sources if v < 0)
    return income, upkeep


def _tile_counts(tilemap):
    built_tiles = tilemap.built_tiles()
    built = sum(1 for t in built_tiles
                if t.occupant is not None
                and getattr(t.occupant, "building_type", None) != "base")
    unlocked = len(tilemap.buildable_tiles()) + len(built_tiles)
    return built, unlocked


SCREEN_ID = "hud"


class Hud:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        # font "md", not "lg": "END TURN" has no words left to cut and needs
        # 90px at "lg" under the SHIPPED pixel font (data/ui/active_font.json
        # -> pixel_emulator, wider per glyph than the SysFont fallback these
        # constants were authored against) in an 80px button. At "md" it needs
        # 68. A per-widget drop, deliberately NOT a change to
        # `data/ui/fonts.json` — the global presets must not move.
        self.end_turn = Button((0, 0, 80, 30), "END TURN", font_key="md")
        self.pause = Button((0, 0, 45, 15), "PAUSE", font_key="md")
        # -- 10L: fast-forward combat-speed buttons (top-left, below the
        # love/xp/income/lives/tiles readout column) --
        self.speed_1x = Button((0, 0, 28, 14), "1×", font_key="sm")
        self.speed_1_5x = Button((0, 0, 28, 14), "1.5×", font_key="sm")
        self.speed_2x = Button((0, 0, 28, 14), "2×", font_key="sm")
        # -- /10L speed --
        # -- drag-select: an always-available toggle sitting directly under the
        # speed row. Wider than a speed button because its label is longer at
        # font "sm"; the 14px height matches so the two rows read as a stack.
        # The FLIP itself lives in main.py's handle_world_click (never in
        # hit(), which the host calls twice per click) — this widget only
        # reports the click and draws the active rim off the host's flag.
        # Copy cut "DRAG SEL" -> "DRAG": the old label needed 58px in this
        # 45px button under the SHIPPED pixel font; "DRAG" needs 32. --
        self.drag_select_btn = Button((0, 0, 45, 14), "DRAG", font_key="sm")
        # -- /drag-select --
        self._clock = 0.0  # drives the levelup-pending pulse
        # The building panel is a full-height right sidebar and the HUD submits
        # AFTER it, so both right-edge buttons would paint on top of it. While
        # it is open they are neither drawn nor hit-tested.
        self._panel_open = False
        # Speed buttons are combat-only chrome: hidden outright in BUILDING
        # phase (build mode), where they have nothing to control (main.py's
        # sim_dt only ever scales the ENEMY phase — build mode always plays
        # at 1x regardless of the selected speed). Recomputed each frame in
        # update(); read back in hit()/submit() the `_panel_open` way, since
        # hit() has no session/phase access of its own.
        self._speed_buttons_visible = True
        # -- 10H --
        self._mx = self._my = 0  # cursor pos: anchors the cooldown bar
        # -- /10H --
        # -- 10L-B: love panel + phase label (added B2) --
        self._love_panel = SimpleNamespace(rect=(6, 6, 95, 17), visible=True)
        # The stone pill behind the income / lives / tiles column, drawn
        # exactly like ``love_panel`` (same body + inset border) so those
        # three readouts stay legible over the world. Its rect is finalized
        # in _layout_readouts() — it wraps the three text anchors.
        self._readout_panel = SimpleNamespace(rect=(6, 22, 95, 30),
                                              visible=True)
        # Its real (End-Turn-relative) rect is computed in _layout_readouts(),
        # the round_label precedent — hence the (0, 0, 0, 0) placeholder here.
        self._phase_label = SimpleNamespace(rect=(0, 0, 0, 0),
                                            font_key="hud_phase",
                                            text_color=None, visible=True,
                                            text_id=None, label="",
                                            align="left")
        # -- 10L-B review fix (HIGH 1): the ~10 stable readouts around the
        # love panel. TEXT stays game-state/code-owned for every one of these
        # (love count, level, xp fraction, income delta, lives, tile count,
        # round number) — the override surface is rect/font_key/text_color/
        # visible only, same principle as boss_cutscene's headline colour
        # staying win/loss-owned. Positions are finalized in submit() (they
        # are relative to the now-applied love_panel/end_turn rects), so
        # these get a SECOND skinning.apply() pass there. --
        # UT-4: each readout now names the `data/ui/strings.json` template
        # it draws through, so the editor can show and edit that text (and
        # re-point the widget at another id) instead of calling it code-owned.
        # The LIVE VALUES stay code-owned — they are the game state.
        self._love_text = label_holder(font_key="xl",
                                       text_id="hud.love_display")
        self._lvl_label = label_holder(font_key="hud_lvl",
                                       text_color=widgets.C_GOLD,
                                       text_id="hud.level")
        self._xp_bar = SimpleNamespace(rect=(0, 0, 55, 4), color=_XP_TRACK,
                                       visible=True)
        self._xp_text = label_holder(font_key="sm",
                                     text_color=widgets.C_UI_TEXT_DIM,
                                     text_id="hud.xp_progress")
        self._income_text = label_holder(font_key="sm",
                                         text_color=_INCOME_PINK,
                                         text_id="hud.income_net")
        self._lives_text = label_holder(font_key="md",
                                        text_color=widgets.C_HP_RED,
                                        text_id="hud.lives")
        self._tiles_text = label_holder(font_key="md",
                                        text_color=widgets.C_UI_TEXT_DIM,
                                        text_id="hud.tiles")
        # align="center" lives on the HOLDER, not on the submit_label call
        # below: it is a constant property of this label (it is centred on the
        # End Turn button), and the exporter reads alignment off the holder to
        # tell the editor which way the text spreads from the stored anchor.
        # Left as a call-site override it recorded as "left" and the editor
        # put the Round counter's hit box half a label to the right of the
        # glyphs. Every other centred label in game/ui already declares it
        # here; this was the one that did not.
        self._round_label = label_holder(font_key="md",
                                         text_color=widgets.C_UI_TEXT_DIM,
                                         align="center",
                                         text_id="hud.round")
        # -- 10L wave-3 phase 4: three baked icon slots beside their readouts.
        # Panel-kind holders (rect/skin/visible) routed through the skinned
        # submit_panel() path (10L-A) — a code-default skin means every
        # no-override draw already goes through the HudSprite branch (the
        # baked art is part of the real HUD, not an opt-in). Rects are
        # finalized in _layout_readouts() below (pill/bar-relative), never
        # inline at submit() time, per the anchor-rect convention. --
        self._icon_love = SimpleNamespace(rect=(0, 0, 0, 0),
                                          skin="ui_icon_love", visible=True)
        self._icon_xp = SimpleNamespace(rect=(0, 0, 0, 0),
                                        skin="ui_icon_xp", visible=True)
        self._icon_lives = SimpleNamespace(rect=(0, 0, 0, 0),
                                           skin="ui_icon_lives", visible=True)
        # -- /10L wave-3 --
        self.ids = {}
        # -- /10L-B --
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        w, h = self.end_turn.rect[2], self.end_turn.rect[3]
        self.end_turn.rect = (view_w - w - 8, view_h - h - 8, w, h)
        pw, ph = self.pause.rect[2], self.pause.rect[3]
        self.pause.rect = (view_w - pw - 8, 6, pw, ph)
        # (phase_label's rect is END-TURN-relative since it moved bottom-right,
        # so it is computed in _layout_readouts() — the round_label precedent.)
        # -- 10L: speed buttons — a fixed row below the readout column.
        # UR-5: derived from the readout pill's bottom rather than a literal
        # (UR-2's halved 55 landed 2px INSIDE the pill, which is font-sized). --
        sy = _readout_bottom() + _READOUT_CLEAR
        sw, sh, gap = 28, 14, 3
        self.speed_1x.rect = (6, sy, sw, sh)
        self.speed_1_5x.rect = (6 + sw + gap, sy, sw, sh)
        self.speed_2x.rect = (6 + 2 * (sw + gap), sy, sw, sh)
        # -- /10L speed --
        # -- drag-select: its own row directly below the speed row --
        sy2 = sy + sh + gap
        sw2 = self.drag_select_btn.rect[2]
        self.drag_select_btn.rect = (6, sy2, sw2, sh)
        # -- /drag-select --
        self.ids = {
            "btn_end_turn": ("button", self.end_turn),
            "btn_pause": ("button", self.pause),
            "love_panel": ("panel", self._love_panel),
            "btn_speed_1x": ("button", self.speed_1x),
            "btn_speed_1_5x": ("button", self.speed_1_5x),
            "btn_speed_2x": ("button", self.speed_2x),
            "btn_drag_select": ("button", self.drag_select_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def _layout_readouts(self):
        """Second ids/apply pass (10L-B review fix): these widgets' DEFAULT
        positions are relative to the now-finalized ``love_panel``/``end_turn``
        rects (post their own override in ``layout()``), so they cannot join
        the first pass without a chicken-and-egg ordering problem."""
        pill = self._love_panel.rect
        lvl_x, lvl_y = pill[0] + pill[2] + 6, pill[1]
        # layout_h: xp_bar's stored/id'd rect feeds screen_defaults.json.
        bar_y = lvl_y + layout_h("hud_lvl") + 3
        # -- 10L wave-3: icon_love sits inside the pill, left of the love
        # count; icon_xp sits left of the bar (lvl_label stays put — it's a
        # separate row above); icon_lives sits left of the lives text. Each
        # icon keeps its OLD anchor x, the text/bar it displaces moves right
        # by ICON + GAP. --
        icon_love_y = pill[1] + (pill[3] - _ICON_SIZE) // 2
        self._icon_love.rect = (pill[0] + 3, icon_love_y, _ICON_SIZE, _ICON_SIZE)
        love_x = self._icon_love.rect[0] + _ICON_SIZE + _ICON_GAP
        self._love_text.rect = (love_x, pill[1] + 3, 0, 0)
        self._lvl_label.rect = (lvl_x, lvl_y, 0, 0)
        icon_xp_y = bar_y - (_ICON_SIZE - 4) // 2
        self._icon_xp.rect = (lvl_x, icon_xp_y, _ICON_SIZE, _ICON_SIZE)
        bar_x = lvl_x + _ICON_SIZE + _ICON_GAP
        self._xp_bar.rect = (bar_x, bar_y, 55, 4)
        self._xp_text.rect = (bar_x, bar_y + 4 + 1, 0, 0)
        # UR-5 fix (triage Step 1, bucket "already 640-scale"): UR-2 halved the
        # income/lives/tiles row STEP with the container (16/18 -> 8/9), but a
        # text row step is a FONT-scale quantity and the fonts did not halve.
        # Measured: layout_h("md") == 13, so the three rows overlapped each
        # other by 5px and 4px. Derive the step from the font instead of a
        # literal, so it can never desync from fonts.json again.
        row0 = _READOUT_TOP
        step = _readout_step()
        self._income_text.rect = (pill[0] + 2, row0, 0, 0)
        self._icon_lives.rect = (pill[0] + 2, row0 + step, _ICON_SIZE, _ICON_SIZE)
        lives_x = self._icon_lives.rect[0] + _ICON_SIZE + _ICON_GAP
        self._lives_text.rect = (lives_x, row0 + step, 0, 0)
        self._tiles_text.rect = (pill[0] + 2, row0 + 2 * step, 0, 0)
        # The readout pill wraps the three rows above (income / lives / tiles)
        # off their DEFAULT anchors — the "no cascade" convention: a rect
        # override on one of those rows does not retarget this panel.
        # layout_h (never a live measurement): this rect is stored + exported.
        pad = _READOUT_PAD
        panel_top = self._income_text.rect[1] - pad
        panel_bottom = self._tiles_text.rect[1] + layout_h("md") + pad
        self._readout_panel.rect = (pill[0], panel_top, pill[2],
                                    panel_bottom - panel_top)
        bx, by, bw, _bh = self.end_turn.rect
        # layout_h: round_label's stored/id'd rect feeds screen_defaults.json.
        self._round_label.rect = (bx + bw // 2, by - layout_h("md") - 2, 0, 0)
        # The phase readout stacks directly above the round label, i.e. the
        # bottom-right cluster over the End Turn button (it used to sit
        # bottom-left at a fixed (6, view_h - 13)). Left-aligned on the
        # button's own left edge; "Defending Phase" at font hud_phase is
        # narrower than the End Turn button, so it cannot run off the right
        # edge.
        # layout_h (never a live measurement): this rect is stored + exported.
        self._phase_label.rect = (
            bx, self._round_label.rect[1] - layout_h("hud_phase") - 4, 0, 0)
        self.ids.update({
            "readout_panel": ("panel", self._readout_panel),
            "love_text": ("label", self._love_text),
            "lvl_label": ("label", self._lvl_label),
            "xp_bar": ("bar", self._xp_bar),
            "xp_text": ("label", self._xp_text),
            "income_text": ("label", self._income_text),
            "lives_text": ("label", self._lives_text),
            "tiles_text": ("label", self._tiles_text),
            "round_label": ("label", self._round_label),
            "phase_label": ("label", self._phase_label),
            "icon_love": ("panel", self._icon_love),
            "icon_xp": ("panel", self._icon_xp),
            "icon_lives": ("panel", self._icon_lives),
        })
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, session, panel, mouse_down=False):
        self._mx, self._my = mx, my  # 10H: the cursor cooldown-bar anchor
        st = session.state
        self._clock += dt
        # unlock / construct / upgrade / base_info, plus the construct preview
        # modal — any of them owns the right column.
        self._panel_open = panel.visible or panel.preview is not None
        # build mode = GamePhase.BUILDING; hidden there (see __init__ note)
        self._speed_buttons_visible = st.phase != GamePhase.BUILDING
        self.end_turn.enabled = (
            st.state == GameState.GAMEPLAY
            and st.phase == GamePhase.BUILDING
            and not self._panel_open)
        # 10L-B: an invisible button is neither hover-tracked nor hit — force
        # ``hovered`` off rather than skip ``hover()`` outright so a stale
        # True from before an override toggled it visible=False can't linger.
        self.end_turn.hover(mx, my, mouse_down)
        self.end_turn.hovered = self.end_turn.hovered and is_visible(self.end_turn)
        self.end_turn.update(dt)
        self.pause.enabled = (st.state == GameState.GAMEPLAY
                              and not self._panel_open)
        self.pause.hover(mx, my, mouse_down)
        self.pause.hovered = self.pause.hovered and is_visible(self.pause)
        self.pause.update(dt)
        # -- 10L: fast-forward speed buttons (round-gated per Session) --
        for idx, btn in ((0, self.speed_1x), (1, self.speed_1_5x),
                         (2, self.speed_2x)):
            btn.enabled = (st.state == GameState.GAMEPLAY
                          and not self._panel_open
                          and self._speed_buttons_visible
                          and session.speed_unlocked(idx))
            btn.hover(mx, my, mouse_down)
            btn.hovered = (btn.hovered and is_visible(btn)
                          and self._speed_buttons_visible)
            btn.update(dt)
        # -- /10L speed --
        # -- drag-select: same enable rule as `pause` — NO unlock/round gate,
        # so the toggle is clickable from round 0 on. --
        self.drag_select_btn.enabled = (st.state == GameState.GAMEPLAY
                                        and not self._panel_open)
        self.drag_select_btn.hover(mx, my, mouse_down)
        self.drag_select_btn.hovered = (self.drag_select_btn.hovered
                                        and is_visible(self.drag_select_btn))
        self.drag_select_btn.update(dt)
        # -- /drag-select --

    def hit(self, mx, my):
        if self._panel_open:
            return None
        if is_visible(self.pause) and self.pause.hit(mx, my):
            return "pause"
        # -- 10L: speed buttons — hidden in build mode, see update() --
        if self._speed_buttons_visible:
            if is_visible(self.speed_1x) and self.speed_1x.hit(mx, my):
                return ("speed", 0)
            if is_visible(self.speed_1_5x) and self.speed_1_5x.hit(mx, my):
                return ("speed", 1)
            if is_visible(self.speed_2x) and self.speed_2x.hit(mx, my):
                return ("speed", 2)
        # -- /10L speed --
        # -- drag-select: a PURE READ. main.py calls Hud.hit() twice per click
        # (the MOUSEBUTTONDOWN `over_ui` pan-arming probe, then for real from
        # handle_world_click on MOUSEBUTTONUP), so a self-toggling hit() —
        # MapOverlays.hit()'s pattern — would double-fire and cancel itself.
        # The host owns the flip, exactly like ("speed", idx). --
        if (is_visible(self.drag_select_btn)
                and self.drag_select_btn.hit(mx, my)):
            return "drag_select"
        # -- /drag-select --
        return ("end_turn" if is_visible(self.end_turn)
               and self.end_turn.hit(mx, my) else None)

    def submit(self, renderer, session, view_w, view_h, hover_cost=None,
              scene=None, drag_select_enabled=False, love_display=None):
        from engine.render import HudRect  # local: keep module import list lean

        st = session.state
        self.layout(view_w, view_h)
        self._layout_readouts()  # 10L-B: second apply() pass (pill-relative)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        t = anim_ms(self._clock)  # 10L-A skin anim clock, shared by every skin draw

        # -- love pill (top-left) -----------------------------------------
        pill = self._love_panel.rect
        if self._love_panel.visible:
            renderer.submit_hud(HudRect(pill, widgets.C_PANEL_STONE, border_radius=4))
            renderer.submit_hud(
                HudRect(pill, widgets.C_PANEL_INSET, border_radius=4, width=1))
        # -- 10L wave-3: love icon, left of the count inside the pill ------
        if is_visible(self._icon_love):
            submit_panel(renderer, self._icon_love.rect,
                        skin=self._icon_love.skin,
                        tint=getattr(self._icon_love, "tint", None), anim_ms=t)
        if hover_cost is not None:
            # Shows the arithmetic ("current - price"), not the remainder —
            # a player can read exactly what they have and what a purchase
            # costs at a glance. Always the real, unanimated `st.love`
            # (a correctness question — "can I afford this right now" — not
            # a payout-flavor display); shown the same way whether or not
            # it's affordable. Two separately-coloured runs (current love
            # stays the plain love colour, only the " - price" half reads
            # red) — two string-table ids rather than one combined template
            # hand-split in code, so each half stays independently
            # designer-editable.
            self._submit_love_hover_cost(renderer, st.love, hover_cost)
        else:
            amount = st.love if love_display is None else love_display
            submit_label(renderer, self._love_text, color=widgets.C_GOLD,
                         amount=amount)

        # -- XP bar + village level (right of the love pill) ---------------
        self._submit_xp(renderer, st)

        # -- readout pill behind income / lives / tiles ---------------------
        # panel BEFORE the three text rows it backs (the panel -> button ->
        # text house order); same body + inset border as the love pill.
        readout = self._readout_panel.rect
        if self._readout_panel.visible:
            renderer.submit_hud(
                HudRect(readout, widgets.C_PANEL_STONE, border_radius=4))
            renderer.submit_hud(
                HudRect(readout, widgets.C_PANEL_INSET, border_radius=4, width=1))

        # -- income line (hover -> 10J breakdown tooltip) -------------------
        sources = income_sources(session)
        net = sum(v for _, v in sources)
        sign = "+" if net >= 0 else ""
        submit_label(renderer, self._income_text, sign=sign, net=net)
        # prototype pill2 hover zone. UR-5: its HEIGHT is font-scale — UR-2
        # halved 18 -> 9 against a 13px "md" row, so the bottom 4px of the
        # income line was not hoverable. Derived from layout_h now.
        income_pill = (pill[0] - 5, _READOUT_TOP - 1, 59,
                       layout_h("md") + _READOUT_PAD)
        # DEFERRED to the very end of this method on purpose: the tooltip must
        # sit on the highest HUD layer so it stays in front of the readout
        # pill it overlaps (the building_ui terrain-tooltip precedent — an
        # "always on top" overlay, not a target of the panel/button/text rule).
        tooltip = (sources if sources and contains(income_pill, self._mx, self._my)
                  else None)

        # -- lives + tile counter -----------------------------------------
        if is_visible(self._icon_lives):
            submit_panel(renderer, self._icon_lives.rect,
                        skin=self._icon_lives.skin,
                        tint=getattr(self._icon_lives, "tint", None), anim_ms=t)
        submit_label(renderer, self._lives_text, count=st.base_lives)
        built, unlocked = _tile_counts(session.tilemap)
        submit_label(renderer, self._tiles_text, built=built,
                     unlocked=unlocked)

        # -- right-edge cluster: pause (top), phase + round + End Turn ------
        # The whole column lives under the building panel, so it is skipped
        # wholesale while that panel is open — drawing only part of it would
        # leave the round label floating over the panel.
        if not self._panel_open:
            bx, by, bw, bh = self.end_turn.rect
            # -- phase readout (bottom-right, directly above the round label).
            # Unclickable: a plain label holder, never hit-tested. It joins the
            # right-edge cluster's _panel_open gate rather than drawing
            # unconditionally, because the building panel is a full-height
            # 260px right sidebar and the HUD submits AFTER it — an
            # unconditional draw here would paint over the open panel. --
            # The two-state copy is a runtime enum pick, so it comes through
            # `text=`; position/font/colour stay the holder's (and the colour
            # still falls back to the phase colour when unset).
            submit_label(renderer, self._phase_label,
                         text=_phase_panel_text(st.phase),
                         color=_phase_color(st.phase, widgets.C_UI_TEXT_DIM))
            if self._round_label.visible:
                # TU-9: round 0 is the tutorial's own scripted round — shown
                # as the word "Tutorial" rather than "ROUND 0"; every round
                # from 1 on (including a skipped run, which starts at 1)
                # reads normally. Both strings go through T() so the Strings
                # panel owns the wording (Phase C).
                round_text = (T("hud.round_tutorial")
                              if st.round_num == 0 else None)
                submit_label(renderer, self._round_label, text=round_text,
                             n=st.round_num)
            # a faint separator under the round text keeps the corner legible
            # (panel-kind — submitted before the button it sits near so it
            # never draws on top of it; game/ui/CLAUDE.md "panel -> button ->
            # text").
            renderer.submit_hud(HudRect((bx, by - 2, bw, 1), widgets.C_UI_BORDER))
            if is_visible(self.end_turn):
                self.end_turn.submit(renderer, anim_ms=t,
                                     **button_kwargs(self.end_turn))
            if is_visible(self.pause):
                self.pause.submit(renderer, anim_ms=t,
                                  **button_kwargs(self.pause))
            # -- 10L: fast-forward speed buttons — active one gets the
            # overlays.py gold-rim treatment (overrides any skin color).
            # Hidden outright in build mode (BUILDING phase) — see update(). --
            if self._speed_buttons_visible:
                for idx, btn in ((0, self.speed_1x), (1, self.speed_1_5x),
                                 (2, self.speed_2x)):
                    if not is_visible(btn):
                        continue
                    if idx == session.combat_speed_idx:
                        btn.submit(renderer, color=widgets.C_UI_BTN,
                                  text_color=widgets.C_GOLD, anim_ms=t)
                        renderer.submit_hud(HudRect(btn.rect, widgets.C_GOLD,
                                                    width=2, border_radius=3))
                    else:
                        btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
            # -- /10L speed --
            # -- drag-select toggle: same gold-rim-when-active treatment as
            # the speed buttons; the state itself is the host's (gp[
            # "drag_select_enabled"]), threaded in per frame. --
            if is_visible(self.drag_select_btn):
                if drag_select_enabled:
                    self.drag_select_btn.submit(renderer,
                                                color=widgets.C_UI_BTN,
                                                text_color=widgets.C_GOLD,
                                                anim_ms=t)
                    renderer.submit_hud(HudRect(self.drag_select_btn.rect,
                                                widgets.C_GOLD, width=2,
                                                border_radius=3))
                else:
                    self.drag_select_btn.submit(
                        renderer, anim_ms=t,
                        **button_kwargs(self.drag_select_btn))
            # -- /drag-select --

        # -- lightning readout (10H; feature-storm-acolyte-multi-build reads
        # the scene's placed casters now, not a single RunState field) ------
        self._submit_lightning(renderer, session, view_h, scene)

        # -- income tooltip, LAST: topmost HUD layer (see the deferral above)
        if tooltip is not None:
            self._submit_income_tooltip(renderer, tooltip, income_pill)

    def _submit_love_hover_cost(self, renderer, current_love, hover_cost):
        """The love pill's hover-preview text, "current - price" as TWO
        separately-coloured runs: the current-love half in the plain love
        colour (a designer's ``text_color`` override on the ``love_text``
        id still wins, the "None means compute" convention every other
        override follows), the " - price" half always red — drawn
        immediately after it via a live width measurement (``text_size``),
        the same technique the income tooltip/lightning readout already use
        for hover-only text with no stored rect. Left-aligned only — the
        ``love_text`` holder is always left-aligned in practice; a future
        non-left override would need this rewritten, so it falls back to
        the single-colour combined draw instead of drawing wrong."""
        holder = self._love_text
        if not is_visible(holder):
            return
        if getattr(holder, "align", "left") != "left":
            submit_label(renderer, holder,
                         text=(T("hud.love_hover_cost_current", current=current_love)
                               + T("hud.love_hover_cost_price", price=hover_cost)),
                         color=widgets.C_RED)
            return
        current_text = T("hud.love_hover_cost_current", current=current_love)
        price_text = T("hud.love_hover_cost_price", price=hover_cost)
        x, y = holder.rect[0], holder.rect[1]
        current_col = getattr(holder, "text_color", None) or widgets.C_GOLD
        submit_text(renderer, current_text, (x, y), holder.font_key, current_col)
        current_w, _h = text_size(current_text, holder.font_key)
        submit_text(renderer, price_text, (x + current_w, y), holder.font_key,
                   widgets.C_RED)

    def _submit_income_tooltip(self, renderer, sources, anchor):
        """The 10J per-source breakdown below the income line (prototype
        ``hud.py:519-554``): green income rows, red ``Upkeep: -N``, gold
        ``Story upgrades: +N``; dark panel + border, left-aligned under the
        anchor."""
        from engine.render import HudRect  # local: keep module import list lean

        rows = []
        for label, amount in sources:
            # Compare against the RESOLVED category text (not a hardcoded
            # literal) so a designer renaming hud.income.upkeep/story in
            # strings.json can't desync this categorization from the label
            # income_sources() actually returned.
            if label == T("hud.income.upkeep"):
                rows.append((T("hud.tooltip_upkeep", amount=amount), _TOOLTIP_RED))
            elif label == T("hud.income.story"):
                rows.append((T("hud.tooltip_story", amount=amount), _TOOLTIP_GOLD))
            else:
                rows.append((T("hud.tooltip_income", label=label, amount=amount),
                            widgets.C_HP_GREEN))
        lh = text_h("sm") + 3
        w = max(text_size(t, "sm")[0] for t, _ in rows) + 4
        h = lh * len(rows) + 4
        x = max(2, anchor[0])
        y = anchor[1] + anchor[3] + 2
        renderer.submit_hud(HudRect((x, y, w, h), _TOOLTIP_BG))
        renderer.submit_hud(HudRect((x, y, w, h), widgets.C_UI_BORDER, width=1))
        ty = y + 2
        for text, color in rows:
            submit_text(renderer, text, (x + 2, ty), "sm", color)
            ty += lh

    def _submit_xp(self, renderer, st):
        """`LVL N`, a purple progress bar, and `xp/threshold`. When a level-up
        is pending the bar reads full and pulses gold (prototype `_render_xp`).
        10L-B: rect/font/track-colour are overridable (``lvl_label``/
        ``xp_bar``/``xp_text``); the ratio + pulse fill stay code-owned (a
        game-state value, like every other HUD readout).

        Under designer-scripted leveling XP is not a mechanic, so the bar, the
        icon and the `40/60` text are all suppressed — `LVL N` stays, since the
        village level itself is still very much a thing."""
        submit_label(renderer, self._lvl_label, n=st.village_level)
        if st.scripted_leveling:
            return
        if st.levelup_pending:
            ratio = 1.0
            # 0.5 Hz sine between the purple and gold ends of the ramp
            t = 0.5 + 0.5 * math.sin(self._clock * math.pi)
            fill = tuple(int(a + (b - a) * t)
                        for a, b in zip(_XP_PURPLE, widgets.C_GOLD))
        else:
            ratio = st.player_xp / st.xp_threshold if st.xp_threshold else 0.0
            fill = _XP_PURPLE
        # -- 10L wave-3: xp icon, left of the bar --------------------------
        if is_visible(self._icon_xp):
            submit_panel(renderer, self._icon_xp.rect,
                        skin=self._icon_xp.skin,
                        tint=getattr(self._icon_xp, "tint", None),
                        anim_ms=anim_ms(self._clock))
        if self._xp_bar.visible:
            bx, by, bw, bh = self._xp_bar.rect
            submit_bar(renderer, bx, by, bw, bh, ratio,
                      bg=self._xp_bar.color, fill=fill, border=widgets.C_UI_BORDER)
        submit_label(renderer, self._xp_text, current=st.player_xp,
                     threshold=st.xp_threshold)

    # -- 10H: lightning + cheat menu ---------------------------------------

    def _submit_lightning(self, renderer, session, view_h, scene):
        """Bottom-left strike readout + a tiny cursor-attached progress bar
        (prototype ``game.py:1829-1863``): shown only while ``phase == ENEMY``
        and lightning is unlocked. Ready -> `⚡ CLICK TO STRIKE`; cooling ->
        the live countdown for the SOONEST-ready placed acolyte (feature-
        storm-acolyte-multi-build — several may exist, each on its own
        cooldown; this readout tracks whichever will fire soonest). No
        placed ``lightning_source`` at all -> nothing to read out, even if
        ``lightning_level`` is latched > 0 from an earlier one that died
        without reviving yet. The backing is OPAQUE black — the HUD pass has
        no per-pixel alpha (10J), like the level-up backdrop."""
        from engine.render import HudRect  # local: keep module import list lean

        st = session.state
        if st.phase != GamePhase.ENEMY or st.lightning_level <= 0 or scene is None:
            return
        cooldowns = session.core_balance["LightningStrike"]["cooldown"]
        soonest = None   # (cooldown_left, tier_cooldown) of the best caster
        for b in scene.by_tag("lightning_source"):
            if not getattr(b, "alive", False):
                continue
            caster = b.get_component(LightningCaster)
            if caster is None:
                continue
            tier_cd = cooldowns[b.tier_number() - 1]
            if soonest is None or caster.cooldown < soonest[0]:
                soonest = (caster.cooldown, tier_cd)
        if soonest is None:
            return
        cooldown_left, tier_cooldown = soonest
        if cooldown_left <= 0:
            label, color = T("hud.lightning_ready"), _LIGHTNING_READY
        else:
            label = T("hud.lightning_cooldown",
                      seconds=f"{cooldown_left:.1f}")
            color = _LIGHTNING_COOLING
        w, h = text_size(label, "md")
        # Bottom-left, at the height the phase banner used to sit at (the
        # banner moved to the bottom-right cluster; this readout kept its own
        # prototype-derived position rather than sliding down into the corner).
        x, y = 6, view_h - 13 - h - 6
        renderer.submit_hud(HudRect((x - 2, y - 2, w + 4, h + 3), (0, 0, 0)))
        submit_text(renderer, label, (x, y), "md", color)
        # 11x2 cursor bar: black track, white fill; full = ready.
        # UR-5 review: halved from 22x3; a 2px-tall bar is at the floor.
        frac = 1.0 - (cooldown_left / tier_cooldown if tier_cooldown else 0.0)
        submit_bar(renderer, self._mx - 5, self._my + 8, 11, 2, frac,
                   bg=(0, 0, 0), fill=(255, 255, 255))

    # -- /10H ---------------------------------------------------------------
