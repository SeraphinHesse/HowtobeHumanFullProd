"""Map overlays (Phase 10I): condition tint, RANGE + HEATMAP + TIER OVERVIEW.

Pure logic (no pygame — the game/ui purity scan covers this module). One class
owns every 10I UI surface so ``hud.py`` (edited by 10G/10H) carries no 10I
diff:

* **World condition tint** — a coloured diamond on every non-GRASS,
  non-BACKGROUND, non-SPAWNING tile inside the visible window (prototype
  ``tile.py:25-30, 166-173``), drawn under buildings/highlights. A tile keeps
  its rolled condition while SPAWNING — only the draw is skipped, so the
  diamond reappears once the tile converts to COMBAT (spawn recede).
* **RANGE toggle** — red diamonds over the union of every alive defender's
  range footprint, using the TARGETING range (``targeting_range_tiles()`` when
  present — the mountain ``def_range_bonus`` included — else ``range_tiles()``;
  prototype ``hud.py:399-430`` / ``game.py:2012-2019`` used raw and so drew a
  tile short on boosted tiles), shaped per an optional duck-typed
  ``range_shape()`` (Chebyshev square when absent; a booster's shape is
  configurable, ``game/buildings/boost.py``). The Maw Mortar IS included
  (its exclusion is pathfinding-only).
* **HEATMAP toggle** — the PREVIOUS round's distinct-enemy traffic per tile,
  blue→yellow→red ramp (prototype ``hud.py:432-470`` / ``game.py:1344-1349,
  927-932``). ``track`` accumulates during the ENEMY phase and snapshots on
  the phase edge, so the overlay is empty before the first wave.
* **TIER OVERVIEW toggle** — a tinted diamond over every PLAYER-BUILT
  building, so a glance answers "what have I actually upgraded?". The colour
  is read off the building's own ``TierState.current_level_in_tier`` (the
  IN-TIER level, 1-indexed) and the 3-colour cycle RESETS at every tier
  advance — a level-1 building reads identically whether it just got placed
  (tier 1) or just tier-advanced (tier 2+), by design. The base ("the hole")
  is excluded — it is not player-built, and it is tag-gated out rather than
  type-string-gated (G-3): it DOES carry a ``TierState``, so the
  component-presence check alone would tint it.

Since the 10J FX sweep the overlays are alpha-FILLED diamonds with the
prototype's exact alphas (tint fill 70 / border 140, RANGE fill 55; heatmap
fill was the prototype's 50+130·t and is now 50+70·t, fix/highlight-render-
order, so the hottest tiles stay visibly see-through once overlays draw
behind buildings) via ``submit_overlay_polys``; outlines remain only where
the prototype drew them.

Cost profile (large-map invariant): O(viewport) tint + O(defenders·r²)
coverage + O(visited tiles) heatmap — never a full-map per-frame scan.

10L-B (Phase 3): the toggle pills are their OWN screen id, ``overlays``
(``data/ui/screens/overlays.json``) — the B1 format's "drop in a file + ids"
extension path, not one of the original 12. ``ids`` names ``btn_range``/
``btn_heatmap``/``btn_tier_overview``; since ``view_w``/``view_h`` are fixed
for this object's whole lifetime (one ``MapOverlays`` per run, like
``BuildingUI``'s mode-independent ids), ``apply()`` runs once in ``__init__``
rather than from a per-frame ``layout()``. Each pill's label is the code-owned
default and becomes JSON-overridable for free through that id (the generic
per-widget ``label`` override).
"""
from engine.render import HudRect
from game.buildings import range_shape
from game.buildings.components import TierState
from game.core.phases import GamePhase
from game.map.conditions import draws_tint
from game.map.tiles import TileCondition, TileState

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, contains, submit_tile_diamond_fill
)
from . import widgets

SCREEN_ID = "overlays"

# World condition tint per condition (prototype tile.py:25-30, verbatim RGB).
_COND_TINT = {
    TileCondition.MOUNTAIN: (130, 100, 60),
    TileCondition.POND: (50, 130, 200),
    TileCondition.FOREST: (30, 100, 30),
}


