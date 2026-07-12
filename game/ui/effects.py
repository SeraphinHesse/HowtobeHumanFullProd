"""World-anchored UI: income/upkeep floaters + building HP bars (Phase 9G).

Pure logic. World-anchored elements compute their screen position through the
coords authority (``cs.world_to_screen``) — so they track the camera — and are
emitted as screen-space HUD primitives (always drawn on top; non-sprite HP bars
are not depth-sorted against buildings, an accepted "HUD on top" simplification
that only shows when a building is damaged). Ports the prototype's
``IncomeFloater`` / ``Building._draw_hp_bar``. The rich VFX set (spark bursts,
gold highlights, blood, muzzle/slash) is the 10J sweep.
"""
import random  # 10H: per-frame bolt jitter (stdlib — pure)

from engine.core import Health
from engine.render import HudLines
from game.buildings.components import BeamAttacker, TierState

from .widgets import (
    C_GOLD, C_HP_GREEN, C_HP_RED, HEART, submit_bar, submit_centered,
)

_UPKEEP_BLUE = (120, 170, 230)
_XP_PURPLE = (202, 140, 245)
_XP_LIFE = 0.9  # prototype XPFloater lifetime (seconds)
# Painter message floaters (Phase 10C): gold "painting finished" on a payout,
# red "painting lost!" when a gone-for-good painter dies. Prototype life 1.5s.
_PAINTER_FINISHED = (255, 255, 100)
_PAINTER_LOST = (255, 100, 100)
_PAINTER_LIFE = 1.5
_BOOST_WHITE = (255, 255, 255)   # prototype boost floater colour

# Sun Scorcher beam colour per tier (prototype outer-beam colour, simplified to
# one line since the HUD pass has no per-pixel alpha for a glow — 10J polish):
# yellow -> orange -> red as the line thickens with tier.
_BEAM_COLORS = ((255, 200, 40), (255, 110, 15), (210, 20, 10))
_CRATER_COLOR = (120, 78, 66)   # spent-shell scorch (world-space diamond)

# -- 10H: lightning + cheat menu --
# Bolt colour ramp (white -> yellow over BOLT_LIFE) + the ground-marker yellow
# (prototype effects.py:222-289 fill (255,240,120)). 8-segment polyline, ±6 px
# horizontal jitter re-rolled every frame — prototype-exact.
_BOLT_SEGMENTS = 8
_BOLT_JITTER = 6
_BOLT_WHITE = (255, 255, 255)
_BOLT_YELLOW = (255, 240, 80)
_LIGHTNING_MARKER = (255, 240, 120)
# -- /10H --


class _Floater:
    __slots__ = ("wx", "wy", "text", "color", "age", "life")

    def __init__(self, wx, wy, text, color, life):
        self.wx = wx
        self.wy = wy
        self.text = text
        self.color = color
        self.age = 0.0
        self.life = life


