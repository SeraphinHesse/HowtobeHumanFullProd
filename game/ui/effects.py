"""World-anchored UI: income/upkeep floaters + building & enemy HP bars (Phase
9G) + the 10J FX sweep (spark bursts, gold tile highlights, building death
bursts, muzzle/slash attack FX, blood splatters).

Pure logic. World-anchored elements compute their screen position through the
coords authority (``cs.world_to_screen``) — so they track the camera — and are
emitted as screen-space HUD primitives (always drawn on top; non-sprite HP bars
are not depth-sorted against buildings, an accepted "HUD on top" simplification
that only shows when a building is damaged). Ports the prototype's
``IncomeFloater`` / ``Building._draw_hp_bar`` / ``Enemy._draw_hp_bar`` /
``src/effects.py`` VFX set.

10J particles simulate in BASE-ZOOM screen pixels relative to their anchor's
world point (offsets scale with ``cs.camera.zoom`` at draw), which keeps the
prototype's pixel velocities/gravity meaningful without iso math outside
``engine.coords``. Enemy attack FX need no core hook: ``watch_enemies`` treats
an ``EnemyCombat.cooldown`` reset while blocked as "an attack just landed"
(the drained-ledger/watcher house pattern).
"""
import random  # 10H bolt jitter / 10J particle spread (stdlib — pure)

from engine.core import Health, SpriteAnimator
from engine.render import HudLines, HudRect, block_center_offset, fit_factor
from engine.render.fonts import layout_h
from game.buildings.components import BeamAttacker, Nameplate, TierState
from game.core.phases import GamePhase

