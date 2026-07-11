"""Building interaction panel (Phase 9G): the right-side selection panel with
four modes (unlock / construct / upgrade / base_info) + the ConstructPreview
modal.

Pure logic. Ports the core of the prototype's ``src/ui/building_ui.py`` for the
two building lines that exist (Defender / Musician). The deferred depth — shift
multi-select, next-tier preview, terrain badges, name dice, lightning +
boss-history sections — lands with its owning phase (10B-10J). Costs are gated
against ``session.state.love`` here and spent by this module (the 9D/9F split:
``place_building`` / ``upgrade`` never touch RunState).

10A wired the research gates: the construct list only offers types the run has
earned, and the upgrade button runs the five-mode ``levelup.upgrade_gate``
classifier — a tier can only be ADVANCED into once it has been researched on a
level-up, and it stays unnamed until its ``unlock_min_round``.
"""
from game.buildings.components import RoundStats
from game.buildings.registry import (
    BUILDING_CLASSES, PlacementError, build_cost, create, place_building,
)
from game.buildings.research import buildable
from game.core.levelup import upgrade_gate
from game.core.xp import scaled_base_income
from game.map.tiles import TileState

from .widgets import (
    C_GOLD, C_HIGHLIGHT, C_HIGHLIGHT2, C_PANEL_STONE, C_RANGE_HIGHLIGHT,
    C_UI_BORDER, C_UI_PANEL, C_UI_TEXT, C_UI_TEXT_DIM, HEART, Button, contains,
    submit_panel, submit_tile_diamond, submit_text,
)


def _building_stats(b):
    """(label, value) rows for a building's current tier — the panel/preview
    stat block. Duck-typed so any future family is picked up."""
    rows = [("HP", b.max_hp())]
    if hasattr(b, "damage"):            # defence family
        rows.append(("Damage", b.damage()))
        rows.append(("Range", b.range_tiles()))
        rows.append(("Atk speed", f"{b.attack_speed():.1f}s"))
        rows.append(("Upkeep", b.upkeep()))
        # 10D: a booster is lifting these — show the un-boosted base for contrast.
        for label, base in b.boosted_stats().items():
            rows.append((f"{label} base", base))
    if hasattr(b, "boost_value"):       # boost building (10D) — buffs neighbours
        rows.append((b._boost_label, f"{b.boost_value() * 100:.1f}%"))
        rows.append(("Upkeep", b.upkeep()))
    if hasattr(b, "payout_amount"):     # painter — risky economy (no yield)
        rows.append(("Progress", f"{b.progress}/{b.rounds_to_payout()}"))
        rows.append(("Payout", f"{HEART}{b.payout_amount()}"))
        rows.append(("Pays in", f"{b.rounds_to_payout()} rounds"))
    elif hasattr(b, "streak_max"):      # meditator — compounding economy
        rows.append(("Yield", b.yield_amount()))  # pure (no streak advance)
        rows.append(("Streak", f"{b.streak}/{b.streak_max()}"))
    elif hasattr(b, "yield_amount"):    # musician
        rows.append(("Yield", b.yield_amount()))
    return rows


def _tier_name(b):
    """The building's current-tier display name from balancing (e.g. "Cave
    Painter"), not the art-slot prefix — so tiers that reuse another line's art
    (Meditator) or share one prefix (Painter) still title correctly."""
    return b.tier_data()["name"]


