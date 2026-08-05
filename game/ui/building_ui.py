"""Building interaction panel (Phase 9G): the right-side selection panel with
four modes (unlock / construct / upgrade / base_info) + the ConstructPreview
modal.

Pure logic. Ports the prototype's ``src/ui/building_ui.py``: panel modes +
terrain badges (10I), the boss-history section (10G), and the 10J
depth — shift multi-select batches (unlock chunk-dedup / construct ×count /
in-tier upgrade sums; tier advance stays primary-only), the name dice, the
upgrade-panel rename row (custom names + rebirth ordinals finally render),
the hover-gated green in-tier stat preview + next-tier card, and the DIED
LAST ROUND tag. Costs are gated against ``session.state.love`` here and spent
by this module (the 9D/9F split: ``place_building`` / ``upgrade`` never touch
RunState).

10A wired the research gates: the construct list only offers types the run has
earned, and the upgrade button runs the five-mode ``levelup.upgrade_gate``
classifier — a tier can only be ADVANCED into once it has been researched on a
level-up, and it stays unnamed until its ``unlock_min_round``.

**feature-storm-acolyte-multi-build**: the Storm Priest run-singleton
grey-out is REMOVED — several may be placed, each priced steeper than the
last (``count_tag``/``LIGHTNING_SOURCE_TAG``, ``game/buildings/registry.py``)
via the group's ``repeat_cost_multiplier``. See that module's doc + `game/
core/CLAUDE.md`'s lightning section for the per-caster level/cooldown side
of the rework.
"""
import random  # 10J: the name-dice reroll (stdlib — pure)
from types import SimpleNamespace

from game.buildings.components import (
    BoostReceiver, Nameplate, RoundStats, TierState, YieldEconomy,
)
from game.buildings.registry import (
    BUILDING_CLASSES, LIGHTNING_SOURCE_TAG, PlacementError, build_cost,
    count_tag, create, place_building,
)
from game.buildings.research import buildable, tiers_unlocked_for
from game.core import lightning  # 10H (sanctioned ui -> core direction)
from game.core.levelup import upgrade_gate
from game.core.xp import scaled_base_income
from game.debug import events as dbg  # debug-mode-telemetry Phase 2
from game.map.tiles import CONDITION_MODIFIER_KEY, TileCondition, TileState

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, contains, submit_panel,
    submit_tile_diamond, submit_text, text_h, text_size
)
from . import widgets

# Both BuildingUI and its nested ConstructPreview share ONE screen id (they
# are one editable "screen" — the panel and its modal preview) with disjoint
# id namespaces ("preview_*" prefix keeps ConstructPreview's ids from
# colliding with BuildingUI's own).
SCREEN_ID = "building_panel"

# 10I: tooltip chrome — dark panel, 1px border in the condition colour
# (prototype building_ui.py:1440-1455).
_COND_TOOLTIP_BG = (20, 15, 35)
# -- 10J: the name-dice glyph (prototype building_ui.py:106) --
_DICE_GLYPH = "⚄"


def _batch_cost(building_type, buildings_balance, tier_idx, repeat_count, count):
    """The escalating BATCH total for ``count`` fresh placements of
    ``building_type`` (feature-storm-acolyte-multi-build), each tile priced
    at its own escalation step — ``repeat_count``, ``repeat_count + 1``, …,
    ``repeat_count + count - 1`` — via ``build_cost`` per step. This is the
    SAME formula ``place_building`` recomputes per tile as ``_do_place``
    walks a batch (each placed tile raises the live ``count_tag`` count
    before the next tile is priced), so this total always agrees with what
    will actually be charged. A type with no ``repeat_cost_multiplier``
    collapses to the familiar flat ``build_cost(...) * count`` (every step
    prices identically)."""
    return sum(build_cost(building_type, buildings_balance, tier_idx,
                          repeat_count + i)
              for i in range(count))


def _display_name(b):
    """Custom name if the player set one, else the tier display name — the 10J
    upgrade-panel title (shows the rebirth ordinals a revive appends)."""
    np = b.get_component(Nameplate)
    if np is not None and np.custom_name:
        return np.custom_name
    return _tier_name(b)


def _random_names(buildings_balance):
    return buildings_balance["BuildingsGlobal"]["random_names"]