from .widgets import (
    C_GOLD, C_HP_GREEN, C_HP_RED, C_UI_TEXT, HEART, submit_bar,
    submit_centered, submit_text,
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

# -- 10G boss: announcement + HP-bar constants ------------------------------
_ANNOUNCE_RED = (220, 40, 40)      # prototype banner colour (10J: alpha fade)
_ANNOUNCE_L1 = "SOMETHING BIG"
_ANNOUNCE_L2 = "IS APPROACHING!"
_BOSS_HUD_BAR_W, _BOSS_HUD_BAR_H = 200, 12   # bottom-centre bar (hud.py:356)
_BOSS_HUD_BAR_LIFT = 55                      # y = view_h - 55
# Every OVERHEAD bar (boss included) comes from `submit_enemy_hp_bars`. Width
# and height are the `HP_BAR_W`/`HP_BAR_H` class attrs on the enemy classes
# (base-zoom px). The LIFT is NOT a constant: since ER-1 a sprite's on-screen
# size derives from its tile footprint, not its sheet, so the bar is placed
# against the sprite's real DRAWN top edge (`_sprite_top`) and `HP_BAR_PAD` is
# only the gap above its head.
_ENEMY_BAR_STACK = 4       # px between stacked bars (prototype `bar_slot * 4`)
_ENEMY_BAR_FALLBACK = (14, 2, 4)   # a stub enemy with no HP_BAR_* attrs
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

# -- 10J FX presets (prototype src/effects.py; timings/counts verbatim, the
# spark/shard velocities are px/s in the prototype's world-pixel space) ------
_SPARK_PRESETS = {          # kind: (life s, particle count)
    "place": (0.75, 10),
    "level1": (0.55, 7),
    "level2": (0.88, 16),
    "tier": (1.20, 26),
}
_SPARK_GRAVITY = 55.0       # px/s^2 (prototype SparkBurst)
_SPARK_RAMP = (             # colour by age: yellow -> orange -> red
    (255, 230, 80), (255, 150, 40), (210, 60, 30))
_GOLD_LIFE = 1.20           # TileGoldHighlight: in 0.15 / hold 0.35 / out 0.70
_GOLD_IN, _GOLD_HOLD = 0.15, 0.35
_GOLD_FILL = (255, 215, 0)      # alpha <= 90 (needs the 10J overlay alpha)
_GOLD_BORDER = (255, 240, 80)   # alpha <= 200
_DEATH_LIFE = 0.65          # BuildingDeathEffect: 14 purple shards
_DEATH_COUNT = 14
_DEATH_GRAVITY = 60.0
_DEATH_COLORS = ((150, 90, 200), (120, 70, 170), (180, 120, 230))
_MUZZLE_LIFE, _MUZZLE_LIFE_STRONG = 0.20, 0.32
_MUZZLE_COUNT, _MUZZLE_COUNT_STRONG = 8, 13
_MUZZLE_RAMP = ((255, 230, 120), (220, 90, 50), (130, 30, 20))
_MUZZLE_SMOKE = (100, 80, 80)   # 25% of particles
_SLASH_LIFE = 0.28
_SLASH_COLORS = ((220, 230, 255), (200, 215, 245), (255, 255, 255))
_SPLATTER_COLOR = (180, 30, 30)  # prototype fallback red, r=4 px
_SPLATTER_ALPHA = 170
_PROJECTILE_STONE = (185, 180, 170)  # defender stone (prototype gray circle)
_PROJECTILE_SHELL = (70, 60, 55)     # mortar shell (darker, larger)
# -- /10J --


def _sprite_top(renderer, cs, enemy, cy, zoom):
    """Screen y of the TOP edge of `enemy`'s sprite as the renderer will draw it
    this frame.

    The renderer centres a frame on the tile diamond's centre and fits it to the
    unit's footprint (`engine/render`), and `cy` — `world_to_screen(wx+0.5,
    wy+0.5)` — IS that centre, so the top edge is half the DRAWN height above it.
    The drawn height is the frame's, through the SAME `fit_factor` flush() uses:
    a sheet's raw pixels no longer say how big it renders.

    A MULTI-TILE unit is drawn on its block's centre, not on the anchor tile `cy`
    names (ER-5), so the bar has to ride the same shift — through the engine's own
    `block_center_offset`, never a restated copy of it. Zero for a 1-tile unit.

    Falls back to `cy` (the tile centre) when there is no sprite or no store to
    size it from — a stub enemy in a headless test still gets a bar.
    """
    assets = getattr(renderer, "assets", None)
    anim = enemy.get_component(SpriteAnimator)
    if assets is None or anim is None or not anim.slot_key:
        return cy
    frame_w, frame_h = assets.frame_size(anim.slot_key)
    s = fit_factor(frame_w, cs.geometry.tile_w, anim.fit_tiles) * anim.scale
    block = block_center_offset(anim.fit_tiles) * cs.geometry.tile_h * zoom
    return cy + block - (frame_h * zoom * s) / 2


class _Floater:
    __slots__ = ("wx", "wy", "text", "color", "age", "life")

    def __init__(self, wx, wy, text, color, life):
        self.wx = wx
        self.wy = wy
        self.text = text
        self.color = color
        self.age = 0.0
        self.life = life


class _Particle:
    """One 10J spark/shard/muzzle mote: a world anchor + a base-zoom pixel
    offset integrated with velocity + gravity. ``ramp`` colours by age;
    ``size`` is the base-zoom rect size."""

    __slots__ = ("wx", "wy", "ox", "oy", "vx", "vy", "gravity", "age", "life",
                 "ramp", "size")

    def __init__(self, wx, wy, vx, vy, gravity, life, ramp, size=(2, 2)):
        self.wx = wx
        self.wy = wy
        self.ox = 0.0
        self.oy = 0.0
        self.vx = vx
        self.vy = vy
        self.gravity = gravity
        self.age = 0.0
        self.life = life
        self.ramp = ramp
        self.size = size

    def step(self, dt):
        self.age += dt
        self.vy += self.gravity * dt
        self.ox += self.vx * dt
        self.oy += self.vy * dt

    def color(self):
        frac = min(0.999, self.age / self.life) if self.life else 0.999
        return self.ramp[int(frac * len(self.ramp))]


class _GoldHighlight:
    """A fading gold diamond on a just-built / tier-advanced tile (prototype
    ``TileGoldHighlight``): fade in 0.15 s, hold 0.35 s, fade out 0.70 s."""

    __slots__ = ("col", "row", "age")

    def __init__(self, col, row):
        self.col = col
        self.row = row
        self.age = 0.0

    def frac(self):
        if self.age < _GOLD_IN:
            return self.age / _GOLD_IN
        if self.age < _GOLD_IN + _GOLD_HOLD:
            return 1.0
        out = _GOLD_LIFE - _GOLD_IN - _GOLD_HOLD
        return max(0.0, 1.0 - (self.age - _GOLD_IN - _GOLD_HOLD) / out)


class _Slash:
    """2-3 diagonal white/blue lines over a melee attacker (prototype
    ``SlashEffect``); ``large`` for the boss."""

    __slots__ = ("wx", "wy", "age", "lines")

    def __init__(self, wx, wy, large, rng=random):
        self.wx = wx
        self.wy = wy
        self.age = 0.0
        size = 11 if large else 7
        self.lines = []
        for _ in range(rng.randint(2, 3)):
            ox = rng.uniform(-6, 6)
            oy = rng.uniform(-10, 2)
            self.lines.append((ox - size, oy - size, ox + size, oy + size,
                               rng.choice(_SLASH_COLORS)))


class FloaterManager:
    """Income/upkeep floaters spawned at payday + per-building/per-enemy HP bars.

    ``spawn_income_events`` is called once when the phase enters INCOME; it reads
    ``state.income_events`` (filled by ``run_payday``) so it never re-derives the
    payday math. Gated by ``ui.FX.income_floaters_enabled``; floater lifetime is
    the income phase duration (``core.PhaseLoop.income_phase_duration``).
    """

    def __init__(self, ui_balance, core_balance):
        self._enabled = ui_balance["FX"]["income_floaters_enabled"]
        self._life = core_balance["PhaseLoop"]["income_phase_duration"]
        self._floaters = []
        # -- 10G boss announcement: timings from ui.FX.boss_announce; the age
        # clock is None while no announcement runs.
        self._announce = ui_balance["FX"]["boss_announce"]
        self._announce_age = None
        # -- 10J FX state --
        self._gore_enabled = ui_balance["FX"]["gore_enabled"]
        self._particles = []      # sparks / death shards / muzzle motes
        self._gold = []           # _GoldHighlight diamonds
        self._slashes = []        # _Slash melee FX
        self._splatters = []      # (wx, wy) blood marks; cleared per round
        self._building_alive = {} # id(building) -> alive (death watcher)
        self._enemy_cooldowns = {}  # id(enemy) -> last EnemyCombat.cooldown
        self.log = None           # GameLog, wired by the host
        # -- /10J --

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
            if self.log is not None and kind == "lost":  # 10J game log
                self.log.post(text)
        state.painter_events.clear()

    def spawn_boost_events(self, state):
        """Drain ``state.boost_events`` (filled by the payday boost slot) into white
        per-turn boost floaters over each buffed defender — prototype white text.
        Called on the INCOME edge beside the income floaters."""
        for col, row, text in state.boost_events:
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, _BOOST_WHITE, self._life))
        state.boost_events.clear()

    # -- 10J FX: sparks, gold highlights, death bursts, muzzle/slash, blood --

    def spawn_building_vfx(self, col, row, kind):
        """Placement/upgrade celebration (prototype ``spawn_building_vfx``,
        game.py:619-626): always a spark burst; ``place``/``tier`` add the
        gold tile highlight. ``kind`` in place / level1 / level2 / tier."""
        life, count = _SPARK_PRESETS.get(kind, _SPARK_PRESETS["place"])
        wx, wy = col + 0.5, row + 0.5
        for _ in range(count):
            # upward-biased gold spray (prototype SparkBurst)
            self._particles.append(_Particle(
                wx, wy, random.uniform(-28, 28), random.uniform(-70, -20),
                _SPARK_GRAVITY, life, _SPARK_RAMP,
                size=(2, 2)))
        if kind in ("place", "tier"):
            self._gold.append(_GoldHighlight(col, row))

    def watch_buildings(self, scene, log=None):
        """Building-death watcher (called every frame): a non-base building
        whose ``alive`` flipped to False this frame bursts 14 purple shards
        (prototype ``BuildingDeathEffect``) and logs the kill when it carries
        a custom name (prototype game.py:710-717)."""
        seen = set()
        for b in scene.by_tag("building"):
            if getattr(b, "building_type", None) == "base":
                continue
            key = id(b)
            seen.add(key)
            alive = getattr(b, "alive", True)
            was_alive = self._building_alive.get(key, True)
            self._building_alive[key] = alive
            if alive or not was_alive:
                continue
            wx, wy = b.transform.wx + 0.5, b.transform.wy + 0.5
            for _ in range(_DEATH_COUNT):
                self._particles.append(_Particle(
                    wx, wy, random.uniform(-45, 45), random.uniform(-80, -10),
                    _DEATH_GRAVITY, _DEATH_LIFE,
                    (random.choice(_DEATH_COLORS),),
                    size=(random.randint(2, 4), random.randint(2, 5))))
            np = b.get_component(Nameplate)
            if log is not None and np is not None and np.custom_name:
                log.post(f"{np.custom_name} has been killed")
        # drop stale ids so a long run can't grow the map unbounded
        if len(self._building_alive) > 2 * len(seen) + 16:
            self._building_alive = {
                k: v for k, v in self._building_alive.items() if k in seen}

    def watch_enemies(self, scene):
        """Enemy attack FX watcher (called every frame during ENEMY): an
        ``EnemyCombat.cooldown`` that RESET (grew) while the enemy is blocked
        means an attack just landed — raider/boss show a melee slash, the
        rest a muzzle spray, strong for the siege cannon (prototype
        enemy.py:222 / siege_cannon.py:109 / raider.py:48 / boss.py:104)."""
        from game.enemies.components import EnemyCombat, PathAgent

        seen = set()
        for e in scene.by_tag("enemy"):
            key = id(e)
            seen.add(key)
            ec = e.get_component(EnemyCombat)
            pa = e.get_component(PathAgent)
            if ec is None:
                continue
            last = self._enemy_cooldowns.get(key)
            self._enemy_cooldowns[key] = ec.cooldown
            if (last is None or ec.cooldown <= last
                    or pa is None or not pa.blocked):
                continue
            wx, wy = e.transform.world_pos
            etype = getattr(e, "ETYPE", "standard")
            if etype in ("raider", "boss"):
                self._slashes.append(_Slash(wx, wy, large=(etype == "boss")))
            else:
                strong = etype == "siege"
                life = _MUZZLE_LIFE_STRONG if strong else _MUZZLE_LIFE
                count = _MUZZLE_COUNT_STRONG if strong else _MUZZLE_COUNT
                for _ in range(count):
                    ramp = (_MUZZLE_SMOKE,) if random.random() < 0.25 \
                        else _MUZZLE_RAMP
                    # leftward spray toward the attacked building (prototype
                    # angle band pi*0.65..1.35)
                    self._particles.append(_Particle(
                        wx, wy, random.uniform(-90, -30),
                        random.uniform(-35, 35), 0.0, life, ramp))
        if len(self._enemy_cooldowns) > 2 * len(seen) + 16:
            self._enemy_cooldowns = {
                k: v for k, v in self._enemy_cooldowns.items() if k in seen}

    def spawn_death_events(self, state, gore_on):
        """Drain ``state.enemy_death_events`` (filled by the Session death /
        base-hit callbacks) into ground blood splatters. Gated by
        ``ui.FX.gore_enabled`` AND the settings toggle — both must be on
        (prototype game.py:1898-99); the ledger drains either way."""
        if not state.enemy_death_events:
            return
        events, state.enemy_death_events = state.enemy_death_events, []
        if not (self._gore_enabled and gore_on):
            return
        self._splatters.extend(events)

    def clear_splatters(self):
        """Previous round's blood clears when the next wave starts (prototype
        ``clear_splatters`` on End Turn, game.py:815)."""
        self._splatters.clear()

    # -- /10J -----------------------------------------------------------------

    def clear(self):
        self._floaters.clear()
        self._announce_age = None
        # -- 10J --
        self._particles.clear()
        self._gold.clear()
        self._slashes.clear()
        self._splatters.clear()
        # -- /10J --

    def update(self, dt):
        for f in self._floaters:
            f.age += dt
        self._floaters = [f for f in self._floaters if f.age < f.life]
        # -- 10G boss: advance the announcement clock --
        if self._announce_age is not None:
            self._announce_age += dt
            a = self._announce
            if self._announce_age >= a["fade_in"] + a["hold"] + a["fade_out"]:
                self._announce_age = None
        # -- 10J particles / highlights / slashes --
        for p in self._particles:
            p.step(dt)
        self._particles = [p for p in self._particles if p.age < p.life]
        for g in self._gold:
            g.age += dt
        self._gold = [g for g in self._gold if g.age < _GOLD_LIFE]
        for s in self._slashes:
            s.age += dt
        self._slashes = [s for s in self._slashes if s.age < _SLASH_LIFE]
        # -- /10J --

    @property
    def active(self):
        return len(self._floaters)

    def submit(self, renderer, cs):
        for f in self._floaters:
            frac = f.age / f.life if f.life else 1.0
            cx, cy = cs.world_to_screen(f.wx, f.wy)
            y = int(cy) - 20 - int(36 * frac)  # rise over its lifetime
            # 10J: alpha fade over the last third (prototype fade = life/3)
            color = f.color
            if frac > 2 / 3:
                color = tuple(color[:3]) + (
                    int(255 * max(0.0, (1.0 - frac) * 3)),)
            submit_centered(renderer, f.text, int(cx), y, "md", color)

    # -- 10J FX draw --------------------------------------------------------

    def submit_splatters(self, renderer, cs):
        """Ground blood marks: a small red alpha ellipse per death (polygon
        approximation of the prototype's r=4 px fallback circle, projected to
        the 2:1 iso ground plane). World-space overlay — drawn under the HUD
        but over the tiles."""
        r = 4.0 / (cs.geometry.tile_w / 2.0)  # 4 px at zoom 1 -> world units
        for wx, wy in self._splatters:
            pts = [(wx, wy - r), (wx + r, wy), (wx, wy + r), (wx - r, wy),
                   (wx + r * 0.6, wy - r * 0.6), (wx - r * 0.6, wy + r * 0.6)]
            # diamond + two jitter points ~= a blobby ellipse after projection
            pts = [pts[0], pts[4], pts[1], pts[2], pts[5], pts[3]]
            renderer.submit_overlay_polys(
                pts, _SPLATTER_COLOR + (_SPLATTER_ALPHA,))

    def submit_gold_highlights(self, renderer):
        """The gold diamond fill + border on freshly built / tier-advanced
        tiles (prototype fill alpha <= 90, border alpha <= 200)."""
        for g in self._gold:
            frac = g.frac()
            pts = [(g.col, g.row), (g.col + 1, g.row),
                   (g.col + 1, g.row + 1), (g.col, g.row + 1)]
            renderer.submit_overlay_polys(
                pts, _GOLD_FILL + (int(90 * frac),))
            renderer.submit_overlay_lines(
                pts, tuple(int(c * frac) for c in _GOLD_BORDER),
                width=2, closed=True)

    def submit_projectiles(self, renderer, cs, scene):
        """In-flight shots (10J): the plain defender stone as a small light
        dot, the mortar shell darker and larger (prototype's procedural
        projectile art; 9E left them logical-only). Read live off the scene
        like the HP bars — homing shots track their target every frame."""
        zoom = cs.camera.zoom
        for p in scene.by_tag("projectile"):
            wx, wy = p.transform.world_pos
            cx, cy = cs.world_to_screen(wx, wy)
            shell = p.name == "shell"
            size = max(2, int((5 if shell else 3) * zoom))
            color = _PROJECTILE_SHELL if shell else _PROJECTILE_STONE
            # lift the dot off the ground plane so it reads as flying
            lift = int(cs.geometry.tile_h * zoom * 0.6)
            renderer.submit_hud(HudRect(
                (int(cx - size / 2), int(cy - lift - size / 2), size, size),
                color, border_radius=size // 2))

    def submit_fx(self, renderer, cs):
        """Screen-space particle FX: sparks / death shards / muzzle motes as
        small filled rects, melee slashes as diagonal lines. Offsets are
        base-zoom pixels around the anchor, scaled by the live zoom."""
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
        """A fading world-space scorch where each mortar shell landed (Phase
        10B). Purely cosmetic — the ``Crater`` GameObjects age + self-despawn in
        the scene; since 10J the diamond is alpha-FILLED and fades by alpha
        (prototype's SRCALPHA ground ellipse)."""
        for c in scene.by_tag("crater"):
            frac = c.fade_frac
            r = c.radius
            cx, cy = c.transform.world_pos
            pts = [(cx + 0.5, cy + 0.5 - r), (cx + 0.5 + r, cy + 0.5),
                   (cx + 0.5, cy + 0.5 + r), (cx + 0.5 - r, cy + 0.5)]
            renderer.submit_overlay_polys(
                pts, _CRATER_COLOR + (int(150 * frac),))

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
            if bolt > 0:
                # 10J: the expanding alpha impact flash (prototype
                # effects.py:222-290 — flash radius grows to ~20 px). An
                # 8-gon in world units projects to the 2:1 ground ellipse.
                fr = (1.0 - bolt) * (20.0 / (cs.geometry.tile_w / 2.0))
                if fr > 0:
                    k = 0.7071 * fr
                    pts = [(wx, wy - fr), (wx + k, wy - k), (wx + fr, wy),
                           (wx + k, wy + k), (wx, wy + fr), (wx - k, wy + k),
                           (wx - fr, wy), (wx - k, wy - k)]
                    renderer.submit_overlay_polys(
                        pts, (255, 250, 200, int(200 * bolt)))
            frac = fx.fade_frac
            if frac > 0:
                r = fx.radius_tiles
                pts = [(wx, wy - r), (wx + r, wy), (wx, wy + r), (wx - r, wy)]
                # 10J: alpha-filled ground marker fading out (prototype fill);
                # the outline keeps the old colour-fade (lines carry no alpha)
                renderer.submit_overlay_polys(
                    pts, _LIGHTNING_MARKER + (int(120 * frac),))
                renderer.submit_overlay_lines(
                    pts, tuple(int(ch * frac) for ch in _LIGHTNING_MARKER),
                    width=2, closed=True)

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

    def submit_enemy_hp_bars(self, renderer, cs, scene):
        """A red/green bar over every live enemy below full HP — the boss
        included (its ``"enemy"`` tag comes free with ``Enemy.EXTRA_TAGS``, and
        its ``HP_BAR_W/H`` make it the wide 48x4 bar it has always had).

        Enemies bunch up hard at a choke point, so bars from enemies sharing a
        tile STACK upward instead of smearing over each other (prototype
        ``game.py:1901-1922`` groups by nearest tile and hands each enemy a
        ``bar_slot``). Grouping is a plain ``round()`` here — the prototype
        divided pixel coords by the tile half-dims; ``transform.wx/wy`` are
        already fractional TILE coords.

        Divergence: the prototype gave a slot to EVERY enemy in a group,
        full-HP ones included (leaving gaps in the stack), because that index
        also drove its sprite-spread ellipse. We do not port the spread, so
        slots are handed out COMPACTLY — only a bar-drawing enemy takes one.
        """
        groups = {}
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            key = (round(e.transform.wx), round(e.transform.wy))
            groups.setdefault(key, []).append(e)

        zoom = cs.camera.zoom
        for group in groups.values():
            slot = 0
            for e in group:
                health = e.get_component(Health)
                if health is None or health.hp >= health.max_hp:
                    continue
                w = getattr(e, "HP_BAR_W", _ENEMY_BAR_FALLBACK[0])
                h = getattr(e, "HP_BAR_H", _ENEMY_BAR_FALLBACK[1])
                pad = getattr(e, "HP_BAR_PAD", _ENEMY_BAR_FALLBACK[2])
                cx, cy = cs.world_to_screen(e.transform.wx + 0.5,
                                            e.transform.wy + 0.5)
                # Hang the bar off the sprite's head: its BOTTOM edge sits `pad`
                # above the drawn top edge. The sprite grows with the camera, so
                # both terms ride the zoom — but the bar itself stays a fixed
                # screen size (every other bar in this file does).
                top = _sprite_top(renderer, cs, e, cy, zoom)
                x = int(cx - w / 2)
                y = int(top - pad * zoom) - h - slot * _ENEMY_BAR_STACK
                submit_bar(renderer, x, y, w, h, health.hp / health.max_hp,
                           bg=C_HP_RED, fill=C_HP_GREEN)
                slot += 1

    # -- 10G boss: announcement + boss HP bars ------------------------------

    def spawn_boss_events(self, state):
        """Drain ``state.boss_events`` (one marker per boss-round End Turn,
        queued by ``Session.end_turn``) into the two-line announcement. The
        enabled gate is ``ui.FX.boss_announce.enabled`` — it lives HERE, not in
        the session, so core stays free of ui balance."""
        if not state.boss_events:
            return
        state.boss_events.clear()
        if not self._announce["enabled"]:
            return
        self._announce_age = 0.0

    def submit_announce(self, renderer, view_w, view_h):
        """The screen-centred "SOMETHING BIG / IS APPROACHING!" banner
        (prototype ``effects.py:292-337``): fade in -> hold -> fade out on the
        ``ui.FX.boss_announce`` timings. Since 10J the fade is a real text
        alpha (RGBA ``HudText``). Ignores the camera; drawn over the game
        surface."""
        if self._announce_age is None:
            return
        a = self._announce
        t = self._announce_age
        if t < a["fade_in"]:
            k = t / a["fade_in"] if a["fade_in"] > 0 else 1.0
        elif t < a["fade_in"] + a["hold"]:
            k = 1.0
        else:
            out = t - a["fade_in"] - a["hold"]
            k = 1.0 - out / a["fade_out"] if a["fade_out"] > 0 else 0.0
        k = max(0.0, min(1.0, k))
        color = _ANNOUNCE_RED + (int(255 * k),)
        cx = view_w // 2
        # layout_h: a screen-centred layout position (engine/render/fonts.py).
        cy = view_h // 2 - layout_h("xl") - 6
        submit_centered(renderer, _ANNOUNCE_L1, cx, cy, "xl", color)
        submit_centered(renderer, _ANNOUNCE_L2, cx, cy + layout_h("xl") + 8,
                        "xl", color)

    def submit_boss_bars(self, renderer, cs, scene, phase, view_w, view_h):
        """The bottom-centre boss HUD bar while a live boss walks (prototype
        ``hud.py:356-368``), found via the ``"boss"`` scene tag (no host ref):
        200x12 at ``view_h - 55``, red under-bar + green fill + 1px border, red
        "BOSS" label left, ``hp/max`` right. ENEMY phase only; vanishes the
        moment the boss dies. The boss's OVERHEAD bar is not drawn here — it
        comes from ``submit_enemy_hp_bars`` with every other enemy's, so the two
        can never double up and it stacks against a death swarm."""
        if phase != GamePhase.ENEMY:
            return
        boss = next((b for b in scene.by_tag("boss")
                     if getattr(b, "alive", False)), None)
        if boss is None:
            return
        health = boss.get_component(Health)
        w, h = _BOSS_HUD_BAR_W, _BOSS_HUD_BAR_H
        x = view_w // 2 - w // 2
        y = view_h - _BOSS_HUD_BAR_LIFT
        ratio = health.hp / health.max_hp if health.max_hp else 0.0
        submit_bar(renderer, x, y, w, h, ratio,
                   bg=C_HP_RED, fill=C_HP_GREEN, border=(0, 0, 0))
        submit_text(renderer, "BOSS", (x - 10, y - 2), "md", C_HP_RED,
                    align="right")
        submit_text(renderer, f"{health.hp}/{health.max_hp}",
                    (x + w + 10, y - 2), "md", C_UI_TEXT)
