"""Main HUD (Phase 9G): love/income panel, XP bar, lives, tile counter, phase
banner, End Turn button.

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

from game.core.boss_bonuses import (
    aoe_count, boss1b_income, boss3b_income, defence_count,
)
from game.core.phases import GamePhase, GameState
from game.core.xp import scaled_base_income

from .widgets import (
    C_GOLD, C_HP_GREEN, C_HP_RED, C_PANEL_INSET, C_PANEL_STONE, C_RED,
    C_UI_BORDER, C_UI_TEXT_DIM, HEART, Button, anim_ms, contains, submit_bar,
    submit_centered, submit_text, text_h, text_size,
)

# -- 10H: lightning + cheat menu --
_LIGHTNING_READY = (255, 240, 80)    # prototype ready-label colour
_LIGHTNING_COOLING = (120, 120, 140)
# -- /10H --

_PHASE_LABEL = {
    GamePhase.BUILDING: "BUILDING",
    GamePhase.ENEMY: "COMBAT!",
    GamePhase.ROUND_END: "REBUILDING",
    GamePhase.LEVELUP: "LEVEL UP",
    GamePhase.INCOME: "PAYDAY",
    GamePhase.BOSS_CUTSCENE: "CUTSCENE",  # -- 10G boss --
}
_PHASE_COLOR = {
    GamePhase.ENEMY: C_RED,
    GamePhase.LEVELUP: C_GOLD,
    GamePhase.INCOME: C_GOLD,
    GamePhase.BOSS_CUTSCENE: C_GOLD,      # -- 10G boss --
}
_INCOME_PINK = (214, 96, 136)
_XP_PURPLE = (168, 105, 222)
_XP_TRACK = (48, 34, 66)
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
    # -- 10G boss-bonus story income: one bounded block so the HUD net keeps
    # matching the next payday — the slot-3 payouts (Boss1B/3B) plus the
    # Boss2A/2B per-recipient deltas the income sweep will fold in (counts have
    # NO alive filter; recipients must be alive to be paid, like the sweep).
    st = session.state
    stacks = st.boss_stacks
    story = boss1b_income(st, session.tilemap) + boss3b_income(st, session.tilemap)
    if stacks["boss2a"]:
        n_musicians = sum(
            1 for t in session.tilemap.built_tiles()
            if getattr(t.occupant, "building_type", None) == "economic"
            and getattr(t.occupant, "alive", False))
        story += defence_count(session.tilemap) * stacks["boss2a"] * n_musicians
    if stacks["boss2b"]:
        n_meditators = sum(
            1 for t in session.tilemap.built_tiles()
            if getattr(t.occupant, "building_type", None) == "meditator"
            and getattr(t.occupant, "alive", False))
        story += aoe_count(session.tilemap) * stacks["boss2b"] * n_meditators
    # -- /10G --
    sources = [("Base", scaled_base_income(st, session.core_balance))]
    if musicians:
        sources.append(("Musicians", musicians))
    if meditators:
        sources.append(("Meditators", meditators))
    if story:
        sources.append(("Story", story))
    if upkeep:
        sources.append(("Upkeep", -upkeep))
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


class Hud:
    def __init__(self, view_w, view_h):
        self.end_turn = Button((0, 0, 160, 60), "END TURN", font_key="lg")
        self.pause = Button((0, 0, 90, 30), "PAUSE", font_key="md")
        self._clock = 0.0  # drives the levelup-pending pulse
        # The building panel is a full-height right sidebar and the HUD submits
        # AFTER it, so both right-edge buttons would paint on top of it. While
        # it is open they are neither drawn nor hit-tested.
        self._panel_open = False
        # -- 10H --
        self._mx = self._my = 0  # cursor pos: anchors the cooldown bar
        # -- /10H --
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        w, h = self.end_turn.rect[2], self.end_turn.rect[3]
        self.end_turn.rect = (view_w - w - 16, view_h - h - 16, w, h)
        pw, ph = self.pause.rect[2], self.pause.rect[3]
        self.pause.rect = (view_w - pw - 16, 12, pw, ph)

    def update(self, dt, mx, my, session, panel, mouse_down=False):
        self._mx, self._my = mx, my  # 10H: the cursor cooldown-bar anchor
        st = session.state
        self._clock += dt
        # unlock / construct / upgrade / base_info, plus the construct preview
        # modal — any of them owns the right column.
        self._panel_open = panel.visible or panel.preview is not None
        self.end_turn.enabled = (
            st.state == GameState.GAMEPLAY
            and st.phase == GamePhase.BUILDING
            and not self._panel_open)
        self.end_turn.hover(mx, my, mouse_down)
        self.end_turn.update(dt)
        self.pause.enabled = (st.state == GameState.GAMEPLAY
                              and not self._panel_open)
        self.pause.hover(mx, my, mouse_down)
        self.pause.update(dt)

    def hit(self, mx, my):
        if self._panel_open:
            return None
        if self.pause.hit(mx, my):
            return "pause"
        return "end_turn" if self.end_turn.hit(mx, my) else None

    def submit(self, renderer, session, view_w, view_h, hover_cost=None):
        from engine.render import HudRect  # local: keep module import list lean

        st = session.state
        self.layout(view_w, view_h)

        # -- love pill (top-left) -----------------------------------------
        pill = (12, 12, 190, 34)
        renderer.submit_hud(HudRect(pill, C_PANEL_STONE, border_radius=4))
        renderer.submit_hud(HudRect(pill, C_PANEL_INSET, border_radius=4, width=1))
        if hover_cost is not None:
            remaining = st.love - hover_cost
            love_txt = f"{HEART} {remaining}" if remaining >= 0 else f"{HEART} -"
            love_col = C_RED
        else:
            love_txt = f"{HEART} {st.love}"
            love_col = C_GOLD
        submit_text(renderer, love_txt, (pill[0] + 10, pill[1] + 7), "xl",
                    love_col)

        # -- XP bar + village level (right of the love pill) ---------------
        self._submit_xp(renderer, st, pill[0] + pill[2] + 12, pill[1])

        # -- income line (hover -> 10J breakdown tooltip) -------------------
        sources = income_sources(session)
        net = sum(v for _, v in sources)
        sign = "+" if net >= 0 else ""
        submit_text(renderer, f"{sign}{net}{HEART}/round", (pill[0] + 4, 50),
                    "sm", _INCOME_PINK)
        income_pill = (pill[0] - 10, 48, 118, 18)  # prototype pill2 hover zone
        if sources and contains(income_pill, self._mx, self._my):
            self._submit_income_tooltip(renderer, sources, income_pill)

        # -- lives + tile counter -----------------------------------------
        submit_text(renderer, f"LIVES {st.base_lives}", (pill[0] + 4, 66),
                    "md", C_HP_RED)
        built, unlocked = _tile_counts(session.tilemap)
        submit_text(renderer, f"{built}/{unlocked} tiles", (pill[0] + 4, 84),
                    "md", C_UI_TEXT_DIM)

        # -- phase banner (bottom-left) -----------------------------------
        label = _PHASE_LABEL.get(st.phase, st.phase.name)
        color = _PHASE_COLOR.get(st.phase, C_UI_TEXT_DIM)
        submit_text(renderer, label, (12, view_h - 26), "hud_phase", color)

        # -- right-edge cluster: pause (top), round + End Turn (bottom) ----
        # The whole column lives under the building panel, so it is skipped
        # wholesale while that panel is open — drawing only part of it would
        # leave the round label floating over the panel.
        if not self._panel_open:
            t = anim_ms(self._clock)
            bx, by, bw, bh = self.end_turn.rect
            submit_centered(renderer, f"ROUND {st.round_num}", bx + bw // 2,
                            by - text_h("md") - 4, "md", C_UI_TEXT_DIM)
            self.end_turn.submit(renderer, anim_ms=t)
            # a faint separator under the round text keeps the corner legible
            renderer.submit_hud(HudRect((bx, by - 2, bw, 1), C_UI_BORDER))
            self.pause.submit(renderer, anim_ms=t)

        # -- lightning readout (10H) ---------------------------------------
        self._submit_lightning(renderer, session, view_h)

    def _submit_income_tooltip(self, renderer, sources, anchor):
        """The 10J per-source breakdown below the income line (prototype
        ``hud.py:519-554``): green income rows, red ``Upkeep: -N``, gold
        ``Story upgrades: +N``; dark panel + border, left-aligned under the
        anchor."""
        from engine.render import HudRect  # local: keep module import list lean

        rows = []
        for label, amount in sources:
            if label == "Upkeep":
                rows.append((f"Upkeep: {amount}", _TOOLTIP_RED))
            elif label == "Story":
                rows.append((f"Story upgrades: +{amount}", _TOOLTIP_GOLD))
            else:
                rows.append((f"{label}: +{amount}", C_HP_GREEN))
        lh = text_h("sm") + 3
        w = max(text_size(t, "sm")[0] for t, _ in rows) + 8
        h = lh * len(rows) + 8
        x = max(2, anchor[0])
        y = anchor[1] + anchor[3] + 2
        renderer.submit_hud(HudRect((x, y, w, h), _TOOLTIP_BG))
        renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER, width=1))
        ty = y + 4
        for text, color in rows:
            submit_text(renderer, text, (x + 4, ty), "sm", color)
            ty += lh

    def _submit_xp(self, renderer, st, x, y):
        """`LVL N`, a purple progress bar, and `xp/threshold`. When a level-up
        is pending the bar reads full and pulses gold (prototype `_render_xp`)."""
        bar_w, bar_h = 110, 9
        if st.levelup_pending:
            ratio = 1.0
            # 0.5 Hz sine between the purple and gold ends of the ramp
            t = 0.5 + 0.5 * math.sin(self._clock * math.pi)
            color = tuple(int(a + (b - a) * t)
                          for a, b in zip(_XP_PURPLE, C_GOLD))
        else:
            ratio = st.player_xp / st.xp_threshold if st.xp_threshold else 0.0
            color = _XP_PURPLE
        submit_text(renderer, f"LVL {st.village_level}", (x, y), "hud_lvl",
                    C_GOLD)
        bar_y = y + text_h("hud_lvl") + 3
        submit_bar(renderer, x, bar_y, bar_w, bar_h, ratio,
                   bg=_XP_TRACK, fill=color, border=C_UI_BORDER)
        submit_text(renderer, f"{st.player_xp}/{st.xp_threshold}",
                    (x, bar_y + bar_h + 2), "sm", C_UI_TEXT_DIM)

    # -- 10H: lightning + cheat menu ---------------------------------------

    def _submit_lightning(self, renderer, session, view_h):
        """Bottom-left strike readout + a tiny cursor-attached progress bar
        (prototype ``game.py:1829-1863``): shown only while ``phase == ENEMY``
        and lightning is unlocked. Ready -> `⚡ CLICK TO STRIKE`; cooling ->
        the live countdown. The backing is OPAQUE black — the HUD pass has no
        per-pixel alpha (10J), like the level-up backdrop."""
        from engine.render import HudRect  # local: keep module import list lean

        st = session.state
        if st.phase != GamePhase.ENEMY or st.lightning_level <= 0:
            return
        cooldown = session.core_balance["LightningStrike"]["cooldown"][
            st.lightning_level - 1]
        if st.lightning_cooldown <= 0:
            label, color = "⚡ CLICK TO STRIKE", _LIGHTNING_READY
        else:
            label = f"⚡ {st.lightning_cooldown:.1f}s"
            color = _LIGHTNING_COOLING
        w, h = text_size(label, "md")
        x, y = 12, view_h - 26 - h - 12  # just above the phase banner
        renderer.submit_hud(HudRect((x - 4, y - 3, w + 8, h + 6), (0, 0, 0)))
        submit_text(renderer, label, (x, y), "md", color)
        # 22x3 cursor bar: black track, white fill; full = ready.
        frac = 1.0 - (st.lightning_cooldown / cooldown if cooldown else 0.0)
        submit_bar(renderer, self._mx - 11, self._my + 16, 22, 3, frac,
                   bg=(0, 0, 0), fill=(255, 255, 255))

    # -- /10H ---------------------------------------------------------------