def _building_stats(b):
    """(label, value) rows for a building's current tier — the panel/preview
    stat block. Duck-typed so any future family is picked up."""
    rows = [("HP", b.max_hp())]
    if hasattr(b, "damage"):            # defence family
        rows.append(("Damage", b.damage()))
        # 10I: the Range row shows the EFFECTIVE (mountain-boosted) range,
        # duck-typed so pre-10I stubs without the method keep working.
        rows.append(("Range",
                     getattr(b, "effective_range_tiles", b.range_tiles)()))
        rows.append(("Atk speed", f"{b.attack_speed():.1f}s"))
        rows.append(("Upkeep", b.upkeep()))
        # 10D: a booster is lifting these — show the un-boosted base for contrast.
        for label, base in b.boosted_stats().items():
            rows.append((f"{label} base", base))
    if hasattr(b, "boost_value"):       # boost building (10D) — buffs neighbours
        rows.append((b._boost_label, f"{b.boost_value() * 100:.1f}%"))
        rows.append(("Upkeep", b.upkeep()))
    if hasattr(b, "wall_hp"):           # wall builder (10E) — raises edge walls
        rows.append(("Wall HP", b.wall_hp()))
        rows.append(("Upkeep", b.upkeep()))
    if hasattr(b, "payout_amount"):     # painter — risky economy (no yield)
        rows.append(("Progress", f"{b.progress}/{b.rounds_to_payout()}"))
        rows.append(("Payout", f"{b.payout_amount()}"))
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
                 view_w, view_h, count=1, tier_idx=0, repeat_count=0,
                 skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.building_type = building_type
        self.cost = cost          # per-building cost (this batch's FIRST tile)
        self.count = count        # 10J: batch size (shift multi-select)
        self._buildings_balance = buildings_balance
        self._tier_idx = tier_idx
        # feature-storm-acolyte-multi-build: the count of already-placed
        # `LIGHTNING_SOURCE_TAG`-tagged occupants at the moment this preview
        # opened — the escalation baseline `total_cost` sums from.
        self._repeat_count = repeat_count
        self.view_w = view_w
        self.view_h = view_h
        self._names = _random_names(buildings_balance)
        temp = create(building_type, 0, 0, buildings_balance, tier_idx)
        self.title = (_tier_name(temp) if count == 1
                      else f"{_tier_name(temp)}  × {count}")
        self.stats = _building_stats(temp)
        self.name = ""
        self.editing = False

        pw, ph = 340, 300
        x, y = view_w // 2 - pw // 2, view_h // 2 - ph // 2
        self.rect = (x, y, pw, ph)
        # 10J: the name row shrinks to make room for the dice reroll button
        # (prototype building_ui.py:136, 243-247).
        self.name_rect = (x + 16, y + 96, pw - 32 - 36, 30)
        self.dice_btn = Button((x + pw - 16 - 30, y + 96, 30, 30),
                               _DICE_GLYPH, "md")
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
        # 10L-B: geometry is fixed for this instance's whole lifetime (a
        # fresh ConstructPreview is built each time the modal opens), so
        # ids/apply run ONCE here rather than every layout() — there is no
        # per-frame layout() to hook.
        self._panel = SimpleNamespace(rect=self.rect, skin=None)
        self.ids = {"preview_panel": ("panel", self._panel),
                    "preview_close_btn": ("button", self.close_btn),
                    "preview_confirm_btn": ("button", self.confirm_btn),
                    "preview_dice_btn": ("button", self.dice_btn)}
        if self.cancel_btn is not None:
            self.ids["preview_cancel_btn"] = ("button", self.cancel_btn)
        self.skinning.apply(self.screen_id, self.ids)
        self.rect = self._panel.rect

    @property
    def total_cost(self):
        """Batch total. feature-storm-acolyte-multi-build: for a batch of a
        type carrying ``repeat_cost_multiplier``, this SUMS the escalating
        sequence (``n``, ``n+1``, ``n+2``, …) starting at ``_repeat_count``,
        not a flat ``cost * count`` — matching what ``place_building`` will
        actually charge tile by tile as ``_do_place`` walks the batch. A
        type with no multiplier collapses to the familiar flat total."""
        return _batch_cost(self.building_type, self._buildings_balance,
                           self._tier_idx, self._repeat_count, self.count)

    @property
    def chosen_name(self):
        return self.name.strip() or f"Unnamed {self.title}"

    def hover(self, mx, my, mouse_down=False):
        for btn in (self.confirm_btn, self.close_btn, self.dice_btn):
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
        if self.cancel_btn is not None:
            self.cancel_btn.hover(mx, my, mouse_down)
            self.cancel_btn.hovered = (self.cancel_btn.hovered
                                       and is_visible(self.cancel_btn))

    def confirm_hovered(self):
        return self.confirm_btn.hovered

    def update(self, dt):
        self.confirm_btn.update(dt)
        self.close_btn.update(dt)
        self.dice_btn.update(dt)
        if self.cancel_btn is not None:
            self.cancel_btn.update(dt)

    def handle_click(self, mx, my):
        """Return an action string (``confirm`` / ``cancel`` / ``close`` /
        ``name`` / None). The host treats the modal as consuming every click.
        An invisible button is never hit (10L-B)."""
        if is_visible(self.close_btn) and self.close_btn.hit(mx, my):
            return "close"
        if (self.cancel_btn is not None and is_visible(self.cancel_btn)
                and self.cancel_btn.hit(mx, my)):
            return "cancel"
        if is_visible(self.confirm_btn) and self.confirm_btn.hit(mx, my):
            return "confirm"
        if (is_visible(self.dice_btn) and self.dice_btn.hit(mx, my)
                and self._names):
            # 10J name dice: always REPLACES the current text (prototype
            # building_ui.py:243-247).
            self.name = random.choice(self._names)
            self.editing = True
            return "name"
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

    def submit(self, renderer, anim_ms=0):
        from engine.render import HudRect

        x, y, w, h = self.rect
        # Submission order (game/ui/CLAUDE.md "panel -> button -> text"):
        # ALL panel/background submissions first, THEN all buttons, THEN all
        # text — HUD draw order is submission order (engine/render/CLAUDE.md).
        if is_visible(self._panel):
            submit_panel(renderer, self.rect, fill=widgets.C_UI_PANEL,
                        border=widgets.C_UI_BORDER, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None),
                        anim_ms=anim_ms)
        nx, ny, nw, nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect, widgets.C_HIGHLIGHT if self.editing else widgets.C_UI_BORDER,
            width=1))
        if is_visible(self.dice_btn):
            self.dice_btn.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self.dice_btn))
        if is_visible(self.confirm_btn):
            self.confirm_btn.submit(renderer, anim_ms=anim_ms,
                                    **button_kwargs(self.confirm_btn))
        if self.cancel_btn is not None and is_visible(self.cancel_btn):
            self.cancel_btn.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(self.cancel_btn))
        if is_visible(self.close_btn):
            self.close_btn.submit(renderer, anim_ms=anim_ms,
                                  **button_kwargs(self.close_btn))
        cx = x + w // 2
        submit_text(renderer, self.title, (cx, y + 12), "lg", widgets.C_UI_TEXT,
                    align="center")
        submit_text(renderer, f"Cost  {self.total_cost}", (cx, y + 44),
                    "md", widgets.C_GOLD, align="center")
        submit_text(renderer, "Name:", (x + 16, y + 76), "sm", widgets.C_UI_TEXT_DIM)
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = widgets.C_UI_TEXT
        else:
            shown = "click to name"
            tcol = widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 8, ny + 7), "md", tcol)
        sy = y + 138
        for label, value in self.stats:
            submit_text(renderer, label, (x + 16, sy), "sm", widgets.C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (x + w - 16, sy), "sm", widgets.C_UI_TEXT,
                        align="right")
            sy += 20


