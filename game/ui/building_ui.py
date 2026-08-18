"""Building interaction panel (Phase 9G): the right-side selection panel with
four modes (unlock / construct / upgrade / base_info) + the ConstructPreview
modal.

Pure logic. Ports the prototype's ``src/ui/building_ui.py``: panel modes +
terrain badges (10I), the boss-history section (10G), and the 10J
depth — shift multi-select batches (unlock chunk-dedup / construct ×count /
in-tier upgrade sums), the name dice, the upgrade-panel rename row (custom
names + rebirth ordinals finally render), the hover-gated green in-tier stat
preview + next-tier card, and the DIED LAST ROUND tag. Costs are gated
against ``session.state.love`` here and spent by this module (the 9D/9F
split: ``place_building`` / ``upgrade`` never touch RunState).

**fix/batch-tier-advance (reworked into a two-stage catch-up-then-advance
flow)**: a multi-selection's UPGRADE/ADVANCE button is ONE unified flow now,
replacing the old "plain in-tier batch" and "advance batch" paths. Stage A
(``_batch_upgrade_targets``) always wins while ANY selected building hasn't
reached level 3 of its current tier yet — swept across the WHOLE selection,
not gated on the primary tile's own mode (the old gate on the primary is
what used to grey the button out entirely whenever the primary itself
couldn't upgrade/advance, even though other selected buildings still
could). Only once nothing needs catching up does Stage B
(``_batch_advance_targets`` / ``game.core.levelup.advance_batch_plan``) run,
advancing whichever selected buildings can reach their next tier right now;
one that can't (already at the final tier, next tier unresearched, or
round-gated) is left sitting at level 3, untouched — it never blocks the
rest. A single selection is unaffected — it still upgrades/advances one step
at a time via the primary-only path, since both batch sweeps are gated on
``len(selected_tiles) > 1``.

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

from game.buildings import range_shape
from game.buildings.components import (
    BoostReceiver, BuildingSprite, Nameplate, RoundStats, TierState,
    YieldEconomy,
)
from game.buildings.movement import MoveError, is_movable, start_move
from game.buildings.registry import (
    BUILDING_CLASSES, LIGHTNING_SOURCE_TAG, PlacementError, build_cost,
    count_tag, create, place_building,
)
from game.buildings.research import buildable, tiers_unlocked_for
from game.core import lightning  # 10H (sanctioned ui -> core direction)
from game.core.levelup import advance_batch_plan, upgrade_gate
from game.core.wall_era import sync_wall_art_era  # wall-era-art feature
from game.core.xp import scaled_base_income
from game.debug import events as dbg  # debug-mode-telemetry Phase 2
from game.map import edge_world_points  # wall-edge selection highlight
from game.map.tiles import (
    CONDITION_BLOCKS_BUILD, CONDITION_MODIFIER_KEY, TileCondition, TileState,
)

from engine.render.fonts import layout_h

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .strings import T
from .widgets import (
    Button, anim_ms, contains, label_holder, submit_label, submit_panel,
    submit_tile_diamond, submit_tile_diamond_fill, submit_text, text_h,
    text_size, wrap_text
)
from . import widgets

# Both BuildingUI and its nested ConstructPreview share ONE screen id (they
# are one editable "screen" — the panel and its modal preview) with disjoint
# id namespaces ("preview_*" prefix keeps ConstructPreview's ids from
# colliding with BuildingUI's own).
SCREEN_ID = "building_panel"

#: Id prefix for a construct card, completed by the card's `building_type`
#: (`card_defence`, `card_economic`, …). The type is the stable key that makes
#: a dynamic-count card list individually overridable; `_clear_card_ids` uses
#: this same prefix to sweep the previous build's entries out of `self.ids`.
_CARD_ID_PREFIX = "card_"

#: MasterSheetColumnsPLAN B3 — id prefix for the upgrade panel's colour
#: swatches, completed by `ColorSwatchRow` with `_<index>` (`upgrade_swatch_0`,
#: …). The COUNT is dynamic (1..16 per master sheet) and the row is rebuilt per
#: selection, so `_clear_colour_ids` sweeps this prefix exactly the way
#: `_clear_card_ids` sweeps `card_` — a stale id would leave `skinning.apply`
#: writing overrides onto a dead Button.
_UPGRADE_COLOR_PREFIX = "upgrade_swatch"

#: Gap between the swatch row's bottom and the upgrade action button's top.
#: The row hangs off `action_btn.rect` (like `move_btn` hangs BELOW it), so it
#: sits in the one free band the upgrade panel has — see `_build_colour_row`
#: for the worked arithmetic.
_COLOUR_ROW_GAP = 6

#: Slot-key prefix for the OPTIONAL dedicated card-portrait art family
#: (`data/slots.json`'s `ui` -> "Card Portraits"), completed by the card's
#: `building_type`. Only consulted when the screen's
#: `defaults.use_card_portrait_slot` is on — see `_card_portrait_slot`.
_CARD_PORTRAIT_PREFIX = "card_portrait_"

#: The love icon drawn inside a card's price button — the baked HUD sprite
#: `hud.py` already signposts love with. NOT a text glyph: `widgets.HEART`
#: was deleted because the game font has no glyph for it (`game/ui/CLAUDE.md`
#: "The love glyph is GONE").
_CARD_LOVE_ICON = "ui_icon_love"

# -- Construct-card geometry (the widget-tree card) ------------------------
# A card is a PARENT holding four children: a square creature portrait on the
# left, a wrapped name block top-right, and a price button under it carrying a
# love icon + the number. Every rect below is ABSOLUTE — `parent` is EDITOR
# authoring metadata that nothing in `game/` reads (`editor/widget_tree.py`),
# so `_build_construct` lays its own children out and no cascade exists at
# runtime.
#
# The vertical fit, at "sm" (`layout_h` 11, so `_row_step("sm")` == 12):
#   portrait   y+3  .. y+37   (34 square)
#   name       two rows from y+2 -> last row ends y+2+12+11 = y+25
#   price btn  y+24 .. y+38   (14 tall: over the 12px click-target floor and
#                              over its own layout_h 11 — `test_ui_min_targets`)
# The name's second row and the price button share one pixel of the card's
# 40px height; the glyphs themselves do not touch, since "sm" draws 9px tall
# inside its 11px layout box.
_CARD_INSET = 6            # card column inset inside the panel (`_card_column`)
_CARD_H = 40
_CARD_GAP = 4              # list pitch = _CARD_H + _CARD_GAP
_CARD_PAD = 3              # portrait inset from the card's top-left corner
_CARD_PORTRAIT = 34        # square portrait side
_CARD_COL_X = 41           # right column x, relative to the card's left edge
_CARD_PRICE_TOP = 24       # price button top, relative to the card's top
_CARD_PRICE_H = 14
_CARD_ICON = 10            # love icon side, inside the price button
_CARD_LIST_TOP = 32        # first card's y at scroll offset 0
_CARD_LIST_BOTTOM_PAD = 30 # clearance for the terrain badge at the panel foot
# Construct-panel-only grey fill alpha for a tile already barred from hosting
# another Painter (widgets.C_PAINTER_USED) — same alpha-tuple pattern as
# overlays.py's _TIER_OVERVIEW_ALPHA.
_PAINTER_USED_ALPHA = 130
# The price pill carries its OWN skin rather than inheriting the card body's
# `defaults.button_skin`: the body is a full-card 9-slice, and stretching that
# same art through a 74x14 pill reads as a squashed card. Baked here for the
# same reason `_CARD_LOVE_ICON` is — it names a specific piece of art, and a
# designer who wants another one overrides `card_<btype>_price`'s `skin` in the
# editor, per card, without touching the body.
_CARD_PRICE_SKIN = "ui_button_pill"
# -- /construct-card geometry ---------------------------------------------

# -- Tile-condition cards (unlock mode) + the editable terrain box ---------
# The unlock panel names the terrain the player is buying, one card per
# DISTINCT condition across every 2x2 chunk in the selection (a chunk is four
# tiles, so a single-chunk unlock is at most four cards and usually one or
# two). Cards are DYNAMIC-count content in the `_build_construct` sense — the
# COUNT varies with the roll, the KEY does not — so each card is id'd
# `cond_card_<condition>` and every part of it is individually overridable.
#
# The vertical fit, at "sm" (`layout_h` 11, so `_row_step("sm")` == 12), for a
# sprite `sh` tall (see the frame-size note below):
#   sprite    y+3 .. y+3+sh   centred horizontally; it owns the top band alone
#   name      one row under it, full width, with the tile count right-aligned
#   effects   under that: ONE row naming the effect, one row carrying its
#             number (see `_COND_EFFECT_LINES`)
# so a card is `_COND_CARD_PAD*2 + sh + step*(1 + rows)` tall, laid out at
# BUILD time (the `_layout_upgrade_rows` precedent: writing the default anchor
# before `skinning.apply` is what lets a designer's rect override win), and
# positioned inside its GROUP container rather than off `panel`.
#
# The sprite is drawn at the art's OWN frame size — `assets.frame_size(slot)`,
# 64x96 for a condition (the tile diamond plus the headroom a mountain or a
# tree needs), 64x32 for the plain ground tile grass falls back to.
# `HudSprite` STRETCHES a frame to the box it is given rather than fitting it,
# so any box that is not the frame's own size distorts the art; a card is
# sized to the sprite instead of the other way round.
#
# A frame size is committed DATA (`asset_manifest.json`), not a font metric,
# so it is deterministic across platforms and may reach a stored rect. The
# fallback is only for a headless panel with no asset store at all.
_COND_CARD_ID_PREFIX = "cond_card_"
_COND_CARD_PAD = 3
_COND_CARD_SPRITE_FALLBACK = (64, 96)

#: The preview a card shows when its condition has no art of its own: the
#: regular buildable ground tile, which is what the bought tile becomes.
#: GRASS is the absence of a condition (its `cond_grass_*` slot ships without
#: art, and the world's own emitter skips it for the same reason), and an
#: un-imported condition slot would otherwise blit the engine's grey X (E-37).
#:
#: Nothing composites a ground tile UNDER the condition art any more — a card
#: draws exactly ONE sprite, at the `cond_card_<condition>_sprite` id, so
#: every card's preview is the same widget and a designer's downsize/position
#: override applies to all four identically. (It used to draw a `_ground`
#: sibling as well; that widget is gone.)
_CARD_GROUND_SLOT = "tile_buildable"

_COND_CARD_GAP = 4         # list pitch = card height + this
_COND_CARD_LIST_TOP = 112  # first card's y, clear of the UNLOCK button (75..93)
                           # and the not-adjacent warning under it (98)
_COND_CARD_LIST_BOTTOM_PAD = 6

#: The two card GROUPS, as their own id'd container widgets. Cards are laid
#: out INSIDE whichever rect their container carries, so moving or resizing
#: one container in the editor shifts and re-windows its whole list — the
#: thing a designer could not do while every card's rect was derived straight
#: off `panel`. Each is the exporter-recorded PARENT of its cards too, so the
#: editor's widget tree shows the group as a branch rather than N roots.
#:
#: A container DRAWS only once it carries a `skin`: unskinned it is pure
#: layout, which keeps the shipped look byte-identical (the golden-parity
#: contract) while letting a designer give the group a real backdrop.
_TERRAIN_LIST_ID = "terrain_card_list"
_CONSTRUCT_LIST_ID = "construct_card_list"

#: The terrain box and each terrain card reserve exactly TWO id'd effect rows,
#: and the two are a PAIR, not a list: row 0 names the effect ("Range"), row 1
#: carries its number ("+1"). That is what lets a designer place the name and
#: the value independently — side by side, or stacked — the same split the
#: per-stat `stat_<key>_label`/`stat_<key>_value` widgets use.
#:
#: It replaces five rows of full sentences ("+1 range for defenders"), which
#: were written for a tooltip that grew to fit them and wrapped once the boxes
#: became a fixed 112px wide. Nothing wraps now: both halves are short by
#: construction, so `_tile_cond_effect_lines` may reach a stored rect with no
#: live font measurement anywhere in the path.
#:
#: Only the FIRST effect a condition carries is shown. Today every condition
#: has exactly one and `map.json` ships modifiers for two conditions at all;
#: a second effect on one condition would need a second pair of rows, not a
#: longer list.
_COND_EFFECT_LINES = 2
# -- /tile-condition cards -------------------------------------------------

# 10I: tooltip chrome — dark panel, 1px border in the condition colour
# (prototype building_ui.py:1440-1455).
_COND_TOOLTIP_BG = (20, 15, 35)
# -- 10J: the name-dice glyph (prototype building_ui.py:106) --
#: UT-3: the dice caption is `building.btn.dice` in the string table now.
#: This stays as the UNCONFIGURED fallback the table was seeded from —
#: the same precedent `game/ui/strings.py` sets for every other literal.
_DICE_GLYPH = "⚄"
# UR-5: the "X" close button. UR-2's halved 20x18 -> 10x9 sat under the 12px
# click-target floor AND was 4px shorter than its own "md" label (layout_h 13),
# which the centred draw then overhung top and bottom. 14x13 is the smallest
# box that holds the glyph and clears the floor.
_CLOSE_W, _CLOSE_H = 14, 13
#: Font for the CONFIRM/CANCEL row shared by ConstructPreview and MovePreview.
#: "md", not "lg" — see the comment at ConstructPreview's button row.
_PREVIEW_BTN_FONT = "md"
#: BU-4: how many wrapped "sm" lines the boss-history popup's hover tooltip may
#: use. The popup's height budget is written against exactly this number (see
#: `_boss_popup_rect`), so the two move together.
_BOSS_TIP_LINES = 4


def _boss_upgrade_copy(session, upgrade_id):
    """``(name, description)`` for a picked boss upgrade — the SAME catalog
    lookup `game/ui/boss_cutscene.py` does for its cards, with the live
    ``params`` formatted into the description so the history can never quote a
    magnitude the cards did not.

    Degrades to ``(upgrade_id, "")`` when no ``boss_upgrades`` balance is wired
    (a bare `Session` a logic test builds) or the id is not in the catalog —
    a history row must render whatever the run recorded.
    """
    balance = getattr(session, "boss_upgrades_balance", None)
    catalog = ({} if balance is None
               else balance["BossUpgrades"]["Catalog"])
    entry = catalog.get(upgrade_id) or {}
    desc = entry.get("description", "")
    try:
        desc = desc.format(**entry.get("params", {}))
    except (KeyError, IndexError, ValueError):
        pass
    return entry.get("name", upgrade_id), desc


def _cond_effect_rows(lines):
    """The `(name, value)` pair padded/capped to exactly `_COND_EFFECT_LINES`
    entries, so row `i` always addresses the same half of the effect.

    No wrapping: both halves are short by construction (see
    `_COND_EFFECT_LINES`), which is what lets the same list drive the BUILD-time
    row budget and the DRAW-time text with no live font measurement between
    them."""
    rows = list(lines[:_COND_EFFECT_LINES])
    return rows + [""] * (_COND_EFFECT_LINES - len(rows))


def _row_step(font_key, leading=1):
    """Vertical step between two stacked text rows in this panel — ``layout_h``
    of the row's font plus ``leading``, never a pixel literal.

    A row step is a FONT-scale quantity, not a surface-scale one
    (``planning/UiResolutionPLAN.md``'s conversion rule; ``game/ui/CLAUDE.md``
    "A text ROW STEP is font-scale"): UR-2 halved every step in this module
    along with the panel while ``data/ui/fonts.json`` deliberately stayed put,
    so rows landed 1-3px on top of each other. ``hud._readout_step()`` is the
    pattern this copies — a FUNCTION, not a module constant, because a
    constant evaluated at import would freeze the pre-``configure_fonts``
    fallback metrics.

    ``leading=0`` is for the two height-constrained stacks whose fit
    arithmetic leaves no room for a leading pixel; each such call site states
    that arithmetic inline.
    """
    return layout_h(font_key) + leading


def _batch_cost(building_type, buildings_balance, tier_idx, repeat_count, count,
                run_state=None, boss_upgrades_balance=None):
    """The escalating BATCH total for ``count`` fresh placements of
    ``building_type`` (feature-storm-acolyte-multi-build), each tile priced
    at its own escalation step — ``repeat_count``, ``repeat_count + 1``, …,
    ``repeat_count + count - 1`` — via ``build_cost`` per step. This is the
    SAME formula ``place_building`` recomputes per tile as ``_do_place``
    walks a batch (each placed tile raises the live ``count_tag`` count
    before the next tile is priced), so this total always agrees with what
    will actually be charged. A type with no ``repeat_cost_multiplier``
    collapses to the familiar flat ``build_cost(...) * count`` (every step
    prices identically).

    ``run_state``/``boss_upgrades_balance`` are BU-3's standard optional
    trailing pair, forwarded per step so a Blocker/WallBuilder batch quotes
    the ``wall_cost_discount`` price ``place_building`` will actually charge."""
    return sum(build_cost(building_type, buildings_balance, tier_idx,
                          repeat_count + i, run_state=run_state,
                          boss_upgrades_balance=boss_upgrades_balance)
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


#: The building stat VOCABULARY (UT-3). Every row a panel can show has a
#: stable key here, and each key owns two id'd widgets in the upgrade panel —
#: ``stat_<key>_label`` and ``stat_<key>_value`` — so a designer can move,
#: recolour, re-font or hide a stat's NAME and its NUMBER independently.
#: The order is the canonical full-list order the default rects are laid out
#: in; a building shows the subset it actually has, stacked compactly.
#: Adding a stat = a key here + a ``building.stat.<key>`` string id.
STAT_KEYS = (
    "hp", "damage", "range", "atk_speed", "upkeep",
    "hp_base", "damage_base", "atk_speed_base",
    "boost", "boost_speed", "boost_damage", "boost_hp",
    "wall_hp", "progress", "payout", "pays_in", "yield", "streak",
)

#: y of the upgrade panel's first stat row, and of base_info's first row —
#: the anchors the pre-UT-3 draw calls spelled inline.
_STAT_BLOCK_TOP = 58
_BASE_INFO_TOP = 36

#: base_info's five fixed rows, in draw order. Each owns a label/value id
#: pair the same way a stat row does.
_BASE_INFO_ROWS = ("lives", "wave", "enemies_killed", "buildings",
                   "base_income")

#: ``Defender.boosted_stats()`` still returns DISPLAY labels
#: (``game/buildings/defence.py``) — mapped to stat keys here rather than
#: widening that method's contract, which nothing else consumes.
_BOOSTED_STAT_KEYS = {"HP": "hp_base", "Damage": "damage_base",
                      "Atk speed": "atk_speed_base"}


def _building_stats(b):
    """``[(stat_key, value)]`` for a building's current tier — the panel/
    preview stat block. Duck-typed so any future family is picked up.

    The LABEL is no longer returned: it is the widget's own
    ``building.stat.<key>`` string-table template, resolved at draw time, so a
    designer can rename "Atk speed" without touching code and without breaking
    the hover-preview match (which compares keys now, not label text)."""
    rows = [("hp", b.max_hp())]
    if hasattr(b, "damage"):            # defence family
        rows.append(("damage", b.damage()))
        # 10I: the Range row shows the EFFECTIVE (mountain-boosted) range,
        # duck-typed so pre-10I stubs without the method keep working.
        rows.append(("range",
                     getattr(b, "effective_range_tiles", b.range_tiles)()))
        rows.append(("atk_speed", f"{b.attack_speed():.1f}s"))
        rows.append(("upkeep", b.upkeep()))
        # 10D: a booster is lifting these — show the un-boosted base for contrast.
        for label, base in b.boosted_stats().items():
            key = _BOOSTED_STAT_KEYS.get(label)
            if key is not None:
                rows.append((key, base))
    if hasattr(b, "boost_value"):       # boost building (10D) — buffs neighbours
        rows.append(("range", b.range_tiles()))
        rows.append((b._boost_stat_key, f"{b.boost_value() * 100:.1f}%"))
        rows.append(("upkeep", b.upkeep()))
    if hasattr(b, "wall_hp"):           # wall builder (10E) — raises edge walls
        rows.append(("wall_hp", b.wall_hp()))
        rows.append(("upkeep", b.upkeep()))
    if hasattr(b, "payout_amount"):     # painter — risky economy (no yield)
        rows.append(("progress", f"{b.progress}/{b.rounds_to_payout()}"))
        rows.append(("payout", f"{b.payout_amount()}"))
        remaining = max(0, b.rounds_to_payout() - b.progress)
        rows.append(("pays_in", f"{remaining} rounds"))
    elif hasattr(b, "streak_max"):      # meditator — compounding economy
        rows.append(("yield", b.yield_amount()))  # pure (no streak advance)
        rows.append(("streak", f"{b.streak}/{b.streak_max()}"))
    elif hasattr(b, "yield_amount"):    # musician
        rows.append(("yield", b.yield_amount()))
    return rows


def _stat_label(key):
    """A stat key's resolved display label — for the few places that need the
    TEXT rather than an id'd widget (the next-tier preview card's combined
    ``label  value`` rows, which are dynamic-count content)."""
    return T(f"building.stat.{key}")


def _tier_name(b):
    """The building's current-tier display name from balancing (e.g. "Cave
    Painter"), not the art-slot prefix — so tiers that reuse another line's art
    (Meditator) or share one prefix (Painter) still title correctly."""
    return b.tier_data()["name"]


#: MasterSheetColumnsPLAN B3 — the ONE key ``_swatch_rgb`` reads out of
#: ``data/balancing/ui.json``. Optional in the schema on purpose (it is NOT in
#: the root ``required`` list), so a balance document without it — the test
#: fixture's, or an older save of the file — degrades to neutral swatches
#: instead of raising.
_BUILDING_COLORS_KEY = "BuildingColors"


def _swatch_rgb(name, ui_balance=None):
    """A colour NAME -> ``(r, g, b)`` for the swatch fill.

    B3: the colours are DATA — ``ui.json``'s ``BuildingColors`` group, a
    ``name -> [r, g, b]`` map a designer edits in the editor's balancing
    panel (which picks the group up for free by recursing the schema). This
    is the ONE place a colour name becomes an RGB; both callers
    (``ConstructPreview``'s row and the upgrade panel's) pass the balance
    dict they already hold.

    **A miss degrades, it never raises** (E-37): an absent group, a `None`
    balance (a bare row built by a tool or a test) or a ``columns`` name with
    no entry all return the neutral ``widgets.C_PANEL_INSET`` — the swatch
    still exists and still picks its column, it is just not tinted. Art may
    declare any colour name it likes; the palette is not obliged to know it.

    The neutral is read as ``widgets.<NAME>`` ATTRIBUTE ACCESS, never
    import-bound: ``widgets.configure_palette`` rebinds every ``C_*``
    constant in place at boot (widgets.py:92-104), which an early
    ``from .widgets import C_PANEL_INSET`` could not see.
    """
    rgb = (ui_balance or {}).get(_BUILDING_COLORS_KEY, {}).get(name)
    if rgb is None:
        return widgets.C_PANEL_INSET
    return tuple(rgb)


class ColorSwatchRow:
    """A right-aligned row of N square colour swatches (building colour).

    Pure layout + hit-test + draw over ``widgets.Button``, factored out
    because TWO screens use it: ``ConstructPreview`` (B2) and the
    ``BuildingUI`` upgrade panel (B3). It owns no game state — the caller
    keeps the selection and feeds it back in through ``submit``, which is
    what lets B3 point it at a live building's ``SpriteAnimator.column``
    while B2 points it at a pending int.

    ``hit`` returns an INDEX, never a name (plan D5: the building stores the
    column index). ``0`` is a real colour, so a miss is ``None`` — never a
    falsy index.
    """

    SIZE = 12   # UR-5 floor exactly (tools/tests/test_ui_min_targets.py:55)
    GAP = 2

    def __init__(self, colors, left, right, top, id_prefix, ui_balance=None):
        """``colors``    - tuple of colour NAMES from the host capability map
                           (``()`` => an empty, inert row).
        ``left``/``right`` - the horizontal band, in logical px; the row is
                           RIGHT-aligned to ``right`` and clamped to the
                           first ``(avail + GAP) // (SIZE + GAP)`` colours
                           (the registry schema permits up to 16 names, and
                           only ~8 twelve-px swatches fit this modal's band).
        ``top``        - the row's top edge, logical px.
        ``id_prefix``  - ``"preview_color"`` (B2) / ``"upgrade_color"`` (B3);
                           widget ids are ``f"{id_prefix}_{i}"``.
        ``ui_balance`` - passed straight to ``_swatch_rgb`` (B3's data hook).
        """
        self._id_prefix = id_prefix
        pitch = self.SIZE + self.GAP
        avail = max(0, int(right) - int(left))
        max_fit = max(0, (avail + self.GAP) // pitch)
        self.colors = tuple(colors or ())[:max_fit]
        n = len(self.colors)
        row_w = n * self.SIZE + (n - 1) * self.GAP if n else 0
        x0 = int(right) - row_w
        #: The swatch buttons, left to right; index i IS master column i.
        self.buttons = [
            Button((x0 + i * pitch, int(top), self.SIZE, self.SIZE), "", "sm")
            for i in range(n)]
        #: Per-swatch fill, resolved once at build time (the palette is
        #: already configured by the time any screen constructs a row).
        self.fills = [_swatch_rgb(name, ui_balance) for name in self.colors]

    @property
    def ids(self):
        """``{widget_id: ("button", Button)}`` — merge into the screen's own
        ``ids`` dict BEFORE it calls ``skinning.apply``. Empty when inert."""
        return {f"{self._id_prefix}_{i}": ("button", btn)
                for i, btn in enumerate(self.buttons)}

    def __bool__(self):
        """False when there is nothing to draw (no colours, or none fit)."""
        return bool(self.buttons)

    def hover(self, mx, my, mouse_down=False):
        for btn in self.buttons:
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)

    def update(self, dt):
        for btn in self.buttons:
            btn.update(dt)

    def hit(self, mx, my):
        """The colour INDEX under the cursor, or ``None``. Never returns 0
        for a miss — 0 is a real colour (S1's sentinel rule)."""
        for i, btn in enumerate(self.buttons):
            if is_visible(btn) and btn.hit(mx, my):
                return i
        return None

    def submit(self, renderer, selected, anim_ms=0):
        """Draw the row. Call from the caller's BUTTON block ONLY, never the
        text block. ``selected`` is the caller's current index (``None`` =>
        none marked); the marker ring is drawn right after its own swatch —
        the sanctioned "highlight ring after its own button" exception
        (``overlays.py MapOverlays.submit_buttons``, game/ui/CLAUDE.md)."""
        from engine.render import HudRect

        for i, btn in enumerate(self.buttons):
            if not is_visible(btn):
                continue
            kwargs = button_kwargs(btn)
            # An override's own colour wins; otherwise the swatch IS its fill.
            if kwargs.get("color") is None:
                kwargs["color"] = self.fills[i]
            btn.submit(renderer, anim_ms=anim_ms, **kwargs)
            if selected is not None and i == selected:
                renderer.submit_hud(
                    HudRect(btn.rect, widgets.highlight_color("tile_selected"),
                             width=1))


class ConstructPreview:
    """Centered modal for placing a new building: name entry + stat preview +
    confirm/cancel (positioned per ``ui.Timing``). Modal — the host routes all
    clicks/keys here while it is open."""

    def __init__(self, building_type, cost, buildings_balance, ui_balance,
                 view_w, view_h, count=1, tier_idx=0, repeat_count=0,
                 skinning=None, *, building_colors=None, run_state=None,
                 boss_upgrades_balance=None):
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
        # BU-3's standard optional trailing pair, held for `total_cost` — the
        # batch figure CONFIRM charges, which must carry the same
        # `wall_cost_discount` reduction the card's own price already showed.
        self._run_state = run_state
        self._boss_upgrades_balance = boss_upgrades_balance
        self.view_w = view_w
        self.view_h = view_h
        self._names = _random_names(buildings_balance)
        temp = create(building_type, 0, 0, buildings_balance, tier_idx)
        self.title = (_tier_name(temp) if count == 1
                      else T("building.preview.title_batch",
                             name=_tier_name(temp), count=count))
        self.stats = _building_stats(temp)
        self.name = ""
        self.editing = False

        pw, ph = 170, 150
        x, y = view_w // 2 - pw // 2, view_h // 2 - ph // 2
        self.rect = (x, y, pw, ph)
        # 10J: the name row shrinks to make room for the dice reroll button
        # (prototype building_ui.py:136, 243-247).
        self.name_rect = (x + 8, y + 48, pw - 16 - 18, 15)
        self.dice_btn = Button((x + pw - 8 - 15, y + 48, 15, 15),
                               T("building.btn.dice"), "md")
        # -- MasterSheetColumnsPLAN B2: the building-colour swatch row --------
        # The HOST derives `{slot_key: (colour_name, ...)}` once at boot
        # (`game/main.py _derive_colour_columns`) and publishes it down to
        # `BuildingUI.colour_columns`; `game/ui` never reaches into the asset
        # layer itself (D6/E-37). Fewer than 2 colours => no widgets at all,
        # no ids, nothing drawn: there is no choice to offer, and a slot with
        # exactly one colour still gets it from `place_building`'s own roll.
        #
        # Vertical fit — the row is `y+36 .. y+47` inclusive (SIZE 12):
        #   cost line (md) occupies y+22 .. y+34   -> 1px of clearance above
        #   name box top edge is y+48              -> exactly abuts, no overlap
        #   stat list still starts at y+69         -> nothing below moves, so
        #   `data/ui/screen_defaults.json` needs no regeneration.
        # 12 is the UR-5 click-target floor exactly and the largest square the
        # 13px band holds (11 would fail the floor, 13 would hit the name box).
        colors = (building_colors or {}).get(temp.slot_key(), ())
        if len(colors) < 2:
            colors = ()
        self.swatches = ColorSwatchRow(
            colors,
            # The only other thing in this band is the "Name:" label at x+8.
            x + 8 + text_size(T("building.preview.name_label"), "sm")[0] + 4,
            x + pw - 8, y + 36, "preview_color", ui_balance=ui_balance)
        #: The colour column this modal will place at, or None when the slot
        #: has no colours (then `place_building` leaves the animator's -1 "no
        #: driver" sentinel). ROLLED HERE so the preview cannot lie: the
        #: player sees the colour they get whether or not they touch a swatch,
        #: and `_do_place` passes this index explicitly. Same `random` module
        #: the name dice already draws from — no rng seam through the UI.
        #: `0` is a real colour index, so this is always tested `is not None`.
        self.chosen_column = (random.randrange(len(self.swatches.colors))
                              if self.swatches else None)
        # -- /B2 --
        self.close_btn = Button((x + pw - 17, y + 3, _CLOSE_W, _CLOSE_H),
                                T("building.btn.close"), "md")
        # Font "md", not "lg": CONFIRM needs 79px at "lg" under the SHIPPED
        # pixel font (`data/ui/active_font.json` -> pixel_emulator, wider per
        # glyph than the `SysFont("monospace")` fallback these constants were
        # authored against) in a 70px button, and there is no shorter word for
        # it. At "md" it needs 59. CANCEL moves with it so the pair stays one
        # row; `_PREVIEW_BTN_FONT` is shared with `MovePreview` below, which
        # shares this modal's chrome and its `preview_*` id namespace.
        btn_y, bw, bh = y + ph - 24, 70, 17
        left = Button((x + 8, btn_y, bw, bh), "", _PREVIEW_BTN_FONT)
        right = Button((x + pw - 8 - bw, btn_y, bw, bh), "", _PREVIEW_BTN_FONT)
        show_cancel = ui_balance["Timing"]["construct_show_cancel"]
        confirm_right = ui_balance["Timing"]["confirm_on_right_side"]
        if show_cancel:
            self.confirm_btn = right if confirm_right else left
            self.cancel_btn = left if confirm_right else right
            self.confirm_btn.label = T("building.btn.confirm")
            self.cancel_btn.label = T("building.btn.cancel")
        else:
            self.confirm_btn = Button((x + 8, btn_y, pw - 16, bh),
                                      T("building.btn.confirm"),
                                      _PREVIEW_BTN_FONT)
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
        # B2: the swatches join the ids BEFORE apply, so a screen override can
        # skin/hide them like any other widget. Empty when the row is inert,
        # so a colourless building's id set is byte-identical to before.
        self.ids.update(self.swatches.ids)
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
                           self._tier_idx, self._repeat_count, self.count,
                           self._run_state, self._boss_upgrades_balance)

    @property
    def chosen_name(self):
        return self.name.strip() or T("building.preview.unnamed",
                                      title=self.title)

    def hover(self, mx, my, mouse_down=False):
        for btn in (self.confirm_btn, self.close_btn, self.dice_btn):
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
        if self.cancel_btn is not None:
            self.cancel_btn.hover(mx, my, mouse_down)
            self.cancel_btn.hovered = (self.cancel_btn.hovered
                                       and is_visible(self.cancel_btn))
        self.swatches.hover(mx, my, mouse_down)   # B2 (a no-op when inert)

    def confirm_hovered(self):
        return self.confirm_btn.hovered

    def update(self, dt):
        self.confirm_btn.update(dt)
        self.close_btn.update(dt)
        self.dice_btn.update(dt)
        if self.cancel_btn is not None:
            self.cancel_btn.update(dt)
        self.swatches.update(dt)                  # B2 (a no-op when inert)

    def handle_click(self, mx, my):
        """Return an action string (``confirm`` / ``cancel`` / ``close`` /
        ``name`` / ``color`` / None). The host treats the modal as consuming
        every click, so ``color`` needs no host branch — it is only the
        panel's own signal that the pick changed.
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
        # B2: BEFORE the name_rect branch. The swatches sit in the band
        # directly above the name box, and `name_rect` is a plain containment
        # test — the broadest branch here — so a later test would let a
        # near-miss swatch click fall through into "click to name".
        idx = self.swatches.hit(mx, my)
        if idx is not None:                # 0 is a real colour: `is not None`
            self.chosen_column = idx
            return "color"
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

        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
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
            self.name_rect,
            # VA-5: the focus ring borrows the SELECTION colour deliberately —
            # it read the same `highlight` palette key before that key moved
            # into procedural.highlights, so this is zero visual change with
            # one home rather than a second copy of the value.
            (widgets.highlight_color("tile_selected") if self.editing
             else widgets.C_UI_BORDER),
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
        # B2: inside the BUTTON block, never the text block (the swatches ARE
        # buttons). Its own selection ring rides immediately behind its swatch.
        self.swatches.submit(renderer, self.chosen_column, anim_ms=anim_ms)
        cx = x + w // 2
        submit_text(renderer, self.title, (cx, y + 6), "lg", widgets.C_UI_TEXT,
                    align="center")
        submit_text(renderer, T("building.preview.cost", cost=self.total_cost),
                    (cx, y + 22),
                    "md", widgets.C_GOLD, align="center")
        submit_text(renderer, T("building.preview.name_label"), (x + 8, y + 38),
                    "sm", widgets.C_UI_TEXT_DIM)
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = widgets.C_UI_TEXT
        else:
            shown = T("building.preview.click_to_name")
            tcol = widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 4, ny + 3), "md", tcol)
        sy = y + 69
        # Font-scale row step (see _row_step). leading=0 here, deliberately:
        # this modal is height-constrained. The widest stat list a FRESH
        # `create()` can produce is the defence family's 5 rows (HP / Damage /
        # Range / Atk speed / Upkeep — `boosted_stats` is always empty on a
        # temp building), so the block runs y+69 .. y+69+4*11+layout_h("sm")
        # = y+124 against a CONFIRM/CANCEL row whose top is y+ph-24 = y+126.
        # A leading pixel per row would push it to y+128 and overlap the
        # buttons, which would mean growing the 170x150 panel; 11 clears them
        # by 2px and leaves every preview_* rect (and screen_defaults.json)
        # untouched.
        step = _row_step("sm", leading=0)
        # Dynamic-count content inside a modal (the construct-card rule):
        # no per-row id, but the LABELS are string-table entries shared
        # with the upgrade panel's id'd rows, so renaming a stat renames
        # it in both places.
        for key, value in self.stats:
            submit_text(renderer, _stat_label(key), (x + 8, sy), "sm",
                        widgets.C_UI_TEXT_DIM)
            submit_text(renderer, str(value), (x + w - 8, sy), "sm", widgets.C_UI_TEXT,
                        align="right")
            sy += step
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)


class MovePreview:
    """Centered confirmation modal for MOVING an already-placed building
    (Building Movement) — the ``ConstructPreview`` sibling, minus the name
    field, the dice and the stat list (nothing about the building changes, it
    just relocates).

    It deliberately mirrors ``ConstructPreview``'s public surface —
    ``hover``/``confirm_hovered``/``update``/``handle_click``/``handle_key``/
    ``submit`` plus a ``confirm_btn`` — so ``main.py``'s existing
    ``panel.preview is not None`` modal branch and ``BuildingUI._preview_click``
    drive it with no preview-class-specific code."""

    def __init__(self, building, dest_tile, cost, rounds, warning_text,
                 ui_balance, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.building = building
        self.dest_tile = dest_tile
        self.cost = cost
        self.rounds = rounds
        self.view_w = view_w
        self.view_h = view_h
        self.title = _display_name(building)
        # `main.py`'s modal branch routes keys at the preview too; a move has
        # nothing to type, so this stays False forever (handle_key is a no-op).
        self.editing = False

        pw = 170
        # Building Movement: a move in transit despawns the building until it
        # lands (`movement.py`'s module docstring) — every combat phase that
        # falls inside that window happens with the building gone. `rounds ==
        # 0` (an instant relocation — the time cost off, or tuned to zero) is
        # the one case that ISN'T true, so the warning is skipped there.
        # Text is designer content (`BuildingsGlobal.Movement.warning_text`,
        # `data/CLAUDE.md`) — wrapped at CONSTRUCT time, not draw time: unlike
        # an id'd widget's `label`, this line is never captured by
        # `screen_defaults.json`/the golden parity pin, so there is no
        # Windows/Linux measurement-drift risk (`game/ui/CLAUDE.md`'s
        # "layout_h, never a live font measurement" note doesn't apply here).
        self._warning_lines = (
            wrap_text(warning_text, "sm", pw - 16, max_lines=3)
            if rounds > 0 and warning_text.strip() else [])
        _warn_step = _row_step("sm", leading=0)
        _warn_h = len(self._warning_lines) * _warn_step
        # 83, not the pre-merge 95: the modal used to stack a separate Cost
        # line and Time line (feature: move-building-time-only-cost merged
        # them into the one `cost_text` line below), which freed exactly one
        # `_row_step("sm")` == 12px row.
        ph = 83 + (_warn_h + 4 if self._warning_lines else 0)
        x, y = view_w // 2 - pw // 2, view_h // 2 - ph // 2
        self.rect = (x, y, pw, ph)
        self.close_btn = Button((x + pw - 17, y + 3, _CLOSE_W, _CLOSE_H),
                                T("building.btn.close"), "md")
        btn_y, bw, bh = y + ph - 24, 70, 17
        left = Button((x + 8, btn_y, bw, bh), "", _PREVIEW_BTN_FONT)
        right = Button((x + pw - 8 - bw, btn_y, bw, bh), "", _PREVIEW_BTN_FONT)
        # Same two `ui.Timing` keys ConstructPreview reads — the modal chrome
        # convention is shared, so a designer flipping them moves both modals.
        # `_PREVIEW_BTN_FONT` is shared for the same reason (see its use in
        # ConstructPreview above for why CONFIRM is not "lg").
        show_cancel = ui_balance["Timing"]["construct_show_cancel"]
        confirm_right = ui_balance["Timing"]["confirm_on_right_side"]
        if show_cancel:
            self.confirm_btn = right if confirm_right else left
            self.cancel_btn = left if confirm_right else right
            self.confirm_btn.label = T("building.btn.confirm")
            self.cancel_btn.label = T("building.btn.cancel")
        else:
            self.confirm_btn = Button((x + 8, btn_y, pw - 16, bh),
                                      T("building.btn.confirm"),
                                      _PREVIEW_BTN_FONT)
            self.cancel_btn = None
        # Geometry is fixed for this instance's whole lifetime (a fresh
        # MovePreview is built each time the modal opens), so ids/apply run
        # ONCE here — the ConstructPreview pattern, sharing its id namespace
        # so an existing `preview_*` skin override styles both modals.
        self._panel = SimpleNamespace(rect=self.rect, skin=None)
        self.ids = {"preview_panel": ("panel", self._panel),
                    "preview_close_btn": ("button", self.close_btn),
                    "preview_confirm_btn": ("button", self.confirm_btn)}
        if self.cancel_btn is not None:
            self.ids["preview_cancel_btn"] = ("button", self.cancel_btn)
        self.skinning.apply(self.screen_id, self.ids)
        self.rect = self._panel.rect

    @property
    def total_cost(self):
        """The ``ConstructPreview.total_cost`` alias: a single move has no
        batch to sum, so this is just ``cost`` (always 0 — ``money_cost_
        enabled`` ships ``false``). Kept for the shared preview surface
        (``ConstructPreview`` carries the same name) and for ``_do_move``'s
        own affordability check via ``self.cost`` beside it — but
        ``BuildingUI.hover`` no longer reads it FOR THIS CLASS specifically
        (feature: move-building-time-only-cost — a move's cost is rounds,
        not love, so hovering CONFIRM must not preview a love spend on the
        HUD's pill; see the ``isinstance(self.preview, MovePreview)`` guard
        there)."""
        return self.cost

    @property
    def cost_text(self):
        """Moving costs only TIME now (feature: move-building-time-only-cost
        — `BuildingsGlobal.Movement.money_cost_enabled` ships `false`), so
        the modal's one Cost line quotes rounds, not love. `self.cost` (the
        love figure, always 0 with the flag off but still read by
        `total_cost`/`_do_move`'s affordability check) is deliberately not
        shown here any more — a 0-love line would be a Cost/Free redundant
        with this one."""
        if self.rounds == 0:
            return T("building.move_preview.cost_instant")
        unit = "round" if self.rounds == 1 else "rounds"
        return T("building.move_preview.cost", rounds=self.rounds, unit=unit)

    def hover(self, mx, my, mouse_down=False):
        for btn in (self.confirm_btn, self.close_btn):
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
        if self.cancel_btn is not None:
            self.cancel_btn.update(dt)

    def handle_click(self, mx, my):
        """Return an action string (``confirm`` / ``cancel`` / ``close`` /
        None) — the ConstructPreview contract ``_preview_click`` reads."""
        if is_visible(self.close_btn) and self.close_btn.hit(mx, my):
            return "close"
        if (self.cancel_btn is not None and is_visible(self.cancel_btn)
                and self.cancel_btn.hit(mx, my)):
            return "cancel"
        if is_visible(self.confirm_btn) and self.confirm_btn.hit(mx, my):
            return "confirm"
        return None

    def handle_key(self, char, key):
        """No text entry on this modal — deliberately inert, so the host's
        uniform `preview.handle_key(...)` routing needs no branch."""

    def submit(self, renderer, anim_ms=0):
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        x, y, w, h = self.rect
        # Submission order (game/ui/CLAUDE.md "panel -> button -> text").
        if is_visible(self._panel):
            submit_panel(renderer, self.rect, fill=widgets.C_UI_PANEL,
                        border=widgets.C_UI_BORDER, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None),
                        anim_ms=anim_ms)
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
        submit_text(renderer, T("building.move.title"), (cx, y + 6), "lg",
                    widgets.C_UI_TEXT, align="center")
        submit_text(renderer, self.title, (cx, y + 20), "md",
                    widgets.C_UI_TEXT_DIM, align="center")
        # Blue, not the love-cost gold every other preview's cost line uses
        # (feature: move-building-time-only-cost) — this line quotes ROUNDS,
        # not love, so it takes the SAME `move_target` highlight cyan as the
        # destination path-line preview (`BuildingUI.submit`'s move-path
        # line, `game/ui/CLAUDE.md`), not a colour that reads as "currency".
        submit_text(renderer, self.cost_text, (cx, y + 36), "md",
                    widgets.highlight_color("move_target"), align="center")
        submit_text(renderer,
                    T("building.move_preview.dest",
                      col=self.dest_tile.col, row=self.dest_tile.row),
                    (cx, y + 48), "sm", widgets.C_UI_TEXT_DIM, align="center")
        # Building Movement: the "will miss combat" warning — only present
        # (non-empty `_warning_lines`) once `rounds > 0`, see __init__.
        wy = y + 48 + _row_step("sm")
        step = _row_step("sm", leading=0)
        for line in self._warning_lines:
            submit_text(renderer, line, (cx, wy), "sm", widgets.C_HP_RED,
                        align="center")
            wy += step
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)


class BuildingUI:
    def __init__(self, view_w, view_h, ui_balance, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self._ui_balance = ui_balance
        self._flash_dur = ui_balance["Timing"]["not_enough_love_duration"]
        self.panel_w = 130
        self.panel_x = view_w - self.panel_w
        self.panel_rect = (self.panel_x, 0, self.panel_w, view_h)
        self._right = self.panel_x + self.panel_w - 7
        self.mode = None
        self.tile = None
        self.preview = None
        # -- TU-6: transient "a placement just landed" signal — the host
        # reads it once right after a successful handle_click() and clears
        # it; NEVER reset in close() (open_for_tile()'s internal close() call
        # inside _do_place() would wipe it before the host gets to read it). --
        self.last_placed_type = None
        # the last_placed_type precedent, for a successful tile unlock — the
        # host reads it once right after a successful handle_click() and
        # clears it; NEVER reset in close() for the same reentrancy reason.
        self.last_unlocked = False
        self._selected = None
        self._session = None
        self._upgrade_hint = None
        self._buildings_balance = None
        self._highlight_tiles = []
        self._highlight_edges = []
        self._painter_used_tiles = []
        self._hover_cost = None
        self._action_cost = 0
        self._clock = 0.0  # 10L-A: one anim clock per screen
        # -- 10J: shift multi-select batch (prototype game.py:189-191) --
        self.selected_tiles = []      # primary first; same category only
        # -- 10J: upgrade-panel rename row + dice; host callbacks --
        self._name_editing = False
        self._name_buf = ""
        # UR-5: the rename row is 15 tall, not UR-2's halved 11 — the text
        # inside it is "sm" (layout_h 11) drawn at +2, and the dice glyph is
        # "md" (layout_h 13); an 11px row clipped both, and the 12x11 dice was
        # under the 12px click-target floor.
        self._name_box_rect = (self.panel_x + 7, 20, self.panel_w - 32, 15)
        self._dice_up = Button(
            (self.panel_x + 7 + self.panel_w - 32 + 3, 20, 14, 15),
            T("building.btn.dice"), "md")
        self.log = None               # GameLog, wired by the host
        self.on_build_vfx = None      # (col, row, kind) -> None, wired by host
        # -- /10J --
        self.close_btn = Button(
            (self.panel_x + self.panel_w - 18, 4, _CLOSE_W, _CLOSE_H),
            T("building.btn.close"), "md")
        self.action_btn = Button(
            (self.panel_x + 6, 0, self.panel_w - 12, 18), "", "lg")
        # Building Movement: the upgrade panel's MOVE BUILDING action. Built
        # once here (the boss_btn/_dice_up mode-independent pattern) and
        # repositioned below action_btn by _build_upgrade; only ever visible in
        # upgrade mode on a SINGLE selection.
        self.move_btn = Button(
            (self.panel_x + 6, 0, self.panel_w - 12, 15), T("building.btn.move"),
            "md")
        self.move_btn.visible = False
        self.cards = []
        #: `{building_type: SimpleNamespace}` — the card's CHILD widgets
        #: (portrait / two name rows / price button / love icon / price text)
        #: plus the wrapped name lines and the live cost the draw pass needs.
        #: `self.cards` stays `[(btype, card_button)]` so `card_rect`, the
        #: hover pass and `_construct_click` are unchanged in shape.
        self._card_parts = {}
        # -- construct-card list: first VISIBLE card index. The list is taller
        # than the panel once several types are unlocked (12 cards x 44px
        # against a ~298px viewport), so it scrolls; the host routes the wheel
        # here from `main.py`'s gameplay MOUSEWHEEL branch. Reset by close(). --
        self.scroll_offset = 0
        #: Host-wired `engine.assets.AssetStore` (the `FloaterManager.assets`
        #: precedent), used ONLY to ask whether a dedicated card portrait has
        #: imported art. None (headless, tests, bare construction) reads as
        #: "no art" and keeps the tier-sprite fallback — never raises.
        self.assets = None
        #: MasterSheetColumnsPLAN B2: `{slot_key: (colour_name, ...)}`, the
        #: colour-capability map the HOST derives once at boot
        #: (`game/main.py _derive_colour_columns`) and publishes with a plain
        #: attribute assignment, exactly like `assets` above. `game/ui` never
        #: reaches into the asset layer itself (D6/E-37). The `{}` default is
        #: what keeps a bare `BuildingUI` (tests, tools) working: an empty map
        #: means no building has colours, so no swatches and no `column=`.
        self.colour_columns = {}
        #: MasterSheetColumnsPLAN B3: the upgrade panel's colour-swatch row —
        #: the SAME `ColorSwatchRow` B2's build-confirm modal uses, pointed at
        #: the LIVE building's `BuildingSprite.column` instead of a pending
        #: int. Rebuilt per selection by `_build_colour_row`; seeded INERT here
        #: (no colours => no buttons, no ids, nothing drawn) so `hover`/
        #: `update`/`hit`/`submit` are safe before the first build and in every
        #: other panel mode.
        self.colour_row = ColorSwatchRow((), 0, 0, 0, _UPGRADE_COLOR_PREFIX)
        # -- 10G boss: base_info "BOSS CHOICES" button + history popup --
        self.boss_btn = Button(
            (self.panel_x + 6, 210, self.panel_w - 12, 16),
            T("building.btn.boss_choices"), "md")
        # UR-5 follow-up: the popup body is a stack of "md" choice rows over a
        # 2-line "sm" hover tooltip, and BOTH steps are font-scale (see
        # _row_step) — 10 and 8 overlapped their 13px/11px lines by 3px each.
        # Correcting them to 14/12 costs height, so the popup GROWS 130 -> 158
        # rather than losing rows or clipping the tooltip. ph = 158 is the
        # smallest height that keeps the SIX choice rows the old 130/step-10
        # layout held:
        #   rows      first at py+24, sixth ends py+24+5*14+13 = py+107,
        #             against a tooltip top of py+ph-50 = py+108
        #   tooltip   2 lines at 12 from py+108 -> bottom py+131
        #   CLOSE     top py+ph-22 = py+136 (5px clear), popup bottom py+158
        # Centred on a 360-tall surface that is y 101..259 — 101px of margin
        # top and bottom. (The old 130 already overhung the CLOSE button with
        # its tooltip by 1px at step 8, and would have overhung by 5px at the
        # correct 12.)
        # BU-4 re-sized it once more, for the SAME reason (content, not taste):
        # a row now names the picked UPGRADE ("Boss 1: Win Concussive Shells")
        # instead of a bare "A"/"B", and the hover tooltip is the catalog's
        # wrapped prose description rather than a pre-broken 2-liner. 170 could
        # not hold either.
        #   width     260 -> a 246px text column, which fits the longest
        #             shipped row ("Boss 10: Loss <17-char name>") at "md"
        #   rows      unchanged: first at py+24, sixth ends py+24+5*14+13 =
        #             py+107
        #   tooltip   up to _BOSS_TIP_LINES (4) "sm" lines at 12, anchored
        #             UPWARDS off the CLOSE button, so its top is
        #             py+ph-26-48 = py+108 at ph = 182 — exactly clear of the
        #             sixth row, the same 1px-tight budget the 158 layout had
        #   CLOSE     top py+ph-22 = py+160 (5px clear), popup bottom py+182
        # Centred on a 360-tall surface: y 89..271.
        pw, ph = 260, 182
        self._boss_popup_rect = (view_w // 2 - pw // 2,
                                 view_h // 2 - ph // 2, pw, ph)
        px, py = self._boss_popup_rect[0], self._boss_popup_rect[1]
        self._boss_close_btn = Button(
            (px + pw // 2 - 30, py + ph - 22, 60, 16),
            T("building.btn.boss_close"), "md")
        self._boss_popup_open = False
        self._boss_hover_row = -1
        # -- /10G --
        # -- 10I: terrain badge hover/tooltip state --
        self._cond_badge_rect = None    # last-submitted badge rect (hit probe)
        self._cond_hover = False
        self._cond_tooltip = None       # (condition, color)
        self._cond_effect_lines = []    # the lines _layout_cond_box stacked
        # -- /10I --
        # unlock-mode terrain cards: [(condition, parts)], one per DISTINCT
        # condition across the selection's chunks (see `_build_cond_cards`)
        self._cond_cards = []
        self._cond_row_count = 0
        self.cond_scroll_offset = 0
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
            "move_btn": ("button", self.move_btn),
            "boss_btn": ("button", self.boss_btn),
            "rename_dice_btn": ("button", self._dice_up),
            "boss_close_btn": ("button", self._boss_close_btn),
        }
        # -- /10L-B --
        self._build_text_holders()

    # -- UT-3: id'd text ---------------------------------------------------

    def _build_text_holders(self):
        """Every piece of text this panel draws, as an id'd label holder.

        Two widgets per STAT — ``stat_<key>_label`` and ``stat_<key>_value``
        — so a designer can place a stat's name and its number independently
        (the whole point of UT-3), plus one per fixed line of every mode.
        Built ONCE here, like the mode-independent buttons above: the panel
        has no ``layout()``, so ``submit()``'s single ``skinning.apply`` pass
        is what threads overrides onto all of them.

        Default rects are STORED (the text-label convention: an ``(x, y, 0,
        0)`` anchor, W/H nominal 0) so the exporter reads a real position and
        a rect override actually moves the text. The stat rows are laid out in
        canonical ``STAT_KEYS`` order here and RE-stacked compactly by
        ``_build_upgrade`` for whichever subset the selected building has.
        """
        x, right = self.panel_x + 7, self._right
        md, sm = _row_step("md"), _row_step("sm")

        def lab(y, text_id, font="md", align="left"):
            anchor_x = right if align == "right" else x
            return label_holder((anchor_x, y, 0, 0), text_id=text_id,
                                font_key=font, align=align)

        self._stat_rows = {}
        y = _STAT_BLOCK_TOP
        for key in STAT_KEYS:
            self._stat_rows[key] = (
                lab(y, f"building.stat.{key}"),
                lab(y, "building.stat.value", align="right"))
            y += md
        for key, (name, value) in self._stat_rows.items():
            self.ids[f"stat_{key}_label"] = ("label", name)
            self.ids[f"stat_{key}_value"] = ("label", value)

        # Fixed lines, one holder each. Their default anchors mirror the
        # literals the pre-UT-3 draw calls used, so nothing moves.
        self._text = {
            "unlock_title": lab(8, "building.unlock.title", "lg"),
            "unlock_hint": lab(35, "building.unlock.hint", "sm"),
            "unlock_blocked": lab(98, "building.unlock.not_adjacent", "sm"),
            "construct_title": lab(8, "building.construct.title", "lg"),
            "upgrade_title": lab(5, None, "lg"),
            "upgrade_name": label_holder(
                (self._name_box_rect[0] + 3, self._name_box_rect[1] + 2, 0, 0),
                text_id="building.upgrade.name_placeholder", font_key="sm"),
            "upgrade_tier_level": lab(34, "building.upgrade.tier_level"),
            "dmg_dealt_label": lab(0, "building.upgrade.dmg_dealt", "sm"),
            "dmg_dealt_value": lab(0, "building.stat.value", "sm", "right"),
            "dmg_taken_label": lab(0, "building.upgrade.dmg_taken", "sm"),
            "dmg_taken_value": lab(0, "building.stat.value", "sm", "right"),
            "died_last_round": label_holder(
                (self.panel_x + self.panel_w // 2, 0, 0, 0),
                text_id="building.upgrade.died_last_round", font_key="sm",
                align="center"),
            "next_tier_header": lab(0, "building.upgrade.next_tier"),
            "upgrade_hint": label_holder(
                (0, 0, 0, 0), text_id=None, font_key="sm", align="center"),
            "base_info_title": lab(8, "building.base_info.title", "lg"),
            "move_title": lab(8, "building.move.title", "lg"),
            "move_name": lab(26, None),
            "move_pick": lab(48, "building.move.pick_tile"),
            "move_hint_1": lab(62, "building.move.hint_1", "sm"),
            "move_hint_2": lab(70, "building.move.hint_2", "sm"),
            "move_hint_cancel": lab(84, "building.move.hint_cancel", "sm"),
        }
        # base_info's five rows are a fixed set, so each gets its own pair.
        y = _BASE_INFO_TOP
        for key in _BASE_INFO_ROWS:
            self._text[f"info_{key}_label"] = lab(y, f"building.base_info.{key}")
            self._text[f"info_{key}_value"] = lab(y, "building.stat.value",
                                                  align="right")
            y += 15
        # -- the terrain badge + effect box, as id'd widgets -----------------
        # Both used to be drawn as bare `HudRect`s shrink-wrapped around a live
        # text measurement, which made them the two things on this panel a
        # designer could not touch. They are widgets now: a `panel` holder for
        # each box and a `label` holder for every line of text in it. The boxes
        # are therefore a FIXED width (the card column's) instead of shrink-
        # wrapped — a stored rect may not depend on a font measurement
        # (`game/ui/CLAUDE.md`) — and the badge caption centres inside it.
        #
        # `_COND_EFFECT_LINES` rows are reserved whether or not today's
        # balancing fills them; `_layout_cond_box` re-stacks the used ones
        # compactly per condition and the rest simply never draw (the
        # `_layout_upgrade_rows` shape). Real geometry lands there, at build
        # time; these are only the anchors the exporter would read for a mode
        # that never opened.
        # `_row_step("sm", 4)` — layout_h + 4, NEVER `text_h`: these rects are
        # STORED (and exported), and a stored rect may not depend on a live
        # font measurement (`tools/tests/test_layout_h_invariant.py`).
        cx, cw = self.panel_x + _CARD_INSET, self.panel_w - 2 * _CARD_INSET
        badge_h = _row_step("sm", 4)
        self._cond_badge = SimpleNamespace(
            rect=(cx, self.view_h - 20, cw, badge_h), skin=None,
            visible=True)
        self._cond_effect_box = SimpleNamespace(
            rect=(cx, self.view_h - 20 - 3 - (sm * _COND_EFFECT_LINES + 5),
                  cw, sm * _COND_EFFECT_LINES + 5), skin=None, visible=True)
        self._text["cond_badge_text"] = label_holder(
            (cx + cw // 2, self.view_h - 18, 0, 0),
            text_id="building.terrain_badge", font_key="sm", align="center")
        for i in range(_COND_EFFECT_LINES):
            self._text[f"cond_effect_line_{i}"] = label_holder(
                (cx + 4, self._cond_effect_box.rect[1] + 2 + i * sm, 0, 0),
                font_key="sm")
        self.ids["cond_badge"] = ("panel", self._cond_badge)
        self.ids["cond_effect_box"] = ("panel", self._cond_effect_box)
        # -- the two card GROUPS (see `_TERRAIN_LIST_ID`) --------------------
        self._construct_list = SimpleNamespace(
            rect=(cx, _CARD_LIST_TOP, cw,
                  self.view_h - _CARD_LIST_BOTTOM_PAD - _CARD_LIST_TOP),
            skin=None, visible=True)
        self._terrain_list = SimpleNamespace(
            rect=(cx, _COND_CARD_LIST_TOP, cw,
                  self.view_h - _COND_CARD_LIST_BOTTOM_PAD
                  - _COND_CARD_LIST_TOP),
            skin=None, visible=True)
        self.ids[_CONSTRUCT_LIST_ID] = ("panel", self._construct_list)
        self.ids[_TERRAIN_LIST_ID] = ("panel", self._terrain_list)
        # -- /terrain badge + effect box ------------------------------------
        for name, holder in self._text.items():
            self.ids[name] = ("label", holder)
        del md, sm      # step values are recomputed per submit (font-scale)

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
        self._highlight_edges = []
        self._painter_used_tiles = []
        self._hover_cost = None
        self.cards = []
        self._card_parts = {}
        self._clear_colour_ids()   # B3: the swatch row is per-selection
        self.scroll_offset = 0   # a fresh panel always opens at the top
        # -- 10J --
        self.selected_tiles = []
        self._name_editing = False
        self._name_buf = ""
        # -- /10J --
        self._stats_bottom = _STAT_BLOCK_TOP  # UT-3, set by _layout_upgrade_rows
        self._boss_popup_open = False  # -- 10G boss --
        # -- 10I: terrain badge state resets with the panel --
        self._cond_badge_rect = None
        self._cond_hover = False
        self._cond_tooltip = None
        self._cond_effect_lines = []
        # -- /10I --
        self._clear_cond_card_ids()
        self.cond_scroll_offset = 0

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
        # Building Movement: destination-picking peels back to the upgrade
        # panel it was entered from, one more rung on the same ladder.
        if self.mode == "move_select":
            self._back_to_upgrade(self._session)
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

    def action_rect(self):
        """Screen rect of the panel's mode-independent action button while it
        means "unlock this tile", or None otherwise (the tile-buying
        tutorial topic's highlighted-button step). ``action_btn`` is reused
        across unlock/construct-advance/upgrade modes, so this only resolves
        in ``"unlock"`` mode — never highlights the wrong button in another
        mode. Read-only — never mutates panel state."""
        return self.action_btn.rect if (
            self.visible and self.mode == "unlock") else None

    # -- /TU-6 ---------------------------------------------------------------

    def open_for_tile(self, tile, session, buildings_balance,
                      selected_tiles=None):
        """Open for the PRIMARY tile; ``selected_tiles`` (10J shift
        multi-select, primary first, same category) batches the unlock /
        construct / in-tier-upgrade / tier-advance actions. The base never
        batches."""
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
            # Building Movement: an endpoint of a move in progress is a plain
            # BUILDABLE tile (so enemies keep pathing through it) but cannot be
            # built on — the panel stays closed rather than offering cards that
            # `place_building` would refuse. That refusal is the enforcement;
            # this is the convenience, same split as the painter-tile bar.
            if session.tilemap.is_moving(tile.col, tile.row):
                self.mode = self.tile = None
                return
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
                    self._set_wall_highlight(occ, session.tilemap)
                else:
                    # range diamond only on a single selection (prototype
                    # game.py:552-556); a batch highlights its tiles.
                    # This IS the upgrade batch — VA-5 first wired it to
                    # `tile_selected` and gave `upgrade_batch` to the CONSTRUCT
                    # panel below, i.e. exactly backwards. Invisible while both
                    # shipped the same colour; the moment a designer bound art
                    # to `tile_selected`, a buildable tile kept the old diamond
                    # and a combat tile did not.
                    self._highlight_tiles = [
                        (t.col, t.row, "upgrade_batch")
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
                # BU-3 #6 tile_discount: the standard optional trailing pair,
                # off the Session (which holds both halves). This is the ONE
                # place the panel prices a tile unlock — the UNLOCK button's
                # label, its affordability gate and `_unlock_click`'s actual
                # `spend_love` all read this list — so the discount cannot
                # show in one and not the other.
                chunks[key] = (t, tm.unlock_cost(
                    t, session.state, session.boss_upgrades_balance))
        return list(chunks.values())

    def _build_unlock(self, session):
        tm = session.tilemap
        chunks = self._unlock_chunks(session)
        cost = sum(c for _, c in chunks)
        adjacent = all(tm.can_unlock(t) for t, _ in chunks)
        self._action_cost = cost
        self.action_btn.rect = (self.panel_x + 6, 75, self.panel_w - 12, 18)
        self.action_btn.enabled = adjacent
        n = len(chunks)
        if not adjacent:
            self.action_btn.label = T("building.action.not_adjacent")
        elif n > 1:
            self.action_btn.label = T("building.action.unlock_many",
                                       n=n, cost=cost)
        else:
            self.action_btn.label = T("building.action.unlock", cost=cost)
        hl = []
        for sel in self.selected_tiles:
            hl.append((sel.col, sel.row, "tile_selected"))
            for t in tm.get_chunk_for_tile(sel):
                if t is not sel:
                    hl.append((t.col, t.row, "section_2x2"))
        self._highlight_tiles = hl
        self._build_cond_cards(session)

    # -- unlock-mode terrain cards ------------------------------------------

    def _cond_card_rows(self, session):
        """``[(condition, count, slot)]`` for the tiles this unlock buys.

        Every 2x2 chunk in the selection contributes its four tiles (not just
        the primary tile's chunk — a shift multi-select buys them all, and the
        player is entitled to see what they are getting), DEDUPED by condition
        so the list is at most one card per `TileCondition`. ``count`` is how
        many of the bought tiles carry it; ``slot`` is the terrain art slot of
        the FIRST such tile that has condition art of its own, falling back to
        `_CARD_GROUND_SLOT` (the plain ground tile) when none of them does —
        never a grey X, the E-37 rule the construct-card portrait follows.

        Ordered by the `TileCondition` declaration order, never by scan order,
        so the same purchase always produces the same list.
        """
        tm = session.tilemap
        seen = {}
        for rep, _cost in self._unlock_chunks(session):
            for t in tm.get_chunk_for_tile(rep):
                count, slot = seen.get(t.condition, (0, None))
                # Keep looking past a ground fallback: a chunk can straddle a
                # BACKGROUND/SPAWNING tile whose condition resolves to no art
                # at all, and the card should show a sibling's real terrain.
                if slot in (None, _CARD_GROUND_SLOT):
                    slot = self._cond_slot(t)
                seen[t.condition] = (count + 1, slot)
        return [(cond, *seen[cond]) for cond in TileCondition if cond in seen]

    def _cond_slot(self, tile):
        """The art slot one tile contributes to its condition's card.

        GRASS always answers `_CARD_GROUND_SLOT`: it is the absence of a
        condition, and its `cond_grass_*` slot ships without art anyway (the
        world's own emitter skips it for the same reason), so the plain ground
        tile IS its preview. Every other condition uses the tile's resolved
        `condition_slot` — `None` on a tile whose state has no condition art at
        all (BACKGROUND / SPAWNING), which a chunk can straddle, so the caller
        keeps looking for a sibling that has art (`_cond_card_rows` prefers any
        non-ground answer) — and only if that slot is actually IMPORTED. An
        un-imported slot would otherwise blit the engine's grey X (E-37); the
        card falls back to the ground tile, exactly as the map falls back to
        its colour diamond."""
        if tile.condition == TileCondition.GRASS:
            return _CARD_GROUND_SLOT
        slot = tile.condition_slot
        return slot if slot and self._has_art(slot) else _CARD_GROUND_SLOT

    def _has_art(self, slot):
        """Is ``slot`` actually imported? The `animation_total_ms(...) is not
        None` probe `_card_portrait_slot` already uses, so the two cannot
        disagree about what "imported" means. No store ⇒ assume yes: a
        headless panel draws nothing anyway."""
        store = self.assets
        if store is None:
            return True
        return store.animation_total_ms(slot, "idle") is not None

    def _cond_sprite_size(self, slot):
        """The slot's OWN frame size — the card is sized to the sprite, never
        the sprite to the card (`HudSprite` stretches). Falls back only for a
        headless panel with no asset store."""
        store = self.assets
        if store is None or not slot:
            return _COND_CARD_SPRITE_FALLBACK
        try:
            return store.frame_size(slot)
        except KeyError:
            return _COND_CARD_SPRITE_FALLBACK

    def _cond_tile_rect(self, x, y, slot):
        """The one sprite rect a card draws, top-left at ``(x, y)``.

        Its own frame size, never scaled to fit — see `_cond_sprite_size`.
        There is no composite any more: a card draws exactly one sprite, so
        every card's preview is the same widget and a designer's override
        lands on all four the same way.
        """
        w, h = self._cond_sprite_size(slot)
        return (x, y, w, h)

    def _cond_card_column(self):
        """``(x, w)`` of the terrain card column — its GROUP's box."""
        rect = self._list_rect(_TERRAIN_LIST_ID, self._terrain_list)
        return rect[0], rect[2]

    def _cond_card_viewport(self):
        """``(top, bottom)`` of the terrain-card list — its GROUP's box.

        At full-size sprites a card is 74-138px tall, so four of them do NOT
        fit at once and this really is a scrolling window (`handle_scroll`),
        not the belt-and-braces clip it was at thumbnail sizes."""
        rect = self._list_rect(_TERRAIN_LIST_ID, self._terrain_list)
        return rect[1], rect[1] + rect[3]

    def _cond_card_in_viewport(self, rect, index=None):
        """Is this card fully inside the group's window?

        ``index`` 0 always answers True: a full-size card is 138px, so a
        designer who sizes the group under that would otherwise get an EMPTY
        list rather than a clipped one. Same argument, same answer, as
        `_cards_visible`'s `max(1, ...)` — always show the card the wheel is
        scrolled to."""
        if index == 0:
            return True
        top, bottom = self._cond_card_viewport()
        return rect[1] >= top and rect[1] + rect[3] <= bottom

    def _build_cond_cards(self, session):
        """One id'd card tree per distinct condition in the purchase.

        Same contract as the construct cards: DYNAMIC count, STABLE key. The
        key is the condition name (`cond_card_grass`, …), so every part of
        every card — body, sprite, name, count, and each of its
        `_COND_EFFECT_LINES` effect rows — is individually overridable, and a
        card whose condition is not in this purchase simply has no widget this
        frame. Laid out here, before `skinning.apply`, so a rect override wins.
        """
        self._clear_cond_card_ids()
        skin = self.skinning.defaults(self.screen_id).get("panel_skin")
        cx, cw = self._cond_card_column()
        top, _bottom = self._cond_card_viewport()
        step = _row_step("sm")
        rows = self._cond_card_rows(session)
        # The FULL row count, kept for `handle_scroll`'s clamp. It may not use
        # `len(self._cond_cards)`: that list only holds the cards from the
        # current offset down, so clamping against it shrinks the limit as you
        # scroll and a scroll past the end walks BACKWARDS.
        self._cond_row_count = len(rows)
        offset = max(0, min(self.cond_scroll_offset, max(0, len(rows) - 1)))
        self.cond_scroll_offset = offset
        y = top
        for cond, count, slot in rows[offset:]:
            lines = self._tile_cond_effect_lines(cond)
            # The sprite owns the card's top band on its own; the name + count
            # row goes UNDER it, and the effect name/value pair under that,
            # spanning the card's full inner width. The row count is the PAIR's
            # length, so a stored height never depends on a font measurement.
            n_rows = _COND_EFFECT_LINES
            # Centred horizontally: a 64px frame in a 118px card would
            # otherwise sit hard against the left edge with 51px of dead space
            # beside it.
            probe_w, _probe_h = self._cond_sprite_size(slot)
            sprite_x = cx + max(_COND_CARD_PAD, (cw - probe_w) // 2)
            sprite_rect = self._cond_tile_rect(
                sprite_x, y + _COND_CARD_PAD, slot)
            rh = sprite_rect[3]
            card_h = 2 * _COND_CARD_PAD + rh + step * (1 + n_rows)
            body = SimpleNamespace(rect=(cx, y, cw, card_h), skin=skin,
                                   visible=True)
            # The card's ONE sprite keeps the `_sprite` id it has always had,
            # so a designer's existing override still points at it — and now
            # applies to grass identically, since grass draws the plain ground
            # tile through this same widget instead of a separate `_ground`.
            sprite = SimpleNamespace(rect=sprite_rect, skin=slot, visible=True)
            name_y = y + _COND_CARD_PAD + rh
            name = label_holder((cx + _COND_CARD_PAD, name_y, 0, 0),
                                text_id="building.cond_card.name",
                                font_key="sm")
            count_lbl = label_holder(
                (cx + cw - _COND_CARD_PAD, name_y, 0, 0),
                text_id="building.cond_card.count", font_key="sm",
                align="right")
            effects = []
            effect_top = name_y + step
            for i in range(_COND_EFFECT_LINES):
                effects.append(label_holder(
                    (cx + _COND_CARD_PAD, effect_top + step * i, 0, 0),
                    font_key="sm"))
            parts = SimpleNamespace(body=body, sprite=sprite,
                                    name=name, count=count_lbl,
                                    count_value=count, effects=effects,
                                    lines=lines)
            self._cond_cards.append((cond, parts))
            key = f"{_COND_CARD_ID_PREFIX}{cond.name.lower()}"
            self.ids[key] = ("panel", body)
            self.ids[f"{key}_sprite"] = ("panel", sprite)
            self.ids[f"{key}_name"] = ("label", name)
            self.ids[f"{key}_count"] = ("label", count_lbl)
            for i, holder in enumerate(effects):
                self.ids[f"{key}_effect_{i}"] = ("label", holder)
            y += card_h + _COND_CARD_GAP

    def _clear_cond_card_ids(self):
        """Drop the last build's `cond_card_*` entries from `self.ids` — the
        `_clear_card_ids` sweep, for the other dynamic-count family. A
        condition that is no longer in the selection must not leave `apply`
        writing overrides onto a widget nothing draws."""
        for key in [k for k in self.ids
                    if k.startswith(_COND_CARD_ID_PREFIX)]:
            del self.ids[key]
        self._cond_cards = []
        self._cond_row_count = 0

    def _submit_list_group(self, renderer, holder, anim_ms=0):
        """Draw a card GROUP's container — but only once it carries a `skin`.

        Unskinned it is pure layout, so the shipped screen is byte-identical
        to before the groups existed (the golden-parity contract); a designer
        who wants a real backdrop behind the list gives the container art and
        it appears BEHIND its cards, which are submitted after it."""
        if holder.skin and is_visible(holder):
            submit_panel(renderer, holder.rect, skin=holder.skin,
                         tint=getattr(holder, "tint", None), anim_ms=anim_ms)

    def _submit_cond_cards(self, renderer, anim_ms=0):
        """Draw the terrain cards back-to-front: body, sprite, then text — the
        house order every widget tree on this panel uses (the HUD queue is
        drawn in submission order, so anything submitted later lands on top).
        """
        self._submit_list_group(renderer, self._terrain_list, anim_ms)
        for index, (cond, parts) in enumerate(self._cond_cards):
            if not self._cond_card_in_viewport(parts.body.rect, index):
                continue
            label, color = widgets.cond_label(cond.name)
            if is_visible(parts.body):
                submit_panel(renderer, parts.body.rect,
                             fill=widgets.C_PANEL_STONE, border=color,
                             skin=parts.body.skin,
                             tint=getattr(parts.body, "tint", None),
                             anim_ms=anim_ms)
            piece = parts.sprite
            if is_visible(piece) and piece.skin:
                submit_panel(renderer, piece.rect, skin=piece.skin,
                             tint=getattr(piece, "tint", None),
                             anim_ms=anim_ms)
            submit_label(renderer, parts.name, color=color, label=label)
            submit_label(renderer, parts.count, color=widgets.C_UI_TEXT_DIM,
                         count=parts.count_value)
            for holder, text in zip(parts.effects,
                                    _cond_effect_rows(parts.lines)):
                submit_label(renderer, holder, text=text,
                             color=widgets.C_UI_TEXT)

    # -- construct card: geometry, art + the two screen-level bools ---------

    def _card_defaults(self):
        """The screen's ``defaults`` section, read FRESH (no caching — the
        `defaults.button_skin` precedent). Two card-specific bools live here
        alongside the skins, both defaulting False:

        ``price_is_click_target`` — when on, ONLY the price button opens the
        construct preview; the portrait and the name go inert. Off (default),
        the whole card is the click target exactly as it always was and the
        price button is drawn but never hit-tested.

        ``use_card_portrait_slot`` — see `_card_portrait_slot`.
        """
        return self.skinning.defaults(self.screen_id)

    def _list_rect(self, list_id, holder):
        """The rect a card GROUP occupies: the designer's authored rect for
        ``list_id`` if there is one, else ``holder``'s code default.

        Read straight off the skinning rather than off the holder, because a
        list builder runs BEFORE `skinning.apply` has written the override
        onto it — the same reason `_card_column` used to read `panel` this
        way. No override (and the disk-free `ScreenSkinning.empty()` the
        exporter records with) falls back to the default, so
        `screen_defaults.json` is unchanged by this."""
        return self.skinning.widget_rect(self.screen_id, list_id)             or holder.rect

    def _card_column(self):
        """``(x, w)`` of the construct card column — its GROUP's box.

        Cards are DYNAMIC-count content: they are laid out in code and cannot
        be re-authored id-by-id in the editor the way a static widget can. The
        group container is what a designer moves instead, and the cards follow
        it here."""
        rect = self._list_rect(_CONSTRUCT_LIST_ID, self._construct_list)
        return rect[0], rect[2]

    def _card_list_viewport(self):
        """``(top, bottom)`` of the scrolling construct card list — its
        GROUP's box. Derived, never a literal, so shrinking the group in the
        editor re-windows the list instead of letting cards spill out of it."""
        rect = self._list_rect(_CONSTRUCT_LIST_ID, self._construct_list)
        return rect[1], rect[1] + rect[3]

    def _cards_visible(self):
        """How many cards fit in the viewport at once (at least 1, so a very
        short surface still shows the card the wheel is scrolled to)."""
        top, bottom = self._card_list_viewport()
        return max(1, (bottom - top) // (_CARD_H + _CARD_GAP))

    def _card_in_viewport(self, rect):
        """Is this card fully inside the scrolling list's window?

        Gated on at DRAW and at HIT, ANDed with `is_visible` — deliberately
        NOT expressed by setting `visible = False` on the off-window cards:
        `visible` is the DESIGNER's override key and forcing it here would
        fight an override. Every card is built at its absolute rect every
        frame regardless of scroll, so `self.ids` (and therefore
        `skinning.apply` and the exporter) always sees the full id set."""
        top, bottom = self._card_list_viewport()
        return rect[1] >= top and rect[1] + rect[3] <= bottom

    def _card_portrait_slot(self, btype, tier_idx):
        """The sprite slot a card's portrait panel draws.

        Default: the building's OWN tier sprite — the same
        `create(...).slot_key()` idiom `_next_tier_card` uses for the upgrade
        panel's thumbnail, so a card shows the creature that placing it
        actually spawns, with no new art to import.

        With `defaults.use_card_portrait_slot` on, it switches to the
        dedicated `card_portrait_<btype>` family instead — falling back to the
        tier sprite whenever that slot has no imported art (E-37: never a grey
        X). The "has art" probe is `animation_total_ms(slot, "idle") is not
        None`, the SAME signal `engine.vfx.spawn_play_once` uses, so the two
        can never disagree about what "imported" means."""
        tier_slot = create(btype, 0, 0, self._buildings_balance,
                           tier_idx).slot_key()
        if not self._card_defaults().get("use_card_portrait_slot"):
            return tier_slot
        slot = f"{_CARD_PORTRAIT_PREFIX}{btype}"
        store = self.assets
        if store is None:
            return tier_slot
        has_art = store.animation_total_ms(slot, "idle") is not None
        return slot if has_art else tier_slot

    def handle_scroll(self, dy):
        """Scroll the construct card list by ``dy`` cards, clamped.

        Sign follows `HighscoresScreen.scroll` (the repo's only other scroll
        seam): a POSITIVE ``dy`` moves DOWN the list. pygame's `MOUSEWHEEL.y`
        is positive scrolling UP, so the host negates it — same as the menu
        wheel arm in `main.py`. In unlock mode it scrolls the terrain
        cards instead; a no-op in every other mode.

        Rebuilds the card list, because a card's rect is ABSOLUTE and the
        offset is baked into it at build time — `open_for_tile` is otherwise
        the only thing that ever calls `_build_construct`, so without this the
        offset would move and nothing on screen would. Cheap: this runs on a
        wheel event, never per frame."""
        if self.mode == "unlock":
            # The terrain-card list scrolls on the same seam. Its cards have
            # VARIABLE height (a condition with more effect lines is taller),
            # so the offset is an INDEX into the list and `_build_cond_cards`
            # re-stacks from there — there is no uniform pitch to multiply.
            limit = max(0, self._cond_row_count - 1)
            offset = max(0, min(limit, self.cond_scroll_offset + int(dy)))
            if offset != self.cond_scroll_offset:
                self.cond_scroll_offset = offset
                self._build_cond_cards(self._session)
            return
        if self.mode != "construct":
            return
        limit = max(0, len(self.cards) - self._cards_visible())
        offset = max(0, min(limit, self.scroll_offset + int(dy)))
        if offset == self.scroll_offset:
            return
        self.scroll_offset = offset
        self._build_construct()

    def _build_construct(self):
        self._clear_card_ids()
        self.cards = []
        state = self._session.state
        # Each card is a WIDGET TREE id'd off `card_<building_type>` (see
        # `_clear_card_ids`, which sweeps all seven with that one prefix) — the
        # COUNT is dynamic (only unlocked types show), but the building type is
        # a stable key, so every part of every card is individually
        # overridable: rect, skin, tint, label, text colour, visibility.
        # `defaults.button_skin` remains the screen-level fallback for a card
        # with no `skin` override of its own — {} (no override) means None,
        # the unskinned flat-rect card the golden parity pin already covers.
        skin = self._card_defaults().get("button_skin")
        # feature-storm-acolyte-multi-build: the Storm Priest run-singleton
        # ban is LIFTED — several may be placed, each priced steeper than the
        # last via the group's `repeat_cost_multiplier`. This is the SAME
        # already-placed count `build_cost`/`place_building` use, computed
        # once for every card (a no-op price-wise for every type without the
        # multiplier key).
        repeat_count = count_tag(self._session.tilemap, LIGHTNING_SOURCE_TAG)
        cx, cw = self._card_column()
        col_x = cx + _CARD_COL_X                 # the right column's left edge
        col_w = cw - _CARD_COL_X - _CARD_PAD     # name wrap width + price width
        step = _row_step("sm")
        top, _bottom = self._card_list_viewport()
        y = top - self.scroll_offset * (_CARD_H + _CARD_GAP)
        for btype in BUILDING_CLASSES:
            if not buildable(state, btype):
                continue  # type not unlocked / tier 1 not researched (10A)
            tier_idx = tiers_unlocked_for(state, btype) - 1
            cost = build_cost(
                btype, self._buildings_balance, tier_idx, repeat_count,
                run_state=state,
                boss_upgrades_balance=self._session.boss_upgrades_balance)
            tier_name = BUILDING_CLASSES[btype]._resolve_tiers(
                self._buildings_balance)[tier_idx]["name"]
            # The card body: the parent, and (unless `price_is_click_target`
            # is on) the click target. Its own label is empty — the name is
            # its own child widget now, so a designer can place the two
            # independently.
            btn = Button((cx, y, cw, _CARD_H), "", "sm", skin=skin)
            portrait = SimpleNamespace(
                rect=(cx + _CARD_PAD, y + _CARD_PAD,
                      _CARD_PORTRAIT, _CARD_PORTRAIT),
                skin=self._card_portrait_slot(btype, tier_idx), visible=True)
            price = Button((col_x, y + _CARD_PRICE_TOP, col_w, _CARD_PRICE_H),
                           "", "sm", skin=_CARD_PRICE_SKIN)
            # Painter, every selected tile already barred (`used_painter_tiles`):
            # disable the card outright rather than let the player click through
            # to a preview that can only fail. A MIXED batch (some barred, some
            # fresh) stays enabled — placement already skips only the barred
            # tiles and builds on the rest (`_do_place`), so disabling here
            # would block placements that would actually succeed. Both click
            # targets are disabled since `price_is_click_target` picks which
            # one is live.
            if (btype == "painter" and self.selected_tiles
                    and all((t.col, t.row) in
                            getattr(state, "used_painter_tiles", ())
                            for t in self.selected_tiles)):
                btn.enabled = False
                price.enabled = False
            icon = SimpleNamespace(
                rect=(col_x + _CARD_PAD, y + _CARD_PRICE_TOP + 2,
                      _CARD_ICON, _CARD_ICON),
                skin=_CARD_LOVE_ICON, visible=True)
            price_text = label_holder(
                (col_x + _CARD_PAD + _CARD_ICON + 3, y + _CARD_PRICE_TOP + 2,
                 0, 0), text_id="building.stat.value", font_key="sm")
            # The name occupies TWO id'd rows so a designer can place them
            # independently. `cost` is passed even though the shipped template
            # no longer spends it: `T` is `str.format`, which ignores a surplus
            # kwarg but raises KeyError on a missing one — so a designer who
            # puts `{cost}` back into the name template gets the price in the
            # name block instead of a crash.
            #
            # The WRAP itself is deliberately NOT done here. `wrap_text`
            # measures the live font, and this text is recorded into
            # `data/ui/screen_defaults.json`'s `label` — a stored artifact,
            # which `game/ui/CLAUDE.md`'s "layout_h, never a live font
            # measurement" rule forbids from depending on a measurement
            # (Windows and Linux/CI disagree by a pixel, and a bigger font
            # preset must not re-break the lines in a committed file). So the
            # holder stores the WHOLE name and `_submit_construct` wraps it at
            # DRAW time, where a live metric is allowed. Row 2's stored label
            # is always empty for the same reason.
            name = T("building.construct.card", name=tier_name, cost=cost)
            name_1 = label_holder((col_x, y + 2, 0, 0), label=name,
                                  font_key="sm")
            # `_name2`, NOT `_name_2`: the exporter derives a card child's
            # parent from its id prefix, and `card_x_name_2` would nest under
            # `card_x_name` instead of sitting beside it as a sibling row.
            name_2 = label_holder((col_x, y + 2 + step, 0, 0), font_key="sm")
            self.cards.append((btype, btn))
            self._card_parts[btype] = SimpleNamespace(
                portrait=portrait, price=price, icon=icon,
                price_text=price_text, name_1=name_1, name_2=name_2,
                name_w=col_w, cost=cost)
            key = f"{_CARD_ID_PREFIX}{btype}"
            self.ids[key] = ("button", btn)
            self.ids[f"{key}_portrait"] = ("panel", portrait)
            self.ids[f"{key}_name"] = ("label", name_1)
            self.ids[f"{key}_name2"] = ("label", name_2)
            self.ids[f"{key}_price"] = ("button", price)
            self.ids[f"{key}_price_icon"] = ("panel", icon)
            self.ids[f"{key}_price_text"] = ("label", price_text)
            y += _CARD_H + _CARD_GAP
        # The construct panel's own selected tile(s) — the SELECTION
        # highlight, not a batch (see the note at the upgrade-batch site).
        self._highlight_tiles = [(t.col, t.row, "tile_selected")
                                 for t in self.selected_tiles]
        # Grey out every BUILDABLE tile that already hosted a Painter and
        # paid out (`state.used_painter_tiles`) — visible only while this
        # construct panel is open, so the player understands, right when
        # they're picking where to build, why a Painter can't go there again
        # (`place_building`'s enforcement, `game/buildings/registry.py`).
        tm = self._session.tilemap
        self._painter_used_tiles = [
            (col, row) for col, row in getattr(state, "used_painter_tiles", ())
            if (t := tm.get(col, row)) is not None
            and t.state == TileState.BUILDABLE]
        # The footer badge + effect box, laid out here (before apply) so a
        # designer's rect override wins — see `_layout_cond_box`.
        self._layout_cond_box(self.tile.condition, self.view_h - 20,
                              above=True)

    def _clear_card_ids(self):
        """Drop last build's `card_*` entries from `self.ids`.

        Unlike every other id in this panel, a card's Button is rebuilt on
        every `_build_construct` (its label carries a live price), so its ids
        entry would otherwise point at a dead Button — `skinning.apply` would
        keep writing overrides onto an object nothing draws, and a type that
        stopped being buildable would linger in the dict forever.

        The card is a widget TREE now — portrait, two name rows, price button,
        love icon, price text — but every one of its ids starts with the same
        `card_` prefix, so this sweep needed no change to cover them."""
        for key in [k for k in self.ids if k.startswith(_CARD_ID_PREFIX)]:
            del self.ids[key]
        self._card_parts = {}

    def _batch_upgrade_targets(self):
        """``[(building, cost)]`` across the selection whose upgrade state is
        ``in_tier`` (prototype building_ui.py:767-791). A single selection is
        a 1-batch."""
        out = []
        for t in self.selected_tiles:
            b = t.occupant
            if b is None or getattr(b, "building_type", None) == "base":
                continue
            mode, cost, _, _ = self._upgrade_state(b)
            if mode == "in_tier" and cost > 0:
                out.append((b, cost))
        return out

    def _batch_advance_targets(self):
        """``[(building, cost, levels_needed)]`` across a multi-selection
        whose next tier is reachable right now (``game.core.levelup.
        advance_batch_plan``) — a building that can never get there no
        matter how much love is spent (already at the final tier, next tier
        unresearched, or round-gated) is excluded. Empty for a single
        selection: ``_upgrade_click``'s primary-only ADVANCE path covers
        that case unchanged."""
        if len(self.selected_tiles) <= 1:
            return []
        out = []
        for t in self.selected_tiles:
            b = t.occupant
            if b is None or getattr(b, "building_type", None) == "base":
                continue
            eligible, cost, levels_needed = advance_batch_plan(
                self._session.state, b, self._buildings_balance,
                self._session.progression_balance,
                self._session.boss_upgrades_balance)  # BU-3 #2
            if eligible:
                out.append((b, cost, levels_needed))
        return out

    def _build_upgrade(self):
        mode, cost, label, hint = self._upgrade_state(self._selected)
        if len(self.selected_tiles) > 1:
            # Two-stage batch flow (catch-up-then-advance): Stage A always
            # wins while ANY selected building hasn't reached level 3 yet —
            # swept across the WHOLE selection, not gated on the primary
            # tile's own mode, so a primary that's itself blocked (tier
            # maxed but unresearched, or at its final tier) no longer greys
            # out a batch that other selected buildings could still take.
            # Only once nothing needs catching up does Stage B (ADVANCE) run.
            upgrade_targets = self._batch_upgrade_targets()
            if upgrade_targets:
                cost = sum(c for _, c in upgrade_targets)
                mode = "in_tier"
                label = T("building.action.upgrade_many",
                          n=len(upgrade_targets), cost=cost)
                hint = None
            else:
                advance_targets = self._batch_advance_targets()
                if advance_targets:
                    # Every selected building is already at level 3 — advance
                    # whichever can reach their next tier right now; a
                    # building that still can't (final tier / unresearched /
                    # round-gated) is left sitting at level 3, untouched.
                    cost = sum(c for _, c, _ in advance_targets)
                    mode = "tier_upgrade"
                    label = f"ADVANCE ×{len(advance_targets)}  {cost}"
                    hint = None
        self.action_btn.rect = (
            self.panel_x + 6, self.view_h - 60, self.panel_w - 12, 18)
        self.action_btn.enabled = mode in ("in_tier", "tier_upgrade")
        self.action_btn.label = label
        self._action_cost = cost if self.action_btn.enabled else 0
        self._upgrade_hint = hint
        self._layout_upgrade_rows()
        self._layout_cond_box(
            getattr(self._selected, "_tile_condition", None)
            or TileCondition.GRASS, 45, above=False)
        self._build_move_btn()
        self._build_colour_row()   # MasterSheetColumnsPLAN B3

    def _layout_upgrade_rows(self):
        """Stack the upgrade panel's text rows for the SELECTED building.

        Runs from ``_build_upgrade`` — i.e. before any ``submit()``, and
        therefore before ``skinning.apply`` — which is what makes a designer's
        rect override win: this writes the DEFAULT anchor, `apply` then
        replaces it for whichever rows carry one. The rows below an overridden
        one keep their own defaults (the no-cascade convention).

        Only the shown subset is stacked; a stat this building does not have
        keeps its canonical-order anchor from ``_build_text_holders`` so the
        exporter still records a real position for its two ids.
        """
        b = self._selected
        if b is None:
            return
        md, sm = _row_step("md"), _row_step("sm")
        y = _STAT_BLOCK_TOP
        for key, _value in _building_stats(b):
            for holder in self._stat_rows[key]:
                holder.rect = (holder.rect[0], y, 0, 0)
            y += md
        rs = b.get_component(RoundStats)
        if rs is not None:
            # Gated exactly like the draw: a building with no RoundStats never
            # drew these rows, so advancing past them would push the next-tier
            # card down for every economy building.
            y += 5
            for name in ("dmg_dealt", "dmg_taken"):
                for suffix in ("label", "value"):
                    h = self._text[f"{name}_{suffix}"]
                    h.rect = (h.rect[0], y, 0, 0)
                y += sm
            died = self._text["died_last_round"]
            died.rect = (died.rect[0], y, 0, 0)
            if rs.dmg_taken_last_round >= b.max_hp():
                y += sm
        #: where the next-tier card starts — read by ``_submit_upgrade``.
        self._stats_bottom = y

    def _build_move_btn(self):
        """Position + gate the MOVE BUILDING button (Building Movement).

        Visible only in upgrade mode on a SINGLE selection — a move is not
        batchable (unlike UPGRADE/ADVANCE, which do batch — see
        ``_build_upgrade``). A Wall Builder can never be moved, so its button
        is shown DISABLED with a hint (the ``_upgrade_hint`` mechanism the
        RESEARCH REQUIRED / NEXT TIER LOCKED states use) rather than
        silently vanishing — the real enforcement is ``start_move``."""
        ax, ay, aw, ah = self.action_btn.rect
        self.move_btn.rect = (ax, ay + ah + 4, aw, 15)
        self.move_btn.visible = len(self.selected_tiles) == 1
        movable = self._selected is not None and is_movable(self._selected)
        self.move_btn.enabled = movable
        if not movable and self.move_btn.visible:
            self.move_btn.label = T("building.btn.move_blocked")
            if not self._upgrade_hint:
                self._upgrade_hint = T("building.hint.wall_rooted")
        else:
            self.move_btn.label = T("building.btn.move")

    def _clear_colour_ids(self):
        """Drop the last build's `upgrade_swatch_*` entries and make the row
        inert (MasterSheetColumnsPLAN B3).

        The `_clear_card_ids` rule, for the same reason: the swatch count is
        dynamic and every swatch Button is rebuilt per selection, so an id left
        pointing at a dead Button would have `skinning.apply` writing overrides
        onto an object nothing draws — and a building with no colour-capable
        art would keep the previous selection's ids forever."""
        for key in [k for k in self.ids
                    if k.startswith(_UPGRADE_COLOR_PREFIX)]:
            del self.ids[key]
        self.colour_row = ColorSwatchRow((), 0, 0, 0, _UPGRADE_COLOR_PREFIX)

    def _build_colour_row(self):
        """Build the upgrade panel's colour-swatch row (B3), or leave it inert.

        THE SAME `ColorSwatchRow` B2's build-confirm modal uses — this panel
        only points it at a different selection source (the LIVE building's
        `BuildingSprite.column`) and a different band.

        Shown only when ALL of these hold (D6). A building on placeholder or
        single-column art shows nothing at all — no row, no gap, no
        placeholder — and never raises:
          * upgrade mode on a SINGLE selection (the `move_btn` rule: recolouring
            a batch is not a feature this phase adds);
          * the host wired a capability map (`colour_columns`, derived once at
            boot by `game/main.py`; `{}` in tests/tools/the layout exporter
            means "no colours" and is the quiet default);
          * that map names >= 2 colours for THIS building's live slot key — one
            colour is not a choice, the same gate `ConstructPreview` applies.

        Vertical band, the ONE piece of dead space the upgrade panel has, all
        of it derived from `action_btn.rect` so nothing already on the panel
        moves (which is what keeps `data/ui/screen_defaults.json` a no-op):
            stat column worst case bottom .......... y = 268 (_submit_upgrade)
            THE SWATCH ROW ......................... y = 282..293 (SIZE 12)
            action_btn top = view_h - 60 ........... y = 300 (6px clear)
            move_btn, then the upgrade hint ........ y = 322+ (unchanged)
        12px is the UR-5 click-target floor exactly (`ColorSwatchRow.SIZE`),
        and the row is right-aligned into the panel's inner width, where the
        helper's own clamp keeps the first `(118 + 2) // 14 = 8` colours."""
        self._clear_colour_ids()
        b = self._selected
        if b is None or len(self.selected_tiles) != 1:
            return
        # The LIVE animator's slot key, not `b.slot_key()`: it is the key the
        # host's map is built on (`registry.place_building` stamps the column
        # off `anim.slot_key`), and `get_component` is None on the base
        # building, which carries no animator at all. The sanctioned
        # `game/ui -> game.buildings.components` read.
        anim = b.get_component(BuildingSprite)
        if anim is None:
            return
        names = (self.colour_columns or {}).get(anim.slot_key, ())
        if len(names) < 2:
            return
        ax, ay, aw, _ah = self.action_btn.rect
        self.colour_row = ColorSwatchRow(
            names, ax, ax + aw,
            ay - ColorSwatchRow.SIZE - _COLOUR_ROW_GAP,
            _UPGRADE_COLOR_PREFIX, ui_balance=self._ui_balance)
        # Merged BEFORE `skinning.apply` (which runs at submit), so a designer
        # override can style/move an individual swatch — the ConstructPreview
        # rule.
        self.ids.update(self.colour_row.ids)

    def _selected_column(self):
        """The live building's colour column, or None when it has no driver.

        `-1` is `SpriteAnimator`'s "no driver" SENTINEL and `0` is a REAL
        colour index, so this is a `>= 0` test and never a truth test."""
        b = self._selected
        anim = b.get_component(BuildingSprite) if b is not None else None
        if anim is None or anim.column < 0:
            return None
        return anim.column

    def _build_move_select(self, session):
        """Highlight every legal move destination: an unbuilt BUILDABLE tile
        that is not already an endpoint of a move in progress."""
        self._highlight_edges = []
        self._highlight_tiles = [
            (t.col, t.row, "move_target")
            for t in session.tilemap.buildable_tiles()
            if not session.tilemap.is_moving(t.col, t.row)]

    def _upgrade_state(self, b):
        """``(mode, cost, button_label, hint)`` — the five-mode research gate
        (``game.core.levelup.upgrade_gate``). ``cost`` is only a love price for
        the two enabled modes; for ``tier_hidden`` it carries the village_level
        it unlocks at (TimelinePLAN D5 — always exactly true), or ``None`` if
        it has no Timeline placement at all."""
        mode, next_name, cost = upgrade_gate(
            self._session.state, b, self._buildings_balance,
            self._session.progression_balance,
            self._session.boss_upgrades_balance)  # BU-3 #2 wall_cost_discount
        if mode == "in_tier":
            return mode, cost, T("building.action.upgrade", cost=cost), None
        if mode == "tier_upgrade":
            return mode, cost, T("building.action.advance",
                                 name=next_name.upper(), cost=cost), None
        if mode == "tier_locked":
            return (mode, cost, T("building.action.research"),
                    T("building.hint.research"))
        if mode == "tier_hidden":
            # cost is the unlocking village_level, or None when the tier has
            # no Timeline placement at all (TimelinePLAN D5).
            hint = (T("building.hint.tier_locked", round=cost)
                    if cost is not None else T("building.hint.tier_unoffered"))
            return mode, cost, T("building.action.tier_locked"), hint
        return mode, 0, T("building.action.max_tier"), None

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
        hl = [(b.col, b.row, "tile_selected")]
        # 10I: the selection highlight shows the EFFECTIVE (mountain-boosted)
        # range — a consumption site of the effective value (prototype
        # game.py:578-581); pathfinding coverage stays on the raw range.
        # `range_shape()` picks the tile-offset geometry (defaults to the
        # Chebyshev square when absent — every defence building; a booster
        # defines it, `game/buildings/boost.py`).
        rfn = getattr(b, "effective_range_tiles",
                      getattr(b, "range_tiles", None))
        if rfn is not None:
            r = int(rfn())
            shape = getattr(b, "range_shape", lambda: "square")()
            for dc, dr in range_shape.offsets(r, shape):
                if tilemap.get(b.col + dc, b.row + dr) is not None:
                    hl.append((b.col + dc, b.row + dr, "attack_range"))
        self._highlight_tiles = hl

    def _set_wall_highlight(self, b, tilemap):
        """Highlight every edge wall ``b`` owns: its walled TILES join the
        range highlight, and each actual EDGE gets a thick line.

        **Gated on OWNERSHIP, not on type** — the walk asks
        ``edge.owner is b``, so a building that owns no edges yields nothing
        and no ``building_type == "wall_builder"`` check is needed. That is
        the repo's G-3 type-agnostic discipline: a future wall-owning
        building type gets this highlight for free, with no edit here.

        Called right after ``_set_range_highlight``, which REPLACES
        ``_highlight_tiles`` wholesale — so this APPENDS to that freshly-built
        list, and resets ``_highlight_edges`` itself first to stay safe to
        call repeatedly.
        """
        self._highlight_edges = []
        for edge in getattr(tilemap, "wall_edges", {}).values():
            if edge.owner is not b:
                continue
            self._highlight_tiles.append(
                (edge.col_a, edge.row_a, "attack_range"))
            pts = edge_world_points(edge.col_a, edge.row_a,
                                    edge.col_b, edge.row_b)
            if pts is None:
                continue          # not a 4-adjacent pair: no edge to draw
            self._highlight_edges.append(pts)

    # -- input ------------------------------------------------------------

    def hover(self, mx, my, mouse_down=False):
        self._hover_cost = None
        # -- 10I: terrain badge hover (rect inflated 2px, prototype
        # building_ui.py:1121-1130); off while the modal preview is open --
        r = self._cond_badge_rect
        self._cond_hover = (
            self.preview is None and r is not None
            and contains((r[0] - 2, r[1] - 2, r[2] + 4, r[3] + 4), mx, my))
        # -- /10I --
        if self.preview is not None:
            self.preview.hover(mx, my, mouse_down)
            # feature: move-building-time-only-cost — a MovePreview's cost is
            # ROUNDS, not love (`money_cost_enabled` ships `false`), so
            # hovering its CONFIRM must NOT preview a love spend against the
            # HUD's top-left pill the way every other preview's confirm does;
            # `_hover_cost` stays `None` and `hud.py`'s pill draws normally.
            if (self.preview.confirm_hovered()
                    and not isinstance(self.preview, MovePreview)):
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
                parts = self._card_parts.get(btype)
                on_screen = self._card_in_viewport(btn.rect)
                btn.hover(mx, my, mouse_down)
                # Never skip hover() outright — a stale True from before an
                # override hid the card would otherwise linger (the rule every
                # id'd button in this file follows). A card scrolled out of
                # the list window is cleared the same way.
                btn.hovered = btn.hovered and is_visible(btn) and on_screen
                if parts is not None:
                    # The price pill lights up with its card whether or not it
                    # is the click target — it is part of one card, and a
                    # half-lit card reads as broken.
                    parts.price.hover(mx, my, mouse_down)
                    parts.price.hovered = (parts.price.hovered
                                           and is_visible(parts.price)
                                           and on_screen)
                if btn.hovered or (parts is not None and parts.price.hovered):
                    tier_idx = tiers_unlocked_for(state, btype) - 1
                    self._hover_cost = _batch_cost(
                        btype, self._buildings_balance, tier_idx,
                        repeat_count, count, state,
                        self._session.boss_upgrades_balance)
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
                # Building Movement: the MOVE BUILDING button. No hover cost —
                # the price depends on the destination, which isn't picked yet.
                self.move_btn.hover(mx, my, mouse_down)
                self.move_btn.hovered = (self.move_btn.hovered
                                         and is_visible(self.move_btn))
                # B3: the colour swatches. A no-op when the row is inert, and
                # it carries the same `is_visible` guard internally.
                self.colour_row.hover(mx, my, mouse_down)
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
                if px + 7 <= mx < px + pw - 7 and my >= py + 24:
                    # SAME step _submit_boss_popup draws with — the hit test
                    # and the draw must never disagree about a row's height.
                    self._boss_hover_row = (my - (py + 24)) // _row_step("md")
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
        # -- UL-10: a clickable layer on THIS panel's own widgets. Consulted
        # after the explicit close (so a stray layer can never reinterpret an
        # X click) and before the mode dispatch. This screen's return contract
        # is bool-consumed, not an action string, and it has no single flat
        # action table spanning its three classes — so only the three RESERVED
        # tokens route here, and every other target (including a widget id in
        # this screen) swallows per Ruling 1. Widget-id RETARGET on the
        # building panel is a deliberate follow-up, not silent scope loss. --
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of)
        if layer_action is not None:
            if layer_action == "close_window":
                self.close()
            elif layer_action == "back" and self.mode == "move_select":
                self._back_to_upgrade(session)
            return True   # "noop"/"back"-with-nowhere-to-go still CONSUME
        # -- /UL-10 --
        if self.mode == "unlock":
            return self._unlock_click(mx, my, session)
        if self.mode == "construct":
            return self._construct_click(mx, my, session, buildings_balance)
        if self.mode == "upgrade":
            return self._upgrade_click(mx, my, session)
        if self.mode == "move_select":
            return self._move_select_click(mx, my, session)
        if self.mode == "base_info":
            return self._base_info_click(mx, my, session)
        return contains(self.panel_rect, mx, my)  # consume inside the panel

    def _move_select_click(self, mx, my, session):
        """Building Movement: while picking a destination the panel only has to
        handle clicks INSIDE itself — a click on the world is the tile pick and
        is `game/main.py`'s job. Anything inside the panel (the close button
        already handled above) cancels back to upgrade mode."""
        if contains(self.panel_rect, mx, my):
            self._back_to_upgrade(session)
            return True
        return False

    def _back_to_upgrade(self, session):
        """Leave move-select and restore the ordinary upgrade view — the same
        rebuild + highlight restore ``open_for_tile``'s upgrade branch does."""
        self.mode = "upgrade"
        self.preview = None
        self._build_upgrade()
        if self._selected is not None and session is not None:
            self._set_range_highlight(self._selected, session.tilemap)
            self._set_wall_highlight(self._selected, session.tilemap)

    def _unlock_click(self, mx, my, session):
        if is_visible(self.action_btn) and self.action_btn.hit(mx, my):
            tm, st = session.tilemap, session.state
            chunks = self._unlock_chunks(session)  # re-check live (10J batch)
            cost = sum(c for _, c in chunks)
            if not all(tm.can_unlock(t) for t, _ in chunks):
                self.action_btn.start_flash(self._flash_dur,
                                            T("building.action.not_adjacent"))
                if self.log is not None:
                    self.log.post(
                        T("building.log.unlock_refused"))
            elif st.love < cost:
                self.action_btn.start_flash(self._flash_dur,
                                        T("building.flash.not_enough_love"))
            else:
                unlocked_any = False
                for tile, chunk_cost in chunks:
                    if tm.do_unlock(tile):
                        st.spend_love(chunk_cost)
                        # BossUpgradeTimelinePLAN BU-3 3.1: the accumulator
                        # boss upgrade #12 (`tile_refund`) pays back. It is
                        # incremented HERE, beside the spend and with the SAME
                        # number, because this is the one place love actually
                        # leaves the player's pocket for a tile — the price
                        # `_unlock_chunks` quotes has already been through
                        # `TileMap.unlock_cost`'s own #6 `tile_discount`, so
                        # the refund pays back what was charged, never the
                        # undiscounted list price.
                        st.love_spent_on_tiles += chunk_cost
                        unlocked_any = True
                self.close()
                self.last_unlocked = unlocked_any  # TU-6: signal a real unlock
            return True
        return contains(self.panel_rect, mx, my)

    def _construct_click(self, mx, my, session, buildings_balance):
        # `defaults.price_is_click_target` picks WHICH rect opens the preview:
        # off (the default) the whole card does, exactly as it always has; on,
        # only the price pill does and the portrait/name go inert. Nothing
        # downstream of the hit changes — same cost, same batch total, same
        # ConstructPreview.
        price_clicks = bool(self._card_defaults().get("price_is_click_target"))
        for btype, btn in self.cards:
            parts = self._card_parts.get(btype)
            if price_clicks:
                target = parts.price if parts is not None else None
            else:
                target = btn
            if (target is not None and is_visible(target)
                    and self._card_in_viewport(btn.rect)
                    and target.hit(mx, my)):
                tier_idx = tiers_unlocked_for(session.state, btype) - 1
                # feature-storm-acolyte-multi-build: the same already-placed
                # count `_build_construct` priced the card off.
                repeat_count = count_tag(session.tilemap, LIGHTNING_SOURCE_TAG)
                # BU-3: the standard optional trailing pair, off the Session.
                bub = session.boss_upgrades_balance
                cost = build_cost(btype, buildings_balance, tier_idx,
                                  repeat_count, run_state=session.state,
                                  boss_upgrades_balance=bub)
                count = max(1, len(self.selected_tiles))
                # 10J batch: the whole batch must be affordable up front
                # (prototype building_ui.py:704-708) — the ESCALATING total,
                # not a flat cost x count, so this gate agrees with what
                # ConstructPreview.total_cost/_do_place will actually charge.
                total = _batch_cost(btype, buildings_balance, tier_idx,
                                    repeat_count, count, session.state, bub)
                if session.state.love < total:
                    # Always flash the CARD, never the price pill, whichever
                    # was clicked: the message is a sentence and the card body
                    # is the only part of the tree wide enough to read it.
                    btn.start_flash(self._flash_dur,
                                        T("building.flash.not_enough_love"))
                else:
                    self.preview = ConstructPreview(
                        btype, cost, buildings_balance, self._ui_balance,
                        self.view_w, self.view_h, count=count, tier_idx=tier_idx,
                        repeat_count=repeat_count, skinning=self.skinning,
                        building_colors=self.colour_columns,  # B2
                        run_state=session.state,             # BU-3 #2
                        boss_upgrades_balance=bub)
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
        # MasterSheetColumnsPLAN B3: a colour swatch recolours the LIVE
        # building immediately — the index the click writes IS the column the
        # renderer reads, so the board updates next frame with no confirm step,
        # nothing spent and nothing logged. Sits AFTER the rename defocus above
        # (so a swatch click commits an in-progress rename exactly like a move
        # click does) and BEFORE `move_btn`, whose rect it never overlaps.
        # `0` is a real colour, so the miss test is `is not None`.
        idx = self.colour_row.hit(mx, my)
        if idx is not None:
            anim = b.get_component(BuildingSprite) if b is not None else None
            if anim is not None:
                anim.column = idx
            return True
        # Building Movement: enter destination-picking mode. The tile pick
        # itself happens in `game/main.py` (the panel only ever sees
        # panel-space clicks); this just arms the mode + the highlight set.
        if (is_visible(self.move_btn) and self.move_btn.enabled
                and self.move_btn.hit(mx, my)):
            self.mode = "move_select"
            self._upgrade_hint = None
            self._build_move_select(session)
            return True
        if is_visible(self.action_btn) and self.action_btn.hit(mx, my):
            mode, cost, _, _ = self._upgrade_state(b)
            # Two-stage batch flow (catch-up-then-advance), multi-select
            # only — mirrors `_build_upgrade`'s priority: Stage A (catch up
            # to level 3) always wins over Stage B (advance) while anything
            # in the selection still needs it, swept across the WHOLE
            # selection rather than gated on the primary tile's own mode.
            upgrade_targets, advance_targets = [], []
            if len(self.selected_tiles) > 1:
                upgrade_targets = self._batch_upgrade_targets()
                if not upgrade_targets:
                    advance_targets = self._batch_advance_targets()
            if upgrade_targets:
                # Stage A: every selected building below level 3 levels up
                # one step, one combined cost. Covers both the old plain
                # in-tier batch and the case that used to grey the button
                # out (a blocked primary alongside a still-catching-up
                # building).
                total = sum(c for _, c in upgrade_targets)
                if st.love < total:
                    self.action_btn.start_flash(self._flash_dur,
                                                T("building.flash.not_enough_love"))
                    return True
                st.spend_love(total)
                for tb, _c in upgrade_targets:
                    tb.upgrade()
                    sync_wall_art_era(st, tb, session.enemies_balance)  # wall-era-art
                    if self.on_build_vfx is not None:
                        lvl = tb.get_component(TierState).current_level_in_tier
                        self.on_build_vfx(tb.col, tb.row,
                                          "level1" if lvl == 2 else "level2")
            elif advance_targets:
                # Stage B: every selected building already at level 3 —
                # advance whichever can reach their next tier now, one
                # combined all-or-nothing cost. Buildings that can't get
                # there yet (max tier / unresearched / round-gated) are
                # excluded by `_batch_advance_targets` and untouched here.
                total = sum(c for _, c, _ in advance_targets)
                if st.love < total:
                    self.action_btn.start_flash(self._flash_dur,
                                                "NOT ENOUGH LOVE")
                    return True
                st.spend_love(total)
                for tb, c, levels_needed in advance_targets:
                    for _ in range(levels_needed):
                        tb.upgrade()
                    tb.advance_tier()
                    lightning.sync_level_from_tier(st, tb)  # Storm Priest wiring
                    sync_wall_art_era(st, tb, session.enemies_balance)  # wall-era-art
                    if session.debug is not None:
                        session.debug.note_love_spent(c, dbg.SPEND_RESEARCH)
                        session.debug.emit(
                            dbg.RESEARCH, building_type=tb.building_type,
                            tier=tb.get_component(TierState).current_tier,
                            cost=c)
                    if self.on_build_vfx is not None:
                        self.on_build_vfx(tb.col, tb.row, "tier")
            elif mode not in ("in_tier", "tier_upgrade"):
                return True  # max / not researched / round-gated: inert
            elif mode == "tier_upgrade":
                # Single-selection tier advance (a multi-select is handled
                # by `advance_targets` above).
                if st.love < cost:
                    self.action_btn.start_flash(self._flash_dur,
                                                T("building.flash.not_enough_love"))
                    return True
                st.spend_love(cost)
                b.advance_tier()
                lightning.sync_level_from_tier(st, b)  # Storm Priest wiring
                sync_wall_art_era(st, b, session.enemies_balance)  # wall-era-art
                if session.debug is not None:
                    session.debug.note_love_spent(cost, dbg.SPEND_RESEARCH)
                    session.debug.emit(
                        dbg.RESEARCH, building_type=b.building_type,
                        tier=b.get_component(TierState).current_tier,
                        cost=cost)
                if self.on_build_vfx is not None:
                    self.on_build_vfx(b.col, b.row, "tier")
            else:
                # Single-selection in-tier upgrade (a multi-select is
                # handled by `upgrade_targets` above; `_batch_upgrade_targets`
                # naturally returns a 1-item list here).
                targets = self._batch_upgrade_targets()
                total = sum(c for _, c in targets)
                if st.love < total:
                    self.action_btn.start_flash(self._flash_dur,
                                                T("building.flash.not_enough_love"))
                    return True
                st.spend_love(total)
                for tb, _c in targets:
                    tb.upgrade()
                    sync_wall_art_era(st, tb, session.enemies_balance)  # wall-era-art
                    if self.on_build_vfx is not None:
                        lvl = tb.get_component(TierState).current_level_in_tier
                        self.on_build_vfx(tb.col, tb.row,
                                          "level1" if lvl == 2 else "level2")
            self._build_upgrade()
            if len(self.selected_tiles) == 1:
                self._set_range_highlight(b, session.tilemap)
                self._set_wall_highlight(b, session.tilemap)
            return True
        return contains(self.panel_rect, mx, my)

    def _preview_click(self, mx, my, session, buildings_balance, scene,
                       occupancy):
        action = self.preview.handle_click(mx, my)
        if action == "confirm":
            if isinstance(self.preview, MovePreview):
                self._do_move(session, buildings_balance, scene, occupancy)
            else:
                self._do_place(session, buildings_balance, scene, occupancy)
        elif action in ("cancel", "close"):
            # Cancelling a MovePreview leaves `mode == "move_select"` on
            # purpose: nothing has moved yet, so the player drops straight
            # back to picking a different destination — the same "cancel undoes
            # the modal, not the mode" reading `_construct_click`'s cancel has
            # (it returns to the construct card list, not to a closed panel).
            self.preview = None
        return True  # modal consumes every click

    def _do_move(self, session, buildings_balance, scene, occupancy):
        """Confirm a MovePreview (Building Movement) — the ``_do_place``
        shape. ``start_move`` is the enforcement point; everything here is the
        love spend + the panel reset."""
        p, st = self.preview, session.state
        if st.love < p.cost:
            p.confirm_btn.start_flash(self._flash_dur,
                                        T("building.flash.not_enough_love"))
            return
        try:
            cost, rounds = start_move(
                session.tilemap, self._selected, p.dest_tile,
                buildings_balance["BuildingsGlobal"]["Movement"], st.love,
                occupancy, scene,
                # BU-3 #4 move_time_cap: the same pair `_pick_move_destination`
                # quoted the modal's round count with, so the rounds charged
                # here can never exceed the capped figure shown.
                run_state=st,
                boss_upgrades_balance=session.boss_upgrades_balance)
        except MoveError:
            # A race since the modal opened (the destination got built on, or
            # another move claimed it) — flash and leave the player in
            # move_select to pick again.
            p.confirm_btn.start_flash(self._flash_dur,
                                            T("building.flash.cannot_move"))
            return
        st.spend_love(cost)
        if self.log is not None:
            self.log.post(T("building.log.moved") if rounds == 0
                          else T("building.log.moving", rounds=rounds))
        self.preview = None
        # The building has vacated its tile, so there is nothing left to show
        # for it here — close outright, exactly as the panel does when a
        # painter's tile frees itself.
        self.close()

    def _do_place(self, session, buildings_balance, scene, occupancy):
        """Place on every selected tile (10J batch; single tile = a 1-batch).
        The chosen name applies to the FIRST tile only (prototype
        building_ui.py:591-619); a tile that fails placement is skipped."""
        p, st = self.preview, session.state
        if st.love < p.total_cost:
            p.confirm_btn.start_flash(self._flash_dur,
                                        T("building.flash.not_enough_love"))
            return
        placed_any = False
        painter_blocked = True  # stays True only if EVERY tile hit the bar
        for i, tile in enumerate(self.selected_tiles or [self.tile]):
            try:
                building, cost = place_building(
                    session.tilemap, tile, p.building_type, st.love,
                    buildings_balance, scene, occupancy, state=st,
                    # B2: the capability map AND the modal's own pick. The
                    # pick is rolled when the modal opens and shown there, so
                    # `column=` is what makes the placed building match the
                    # preview — every tile of the batch gets the same colour.
                    # `None` (a slot with no colours) falls through to B1's
                    # own path, which leaves the -1 "no driver" sentinel;
                    # `0` is a real colour and must never be read as "unset".
                    colour_columns=self.colour_columns,
                    column=getattr(p, "chosen_column", None),
                    # BU-3: `state=st` above is already the RunState half of
                    # the pair; this is the other half (#2 wall_cost_discount
                    # on the charged price, #5 musician_auto_level).
                    boss_upgrades_balance=session.boss_upgrades_balance)
            except PlacementError:
                if not (p.building_type == "painter"
                        and (tile.col, tile.row) in
                        getattr(st, "used_painter_tiles", ())):
                    painter_blocked = False
                continue
            painter_blocked = False
            st.spend_love(cost)
            st.buildings_placed += 1
            placed_any = True
            lightning.unlock_from_placement(st, building)  # Storm Priest wiring
            sync_wall_art_era(st, building, session.enemies_balance)  # wall-era-art
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
            msg = (T("building.flash.painter_tile_used") if painter_blocked
                   else T("building.flash.not_enough_love"))
            p.confirm_btn.start_flash(self._flash_dur, msg)
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
        self.move_btn.update(dt)          # Building Movement
        self.colour_row.update(dt)        # B3 (a no-op when inert)
        self._dice_up.update(dt)  # 10J rename dice
        self.boss_btn.update(dt)          # -- 10G boss --
        self._boss_close_btn.update(dt)   # -- 10G boss --
        for btype, btn in self.cards:
            btn.update(dt)
            parts = self._card_parts.get(btype)
            if parts is not None:
                parts.price.update(dt)   # its own hover/flash clock
        if self.preview is not None:
            self.preview.update(dt)

    def submit(self, renderer, session):
        t = anim_ms(self._clock)
        for col, row, event in self._highlight_tiles:
            widgets.submit_highlight(renderer, event, col, row,
                                     assets=self.assets, anim_time_ms=t)
        for col, row in self._painter_used_tiles:
            submit_tile_diamond_fill(
                renderer, col, row,
                (*widgets.C_PAINTER_USED, _PAINTER_USED_ALPHA))
        # Each selected wall builder's actual EDGES, as thick world-space
        # lines. Sits BEFORE the `visible` guard exactly like the tile
        # diamonds above it, so the two behave identically.
        for pts in self._highlight_edges:
            renderer.submit_overlay_lines(
                pts, widgets.highlight_color("wall_edge"),
                width=widgets.highlight_params("wall_edge")["border_width"])
        # Building Movement: the straight-line (Manhattan) path to the picked
        # destination, shown once a destination is chosen — L-shaped
        # (col-first, then row), matching the tiles move_distance() actually
        # counts. Derived fresh from the live preview every frame (no stored
        # state, no fade clock); sits before the `visible` guard like the
        # highlights above it, so it behaves identically.
        if isinstance(self.preview, MovePreview):
            b, dest = self.preview.building, self.preview.dest_tile
            path_pts = [(b.col + 0.5, b.row + 0.5),
                        (dest.col + 0.5, b.row + 0.5),
                        (dest.col + 0.5, dest.row + 0.5)]
            renderer.submit_overlay_lines(path_pts,
                                     widgets.highlight_color("move_target"),
                                          width=3)
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
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
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
        elif self.mode == "move_select":
            self._submit_move_select(renderer, t)
        elif self.mode == "base_info":
            self._submit_base_info(renderer, session, t)
        # -- 10I: the hovered terrain tooltip draws LAST, on top of the panel
        # (prototype building_ui.py:1121-1130) --
        if self._cond_hover and self._cond_tooltip is not None:
            self._submit_cond_tooltip(renderer, *self._cond_tooltip)
        # -- /10I --
        if self.preview is not None:
            self.preview.submit(renderer, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)

    def _submit_unlock(self, renderer, session, anim_ms=0):
        txt = self._text
        submit_label(renderer, txt["unlock_title"], color=widgets.C_UI_TEXT)
        submit_label(renderer, txt["unlock_hint"], color=widgets.C_UI_TEXT_DIM)
        if not session.tilemap.can_unlock(self.tile):
            submit_label(renderer, txt["unlock_blocked"],
                         color=widgets.C_UI_TEXT_DIM)
        if is_visible(self.action_btn):
            self.action_btn.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(self.action_btn))
        # The terrain CARDS replace the footer badge + hover tooltip in this
        # mode: every condition the purchase covers is spelled out inline, so
        # a pill naming only the primary tile's condition would say a fourth
        # of the same thing twice. The badge is still drawn in construct and
        # upgrade modes, where there is exactly one tile to describe.
        self._submit_cond_cards(renderer, anim_ms)

    def _submit_construct(self, renderer, anim_ms=0):
        submit_label(renderer, self._text["construct_title"],
                     color=widgets.C_UI_TEXT)
        self._submit_list_group(renderer, self._construct_list, anim_ms)
        # Each card is a widget tree, drawn in the house back-to-front order
        # (panel/background -> buttons -> standalone text). Every part follows
        # the same rules as any other id'd widget: a `visible: false` override
        # skips it, and `color`/`text_color` ride along via button_kwargs.
        # `_card_in_viewport` is the scroll window — a card scrolled out of the
        # list is simply not drawn (see that method for why this is not
        # expressed as `visible = False`).
        for btype, btn in self.cards:
            parts = self._card_parts.get(btype)
            if parts is None or not self._card_in_viewport(btn.rect):
                continue
            # The card BODY first: it is this tree's background, and the HUD
            # queue is drawn in pure submission order (`Renderer.submit_hud`
            # appends; nothing sorts), so anything submitted after it lands on
            # top. Drawing the portrait first instead hides it completely the
            # moment the body carries real art — the whole 34x34 sits inside
            # the body's rect. That stayed invisible for as long as
            # `defaults.button_skin` was unset and the body drew as a flat
            # rect, and broke the screen the day a designer skinned the card.
            if is_visible(btn):
                btn.submit(renderer, anim_ms=anim_ms, **button_kwargs(btn))
            # then the portrait, on top of the body it sits in
            if is_visible(parts.portrait):
                submit_panel(renderer, parts.portrait.rect,
                             skin=parts.portrait.skin,
                             tint=getattr(parts.portrait, "tint", None),
                             anim_ms=anim_ms)
            if is_visible(parts.price):
                parts.price.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(parts.price))
            if is_visible(parts.icon):
                submit_panel(renderer, parts.icon.rect, skin=parts.icon.skin,
                             tint=getattr(parts.icon, "tint", None),
                             anim_ms=anim_ms)
            # then the text, always on top. The name is wrapped HERE, not in
            # `_build_construct` — a live font measurement is allowed at draw
            # time but must never reach a stored rect or the exported
            # `label` (see the note where the holders are built). Row 1 owns
            # the whole name, so a designer's `label` override on it still
            # drives both rows; row 2 lends only its position, font and colour,
            # and draws nothing when the name fits on one line.
            lines = widgets.wrap_text(parts.name_1.label or "", "sm",
                                      parts.name_w, max_lines=2)
            for holder, line in zip((parts.name_1, parts.name_2), lines):
                submit_label(renderer, holder, text=line,
                             color=widgets.C_UI_TEXT)
            submit_label(renderer, parts.price_text, value=parts.cost,
                         color=widgets.C_UI_TEXT)
        # -- 10I: tile terrain footer badge (effect box above) --
        self._submit_cond_badge(renderer, self.tile.condition)
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
        """``(slot_key, next_tier_name, first-3 stat rows)`` for tier+1 level 1
        (prototype ``_draw_next_tier_preview``), or None at the last tier.

        The header TEXT is no longer built here — the card's header is an id'd
        label whose ``building.upgrade.next_tier`` template formats the name."""
        if not b.has_next_tier():
            return None
        temp = create(b.building_type, b.col, b.row, self._buildings_balance)
        tts = temp.get_component(TierState)
        tts.current_tier = b.get_component(TierState).current_tier + 1
        tts.current_level_in_tier = 1
        temp.apply_tier_stats()
        return temp.slot_key(), _tier_name(temp), _building_stats(temp)[:3]

    @staticmethod
    def _submit_stat_delta(renderer, holder, value, pv):
        """Draws a stat row's value for the hover-preview delta case
        (feature: upgrade-stat-delta-preview, user decision): a plain
        NUMERIC current/next pair (``hp``/``damage``/``range``/etc. — never
        a formatted string like ``atk_speed``'s ``"1.0s"`` or
        ``progress``'s ``"3/5"``, which keep the old whole-value-turns-green
        behavior via the caller's ``submit_label`` fallback) reads as
        ``"40 + 5"``/``"40 - 5"`` instead of replacing the value outright
        with the flat next-level number ``"45"``. Only the delta suffix is
        green (``C_GREEN_STAT``); the base number keeps the stat's normal
        color, so the split needs two ``submit_text`` calls instead of one
        ``submit_label`` — there is no multi-color run in that helper.

        Positions itself so the COMBINED string lands exactly where
        ``submit_label`` would have drawn the single value at this holder's
        alignment (left/right/center) — nothing shifts on screen when a
        stat starts previewing a delta."""
        if not is_visible(holder):
            return
        delta = pv - value
        sign = "+" if delta >= 0 else "-"
        base_text = str(value)
        delta_text = f" {sign} {abs(delta)}"
        font_key = holder.font_key
        base_w, _ = text_size(base_text, font_key)
        full_w, _ = text_size(base_text + delta_text, font_key)
        anchor_x, y = holder.rect[0], holder.rect[1]
        align = getattr(holder, "align", "left") or "left"
        if align == "right":
            start_x = anchor_x - full_w
        elif align == "center":
            start_x = anchor_x - full_w / 2
        else:
            start_x = anchor_x
        base_col = getattr(holder, "text_color", None) or widgets.C_UI_TEXT
        submit_text(renderer, base_text, (start_x, y), font_key, base_col)
        submit_text(renderer, delta_text, (start_x + base_w, y), font_key,
                    widgets.C_GREEN_STAT)

    def _submit_upgrade(self, renderer, anim_ms=0):
        from engine.render import HudRect, HudSprite

        x, b = self.panel_x + 7, self._selected
        up_mode, _, _, _ = self._upgrade_state(b)
        txt = self._text
        # 10J: the title is the DISPLAY name — custom names + rebirth ordinals
        # finally show; the tier name moves to the Level row. `text=` because
        # the string IS the player's own name for the building, which no
        # designer template can produce; its geometry/font/colour stay theirs.
        submit_label(renderer, txt["upgrade_title"], text=_display_name(b),
                     color=widgets.C_UI_TEXT)
        # -- 10J rename row: input box + dice --
        renderer.submit_hud(HudRect(self._name_box_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self._name_box_rect,
            (widgets.highlight_color("tile_selected") if self._name_editing
             else widgets.C_UI_BORDER), width=1))
        if self._name_buf or self._name_editing:
            submit_label(renderer, txt["upgrade_name"],
                         text=self._name_buf + "_", color=widgets.C_UI_TEXT)
        else:
            submit_label(renderer, txt["upgrade_name"],
                         color=widgets.C_UI_TEXT_DIM)
        if is_visible(self._dice_up):
            self._dice_up.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self._dice_up))
        # -- /10J --
        submit_label(renderer, txt["upgrade_tier_level"],
                     color=widgets.C_UI_TEXT_DIM,
                     tier=_tier_name(b), level=b.level)
        # -- 10I: terrain badge (ALWAYS shown incl. Grass), reading the
        # building's placement snapshot; effect box below the badge --
        self._submit_cond_badge(
            renderer,
            getattr(b, "_tile_condition", None) or TileCondition.GRASS)
        # -- /10I --
        # 10J: hovering an enabled in-tier UPGRADE button previews the next
        # level's stats in green (prototype building_ui.py:1021, 1057-58).
        preview = None
        if up_mode == "in_tier" and self.action_btn.hovered:
            preview = dict(self._next_level_rows(b) or ())
        # Every row step below is font-scale (see _row_step): "md" -> 14,
        # "sm" -> 12. Worst-case fit for this whole column, against the
        # upgrade action button whose top is view_h - 60 = 300:
        #   stats     58 + 8*14                        = 170  (8 = the widest
        #             list, defence's 5 rows + 3 boosted-stat rows)
        #   round      +5, +12, +12, +12 (DIED tag)    = 211
        #   next tier  +4 divider, +4, header +14      = 233
        #   3 card rows at 12 (beside a 19px thumb)    -> bottom 268
        # 268 < 300, so nothing here needs the panel (which is view_h tall
        # anyway) to grow.
        md_step, sm_step = _row_step("md"), _row_step("sm")
        for key, value in _building_stats(b):
            name_h, value_h = self._stat_rows[key]
            submit_label(renderer, name_h, color=widgets.C_UI_TEXT_DIM)
            pv = preview.get(key) if preview else None
            changed = pv is not None and pv != value
            # feature: upgrade-stat-delta-preview — a plain numeric pair
            # reads as "40 + 5" (base normal color, delta green); a
            # formatted-string stat (atk_speed's "1.0s", progress's "3/5",
            # …) keeps the old whole-value-turns-green behavior, since a
            # bare arithmetic delta doesn't read cleanly there.
            if (changed and isinstance(value, (int, float))
                    and isinstance(pv, (int, float))):
                self._submit_stat_delta(renderer, value_h, value, pv)
            else:
                submit_label(renderer, value_h,
                             color=(widgets.C_GREEN_STAT if changed
                                    else widgets.C_UI_TEXT),
                             value=pv if changed else value)
        rs = b.get_component(RoundStats)
        if rs is not None:
            for label_key, value_key, amount in (
                    ("dmg_dealt_label", "dmg_dealt_value",
                     rs.dmg_dealt_last_round),
                    ("dmg_taken_label", "dmg_taken_value",
                     rs.dmg_taken_last_round)):
                submit_label(renderer, txt[label_key],
                             color=widgets.C_UI_TEXT_DIM)
                submit_label(renderer, txt[value_key],
                             color=widgets.C_UI_TEXT, value=amount)
            # -- 10J: a building whose last-round damage covered its full HP
            # died last round (prototype building_ui.py:1083-86) --
            if rs.dmg_taken_last_round >= b.max_hp():
                submit_label(renderer, txt["died_last_round"],
                             color=widgets.C_RED)
        y = self._stats_bottom
        # -- 10J: next-tier card when a tier advance is on the table
        # (prototype ``_draw_next_tier_preview``; hidden while round-gated) --
        if up_mode in ("tier_upgrade", "tier_locked"):
            card = self._next_tier_card(b)
            if card is not None:
                slot, next_name, rows = card
                y += 4
                renderer.submit_hud(HudRect(
                    (x, y, self.panel_w - 14, 1), widgets.C_UI_BORDER))
                y += 4
                header = txt["next_tier_header"]
                header.rect = (header.rect[0], y, 0, 0)
                submit_label(renderer, header, color=widgets.C_GREEN_STAT,
                             name=next_name)
                y += md_step
                if slot:
                    renderer.submit_hud(HudSprite(slot, (x, y), (19, 19)))
                ry = y
                # Dynamic-count content (three rows of whichever stats the
                # next tier has) — no per-row id, the same rule the construct
                # cards follow; its TEXT is still designer-owned.
                for key, value in rows:
                    submit_text(renderer,
                                T("building.upgrade.next_tier_row",
                                  label=_stat_label(key), value=value),
                                (x + 23, ry), "sm", widgets.C_UI_TEXT_DIM)
                    ry += sm_step
        if is_visible(self.action_btn):
            self.action_btn.submit(renderer, anim_ms=anim_ms,
                                   **button_kwargs(self.action_btn))
        # Building Movement: MOVE BUILDING sits directly under the upgrade
        # action button (single selection only — see _build_move_btn).
        if is_visible(self.move_btn):
            self.move_btn.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self.move_btn))
        # B3: the colour swatches, still inside the BUTTON block (they ARE
        # buttons) and before the hint text. Inert => draws nothing. The
        # selection ring rides right after its own swatch, inside the row.
        self.colour_row.submit(renderer, self._selected_column(),
                               anim_ms=anim_ms)
        if self._upgrade_hint:
            bx, by, bw, bh = self.action_btn.rect
            if is_visible(self.move_btn):
                bx, by, bw, bh = self.move_btn.rect
            hint = txt["upgrade_hint"]
            hint.rect = (bx + bw // 2, by + bh + 3, 0, 0)
            submit_label(renderer, hint, text=self._upgrade_hint,
                         color=widgets.C_UI_TEXT_DIM)

    def _submit_move_select(self, renderer, anim_ms=0):
        """The destination-picking view (Building Movement): the panel becomes
        a short instruction card while every legal tile is highlighted in the
        world (the `_highlight_tiles` loop in `submit`, above)."""
        b, txt = self._selected, self._text
        submit_label(renderer, txt["move_title"], color=widgets.C_UI_TEXT)
        if b is not None:
            submit_label(renderer, txt["move_name"], text=_display_name(b),
                         color=widgets.C_UI_TEXT_DIM)
        submit_label(renderer, txt["move_pick"],
                     color=widgets.highlight_color("move_target"))
        for key in ("move_hint_1", "move_hint_2", "move_hint_cancel"):
            submit_label(renderer, txt[key], color=widgets.C_UI_TEXT_DIM)

    # -- 10I: terrain badge + effect tooltip (prototype building_ui.py
    # :998-1014 badge, :1418-1438 effect lines, :1440-1477 chrome/footer) ----

    def _tile_cond_effect_lines(self, condition):
        """``[name, value]`` for a condition's effect — the NAME of the thing
        it changes ("Range") and the change itself ("+1") — values read LIVE
        from the map balancing.

        Two entries, always, so row `i` always addresses the same half (see
        `_COND_EFFECT_LINES`); a condition with nothing to say leaves the
        value blank. Only the FIRST effect is reported — every condition has
        exactly one today. Prototype-exact: the enemy dmg/speed effects are
        deliberately NOT listed."""
        if condition == TileCondition.GRASS:
            return ["No effect", ""]
        if condition in CONDITION_BLOCKS_BUILD:
            return ["Unbuildable", ""]
        mods = self._session.tilemap.balance["TileConditions"]["modifiers"]
        m = mods.get(CONDITION_MODIFIER_KEY.get(condition), {})
        if m.get("def_range_bonus"):
            return ["Range", f'+{m["def_range_bonus"]}']
        if m.get("def_attack_speed_penalty"):
            return ["Atk speed",
                    f'-{m["def_attack_speed_penalty"] * 100:.0f}%']
        if m.get("def_dmg_penalty"):
            return ["Damage", f'-{m["def_dmg_penalty"] * 100:.0f}%']
        if m.get("eco_yield_penalty"):
            return ["Economy", f'-{m["eco_yield_penalty"] * 100:.0f}%']
        if m.get("eco_yield_bonus"):
            return ["Economy", f'+{m["eco_yield_bonus"] * 100:.0f}%']
        return ["No effect", ""]

    def _layout_cond_box(self, condition, y, above):
        """Place the terrain badge + effect box for ``condition``, with the
        badge's top at ``y`` and the box above or below it.

        Runs from the MODE BUILDERS (`_build_construct` / `_build_upgrade`) —
        i.e. before any `submit()`, and therefore before `skinning.apply` —
        which is what makes a designer's rect override win: this writes the
        DEFAULT anchor, `apply` then replaces it for whichever of the seven
        widgets carry one (`_layout_upgrade_rows`'s convention, and the same
        no-cascade rule: overriding the box does not move its lines).

        The effect NAME and its VALUE are stacked from the box's top by
        default, one row each; a designer who wants them side by side moves
        `cond_effect_line_1` in the editor (the two rows are independent
        widgets precisely so that is possible).
        """
        lines = self._tile_cond_effect_lines(condition)
        self._cond_effect_lines = lines
        step = _row_step("sm")
        badge_h = _row_step("sm", 4)   # layout_h, not text_h — see above
        bx, _by, bw, _bh = self._cond_badge.rect
        self._cond_badge.rect = (bx, y, bw, badge_h)
        self._text["cond_badge_text"].rect = (bx + bw // 2, y + 2, 0, 0)
        box_h = step * _COND_EFFECT_LINES + 5
        box_y = y - box_h - 3 if above else y + badge_h + 3
        self._cond_effect_box.rect = (bx, box_y, bw, box_h)
        for i in range(_COND_EFFECT_LINES):
            self._text[f"cond_effect_line_{i}"].rect = (
                bx + 4, box_y + 2 + i * step, 0, 0)

    def _submit_cond_badge(self, renderer, condition):
        """The ``Terrain: <Label>`` pill, drawn from its id'd widgets at
        whatever rect `_layout_cond_box` (then `skinning.apply`) left them at.

        Records the badge's LIVE rect as the hover probe — so a designer who
        moves the pill moves its tooltip trigger with it — and the pending
        tooltip, which `submit` draws last so it sits on top."""
        label, color = widgets.cond_label(condition.name)
        if not is_visible(self._cond_badge) and not is_visible(
                self._text["cond_badge_text"]):
            self._cond_badge_rect = None
            self._cond_tooltip = None
            return
        rect = self._cond_badge.rect
        self._cond_badge_rect = rect
        if is_visible(self._cond_badge):
            submit_panel(renderer, rect, fill=widgets.C_PANEL_STONE,
                         border=color, skin=self._cond_badge.skin,
                         tint=getattr(self._cond_badge, "tint", None))
        submit_label(renderer, self._text["cond_badge_text"], color=color,
                     label=label)
        self._cond_tooltip = (condition, color)

    def _submit_cond_tooltip(self, renderer, condition, color):
        """The effect box: dark panel, 1px border in the condition colour,
        and one id'd label per effect line. Lines past the condition's own
        count are simply not drawn."""
        if is_visible(self._cond_effect_box):
            submit_panel(renderer, self._cond_effect_box.rect,
                         fill=_COND_TOOLTIP_BG, border=color,
                         skin=self._cond_effect_box.skin,
                         tint=getattr(self._cond_effect_box, "tint", None))
        rows = _cond_effect_rows(self._cond_effect_lines)
        for i, text in enumerate(rows):
            submit_label(renderer, self._text[f"cond_effect_line_{i}"],
                         text=text, color=widgets.C_UI_TEXT)

    # -- /10I ---------------------------------------------------------------

    def _submit_base_info(self, renderer, session, anim_ms=0):
        st, txt = session.state, self._text
        income = scaled_base_income(st, session.core_balance)
        submit_label(renderer, txt["base_info_title"], color=widgets.C_UI_TEXT)
        values = {
            "lives": st.base_lives,
            "wave": st.round_num,
            "enemies_killed": st.enemies_killed,
            "buildings": st.buildings_placed,
            "base_income": T("building.base_info.income_value", amount=income),
        }
        for key in _BASE_INFO_ROWS:
            submit_label(renderer, txt[f"info_{key}_label"],
                         color=widgets.C_UI_TEXT_DIM)
            submit_label(renderer, txt[f"info_{key}_value"],
                         color=widgets.C_UI_TEXT, value=values[key])
        # -- 10G boss: BOSS CHOICES button + history popup --
        if is_visible(self.boss_btn):
            self.boss_btn.submit(renderer, anim_ms=anim_ms,
                                 **button_kwargs(self.boss_btn))
        if self._boss_popup_open:
            self._submit_boss_popup(renderer, session, anim_ms)
        # -- /10G --

    def _submit_boss_popup(self, renderer, session, anim_ms=0):
        """The small boss-history popup (prototype ``_BossHistoryPanel``): one
        row per ``(boss_num, upgrade_id, outcome)``, the hovered row's upgrade
        description as a tooltip, "None yet" when empty, a Close button (10G;
        re-pointed at the boss-upgrade history in BU-4)."""
        px, py, pw, ph = self._boss_popup_rect
        # B3: the popup body is dynamic-count content (choice history rows) —
        # not id'd, styled from the screen's defaults.panel_skin instead.
        panel_skin = self.skinning.defaults(self.screen_id).get("panel_skin")
        submit_panel(renderer, self._boss_popup_rect, skin=panel_skin,
                    anim_ms=anim_ms)
        submit_text(renderer, T("building.boss.title"), (px + pw // 2, py + 7),
                    "lg", widgets.C_UI_TEXT, align="center")
        choices = session.state.boss_upgrade_choices
        y = py + 24
        if not choices:
            submit_text(renderer, T("building.boss.none_yet"), (px + 7, y),
                        "md", widgets.C_UI_TEXT_DIM)
        hover_desc = None
        for i, (boss_num, upgrade_id, outcome) in enumerate(choices):
            hovered = i == self._boss_hover_row
            name, desc = _boss_upgrade_copy(session, upgrade_id)
            submit_text(
                renderer,
                T("building.boss.row", n=boss_num,
                  outcome=outcome.capitalize(), option=name),
                (px + 7, y), "md", widgets.C_GOLD if hovered else widgets.C_UI_TEXT)
            if hovered:
                hover_desc = desc
            # Font-scale (see _row_step) and the SAME expression `hover`'s
            # row hit test divides by.
            y += _row_step("md")
        if hover_desc:
            # The catalog description is prose, so it wraps to the popup and
            # is clamped to _BOSS_TIP_LINES; the block is anchored UPWARDS off
            # the CLOSE button (top py + ph - 22) by however many lines it
            # actually used, so a 1-line tip sits low and a 4-line one starts
            # exactly at the row budget's floor (see the rect's arithmetic).
            tip_step = _row_step("sm")
            lines = wrap_text(hover_desc, "sm", pw - 14, _BOSS_TIP_LINES)
            ty = py + ph - 26 - len(lines) * tip_step
            for line in lines:
                submit_text(renderer, line, (px + 7, ty), "sm", widgets.C_UI_TEXT_DIM)
                ty += tip_step
        if is_visible(self._boss_close_btn):
            self._boss_close_btn.submit(renderer, anim_ms=anim_ms,
                                        **button_kwargs(self._boss_close_btn))