class FloaterManager:
    """Income/upkeep floaters spawned at payday + per-building HP bars.

    ``spawn_income_events`` is called once when the phase enters INCOME; it reads
    ``state.income_events`` (filled by ``run_payday``) so it never re-derives the
    payday math. Gated by ``ui.FX.income_floaters_enabled``; floater lifetime is
    the income phase duration (``core.PhaseLoop.income_phase_duration``).
    """

    def __init__(self, ui_balance, core_balance):
        self._enabled = ui_balance["FX"]["income_floaters_enabled"]
        self._life = core_balance["PhaseLoop"]["income_phase_duration"]
        self._floaters = []

    def spawn_income_events(self, state):
        if not self._enabled:
            return
        for col, row, amount, kind in state.income_events:
            color = C_GOLD if kind == "income" else _UPKEEP_BLUE
            text = f"+{amount}{HEART}" if amount >= 0 else str(amount)
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, color, self._life))

    def spawn_xp_events(self, state):
        """Drain ``state.xp_events`` (filled by the Session's XP award sites)
        into short purple floaters. Called every frame — XP is granted mid-combat,
        not once at a phase edge like income. The prototype's ``xp_icon`` sprite
        has no slot in this repo, so the floater is text-only (10J)."""
        for wx, wy, amount in state.xp_events:
            self._floaters.append(
                _Floater(wx, wy, f"+{amount}", _XP_PURPLE, _XP_LIFE))
        state.xp_events.clear()

    def spawn_painter_events(self, state):
        """Drain ``state.painter_events`` (filled by the payday Painter slot +
        revive) into 1.5s message floaters — gold "painting finished", red
        "painting lost!". Called on the INCOME edge beside the income floaters."""
        for col, row, text, kind in state.painter_events:
            color = _PAINTER_FINISHED if kind == "finished" else _PAINTER_LOST
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, color, _PAINTER_LIFE))
        state.painter_events.clear()

    def spawn_boost_events(self, state):
        """Drain ``state.boost_events`` (filled by the payday boost slot) into white
        per-turn boost floaters over each buffed defender — prototype white text.
        Called on the INCOME edge beside the income floaters."""
        for col, row, text in state.boost_events:
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, _BOOST_WHITE, self._life))
        state.boost_events.clear()

    def clear(self):
        self._floaters.clear()

    def update(self, dt):
        for f in self._floaters:
            f.age += dt
        self._floaters = [f for f in self._floaters if f.age < f.life]

    @property
    def active(self):
        return len(self._floaters)

    def submit(self, renderer, cs):
        for f in self._floaters:
            frac = f.age / f.life if f.life else 1.0
            cx, cy = cs.world_to_screen(f.wx, f.wy)
            y = int(cy) - 20 - int(36 * frac)  # rise over its lifetime
            submit_centered(renderer, f.text, int(cx), y, "md", f.color)

    def submit_beams(self, renderer, cs, scene):
        """A per-tier colored line from each firing Sun Scorcher to its target
        (Phase 10B). Reads the live ``BeamAttacker._target`` the combat sweep
        sets — so the beam shows only while the beam is actually engaging and
        vanishes during its target-death cooldown. Screen-space HudLines (no
        alpha glow — 10J)."""
        for b in scene.by_tag("combat"):
            beam = b.get_component(BeamAttacker)
            if beam is None:
                continue
            target = getattr(beam, "_target", None)
            if target is None or not getattr(target, "alive", False):
                continue
            tier = b.get_component(TierState).current_tier
            color = _BEAM_COLORS[min(tier, len(_BEAM_COLORS) - 1)]
            ox, oy = cs.world_to_screen(b.transform.wx + 0.5, b.transform.wy + 0.5)
            tx, ty = cs.world_to_screen(target.transform.wx + 0.5,
                                        target.transform.wy + 0.5)
            top = int(cs.geometry.tile_h * cs.camera.zoom)  # crystal-ball height
            renderer.submit_hud(HudLines(
                ((int(ox), int(oy) - top), (int(tx), int(ty))),
                color, width=2 + tier))

    def submit_craters(self, renderer, cs, scene):
        """A fading world-space diamond where each mortar shell landed (Phase
        10B). Purely cosmetic — the ``Crater`` GameObjects age + self-despawn in
        the scene; here we just draw them, fading the colour toward black over
        the crater's life (the HUD/overlay pass has no alpha — 10J)."""
        for c in scene.by_tag("crater"):
            frac = c.fade_frac
            r = c.radius
            cx, cy = c.transform.world_pos
            color = tuple(int(ch * frac) for ch in _CRATER_COLOR)
            pts = [(cx + 0.5, cy + 0.5 - r), (cx + 0.5 + r, cy + 0.5),
                   (cx + 0.5, cy + 0.5 + r), (cx + 0.5 - r, cy + 0.5)]
            renderer.submit_overlay_lines(pts, color, width=2, closed=True)

    # -- 10H: lightning + cheat menu ---------------------------------------

    def submit_lightning(self, renderer, cs, scene):
        """Bolt + ground marker for each live ``"lightning_fx"`` object (Phase
        10H, prototype ``effects.py LightningEffect``): (1) a jagged
        screen-space polyline from the top of the screen (y=0) down to the
        impact point — ±6 px horizontal jitter re-rolled every frame, colour
        fading white -> yellow over the 0.5 s bolt life; (2) a fading yellow
        world-space diamond sized to the REAL blast radius (the crater
        pattern; a world diamond of r tiles projects to a 2:1 screen lozenge —
        exactly the prototype's w = 2r, h = r ground ellipse). The alpha
        impact-flash circle is 10J (no per-pixel alpha in the HUD/overlay
        pass). The FX objects age + self-despawn in the scene on the host's
        ENEMY-scaled sim dt; here we only draw them."""
        for fx in scene.by_tag("lightning_fx"):
            wx, wy = fx.transform.world_pos
            bolt = fx.bolt_frac
            if bolt > 0:
                sx, sy = cs.world_to_screen(wx, wy)
                pts = []
                for i in range(_BOLT_SEGMENTS + 1):
                    t = i / _BOLT_SEGMENTS
                    jitter = (random.uniform(-_BOLT_JITTER, _BOLT_JITTER)
                              if 0 < i < _BOLT_SEGMENTS else 0.0)
                    pts.append((int(sx + jitter), int(sy * t)))
                # white -> yellow along the fade, darkening out (no alpha).
                progress = 1.0 - bolt
                color = tuple(
                    int((w + (yl - w) * progress) * bolt)
                    for w, yl in zip(_BOLT_WHITE, _BOLT_YELLOW))
                renderer.submit_hud(HudLines(tuple(pts), color, width=2))
            frac = fx.fade_frac
            if frac > 0:
                r = fx.radius_tiles
                color = tuple(int(ch * frac) for ch in _LIGHTNING_MARKER)
                pts = [(wx, wy - r), (wx + r, wy), (wx, wy + r), (wx - r, wy)]
                renderer.submit_overlay_lines(pts, color, width=2, closed=True)

    # -- /10H ---------------------------------------------------------------

    def submit_hp_bars(self, renderer, cs, scene):
        """A red/green bar over every non-base building below full HP (prototype
        hides the bar at full HP)."""
        zoom = cs.camera.zoom
        tile_h = cs.geometry.tile_h
        for b in scene.by_tag("building"):
            if getattr(b, "building_type", None) == "base":
                continue
            health = b.get_component(Health)
            if health is None or health.hp >= health.max_hp:
                continue
            cx, cy = cs.world_to_screen(b.transform.wx + 0.5,
                                        b.transform.wy + 0.5)
            w, h = 28, 4
            x = int(cx - w / 2)
            y = int(cy - tile_h * zoom)  # a little above the tile centre
            submit_bar(renderer, x, y, w, h, health.hp / health.max_hp,
                       bg=C_HP_RED, fill=C_HP_GREEN, border=(0, 0, 0))