# TIER OVERVIEW fill alpha (a plain int — safe as a module constant, unlike a
# colour). Designer-picked yellow/pink/blue (a same-hue purple ramp read as
# indistinguishable grey in a live playtest, and a second same-family red/
# gold/green pass still wasn't distinct enough). Neither pink nor blue exists
# in the shared widgets.C_* palette, so level 2 reuses the house purple
# (closest to pink) and level 3 reuses the POND condition tint below (the
# only blue anywhere in this file) rather than inventing new, unreused
# colours.
_TIER_OVERVIEW_ALPHA = 110


def _level_color(level_in_tier):
    """The TIER OVERVIEW tint for a 1-indexed IN-TIER level cursor
    (``TierState.current_level_in_tier``), clamped to the last entry for any
    future 4th+ level: yellow (``C_GOLD``) at level 1 / pink-ish
    (``C_PURPLE``) at level 2 / blue (the POND tint, ``_COND_TINT``) at level
    3+.

    Keyed by the LEVEL WITHIN the current tier, not the tier itself — the
    3-colour cycle resets at every tier advance, so a freshly-advanced
    building (level 1 of its new tier) reads identically to a freshly-placed
    one (level 1 of tier 1): e.g. a level-1 Slinger (tier 2) is the same gold
    as a level-1 Stone Thrower (tier 1).

    A FUNCTION, not a module-level tuple: every ``widgets.C_*`` must be a
    fresh attribute read (UH-6/D5 — ``configure_palette`` rebinds those
    attributes at boot, and a copy taken at import time would go stale).
    ``_COND_TINT`` is NOT palette-driven (a plain prototype-verbatim module
    dict, never rebound), so indexing it directly carries no such risk.
    """
    colors = (widgets.C_GOLD, widgets.C_PURPLE, _COND_TINT[TileCondition.POND])
    return colors[min(max(0, level_in_tier - 1), len(colors) - 1)]


def heat_color(t):
    """The prototype's blue→yellow→red heat ramp (``hud.py:452-465``) WITH its
    alpha (10J, capped lower by fix/highlight-render-order so hot tiles stay
    see-through under buildings): t=0 → (0,100,200,50), t=0.5 →
    (255,255,0,85), t=1 → (255,0,0,120)."""
    a = int(50 + 70 * t)
    if t < 0.5:
        return (int(255 * 2 * t), int(100 + 155 * 2 * t),
                int(200 - 200 * 2 * t), a)
    return (255, int(255 - 255 * (2 * t - 1)), 0, a)


