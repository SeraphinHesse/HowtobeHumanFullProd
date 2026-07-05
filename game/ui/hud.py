"""Main HUD (Phase 9G): love/income panel, lives, tile counter, phase banner,
End Turn button.

Pure logic (no pygame): reads the ``Session``/``RunState`` and the tile grid,
emits screen-space HUD primitives via ``renderer.submit_hud``. Ports the
prototype's ``src/ui/hud.py`` core (the speed controls, XP bar, boss/lightning
readouts and map-overlay toggles are their own later phases — 10A/10F/10G/10H/
10I). The hole is lives-based (HP mode was removed), so the base readout is a
life count, never an HP bar.
"""
from game.core.phases import GamePhase, GameState

from .widgets import (
    C_GOLD, C_HP_RED, C_PANEL_INSET, C_PANEL_STONE, C_RED, C_UI_BORDER,
    C_UI_TEXT_DIM, HEART, Button, submit_centered, submit_text, text_h,
)

_PHASE_LABEL = {
    GamePhase.BUILDING: "BUILDING",
    GamePhase.ENEMY: "COMBAT!",
    GamePhase.ROUND_END: "REBUILDING",
    GamePhase.INCOME: "PAYDAY",
}
_PHASE_COLOR = {
    GamePhase.ENEMY: C_RED,
    GamePhase.INCOME: C_GOLD,
}
_INCOME_PINK = (214, 96, 136)


def income_breakdown(session):
    """(gross_income, total_upkeep) this HUD would pay next payday — the flat
    base income plus every alive building's duck-typed ``yield_amount`` /
    ``upkeep`` (mirrors the payday sweep, so the readout can't drift)."""
    income = session.core_balance["TheHole"]["base_income"]
    upkeep = 0
    for t in session.tilemap.built_tiles():
        b = t.occupant
        if b is None or not getattr(b, "alive", False):
            continue
        yfn = getattr(b, "yield_amount", None)
        if yfn is not None:
            income += yfn()
        ufn = getattr(b, "upkeep", None)
        if ufn is not None:
            upkeep += ufn()
    return income, upkeep


def _tile_counts(tilemap):
    built = sum(1 for t in tilemap.built_tiles()
                if t.occupant is not None
                and getattr(t.occupant, "building_type", None) != "base")
    unlocked = len(tilemap.buildable_tiles()) + len(tilemap.built_tiles())
    return built, unlocked


class Hud:
    def __init__(self, view_w, view_h):
        self.end_turn = Button((0, 0, 160, 60), "END TURN", font_key="lg")
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        w, h = self.end_turn.rect[2], self.end_turn.rect[3]
        self.end_turn.rect = (view_w - w - 16, view_h - h - 16, w, h)

    def update(self, dt, mx, my, session, panel):
        st = session.state
        self.end_turn.enabled = (
            st.state == GameState.GAMEPLAY
            and st.phase == GamePhase.BUILDING
            and not panel.visible)
        self.end_turn.hover(mx, my)
        self.end_turn.update(dt)

    def hit(self, mx, my):
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

        # -- income line --------------------------------------------------
        income, upkeep = income_breakdown(session)
        net = income - upkeep
        sign = "+" if net >= 0 else ""
        submit_text(renderer, f"{sign}{net}{HEART}/round", (pill[0] + 4, 50),
                    "sm", _INCOME_PINK)

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

        # -- End Turn button + round (bottom-right) -----------------------
        bx, by, bw, bh = self.end_turn.rect
        submit_centered(renderer, f"ROUND {st.round_num}", bx + bw // 2,
                        by - text_h("md") - 4, "md", C_UI_TEXT_DIM)
        self.end_turn.submit(renderer)
        # a faint separator under the round text keeps the corner legible
        renderer.submit_hud(HudRect((bx, by - 2, bw, 1), C_UI_BORDER))