class ConstructPreview:
    """Centered modal for placing a new building: name entry + stat preview +
    confirm/cancel (positioned per ``ui.Timing``). Modal — the host routes all
    clicks/keys here while it is open."""

    def __init__(self, building_type, cost, buildings_balance, ui_balance,
                 view_w, view_h):
        self.building_type = building_type
        self.cost = cost
        self.view_w = view_w
        self.view_h = view_h
        temp = create(building_type, 0, 0, buildings_balance)
        self.title = _tier_name(temp)
        self.stats = _building_stats(temp)
        self.name = ""
        self.editing = False

        pw, ph = 340, 300
        x, y = view_w // 2 - pw // 2, view_h // 2 - ph // 2
        self.rect = (x, y, pw, ph)
        self.name_rect = (x + 16, y + 96, pw - 32, 30)
        self.close_btn = Button((x + pw - 26, y + 6, 20, 18), "X", "md")
        btn_y, bw, bh = y + ph - 48, 140, 34
        left = Button((x + 16, btn_y, bw, bh), "", "lg")
        right = Button((x + pw - 16 - bw, btn_y, bw, bh), "", "lg")
        show_cancel = ui_balance["Timing"]["construct_show_cancel"]
        confirm_right = ui_balance["Timing"]["confirm_on_right_side"]
        if show_cancel:
            self.confirm_btn = right if confirm_right else left
            self.cancel_btn = left if confirm_right else right
            self.confirm_btn.label = "CONFIRM"
            self.cancel_btn.label = "CANCEL"
        else:
            self.confirm_btn = Button((x + 16, btn_y, pw - 32, bh), "CONFIRM",
                                      "lg")
            self.cancel_btn = None

    @property
    def chosen_name(self):
        return self.name.strip() or f"Unnamed {self.title}"

    def hover(self, mx, my):
        self.confirm_btn.hover(mx, my)
        self.close_btn.hover(mx, my)
        if self.cancel_btn is not None:
            self.cancel_btn.hover(mx, my)

    def confirm_hovered(self):
        return self.confirm_btn.hovered

    def update(self, dt):
        self.confirm_btn.update(dt)
        self.close_btn.update(dt)
        if self.cancel_btn is not None:
            self.cancel_btn.update(dt)

    def handle_click(self, mx, my):
        """Return an action string (``confirm`` / ``cancel`` / ``close`` /
        ``name`` / None). The host treats the modal as consuming every click."""
        if self.close_btn.hit(mx, my):
            return "close"
        if self.cancel_btn is not None and self.cancel_btn.hit(mx, my):
            return "cancel"
        if self.confirm_btn.hit(mx, my):
            return "confirm"
        if contains(self.name_rect, mx, my):
            if not self.editing:
                self.editing = True
                self.name = ""  # click-to-clear (prototype)
            return "name"
        return None

    def handle_key(self, char, key):
        if not self.editing:
            return
        if key in ("return", "escape"):
            self.editing = False
        elif key == "backspace":
            self.name = self.name[:-1]
        elif char and char.isprintable() and len(self.name) < 20:
            self.name += char

    def submit(self, renderer):
        from engine.render import HudRect

        x, y, w, h = self.rect
        submit_panel(renderer, self.rect, fill=C_UI_PANEL, border=C_UI_BORDER)
        cx = x + w // 2
        submit_text(renderer, self.title, (cx, y + 12), "lg", C_UI_TEXT,
                    align="center")
        submit_text(renderer, f"Cost  {HEART}{self.cost}", (cx, y + 44), "md",
                    C_GOLD, align="center")
        submit_text(renderer, "Name:", (x + 16, y + 76), "sm", C_UI_TEXT_DIM)
        nx, ny, nw, nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect, C_HIGHLIGHT if self.editing else C_UI_BORDER,
            width=1))
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = C_UI_TEXT
        else:
            shown = "click to name"
            tcol = C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 8, ny + 7), "md", tcol)
        sy = y + 138
        for label, value in self.stats:
            submit_text(renderer, label, (x + 16, sy), "sm", C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (x + w - 16, sy), "sm", C_UI_TEXT,
                        align="right")
            sy += 20
        self.confirm_btn.submit(renderer)
        if self.cancel_btn is not None:
            self.cancel_btn.submit(renderer)
        self.close_btn.submit(renderer)


