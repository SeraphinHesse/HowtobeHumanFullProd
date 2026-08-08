"""Map overlays (Phase 10I): condition tint, RANGE + HEATMAP toggles.

Pure logic (no pygame — the game/ui purity scan covers this module). One class
owns every 10I UI surface so ``hud.py`` (edited by 10G/10H) carries no 10I
diff:

* **World condition tint** — a coloured diamond on every non-GRASS,
  non-BACKGROUND, non-SPAWNING tile inside the visible window (prototype
  ``tile.py:25-30, 166-173``), drawn under buildings/highlights. A tile keeps
  its rolled condition while SPAWNING — only the draw is skipped, so the
  diamond reappears once the tile converts to COMBAT (spawn recede).
* **RANGE toggle** — red diamonds over the union of every alive defender's
  Chebyshev range square, using RAW ``range_tiles()`` (prototype
  ``hud.py:399-430`` / ``game.py:2012-2019``). The Maw Mortar IS included
  (its exclusion is pathfinding-only); ``"boost"``-tagged occupants contribute
  their 4-cardinal plus-shape.
* **HEATMAP toggle** — the PREVIOUS round's distinct-enemy traffic per tile,
  blue→yellow→red ramp (prototype ``hud.py:432-470`` / ``game.py:1344-1349,
  927-932``). ``track`` accumulates during the ENEMY phase and snapshots on
  the phase edge, so the overlay is empty before the first wave.

Since the 10J FX sweep the overlays are alpha-FILLED diamonds with the
prototype's exact alphas (tint fill 70 / border 140, RANGE fill 55, heatmap
fill 50+130·t) via ``submit_overlay_polys``; outlines remain only where the
prototype drew them.

Cost profile (large-map invariant): O(viewport) tint + O(defenders·r²)
coverage + O(visited tiles) heatmap — never a full-map per-frame scan.

10L-B (Phase 3): the two toggle pills are their OWN screen id, ``overlays``
(``data/ui/screens/overlays.json``) — the B1 format's "drop in a file + ids"
extension path, not one of the original 12. ``ids`` names ``btn_range``/
``btn_heatmap``; since ``view_w``/``view_h`` are fixed for this object's whole
lifetime (one ``MapOverlays`` per run, like ``BuildingUI``'s mode-independent
ids), ``apply()`` runs once in ``__init__`` rather than from a per-frame
``layout()``.
"""
from engine.render import HudRect
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

# The boost plus-shape (cardinal neighbours only — prototype hud.py:411-420).
_PLUS_DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0))


def heat_color(t):
    """The prototype's blue→yellow→red heat ramp (``hud.py:452-465``) WITH its
    alpha (10J): t=0 → (0,100,200,50), t=0.5 → (255,255,0,115),
    t=1 → (255,0,0,180)."""
    a = int(50 + 130 * t)
    if t < 0.5:
        return (int(255 * 2 * t), int(100 + 155 * 2 * t),
                int(200 - 200 * 2 * t), a)
    return (255, int(255 - 255 * (2 * t - 1)), 0, a)


class MapOverlays:
    """The two persistent bottom-left toggle pills + the overlay submit pass.
    State (``show_range`` / ``show_heatmap`` / ``path_heatmap``) persists
    across phases and rounds within a run — a fresh run builds a fresh
    instance (prototype: fields on the HUD object)."""

    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.show_range = False
        self.show_heatmap = False
        # Left of the phase banner, stacked above it (the banner sits at
        # view_h-26; hud End Turn owns the bottom-right corner).
        self.range_btn = Button((12, view_h - 72, 74, 26), "RANGE", "sm")
        self.heatmap_btn = Button((90, view_h - 72, 74, 26), "HEATMAP", "sm")
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
        return False

    def over(self, mx, my):
        """Pure containment probe for the host's ``over_ui`` check (a press on
        a pill must not arm camera panning)."""
        return (contains(self.range_btn.rect, mx, my)
                or contains(self.heatmap_btn.rect, mx, my))

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.range_btn.hover(mx, my, mouse_down)
        self.range_btn.hovered = self.range_btn.hovered and is_visible(self.range_btn)
        self.heatmap_btn.hover(mx, my, mouse_down)
        self.heatmap_btn.hovered = (self.heatmap_btn.hovered
                                    and is_visible(self.heatmap_btn))
        self.range_btn.update(dt)
        self.heatmap_btn.update(dt)

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
        """Union of covered tiles for the RANGE overlay: a Chebyshev square
        per alive built occupant with duck-typed RAW ``range_tiles() > 0``
        (mortar included — the aoe exclusion is pathfinding-only), plus the
        4-cardinal plus-shape per ``"boost"``-tagged occupant."""
        covered = set()
        for tile in tilemap.built_tiles():
            b = tile.occupant
            if b is None or not getattr(b, "alive", False):
                continue
            rfn = getattr(b, "range_tiles", None)
            if rfn is not None:
                r = int(rfn())
                if r > 0:
                    for dc in range(-r, r + 1):
                        for dr in range(-r, r + 1):
                            covered.add((tile.col + dc, tile.row + dr))
            if "boost" in getattr(b, "tags", ()):
                for dc, dr in _PLUS_DIRS:
                    covered.add((tile.col + dc, tile.row + dr))
        return covered

    # -- render --------------------------------------------------------------

    def submit(self, renderer, tilemap, scene, window):
        """World-space overlay diamonds, submitted between the scene items and
        the panel highlights (conditions draw under the selection). ``window``
        is the host's ``(cmin, cmax, rmin, rmax)`` visible-tile window — the
        tint never scans beyond it (large-map invariant)."""
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
                    renderer, c, r, widgets.C_RANGE_HIGHLIGHT + (55,),
                    border=widgets.C_RANGE_HIGHLIGHT, border_width=1)
        if self.show_heatmap and self.path_heatmap:
            max_count = max(self.path_heatmap.values())
            for (c, r), count in self.path_heatmap.items():
                t = min(1.0, count / max_count) if max_count else 0.0
                submit_tile_diamond_fill(renderer, c, r, heat_color(t))

    def submit_buttons(self, renderer):
        """The HUD-pass toggle pills; an active toggle gets a gold rim + gold
        label (prototype hud.py:383-392). An invisible pill draws nothing
        (10L-B)."""
        t = anim_ms(self._clock)
        for btn, active in ((self.range_btn, self.show_range),
                            (self.heatmap_btn, self.show_heatmap)):
            if not is_visible(btn):
                continue
            if active:
                # active state is code-owned styling (like boss_cutscene's
                # win/loss headline colour) — it always wins over an
                # override's color/text_color, same as the pre-10L-B behavior.
                btn.submit(renderer, color=widgets.C_UI_BTN, text_color=widgets.C_GOLD,
                          anim_ms=t)
                renderer.submit_hud(HudRect(btn.rect, widgets.C_GOLD, width=2,
                                            border_radius=3))
            else:
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