class BuildingUI:
    def __init__(self, view_w, view_h, ui_balance, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
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
        # -- TU-6: transient "a placement just landed" signal — the host
        # reads it once right after a successful handle_click() and clears
        # it; NEVER reset in close() (open_for_tile()'s internal close() call
        # inside _do_place() would wipe it before the host gets to read it). --
        self.last_placed_type = None
        self._selected = None
        self._session = None
        self._upgrade_hint = None
        self._buildings_balance = None
        self._highlight_tiles = []
        self._hover_cost = None
        self._action_cost = 0
        self._clock = 0.0  # 10L-A: one anim clock per screen
        # -- 10J: shift multi-select batch (prototype game.py:189-191) --
        self.selected_tiles = []      # primary first; same category only
        # -- 10J: upgrade-panel rename row + dice; host callbacks --
        self._name_editing = False
        self._name_buf = ""
        self._name_box_rect = (self.panel_x + 14, 40, self.panel_w - 64, 22)
        self._dice_up = Button(
            (self.panel_x + 14 + self.panel_w - 64 + 6, 40, 24, 22),
            _DICE_GLYPH, "md")
        self.log = None               # GameLog, wired by the host
        self.on_build_vfx = None      # (col, row, kind) -> None, wired by host
        # -- /10J --
        self.close_btn = Button(
            (self.panel_x + self.panel_w - 28, 8, 20, 18), "X", "md")
        self.action_btn = Button(
            (self.panel_x + 12, 0, self.panel_w - 24, 36), "", "lg")
        self.cards = []
        # -- 10G boss: base_info "BOSS CHOICES" button + history popup --
        self.boss_btn = Button(
            (self.panel_x + 12, 420, self.panel_w - 24, 32),
            "BOSS CHOICES", "md")
        pw, ph = 340, 260
        self._boss_popup_rect = (view_w // 2 - pw // 2,
                                 view_h // 2 - ph // 2, pw, ph)
        px, py = self._boss_popup_rect[0], self._boss_popup_rect[1]
        self._boss_close_btn = Button(
            (px + pw // 2 - 60, py + ph - 44, 120, 32), "CLOSE", "md")
        self._boss_popup_open = False
        self._boss_hover_row = -1
        # -- /10G --
        # -- 10I: terrain badge hover/tooltip state --
        self._cond_badge_rect = None    # last-submitted badge rect (hit probe)
        self._cond_hover = False
        self._cond_tooltip = None       # (condition, color, rect, above)
        # -- /10I --
        # -- 10L-B: mode-independent ids (submit() has no separate layout()) --
        # ``rename_dice_btn``/``boss_close_btn`` close a Phase-3 id-coverage
        # gap: both are created once here with a fixed lifetime rect (the
        # dice/close pattern every other mode-independent id already uses),
        # so they join the same one-time ids dict.
        self._panel = SimpleNamespace(rect=self.panel_rect, skin=None)
        self.ids = {
            "panel": ("panel", self._panel),
            "close_btn": ("button", self.close_btn),
            "action_btn": ("button", self.action_btn),
            "boss_btn": ("button", self.boss_btn),
            "rename_dice_btn": ("button", self._dice_up),
            "boss_close_btn": ("button", self._boss_close_btn),
        }
        # -- /10L-B --

    # -- open / close -----------------------------------------------------

    @property
    def visible(self):
        return self.mode is not None

    @property
    def hover_cost(self):
        return self._hover_cost

    @property
    def name_editing(self):
        """True while the upgrade panel's rename row is capturing keys (10J) —
        the host routes keyboard input here instead of the shortcut keys."""
        return self._name_editing

    def close(self):
        self.mode = None
        self.tile = None
        self.preview = None
        self._selected = None
        self._upgrade_hint = None
        self._highlight_tiles = []
        self._hover_cost = None
        self.cards = []
        # -- 10J --
        self.selected_tiles = []
        self._name_editing = False
        self._name_buf = ""
        # -- /10J --
        self._boss_popup_open = False  # -- 10G boss --
        # -- 10I: terrain badge state resets with the panel --
        self._cond_badge_rect = None
        self._cond_hover = False
        self._cond_tooltip = None
        # -- /10I --

    def dismiss(self):
        """One stage of the Esc / right-click dismiss ladder; True if consumed.

        Sub-overlays peel off first (preview -> construct list, boss popup ->
        base_info); only a bare panel closes outright.
        """
        if self.preview is not None:
            self.preview = None
            return True
        if self._boss_popup_open:
            self._boss_popup_open = False
            self._boss_hover_row = -1
            return True
        if self.visible:
            self.close()
            return True
        return False

    # -- TU-6: tutorial highlight rect queries (read-only, additive) --------

    def card_rect(self, building_type):
        """Screen rect of the construct-mode card for ``building_type``, or
        None if not currently shown. Read-only — never mutates panel state."""
        if self.mode != "construct":
            return None
        for btype, btn in self.cards:
            if btype == building_type:
                return btn.rect
        return None

    def confirm_rect(self):
        """Screen rect of the open ``ConstructPreview``'s CONFIRM button, or
        None when no preview is open."""
        return self.preview.confirm_btn.rect if self.preview is not None else None

    def close_rect(self):
        """Screen rect of the panel's own CLOSE (X) button, or None when the
        panel isn't open (TU-8, Fix 2's close-panel-hint step). Read-only —
        never mutates panel state."""
        return self.close_btn.rect if self.visible else None

    # -- /TU-6 ---------------------------------------------------------------

    def open_for_tile(self, tile, session, buildings_balance,
                      selected_tiles=None):
        """Open for the PRIMARY tile; ``selected_tiles`` (10J shift
        multi-select, primary first, same category) batches the unlock /
        construct / in-tier-upgrade actions. The base never batches."""
        self.close()
        if tile is None:
            return
        self._buildings_balance = buildings_balance
        self._session = session
        self.selected_tiles = (list(selected_tiles) if selected_tiles
                               else [tile])
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
                self.selected_tiles = [tile]  # base never batches
            elif occ is not None:
                self.mode, self.tile, self._selected = "upgrade", tile, occ
                self._build_upgrade()
                if len(self.selected_tiles) == 1:
                    self._set_range_highlight(occ, session.tilemap)
                else:
                    # range diamond only on a single selection (prototype
                    # game.py:552-556); a batch highlights its tiles.
                    self._highlight_tiles = [
                        (t.col, t.row, widgets.C_HIGHLIGHT)
                        for t in self.selected_tiles]
        # SPAWNING / BACKGROUND / empty BUILT -> stays closed

    # -- per-mode builders ------------------------------------------------

    def _unlock_chunks(self, session):
        """The DISTINCT 2×2 chunks the selection covers, as ``(rep_tile,
        cost)`` — two selected tiles in the same chunk unlock (and cost) once
        (prototype ``_unlock_cost`` frozenset dedup, building_ui.py:1277-97)."""
        tm = session.tilemap
        chunks = {}
        for t in self.selected_tiles:
            key = frozenset((c.col, c.row) for c in tm.get_chunk_for_tile(t))
            if key not in chunks:
                chunks[key] = (t, tm.unlock_cost(t))
        return list(chunks.values())

    def _build_unlock(self, session):
        tm = session.tilemap
        chunks = self._unlock_chunks(session)
        cost = sum(c for _, c in chunks)
        adjacent = all(tm.can_unlock(t) for t, _ in chunks)
        self._action_cost = cost
        self.action_btn.rect = (self.panel_x + 12, 150, self.panel_w - 24, 36)
        self.action_btn.enabled = adjacent
        n = len(chunks)
        if not adjacent:
            self.action_btn.label = "NOT ADJACENT"
        elif n > 1:
            self.action_btn.label = f"UNLOCK {n} AREAS  {cost}"
        else:
            self.action_btn.label = f"UNLOCK  {cost}"
        hl = []
        for sel in self.selected_tiles:
            hl.append((sel.col, sel.row, widgets.C_HIGHLIGHT))
            for t in tm.get_chunk_for_tile(sel):
                if t is not sel:
                    hl.append((t.col, t.row, widgets.C_HIGHLIGHT2))
        self._highlight_tiles = hl

    def _build_construct(self):
        self.cards = []
        y = 64
        state = self._session.state
        # B3: construct cards are dynamic-count (never id'd) and inherit the
        # screen's defaults.button_skin instead — {} (no override) means None,
        # the unskinned flat-rect card the golden parity pin already covers.
        skin = self.skinning.defaults(self.screen_id).get("button_skin")
        # feature-storm-acolyte-multi-build: the Storm Priest run-singleton
        # ban is LIFTED — several may be placed, each priced steeper than the
        # last via the group's `repeat_cost_multiplier`. This is the SAME
        # already-placed count `build_cost`/`place_building` use, computed
        # once for every card (a no-op price-wise for every type without the
        # multiplier key).
        repeat_count = count_tag(self._session.tilemap, LIGHTNING_SOURCE_TAG)
        for btype in BUILDING_CLASSES:
            if not buildable(state, btype):
                continue  # type not unlocked / tier 1 not researched (10A)
            tier_idx = tiers_unlocked_for(state, btype) - 1
            cost = build_cost(btype, self._buildings_balance, tier_idx,
                              repeat_count)
            name = BUILDING_CLASSES[btype]._resolve_tiers(
                self._buildings_balance)[tier_idx]["name"]
            label = f"{name}  {cost}"
            btn = Button((self.panel_x + 12, y, self.panel_w - 24, 42),
                         label, "md", skin=skin)
            self.cards.append((btype, btn))
            y += 50
        self._highlight_tiles = [(t.col, t.row, widgets.C_HIGHLIGHT)
                                 for t in self.selected_tiles]

    def _batch_upgrade_targets(self):
        """``[(building, cost)]`` across the selection whose upgrade state is
        ``in_tier`` (prototype building_ui.py:767-791). A single selection is
        a 1-batch; tier ADVANCE never batches (primary only)."""
        out = []
        for t in self.selected_tiles:
            b = t.occupant
            if b is None or getattr(b, "building_type", None) == "base":
                continue
            mode, cost, _, _ = self._upgrade_state(b)
            if mode == "in_tier" and cost > 0:
                out.append((b, cost))
        return out

    def _build_upgrade(self):
        mode, cost, label, hint = self._upgrade_state(self._selected)
        if mode == "in_tier" and len(self.selected_tiles) > 1:
            targets = self._batch_upgrade_targets()
            cost = sum(c for _, c in targets)
            label = f"UPGRADE ×{len(targets)}  {cost}"
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
            return mode, cost, f"UPGRADE  {cost}", None
        if mode == "tier_upgrade":
            return mode, cost, f"ADVANCE: {next_name.upper()}  {cost}", None
        if mode == "tier_locked":
            return mode, cost, "RESEARCH REQUIRED", "Research it on levelup"
        if mode == "tier_hidden":
            return mode, cost, "NEXT TIER LOCKED", f"Unlocks at round {cost}"
        return mode, 0, "MAX TIER", None

    def _base_info_click(self, mx, my, session):
        """Click handling for base_info mode — 10G boss-history popup consumes
        clicks inside itself and closes on its button; the BOSS CHOICES
        button opens it. Everything else inside the panel is consumed."""
        # -- 10G boss popup (checked first; prototype-faithful fall-through:
        # only the close button and clicks inside the popup rect consume) --
        if self._boss_popup_open:
            if (is_visible(self._boss_close_btn)
                    and self._boss_close_btn.hit(mx, my)):
                self._boss_popup_open = False
                return True
            if contains(self._boss_popup_rect, mx, my):
                return True
        # -- 10G BOSS CHOICES button --
        if is_visible(self.boss_btn) and self.boss_btn.hit(mx, my):
            self._boss_popup_open = True
            return True
        return contains(self.panel_rect, mx, my)

    def _set_range_highlight(self, b, tilemap):
        hl = [(b.col, b.row, widgets.C_HIGHLIGHT)]
        # 10I: the selection highlight shows the EFFECTIVE (mountain-boosted)
        # range — a consumption site of the effective value (prototype
        # game.py:578-581); pathfinding coverage stays on the raw range.
        rfn = getattr(b, "effective_range_tiles",
                      getattr(b, "range_tiles", None))
        if rfn is not None:
            r = int(rfn())
            for dc in range(-r, r + 1):
                for dr in range(-r, r + 1):
                    if dc == 0 and dr == 0:
                        continue
                    if tilemap.get(b.col + dc, b.row + dr) is not None:
                        hl.append((b.col + dc, b.row + dr, widgets.C_RANGE_HIGHLIGHT))
        self._highlight_tiles = hl

    # -- input ------------------------------------------------------------

    def hover(self, mx, my, mouse_down=False):
        self._hover_cost = None
        # -- 10I: terrain badge hover (rect inflated 4px, prototype
        # building_ui.py:1121-1130); off while the modal preview is open --
        r = self._cond_badge_rect
        self._cond_hover = (
            self.preview is None and r is not None
            and contains((r[0] - 4, r[1] - 4, r[2] + 8, r[3] + 8), mx, my))
        # -- /10I --
        if self.preview is not None:
            self.preview.hover(mx, my, mouse_down)
            if self.preview.confirm_hovered():
                # The BATCH total, not the first tile's unit price — matches
                # what CONFIRM will actually charge (feature-storm-acolyte-
                # multi-build's escalating sequence, or the familiar flat
                # total for every other type).
                self._hover_cost = self.preview.total_cost
            return
        if not self.visible:
            return
        self.close_btn.hover(mx, my, mouse_down)
        self.close_btn.hovered = self.close_btn.hovered and is_visible(self.close_btn)
        if self.mode == "construct":
            count = max(1, len(self.selected_tiles))  # 10J batch
            state = self._session.state
            # feature-storm-acolyte-multi-build: the SAME already-placed
            # count every card's price/label uses (`_build_construct`),
            # computed once per hover pass.
            repeat_count = count_tag(self._session.tilemap, LIGHTNING_SOURCE_TAG)
            for btype, btn in self.cards:
                btn.hover(mx, my, mouse_down)
                if btn.hovered:
                    tier_idx = tiers_unlocked_for(state, btype) - 1
                    self._hover_cost = _batch_cost(
                        btype, self._buildings_balance, tier_idx,
                        repeat_count, count)
        elif self.mode in ("unlock", "upgrade"):
            self.action_btn.hover(mx, my, mouse_down)
            self.action_btn.hovered = (self.action_btn.hovered
                                       and is_visible(self.action_btn))
            if self.action_btn.hovered:
                self._hover_cost = self._action_cost
            if self.mode == "upgrade":
                self._dice_up.hover(mx, my, mouse_down)  # 10J rename dice
                self._dice_up.hovered = (self._dice_up.hovered
                                         and is_visible(self._dice_up))
        elif self.mode == "base_info":
            # -- 10G boss: base_info button + popup row hover (desc tooltip) --
            self.boss_btn.hover(mx, my, mouse_down)
            self.boss_btn.hovered = self.boss_btn.hovered and is_visible(self.boss_btn)
            self._boss_hover_row = -1
            if self._boss_popup_open:
                self._boss_close_btn.hover(mx, my, mouse_down)
                self._boss_close_btn.hovered = (
                    self._boss_close_btn.hovered
                    and is_visible(self._boss_close_btn))
                px, py, pw, _ph = self._boss_popup_rect
                if px + 14 <= mx < px + pw - 14 and my >= py + 48:
                    self._boss_hover_row = (my - (py + 48)) // 20
            # -- /10G --

    def handle_key(self, char, key):
        if self.preview is not None:
            self.preview.handle_key(char, key)
            return
        # -- 10J: upgrade-panel rename row (the ConstructPreview key model) --
        if self._name_editing:
            if key == "return":
                self._commit_rename()
            elif key == "escape":
                self._name_editing = False
                self._name_buf = ""
            elif key == "backspace":
                self._name_buf = self._name_buf[:-1]
            elif char and char.isprintable() and len(self._name_buf) < 20:
                self._name_buf += char

    def handle_click(self, mx, my, session, buildings_balance, scene, occupancy):
        """Return True if the click was consumed by the UI (host must then NOT
        pick a tile). The preview modal consumes everything; an open panel
        consumes any click inside its rect."""
        if self.preview is not None:
            return self._preview_click(mx, my, session, buildings_balance,
                                       scene, occupancy)
        if not self.visible:
            return False
        if is_visible(self.close_btn) and self.close_btn.hit(mx, my):
            self.close()
            return True
        if self.mode == "unlock":
            return self._unlock_click(mx, my, session)
        if self.mode == "construct":
            return self._construct_click(mx, my, session, buildings_balance)
        if self.mode == "upgrade":
            return self._upgrade_click(mx, my, session)
        if self.mode == "base_info":
            return self._base_info_click(mx, my, session)
        return contains(self.panel_rect, mx, my)  # consume inside the panel

    def _unlock_click(self, mx, my, session):
        if is_visible(self.action_btn) and self.action_btn.hit(mx, my):
            tm, st = session.tilemap, session.state
            chunks = self._unlock_chunks(session)  # re-check live (10J batch)
            cost = sum(c for _, c in chunks)
            if not all(tm.can_unlock(t) for t, _ in chunks):
                self.action_btn.start_flash(self._flash_dur, "NOT ADJACENT")
                if self.log is not None:
                    self.log.post(
                        "Can only unlock tiles touching your territory")
            elif st.love < cost:
                self.action_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
            else:
                for tile, chunk_cost in chunks:
                    if tm.do_unlock(tile):
                        st.spend_love(chunk_cost)
                self.close()
            return True
        return contains(self.panel_rect, mx, my)

    def _construct_click(self, mx, my, session, buildings_balance):
        for btype, btn in self.cards:
            if btn.hit(mx, my):
                tier_idx = tiers_unlocked_for(session.state, btype) - 1
                # feature-storm-acolyte-multi-build: the same already-placed
                # count `_build_construct` priced the card off.
                repeat_count = count_tag(session.tilemap, LIGHTNING_SOURCE_TAG)
                cost = build_cost(btype, buildings_balance, tier_idx,
                                  repeat_count)
                count = max(1, len(self.selected_tiles))
                # 10J batch: the whole batch must be affordable up front
                # (prototype building_ui.py:704-708) — the ESCALATING total,
                # not a flat cost x count, so this gate agrees with what
                # ConstructPreview.total_cost/_do_place will actually charge.
                total = _batch_cost(btype, buildings_balance, tier_idx,
                                    repeat_count, count)
                if session.state.love < total:
                    btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
                else:
                    self.preview = ConstructPreview(
                        btype, cost, buildings_balance, self._ui_balance,
                        self.view_w, self.view_h, count=count, tier_idx=tier_idx,
                        repeat_count=repeat_count, skinning=self.skinning)
                return True
        return contains(self.panel_rect, mx, my)

    def _commit_rename(self):
        """Apply the rename buffer to the primary building. A no-op rename is
        deliberately skipped so it can't reset the rebirth chain (prototype
        ``_commit_upgrade_name``, building_ui.py:1264-75)."""
        self._name_editing = False
        name, self._name_buf = self._name_buf.strip(), ""
        b = self._selected
        if b is None or not name:
            return
        np = b.get_component(Nameplate)
        if np is not None and name == np.custom_name:
            return
        b.set_name(name)

    def _upgrade_click(self, mx, my, session):
        b, st = self._selected, session.state
        # -- 10J: rename row — dice fills the buffer, the box click-to-clears,
        # a click anywhere else while editing commits (defocus) --
        if is_visible(self._dice_up) and self._dice_up.hit(mx, my):
            names = _random_names(self._buildings_balance)
            if names:
                self._name_buf = random.choice(names)
                self._name_editing = True
            return True
        if contains(self._name_box_rect, mx, my):
            if not self._name_editing:
                self._name_editing = True
                self._name_buf = ""
            return True
        if self._name_editing:
            self._commit_rename()
        # -- /10J --
        if is_visible(self.action_btn) and self.action_btn.hit(mx, my):
            mode, cost, _, _ = self._upgrade_state(b)
            if mode not in ("in_tier", "tier_upgrade"):
                return True  # max / not researched / round-gated: inert
            if mode == "tier_upgrade":
                # Tier research advances ONE building only (prototype
                # building_ui.py:757-766) — never the batch.
                if st.love < cost:
                    self.action_btn.start_flash(self._flash_dur,
                                                "NOT ENOUGH LOVE")
                    return True
                st.spend_love(cost)
                b.advance_tier()
                lightning.sync_level_from_tier(st, b)  # Storm Priest wiring
                if session.debug is not None:
                    session.debug.note_love_spent(cost, dbg.SPEND_RESEARCH)
                    session.debug.emit(
                        dbg.RESEARCH, building_type=b.building_type,
                        tier=b.get_component(TierState).current_tier,
                        cost=cost)
                if self.on_build_vfx is not None:
                    self.on_build_vfx(b.col, b.row, "tier")
            else:
                targets = self._batch_upgrade_targets()
                total = sum(c for _, c in targets)
                if st.love < total:
                    self.action_btn.start_flash(self._flash_dur,
                                                "NOT ENOUGH LOVE")
                    return True
                st.spend_love(total)
                for tb, _c in targets:
                    tb.upgrade()
                    if self.on_build_vfx is not None:
                        lvl = tb.get_component(TierState).current_level_in_tier
                        self.on_build_vfx(tb.col, tb.row,
                                          "level1" if lvl == 2 else "level2")
            self._build_upgrade()
            if len(self.selected_tiles) == 1:
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
        """Place on every selected tile (10J batch; single tile = a 1-batch).
        The chosen name applies to the FIRST tile only (prototype
        building_ui.py:591-619); a tile that fails placement is skipped."""
        p, st = self.preview, session.state
        if st.love < p.total_cost:
            p.confirm_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
            return
        placed_any = False
        for i, tile in enumerate(self.selected_tiles or [self.tile]):
            try:
                building, cost = place_building(
                    session.tilemap, tile, p.building_type, st.love,
                    buildings_balance, scene, occupancy, state=st)
            except PlacementError:
                continue
            st.spend_love(cost)
            st.buildings_placed += 1
            placed_any = True
            lightning.unlock_from_placement(st, building)  # Storm Priest wiring
            if session.debug is not None:
                session.debug.note_love_spent(cost, dbg.SPEND_PLACE)
                session.debug.emit(
                    dbg.PLACE, building_type=p.building_type, col=tile.col,
                    row=tile.row, cost=cost, tier=p._tier_idx)
            if i == 0:
                building.set_name(p.chosen_name)
            if self.on_build_vfx is not None:  # 10J: sparks + gold highlight
                self.on_build_vfx(tile.col, tile.row, "place")
        if not placed_any:
            p.confirm_btn.start_flash(self._flash_dur, "NOT ENOUGH LOVE")
            return
        self.last_placed_type = p.building_type  # TU-6: signal a real placement
        self.preview = None
        selection = list(self.selected_tiles)  # keep the batch selected
        self.open_for_tile(self.tile, session, buildings_balance,
                           selected_tiles=selection)  # -> upgrade

    # -- per-frame --------------------------------------------------------

    def update(self, dt):
        self._clock += dt
        self.action_btn.update(dt)
        self.close_btn.update(dt)
        self._dice_up.update(dt)  # 10J rename dice
        self.boss_btn.update(dt)          # -- 10G boss --
        self._boss_close_btn.update(dt)   # -- 10G boss --
        for _, btn in self.cards:
            btn.update(dt)
        if self.preview is not None:
            self.preview.update(dt)

    def submit(self, renderer, session):
        t = anim_ms(self._clock)
        for col, row, color in self._highlight_tiles:
            submit_tile_diamond(renderer, col, row, color)
        if not self.visible:
            return
        # -- 10I: badge rect/tooltip refresh each frame (base_info shows no
        # badge, so a mode without a badge must clear last frame's rect) --
        self._cond_badge_rect = None
        self._cond_tooltip = None
        # -- /10I --
        # -- 10L-B: no separate layout() step, so apply() runs here (once per
        # visible frame, before the panel/buttons it may reposition/reskin) --
        self._panel.rect = self.panel_rect
        self.skinning.apply(self.screen_id, self.ids)
        self.panel_rect = self._panel.rect
        self.skinning.submit_background(renderer, self.screen_id,
                                        self.view_w, self.view_h)
        if is_visible(self._panel):
            submit_panel(renderer, self.panel_rect, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None), anim_ms=t)
        if is_visible(self.close_btn):
            self.close_btn.submit(renderer, anim_ms=t, **button_kwargs(self.close_btn))
        if self.mode == "unlock":
            self._submit_unlock(renderer, session, t)
        elif self.mode == "construct":
            self._submit_construct(renderer, t)
        elif self.mode == "upgrade":
            self._submit_upgrade(renderer, t)
        elif self.mode == "base_info":
            self._submit_base_info(renderer, session, t)
        # -- 10I: the hovered terrain tooltip draws LAST, on top of the panel
        # (prototype building_ui.py:1121-1130) --
        if self._cond_hover and self._cond_tooltip is not None:
            self._submit_cond_tooltip(renderer, *self._cond_tooltip)
        # -- /10I --
        if self.preview is not None:
            self.preview.submit(renderer, anim_ms=t)

    def _submit_unlock(self, renderer, session, anim_ms=0):
        x = self.panel_x + 14
        submit_text(renderer, "UNLOCK TILE", (x, 16), "lg", widgets.C_UI_TEXT)
        submit_text(renderer, "Unlocks a 2x2 area", (x, 70), "sm",
                    widgets.C_UI_TEXT_DIM)
        if not session.tilemap.can_unlock(self.tile):
            submit_text(renderer, "Must touch your territory", (x, 196), "sm",
                        widgets.C_UI_TEXT_DIM)
        if is_visible(self.action_btn):
            self.action_btn.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(self.action_btn))
        # -- 10I: tile terrain footer badge (tooltip above) --
        self._submit_cond_badge(renderer, self.tile.condition,
                                self.view_h - 40, above=True)
        # -- /10I --

    def _submit_construct(self, renderer, anim_ms=0):
        submit_text(renderer, "BUILD", (self.panel_x + 14, 16), "lg", widgets.C_UI_TEXT)
        for _, btn in self.cards:
            btn.submit(renderer, anim_ms=anim_ms)
        # -- 10I: tile terrain footer badge (tooltip above) --
        self._submit_cond_badge(renderer, self.tile.condition,
                                self.view_h - 40, above=True)
        # -- /10I --

    def _next_level_rows(self, b):
        """``_building_stats`` at the NEXT in-tier level, computed on a
        throwaway clone that copies the tier cursor + boost/condition/streak
        context (the prototype's ``b.stats_preview()``, hover-gated green
        values). None at the tier max."""
        temp = create(b.building_type, b.col, b.row, self._buildings_balance)
        ts = b.get_component(TierState)
        tts = temp.get_component(TierState)
        tts.current_tier = ts.current_tier
        tts.current_level_in_tier = ts.current_level_in_tier
        temp._tile_condition = getattr(b, "_tile_condition", None)
        temp._condition_mods = getattr(b, "_condition_mods", {})
        rcv = b.get_component(BoostReceiver)
        trcv = temp.get_component(BoostReceiver)
        if rcv is not None and trcv is not None:
            trcv.damage_pct = rcv.damage_pct
            trcv.speed_pct = rcv.speed_pct
            trcv.hp_pct = rcv.hp_pct
            trcv.explosion_debuffs = list(rcv.explosion_debuffs)
        ye = b.get_component(YieldEconomy)
        tye = temp.get_component(YieldEconomy)
        if ye is not None and tye is not None:
            tye.streak = ye.streak
        if not temp.upgrade():
            return None
        return _building_stats(temp)

    def _next_tier_card(self, b):
        """``(slot_key, "Next: <name>", first-3 stat rows)`` for tier+1 level 1
        (prototype ``_draw_next_tier_preview``), or None at the last tier."""
        if not b.has_next_tier():
            return None
        temp = create(b.building_type, b.col, b.row, self._buildings_balance)
        tts = temp.get_component(TierState)
        tts.current_tier = b.get_component(TierState).current_tier + 1
        tts.current_level_in_tier = 1
        temp.apply_tier_stats()
        return temp.slot_key(), f"Next: {_tier_name(temp)}", \
            _building_stats(temp)[:3]

    def _submit_upgrade(self, renderer, anim_ms=0):
        from engine.render import HudRect, HudSprite

        x, b = self.panel_x + 14, self._selected
        up_mode, _, _, _ = self._upgrade_state(b)
        # 10J: the title is the DISPLAY name — custom names + rebirth ordinals
        # finally show; the tier name moves to the Level row.
        submit_text(renderer, _display_name(b), (x, 10), "lg", widgets.C_UI_TEXT)
        # -- 10J rename row: input box + dice --
        nx, ny, nw, nh = self._name_box_rect
        renderer.submit_hud(HudRect(self._name_box_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self._name_box_rect,
            widgets.C_HIGHLIGHT if self._name_editing else widgets.C_UI_BORDER, width=1))
        if self._name_buf or self._name_editing:
            shown, tcol = self._name_buf + "_", widgets.C_UI_TEXT
        else:
            shown, tcol = "click here to change name", widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 6, ny + 4), "sm", tcol)
        if is_visible(self._dice_up):
            self._dice_up.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self._dice_up))
        # -- /10J --
        submit_text(renderer, f"{_tier_name(b)} — Level {b.level}", (x, 68),
                    "md", widgets.C_UI_TEXT_DIM)
        # -- 10I: terrain badge (ALWAYS shown incl. Grass), reading the
        # building's placement snapshot; tooltip below the badge --
        self._submit_cond_badge(
            renderer,
            getattr(b, "_tile_condition", None) or TileCondition.GRASS,
            90, above=False)
        # -- /10I --
        # 10J: hovering an enabled in-tier UPGRADE button previews the next
        # level's stats in green (prototype building_ui.py:1021, 1057-58).
        preview = None
        if up_mode == "in_tier" and self.action_btn.hovered:
            preview = dict(self._next_level_rows(b) or ())
        y = 116
        for label, value in _building_stats(b):
            submit_text(renderer, label, (x, y), "md", widgets.C_UI_TEXT_DIM)
            pv = preview.get(label) if preview else None
            if pv is not None and pv != value:
                submit_text(renderer, str(pv), (self._right, y), "md",
                            widgets.C_GREEN_STAT, align="right")
            else:
                submit_text(renderer, str(value), (self._right, y), "md",
                            widgets.C_UI_TEXT, align="right")
            y += 24
        rs = b.get_component(RoundStats)
        if rs is not None:
            y += 10
            submit_text(renderer, "Damage dealt", (x, y), "sm", widgets.C_UI_TEXT_DIM)
            submit_text(renderer, str(rs.dmg_dealt_last_round), (self._right, y),
                        "sm", widgets.C_UI_TEXT, align="right")
            y += 18
            submit_text(renderer, "Damage taken", (x, y), "sm", widgets.C_UI_TEXT_DIM)
            submit_text(renderer, str(rs.dmg_taken_last_round), (self._right, y),
                        "sm", widgets.C_UI_TEXT, align="right")
            y += 18
            # -- 10J: a building whose last-round damage covered its full HP
            # died last round (prototype building_ui.py:1083-86) --
            if rs.dmg_taken_last_round >= b.max_hp():
                submit_text(renderer, "DIED LAST ROUND",
                            (self.panel_x + self.panel_w // 2, y), "sm",
                            widgets.C_RED, align="center")
                y += 18
        # -- 10J: next-tier card when a tier advance is on the table
        # (prototype ``_draw_next_tier_preview``; hidden while round-gated) --
        if up_mode in ("tier_upgrade", "tier_locked"):
            card = self._next_tier_card(b)
            if card is not None:
                slot, header, rows = card
                y += 8
                renderer.submit_hud(HudRect(
                    (x, y, self.panel_w - 28, 1), widgets.C_UI_BORDER))
                y += 8
                submit_text(renderer, header, (x, y), "md", widgets.C_GREEN_STAT)
                y += 22
                if slot:
                    renderer.submit_hud(HudSprite(slot, (x, y), (38, 38)))
                ry = y
                for label, value in rows:
                    submit_text(renderer, f"{label}  {value}", (x + 46, ry),
                                "sm", widgets.C_UI_TEXT_DIM)
                    ry += 16
        if is_visible(self.action_btn):
            self.action_btn.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(self.action_btn))
        if self._upgrade_hint:
            bx, by, bw, bh = self.action_btn.rect
            submit_text(renderer, self._upgrade_hint, (bx + bw // 2, by + bh + 6),
                        "sm", widgets.C_UI_TEXT_DIM, align="center")

    # -- 10I: terrain badge + effect tooltip (prototype building_ui.py
    # :998-1014 badge, :1418-1438 effect lines, :1440-1477 chrome/footer) ----

    def _tile_cond_effect_lines(self, condition):
        """Human copy for a condition's effects, values read LIVE from the map
        balancing. Prototype-exact: the enemy dmg/speed effects are
        deliberately NOT listed."""
        if condition == TileCondition.GRASS:
            return ["No terrain effect"]
        mods = self._session.tilemap.balance["TileConditions"]["modifiers"]
        m = mods.get(CONDITION_MODIFIER_KEY.get(condition), {})
        lines = []
        if m.get("def_range_bonus"):
            lines.append(f'+{m["def_range_bonus"]} range for defenders')
        if m.get("def_attack_speed_penalty"):
            lines.append(
                f'-{m["def_attack_speed_penalty"] * 100:.0f}% atk speed'
                ' for defenders')
        if m.get("def_dmg_penalty"):
            lines.append(
                f'-{m["def_dmg_penalty"] * 100:.0f}% damage for defenders')
        if m.get("eco_yield_penalty"):
            lines.append(
                f'-{m["eco_yield_penalty"] * 100:.0f}%/round'
                ' for economy')
        if m.get("eco_yield_bonus"):
            lines.append(
                f'+{m["eco_yield_bonus"] * 100:.0f}%/round'
                ' for economy')
        return lines or ["No terrain effect"]

    def _submit_cond_badge(self, renderer, condition, y, above):
        """The ``Terrain: <Label>`` pill, centred in the panel, in the
        condition colour. Records its rect (the hover probe) and the pending
        tooltip — drawn last by ``submit`` so it sits on top."""
        from engine.render import HudRect  # local: keep module imports lean

        label, color = widgets.cond_label(condition.name)
        text = f"Terrain: {label}"
        w = text_size(text, "sm")[0] + 16
        h = text_h("sm") + 8
        x = self.panel_x + (self.panel_w - w) // 2
        rect = (x, y, w, h)
        self._cond_badge_rect = rect
        renderer.submit_hud(HudRect(rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(rect, color, width=1))
        submit_text(renderer, text, (x + 8, y + 4), "sm", color)
        self._cond_tooltip = (condition, color, rect, above)

    def _submit_cond_tooltip(self, renderer, condition, color, badge_rect,
                             above):
        """The effect tooltip: dark panel, 1px border in the condition colour,
        centred horizontally on the panel, above or below the badge."""
        from engine.render import HudRect

        lines = self._tile_cond_effect_lines(condition)
        lh = text_h("sm") + 4
        w = max(text_size(t, "sm")[0] for t in lines) + 16
        h = lh * len(lines) + 10
        bx, by, bw, bh = badge_rect
        x = self.panel_x + (self.panel_w - w) // 2
        y = by - h - 6 if above else by + bh + 6
        renderer.submit_hud(HudRect((x, y, w, h), _COND_TOOLTIP_BG))
        renderer.submit_hud(HudRect((x, y, w, h), color, width=1))
        ty = y + 5
        for t in lines:
            submit_text(renderer, t, (x + 8, ty), "sm", widgets.C_UI_TEXT)
            ty += lh

    # -- /10I ---------------------------------------------------------------

    def _submit_base_info(self, renderer, session, anim_ms=0):
        x, st = self.panel_x + 14, session.state
        income = scaled_base_income(st, session.core_balance)
        submit_text(renderer, "THE HOLE", (x, 16), "lg", widgets.C_UI_TEXT)
        rows = [
            ("Lives", st.base_lives),
            ("Wave", st.round_num),
            ("Enemies killed", st.enemies_killed),
            ("Buildings", st.buildings_placed),
            ("Base income", f"{income}/round"),
        ]
        y = 72
        for label, value in rows:
            submit_text(renderer, label, (x, y), "md", widgets.C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (self._right, y), "md", widgets.C_UI_TEXT,
                        align="right")
            y += 30
        # -- 10G boss: BOSS CHOICES button + history popup --
        if is_visible(self.boss_btn):
            self.boss_btn.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self.boss_btn))
        if self._boss_popup_open:
            self._submit_boss_popup(renderer, session, anim_ms)
        # -- /10G --

    def _submit_boss_popup(self, renderer, session, anim_ms=0):
        """The small boss-history popup (prototype ``_BossHistoryPanel``): one
        row per ``(boss_num, option, outcome)``, the hovered row's bonus desc
        as a tooltip line, "None yet" when empty, a Close button (10G)."""
        from game.core.boss_bonuses import choice_desc

        px, py, pw, ph = self._boss_popup_rect
        # B3: the popup body is dynamic-count content (choice history rows) —
        # not id'd, styled from the screen's defaults.panel_skin instead.
        panel_skin = self.skinning.defaults(self.screen_id).get("panel_skin")
        submit_panel(renderer, self._boss_popup_rect, skin=panel_skin,
                    anim_ms=anim_ms)
        submit_text(renderer, "Boss Choices", (px + pw // 2, py + 14), "lg",
                    widgets.C_UI_TEXT, align="center")
        choices = session.state.boss_choices
        y = py + 48
        if not choices:
            submit_text(renderer, "None yet", (px + 14, y), "md",
                        widgets.C_UI_TEXT_DIM)
        hover_desc = None
        for i, (boss_num, option, outcome) in enumerate(choices):
            hovered = i == self._boss_hover_row
            submit_text(
                renderer,
                f"Boss {boss_num}: {outcome.capitalize()} {option}",
                (px + 14, y), "md", widgets.C_GOLD if hovered else widgets.C_UI_TEXT)
            if hovered:
                hover_desc = choice_desc((boss_num - 1) % 3, option)
            y += 20
        if hover_desc is not None:
            ty = py + ph - 80
            for line in hover_desc.split("\n"):
                submit_text(renderer, line, (px + 14, ty), "sm", widgets.C_UI_TEXT_DIM)
                ty += 16
        if is_visible(self._boss_close_btn):
            self._boss_close_btn.submit(renderer, anim_ms=anim_ms,
                                        **button_kwargs(self._boss_close_btn))