class BuildingUI:
    def __init__(self, view_w, view_h, ui_balance):
        self.view_w = view_w
        self.view_h = view_h
        self._ui_balance = ui_balance
        self._flash_dur = ui_balance["Timing"]["not_enough_love_duration"]
        self.panel_w = 260
        self.panel_x = view_w - self.panel_w
        self.panel_rect = (self.panel_x, 0, self.panel_w, view_h)
        self._right = self.panel_x + self.panel_w - 14
        self.mode = None
        self.tile = None
        self.preview = None
        self._selected = None
        self._session = None
        self._upgrade_hint = None
        self._buildings_balance = None
        self._highlight_tiles = []
        self._hover_cost = None
        self._action_cost = 0
        self.close_btn = Button(
            (self.panel_x + self.panel_w - 28, 8, 20, 18), "X", "md")
        self.action_btn = Button(
            (self.panel_x + 12, 0, self.panel_w - 24, 36), "", "lg")
        self.cards = []

    # -- open / close -----------------------------------------------------

    @property
    def visible(self):
        return self.mode is not None

    @property
    def hover_cost(self):
        return self._hover_cost

    def close(self):
        self.mode = None
        self.tile = None
        self.preview = None
        self._selected = None
        self._upgrade_hint = None
        self._highlight_tiles = []
        self._hover_cost = None
        self.cards = []

    def open_for_tile(self, tile, session, buildings_balance):
        self.close()
        if tile is None:
            return
        self._buildings_balance = buildings_balance
        self._session = session
        st = tile.state
        if st == TileState.COMBAT:
            self.mode, self.tile = "unlock", tile
            self._build_unlock(session)
        elif st == TileState.BUILDABLE:
            self.mode, self.tile = "construct", tile
            self._build_construct()
        elif st == TileState.BUILT:
            occ = tile.occupant
            if getattr(occ, "building_type", None) == "base":
                self.mode, self.tile = "base_info", tile
            elif occ is not None:
                self.mode, self.tile, self._selected = "upgrade", tile, occ
                self._build_upgrade()
                self._set_range_highlight(occ, session.tilemap)
        # SPAWNING / BACKGROUND / empty BUILT -> stays closed

    # -- per-mode builders ------------------------------------------------

    def _build_unlock(self, session):
        tm = session.tilemap
        cost = tm.unlock_cost(self.tile)
        adjacent = tm.can_unlock(self.tile)
        self._action_cost = cost
        self.action_btn.rect = (self.panel_x + 12, 150, self.panel_w - 24, 36)
        self.action_btn.enabled = adjacent
        self.action_btn.label = (
            f"UNLOCK  {HEART}{cost}" if adjacent else "NOT ADJACENT")
        hl = [(self.tile.col, self.tile.row, C_HIGHLIGHT)]
        for t in tm.get_chunk_for_tile(self.tile):
            if t is not self.tile:
                hl.append((t.col, t.row, C_HIGHLIGHT2))
        self._highlight_tiles = hl

    def _build_construct(self):
        self.cards = []
        y = 64
        state = self._session.state
        for btype in BUILDING_CLASSES:
            if not buildable(state, btype):
                continue  # type not unlocked / tier 1 not researched (10A)
            cost = build_cost(btype, self._buildings_balance)
            name = BUILDING_CLASSES[btype]._resolve_tiers(
                self._buildings_balance)[0]["name"]
            btn = Button((self.panel_x + 12, y, self.panel_w - 24, 42),
                         f"{name}  {HEART}{cost}", "md")
            self.cards.append((btype, btn))
            y += 50
        self._highlight_tiles = [(self.tile.col, self.tile.row, C_HIGHLIGHT)]

    def _build_upgrade(self):
        mode, cost, label, hint = self._upgrade_state(self._selected)
        self.action_btn.rect = (
            self.panel_x + 12, self.view_h - 120, self.panel_w - 24, 36)
        self.action_btn.enabled = mode in ("in_tier", "tier_upgrade")
        self.action_btn.label = label
        self._action_cost = cost if self.action_btn.enabled else 0
        self._upgrade_hint = hint

    def _upgrade_state(self, b):
        """``(mode, cost, button_label, hint)`` — the five-mode research gate
        (``game.core.levelup.upgrade_gate``). ``cost`` is only a love price for
        the two enabled modes; for ``tier_hidden`` it carries the unlock round."""
        mode, next_name, cost = upgrade_gate(
            self._session.state, b, self._buildings_balance)
        if mode == "in_tier":
            return mode, cost, f"UPGRADE  {HEART}{cost}", None
        if mode == "tier_upgrade":
            return mode, cost, f"ADVANCE: {next_name.upper()}  {HEART}{cost}", None
        if mode == "tier_locked":
            return mode, cost, "RESEARCH REQUIRED", "Research it on levelup"
        if mode == "tier_hidden":
            return mode, cost, "NEXT TIER LOCKED", f"Unlocks at round {cost}"
        return mode, 0, "MAX TIER", None

    def _set_range_highlight(self, b, tilemap):
        hl = [(b.col, b.row, C_HIGHLIGHT)]
        rfn = getattr(b, "range_tiles", None)
        if rfn is not None:
            r = int(rfn())
            for dc in range(-r, r + 1):
                for dr in range(-r, r + 1):
                    if dc == 0 and dr == 0:
                        continue
                    if tilemap.get(b.col + dc, b.row + dr) is not None:
                        hl.append((b.col + dc, b.row + dr, C_RANGE_HIGHLIGHT))
        self._highlight_tiles = hl

    # -- input ------------------------------------------------------------

    def hover(self, mx, my):
        self._hover_cost = None
        if self.preview is not None:
            self.preview.hover(mx, my)
            if self.preview.confirm_hovered():
                self._hover_cost = self.preview.cost
            return
        if not self.visible:
            return
        self.close_btn.hover(mx, my)
        if self.mode == "construct":
            for btype, btn in self.cards:
                btn.hover(mx, my)
                if btn.hovered:
                    self._hover_cost = build_cost(btype, self._buildings_balance)
        elif self.mode in ("unlock", "upgrade"):
            self.action_btn.hover(mx, my)
            if self.action_btn.hovered:
                self._hover_cost = self._action_cost

    def handle_key(self, char, key):
        if self.preview is not None:
            self.preview.handle_key(char, key)

    def handle_click(self, mx, my, session, buildings_balance, scene, occupancy):
        """Return True if the click was consumed by the UI (host must then NOT
        pick a tile). The preview modal consumes everything; an open panel
        consumes any click inside its rect."""
        if self.preview is not None:
            return self._preview_click(mx, my, session, buildings_balance,
                                       scene, occupancy)
        if not self.visible:
            return False
        if self.close_btn.hit(mx, my):
            self.close()
            return True
        if self.mode == "unlock":
            return self._unlock_click(mx, my, session)
        if self.mode == "construct":
            return self._construct_click(mx, my, session, buildings_balance)
        if self.mode == "upgrade":
            return self._upgrade_click(mx, my, session)
        return contains(self.panel_rect, mx, my)  # base_info: consume inside

    def _unlock_click(self, mx, my, session):
        if self.action_btn.hit(mx, my):
            tm, st = session.tilemap, session.state
            cost = tm.unlock_cost(self.tile)
            if not tm.can_unlock(self.tile):
                self.action_btn.start_flash(self._flash_dur, "NOT ADJACENT")
            elif st.love < cost:
                self.action_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
            elif tm.do_unlock(self.tile):
                st.spend_love(cost)
                self.close()
            return True
        return contains(self.panel_rect, mx, my)

    def _construct_click(self, mx, my, session, buildings_balance):
        for btype, btn in self.cards:
            if btn.hit(mx, my):
                cost = build_cost(btype, buildings_balance)
                if session.state.love < cost:
                    btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
                else:
                    self.preview = ConstructPreview(
                        btype, cost, buildings_balance, self._ui_balance,
                        self.view_w, self.view_h)
                return True
        return contains(self.panel_rect, mx, my)

    def _upgrade_click(self, mx, my, session):
        b, st = self._selected, session.state
        if self.action_btn.hit(mx, my):
            mode, cost, _, _ = self._upgrade_state(b)
            if mode not in ("in_tier", "tier_upgrade"):
                return True  # max / not researched / round-gated: inert
            if st.love < cost:
                self.action_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
                return True
            st.spend_love(cost)
            if mode == "tier_upgrade":
                b.advance_tier()
            else:
                b.upgrade()
            self._build_upgrade()
            self._set_range_highlight(b, session.tilemap)
            return True
        return contains(self.panel_rect, mx, my)

    def _preview_click(self, mx, my, session, buildings_balance, scene,
                       occupancy):
        action = self.preview.handle_click(mx, my)
        if action == "confirm":
            self._do_place(session, buildings_balance, scene, occupancy)
        elif action in ("cancel", "close"):
            self.preview = None
        return True  # modal consumes every click

    def _do_place(self, session, buildings_balance, scene, occupancy):
        p, st = self.preview, session.state
        try:
            building, cost = place_building(
                session.tilemap, self.tile, p.building_type, st.love,
                buildings_balance, scene, occupancy, state=st)
        except PlacementError:
            p.confirm_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
            return
        st.spend_love(cost)
        st.buildings_placed += 1
        building.set_name(p.chosen_name)
        self.preview = None
        self.open_for_tile(self.tile, session, buildings_balance)  # -> upgrade

    # -- per-frame --------------------------------------------------------

    def update(self, dt):
        self.action_btn.update(dt)
        self.close_btn.update(dt)
        for _, btn in self.cards:
            btn.update(dt)
        if self.preview is not None:
            self.preview.update(dt)

    def submit(self, renderer, session):
        for col, row, color in self._highlight_tiles:
            submit_tile_diamond(renderer, col, row, color)
        if not self.visible:
            return
        submit_panel(renderer, self.panel_rect)
        self.close_btn.submit(renderer)
        if self.mode == "unlock":
            self._submit_unlock(renderer, session)
        elif self.mode == "construct":
            self._submit_construct(renderer)
        elif self.mode == "upgrade":
            self._submit_upgrade(renderer)
        elif self.mode == "base_info":
            self._submit_base_info(renderer, session)
        if self.preview is not None:
            self.preview.submit(renderer)

    def _submit_unlock(self, renderer, session):
        x = self.panel_x + 14
        submit_text(renderer, "UNLOCK TILE", (x, 16), "lg", C_UI_TEXT)
        submit_text(renderer, "Unlocks a 2x2 area", (x, 70), "sm",
                    C_UI_TEXT_DIM)
        if not session.tilemap.can_unlock(self.tile):
            submit_text(renderer, "Must touch your territory", (x, 196), "sm",
                        C_UI_TEXT_DIM)
        self.action_btn.submit(renderer)

    def _submit_construct(self, renderer):
        submit_text(renderer, "BUILD", (self.panel_x + 14, 16), "lg", C_UI_TEXT)
        for _, btn in self.cards:
            btn.submit(renderer)

    def _submit_upgrade(self, renderer):
        x, b = self.panel_x + 14, self._selected
        title = _tier_name(b)
        submit_text(renderer, title, (x, 12), "lg", C_UI_TEXT)
        submit_text(renderer, f"Level {b.level}", (x, 46), "md", C_UI_TEXT_DIM)
        y = 92
        for label, value in _building_stats(b):
            submit_text(renderer, label, (x, y), "md", C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (self._right, y), "md", C_UI_TEXT,
                        align="right")
            y += 24
        rs = b.get_component(RoundStats)
        if rs is not None:
            y += 10
            submit_text(renderer, "Damage dealt", (x, y), "sm", C_UI_TEXT_DIM)
            submit_text(renderer, str(rs.dmg_dealt_last_round), (self._right, y),
                        "sm", C_UI_TEXT, align="right")
            y += 18
            submit_text(renderer, "Damage taken", (x, y), "sm", C_UI_TEXT_DIM)
            submit_text(renderer, str(rs.dmg_taken_last_round), (self._right, y),
                        "sm", C_UI_TEXT, align="right")
        self.action_btn.submit(renderer)
        if self._upgrade_hint:
            bx, by, bw, bh = self.action_btn.rect
            submit_text(renderer, self._upgrade_hint, (bx + bw // 2, by + bh + 6),
                        "sm", C_UI_TEXT_DIM, align="center")

    def _submit_base_info(self, renderer, session):
        x, st = self.panel_x + 14, session.state
        income = scaled_base_income(st, session.core_balance)
        submit_text(renderer, "THE HOLE", (x, 16), "lg", C_UI_TEXT)
        rows = [
            ("Lives", st.base_lives),
            ("Wave", st.round_num),
            ("Enemies killed", st.enemies_killed),
            ("Buildings", st.buildings_placed),
            ("Base income", f"{income}{HEART}/round"),
        ]
        y = 72
        for label, value in rows:
            submit_text(renderer, label, (x, y), "md", C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (self._right, y), "md", C_UI_TEXT,
                        align="right")
            y += 30
