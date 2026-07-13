"""Map overlays (Phase 10I): condition tint, RANGE + HEATMAP toggles.

Pure logic (no pygame — the game/ui purity scan covers this module). One class
owns every 10I UI surface so ``hud.py`` (edited by 10G/10H) carries no 10I
diff:

* **World condition tint** — a coloured diamond on every non-GRASS,
  non-BACKGROUND tile inside the visible window (prototype ``tile.py:25-30,
  166-173``), drawn under buildings/highlights.
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
"""
from engine.render import HudRect
from game.core.phases import GamePhase
from game.map.tiles import TileCondition, TileState

from .widgets import (
    C_GOLD, C_RANGE_HIGHLIGHT, C_UI_BTN, Button, contains,
    submit_tile_diamond_fill,
)

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

    def __init__(self, view_w, view_h):
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

    # -- input ---------------------------------------------------------------

    def hit(self, mx, my):
        """Flip the matching toggle; True = the click was consumed (the pills
        never return a HUD action — prototype hud.py:223-228)."""
        if self.range_btn.hit(mx, my):
            self.show_range = not self.show_range
            return True
        if self.heatmap_btn.hit(mx, my):
            self.show_heatmap = not self.show_heatmap
            return True
        return False

    def over(self, mx, my):
        """Pure containment probe for the host's ``over_ui`` check (a press on
        a pill must not arm camera panning)."""
        return (contains(self.range_btn.rect, mx, my)
                or contains(self.heatmap_btn.rect, mx, my))

    def update(self, dt, mx, my):
        self.range_btn.hover(mx, my)
        self.heatmap_btn.hover(mx, my)
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
                if t is None or t.state == TileState.BACKGROUND:
                    continue
                tint = _COND_TINT.get(t.condition)
                if tint is not None:
                    # prototype tile.py:169-172: fill alpha 70 (the border is
                    # an opaque line — OverlayLines carries no alpha)
                    submit_tile_diamond_fill(
                        renderer, c, r, tint + (70,),
                        border=tint, border_width=2)
        if self.show_range:
            for (c, r) in self.range_coverage(tilemap):
                # prototype hud.py:424-425: fill alpha 55
                submit_tile_diamond_fill(
                    renderer, c, r, C_RANGE_HIGHLIGHT + (55,),
                    border=C_RANGE_HIGHLIGHT, border_width=1)
        if self.show_heatmap and self.path_heatmap:
            max_count = max(self.path_heatmap.values())
            for (c, r), count in self.path_heatmap.items():
                t = min(1.0, count / max_count) if max_count else 0.0
                submit_tile_diamond_fill(renderer, c, r, heat_color(t))

    def submit_buttons(self, renderer):
        """The HUD-pass toggle pills; an active toggle gets a gold rim + gold
        label (prototype hud.py:383-392)."""
        for btn, active in ((self.range_btn, self.show_range),
                            (self.heatmap_btn, self.show_heatmap)):
            if active:
                btn.submit(renderer, color=C_UI_BTN, text_color=C_GOLD)
                renderer.submit_hud(HudRect(btn.rect, C_GOLD, width=2,
                                            border_radius=3))
            else:
                btn.submit(renderer)