class MapOverlays:
    """The three persistent bottom-left toggle pills + the overlay submit pass.
    State (``show_range`` / ``show_heatmap`` / ``show_tier_overview`` /
    ``path_heatmap``) persists across phases and rounds within a run — a fresh
    run builds a fresh instance (prototype: fields on the HUD object). The
    toggles are fully INDEPENDENT of each other and of every other overlay
    (selection, drag-select, the upgrade panel): there is no mutual
    exclusion anywhere in this class."""

    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.show_range = False
        self.show_heatmap = False
        self.show_tier_overview = False
        # Left of the phase banner, stacked above it (the banner sits at
        # view_h-13; hud End Turn owns the bottom-right corner).
        # UR-5: 41 wide, not UR-2's halved 37. All THREE pills are 41 wide on
        # one row at x = 6 / 51 / 96 (the same 4px gap), which is what makes
        # them read as one control group.
        #
        # The copy is cut to fit the SHIPPED pixel font
        # (`data/ui/active_font.json` -> pixel_emulator), which is wider per
        # glyph than the `SysFont("monospace")` fallback every pixel constant
        # in `game/ui` was authored against: "HEATMAP" needed 51px in a 41px
        # pill and "TIER OVERVIEW" 89px. At "sm" under that font the shipped
        # labels measure RANGE 38, HEAT 30, TIERS 36 including the 4px
        # `LABEL_MARGIN` — so the third pill also came back DOWN, 76 -> 41,
        # to the shared width instead of being the odd one out. (UR-5 had
        # widened it 69 -> 76 for the fallback font; that number is gone with
        # the long label that needed it.)
        self.range_btn = Button((6, view_h - 36, 41, 13), "RANGE", "sm")
        self.heatmap_btn = Button((51, view_h - 36, 41, 13), "HEAT", "sm")
        self.tier_overview_btn = Button((96, view_h - 36, 41, 13),
                                        "TIERS", "sm")
        # Heatmap accumulators: distinct enemy ids per tile while the ENEMY
        # phase runs; snapshot to counts on the phase edge.
        self._current = {}
        self.path_heatmap = {}
        # {condition slot key: tint_overlay} over the condition slots that have
        # imported art — set by the host from the asset manifest. Empty ⇒ no
        # condition has art ⇒ every non-grass tile keeps its colour diamond,
        # which is exactly the pre-art behaviour.
        self.condition_art = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        # 10L-B: fixed for this object's lifetime — apply once (no per-frame
        # layout() step, matching BuildingUI's mode-independent ids).
        self.ids = {
            "btn_range": ("button", self.range_btn),
            "btn_heatmap": ("button", self.heatmap_btn),
            "btn_tier_overview": ("button", self.tier_overview_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    # -- input ---------------------------------------------------------------

    def hit(self, mx, my):
        """Flip the matching toggle; True = the click was consumed (the pills
        never return a HUD action — prototype hud.py:223-228). An invisible
        pill is never hit (10L-B)."""
        if is_visible(self.range_btn) and self.range_btn.hit(mx, my):
            self.show_range = not self.show_range
            return True
        if is_visible(self.heatmap_btn) and self.heatmap_btn.hit(mx, my):
            self.show_heatmap = not self.show_heatmap
            return True
        if (is_visible(self.tier_overview_btn)
                and self.tier_overview_btn.hit(mx, my)):
            self.show_tier_overview = not self.show_tier_overview
            return True
        return False

    def over(self, mx, my):
        """Pure containment probe for the host's ``over_ui`` check (a press on
        a pill must not arm camera panning)."""
        return (contains(self.range_btn.rect, mx, my)
                or contains(self.heatmap_btn.rect, mx, my)
                or contains(self.tier_overview_btn.rect, mx, my))

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.range_btn.hover(mx, my, mouse_down)
        self.range_btn.hovered = self.range_btn.hovered and is_visible(self.range_btn)
        self.heatmap_btn.hover(mx, my, mouse_down)
        self.heatmap_btn.hovered = (self.heatmap_btn.hovered
                                    and is_visible(self.heatmap_btn))
        self.tier_overview_btn.hover(mx, my, mouse_down)
        self.tier_overview_btn.hovered = (self.tier_overview_btn.hovered
                                          and is_visible(self.tier_overview_btn))
        self.range_btn.update(dt)
        self.heatmap_btn.update(dt)
        self.tier_overview_btn.update(dt)

    # -- heatmap tracking (prototype game.py:1344-1349 / 927-932) -------------

    def track(self, phase, prev_phase, scene):
        """Call once per frame BEFORE the host rolls ``prev_phase``. During
        ENEMY, collect each live enemy's id under its current tile; on the
        ENEMY→(anything) edge, snapshot distinct counts and clear — so the
        overlay always shows the PREVIOUS round's traffic."""
        if phase == GamePhase.ENEMY:
            for e in scene.by_tag("enemy"):
                if not getattr(e, "alive", False):
                    continue
                wx, wy = e.transform.world_pos
                key = (round(wx), round(wy))
                self._current.setdefault(key, set()).add(id(e))
        elif prev_phase == GamePhase.ENEMY:
            self.path_heatmap = {k: len(v) for k, v in self._current.items()}
            self._current.clear()

    # -- RANGE coverage (overlay-side: mortar INCLUDED, boosts plus-shape) ----

    @staticmethod
    def range_coverage(tilemap):
        """Union of covered tiles for the RANGE overlay: the tile-offset
        geometry (``game/buildings/range_shape.py``) per alive built occupant
        with a duck-typed range ``> 0`` (mortar included — the aoe exclusion is
        pathfinding-only). ``range_shape()`` picks the shape (defaults to a
        Chebyshev square when absent — every defence building; a booster
        defines it, defaulting to ``"plus"``, `game/buildings/boost.py`).

        The range read is the TARGETING range — i.e. the tile-condition
        (mountain ``def_range_bonus``) modified value the combat sweep really
        acquires with (``DefenceBuilding.targeting_range_tiles``), so a
        mountain defender's overlay footprint matches both its panel Range row
        and where it can actually shoot. It used to read RAW ``range_tiles()``
        for prototype parity, which drew a one-tile-short square for every
        boosted defender. Pathfinding coverage (``buildings/coverage.py``)
        still reads the raw value — that split is deliberate."""
        covered = set()
        for tile in tilemap.built_tiles():
            b = tile.occupant
            if b is None or not getattr(b, "alive", False):
                continue
            rfn = getattr(b, "targeting_range_tiles",
                          getattr(b, "range_tiles", None))
            if rfn is None:
                continue
            r = int(rfn())
            if r <= 0:
                continue
            shape = getattr(b, "range_shape", lambda: "square")()
            for dc, dr in range_shape.offsets(r, shape):
                covered.add((tile.col + dc, tile.row + dr))
        return covered

    # -- render --------------------------------------------------------------

    def submit(self, renderer, tilemap, scene, window):
        """World-space overlay diamonds, submitted between the scene items and
        the panel highlights (conditions draw under the selection). ``window``
        is the host's ``(cmin, cmax, rmin, rmax)`` visible-tile window — the
        tint never scans beyond it (large-map invariant)."""
        # ``anim_t``, not ``t``: the tile loop below already owns that name.
        anim_t = anim_ms(self._clock)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of, anim_t)
        cmin, cmax, rmin, rmax = window
        for r in range(max(0, rmin), min(tilemap.rows - 1, rmax) + 1):
            for c in range(max(0, cmin), min(tilemap.cols - 1, cmax) + 1):
                t = tilemap.get(c, r)
                if t is None or t.state in (TileState.BACKGROUND,
                                             TileState.SPAWNING):
                    continue
                tint = _COND_TINT.get(t.condition)
                # The diamond is a FALLBACK now: a tile whose condition art is
                # imported draws that sprite on the `terrain` layer instead,
                # unless its manifest entry asks for the tint underneath.
                if tint is not None and draws_tint(t.condition_slot,
                                                   self.condition_art):
                    # prototype tile.py:169-172: fill alpha 70 (the border is
                    # an opaque line — OverlayLines carries no alpha)
                    submit_tile_diamond_fill(
                        renderer, c, r, tint + (70,),
                        border=tint, border_width=2)
        if self.show_range:
            for (c, r) in self.range_coverage(tilemap):
                # prototype hud.py:424-425: fill alpha 55
                submit_tile_diamond_fill(
                    renderer, c, r,
                    widgets.highlight_color("attack_range") + (55,),
                    border=widgets.highlight_color("attack_range"),
                    border_width=1)
        if self.show_heatmap and self.path_heatmap:
            max_count = max(self.path_heatmap.values())
            for (c, r), count in self.path_heatmap.items():
                t = min(1.0, count / max_count) if max_count else 0.0
                submit_tile_diamond_fill(renderer, c, r, heat_color(t))
        if self.show_tier_overview:
            # O(built tiles) via the _by_state index — never a full-map scan
            # (the large-map invariant range_coverage above also honours).
            for tile in tilemap.built_tiles():
                b = tile.occupant
                if b is None or "base" in getattr(b, "tags", ()):
                    continue        # the hole is not a player-built building
                ts = b.get_component(TierState)
                if ts is None:
                    continue
                submit_tile_diamond_fill(
                    renderer, tile.col, tile.row,
                    _level_color(ts.current_level_in_tier)
                    + (_TIER_OVERVIEW_ALPHA,))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of, anim_t)

    def submit_buttons(self, renderer):
        """The HUD-pass toggle pills; an active toggle gets a gold rim + gold
        label (prototype hud.py:383-392). An invisible pill draws nothing
        (10L-B)."""
        t = anim_ms(self._clock)
        for btn, active in ((self.range_btn, self.show_range),
                            (self.heatmap_btn, self.show_heatmap),
                            (self.tier_overview_btn, self.show_tier_overview)):
            if not is_visible(btn):
                continue
            if active:
                # active state is code-owned styling (like hud.py's own
                # phase-banner colour) — it always wins over an
                # override's color/text_color, same as the pre-10L-B behavior.
                btn.submit(renderer, color=widgets.C_UI_BTN, text_color=widgets.C_GOLD,
                          anim_ms=t)
                renderer.submit_hud(HudRect(btn.rect, widgets.C_GOLD, width=2,
                                            border_radius=3))
            else:
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
