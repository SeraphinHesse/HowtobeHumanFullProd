"""``VfxSystem`` (ESV-3a): owns the particle/gold/slash/splatter lists,
``update(dt)`` and the two submit passes.

Two submit surfaces, not one, because the host interleaves them at
different points in the frame: world-overlay effects (splatters, gold tile
highlights — drawn before the panel) and HUD effects (particles, slashes —
drawn after the bars). ``game/ui/effects.py``'s ``FloaterManager`` keeps
three thin public methods (``submit_splatters``/``submit_gold_highlights``/
``submit_fx``) delegating to these so the host's existing two call SITES
(``game/main.py``) and their ordering are untouched.

Pure Python — no pygame, no data/ access (D5). Draws through the injected
``renderer``'s ``submit_hud``/``submit_overlay_polys``/``submit_overlay_lines``
(``engine.render``), never a raw pygame call.
"""
from engine.render import HudLines, HudRect

from . import emitters


class VfxSystem:
    """``params`` is a ``params.VfxParams`` bundle (death_burst/muzzle/slash/
    gold/splatter); ``rng`` is a ``random.Random``-compatible object threaded
    into every emit call (the caller may pass the stdlib ``random`` module
    itself to keep drawing from the same global stream the pre-ESV-3a inline
    ``random.uniform(...)`` calls used, or a seeded ``random.Random`` for
    tests)."""

    def __init__(self, params, *, rng):
        self._params = params
        self._rng = rng
        self._particles = []
        self._gold = []
        self._slashes = []
        self._splatters = []

    # -- emit ---------------------------------------------------------------

    def emit_burst(self, kind_params, wx, wy):
        """A spark-style burst. ``kind_params`` is an explicit
        ``params.BurstParams`` — spark preset keys (``"place"``/``"tier"``/
        ...) are game vocabulary, resolved by the caller before this call."""
        self._particles.extend(
            emitters.emit_burst(self._rng, wx, wy, kind_params))

    def emit_shards(self, wx, wy):
        """A building-death shard burst, from the held ``death_burst``
        params."""
        self._particles.extend(
            emitters.emit_shards(self._rng, wx, wy, self._params.death_burst))

    def emit_muzzle(self, wx, wy, strong=False):
        """A ranged-attack muzzle spray, from the held ``muzzle`` params."""
        self._particles.extend(emitters.emit_muzzle(
            self._rng, wx, wy, self._params.muzzle, strong))

    def emit_slash(self, wx, wy, large=False):
        """A melee slash, from the held ``slash`` params."""
        self._slashes.append(emitters.emit_slash(
            self._rng, wx, wy, large, self._params.slash))

    def emit_gold(self, col, row):
        """A gold tile highlight, from the held ``gold`` params."""
        self._gold.append(emitters.emit_gold(col, row, self._params.gold))

    def add_splatters(self, points):
        """Extend the ground blood marks with world ``(wx, wy)`` points (no
        emitter — a splatter carries no per-instance RNG state)."""
        self._splatters.extend(points)

    def clear_splatters(self):
        self._splatters.clear()

    def clear(self):
        self._particles.clear()
        self._gold.clear()
        self._slashes.clear()
        self._splatters.clear()

    # -- update ---------------------------------------------------------------

    def update(self, dt):
        for p in self._particles:
            p.step(dt)
        self._particles = [p for p in self._particles if p.age < p.life]
        for g in self._gold:
            g.age += dt
        self._gold = [g for g in self._gold if g.age < g.life]
        for s in self._slashes:
            s.age += dt
        self._slashes = [s for s in self._slashes if s.age < s.life]

    # -- submit ---------------------------------------------------------------

    def submit_hud(self, renderer, cs):
        """Particles + slashes as screen-space HUD primitives (offsets are
        base-zoom pixels around the anchor, scaled by the live zoom)."""
        zoom = cs.camera.zoom
        for p in self._particles:
            cx, cy = cs.world_to_screen(p.wx, p.wy)
            w = max(1, int(p.size[0] * zoom))
            h = max(1, int(p.size[1] * zoom))
            renderer.submit_hud(HudRect(
                (int(cx + p.ox * zoom), int(cy + p.oy * zoom), w, h),
                p.color()))
        for s in self._slashes:
            cx, cy = cs.world_to_screen(s.wx, s.wy)
            for x1, y1, x2, y2, color in s.lines:
                renderer.submit_hud(HudLines(
                    ((int(cx + x1 * zoom), int(cy + y1 * zoom)),
                     (int(cx + x2 * zoom), int(cy + y2 * zoom))),
                    color, width=2))

    def submit_splatters(self, renderer, cs):
        """Ground blood marks: a small alpha polygon approximation of a
        circle, projected to the 2:1 iso ground plane. World-space overlay."""
        sp = self._params.splatter
        r = sp.radius_px / (cs.geometry.tile_w / 2.0)
        j = sp.jitter
        for wx, wy in self._splatters:
            pts = [(wx, wy - r), (wx + r, wy), (wx, wy + r), (wx - r, wy),
                   (wx + r * j, wy - r * j), (wx - r * j, wy + r * j)]
            pts = [pts[0], pts[4], pts[1], pts[2], pts[5], pts[3]]
            renderer.submit_overlay_polys(pts, sp.color + (sp.alpha,))

    def submit_gold_highlights(self, renderer):
        """The gold diamond fill + border on freshly built / tier-advanced
        tiles."""
        gp = self._params.gold
        for g in self._gold:
            frac = g.frac()
            pts = [(g.col, g.row), (g.col + 1, g.row),
                   (g.col + 1, g.row + 1), (g.col, g.row + 1)]
            renderer.submit_overlay_polys(
                pts, gp.fill_color + (int(gp.fill_alpha * frac),))
            renderer.submit_overlay_lines(
                pts, tuple(int(c * frac) for c in gp.border_color),
                width=gp.border_width, closed=True)
