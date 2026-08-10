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

**ESV-3a**: the particle/gold/slash/splatter emitters + their tunables moved to
``engine.vfx`` / ``data/balancing/vfx.json`` (spark bursts, building-death
shards, muzzle spray, melee slash, gold tile highlight, blood splatter, and
floater colour/lifetime params). ``_params_from_balance`` is the ONE place the
JSON key names and the engine's dataclass fields meet — ``engine.vfx`` never
learns a key name (D5). ``FloaterManager`` keeps every public method name and
delegates their bodies to the ``VfxSystem`` it now owns (``self._vfx``).

**ESV-3b**: the Sun Scorcher beam, mortar crater, lightning bolt/flash/marker
and boss announce colour/alpha params moved the same way (``self._vfx_params``,
held alongside ``self._vfx`` — these four are NOT ``VfxSystem`` state, since
the scene already owns the crater/lightning GameObjects' fade clocks; see
``engine/vfx/params.py``'s module docstring). ``submit_lightning`` is the one
draw that consumes random numbers (re-rolled every submitted frame, not once
at emit) — it now draws through ``self._rng`` (the same injected stdlib
``random`` module ``self._vfx`` shares) instead of the bare module-level call,
so a seeded test can pin it without touching the live game's shared draw
stream. The two scene-object fade lifetimes (``crater.life``,
``lightning.bolt_life``/``marker_life``) are threaded from here down through
``resolve_combat``/``lightning.strike`` to the ``CraterFade``/``LightningFXFade``
components that actually own the despawn clocks — see ``game/enemies/combat.py``
and ``game/core/lightning.py``.

**ESV-5**: a 9-row sprite-one-shot **trigger table**
(``data/balancing/vfx.json``'s top-level ``triggers`` sibling of
``procedural``) lets a designer bind an imported ``vfx_*`` sheet to any of the
8 LIVE cosmetic EVENTS (``building_placed``/``_level_up``/``_tier_up``,
``building_destroyed``, ``enemy_attack_melee``/``_ranged``, ``enemy_death``,
``splash_impact``) plus the still-inert 9th, ``defender_fire`` (no defender
fires ANY vfx today — deliberately unbound, a future phase's convergence
demo). ``_triggers_from_balance`` is the ONE place a trigger-table event NAME
is read out of the JSON
(mirroring ``_params_from_balance`` for the procedural side); every call site
below now goes through the private ``_play(event, wx, wy, **kw)`` dispatcher
instead of calling ``self._vfx.emit_*``/``add_splatters`` directly. Resolution
order (per event, every dispatch): a non-empty ``sprite_slot`` whose slot has
imported art spawns a one-shot ``engine.vfx.PlayOnceVfx`` sprite
(``spawn_play_once`` — ``None`` back means "no art yet", E-37); otherwise the
named ``procedural`` kind runs through the SAME ``self._vfx``/``self._spark_
presets`` this file already built; an empty ``procedural`` (or an event absent
from the table) is a silent no-op — never a raise. Every shipped row's
``procedural`` reproduces exactly what that call site did before this phase,
so a fresh checkout with no art imported is byte-identical.
``_play`` needs two handles this class did not have before: ``self.assets``
(an ``AssetStore``) and ``self.scene`` (the live ``Scene``), both host-wired
attributes (the ``self.log`` precedent) defaulting to ``None`` — either being
``None`` degrades to the procedural branch, never raises, so every existing
bare-constructed ``FloaterManager`` in the test suite keeps working unchanged.
``splash_impact`` (a mortar shell's landing) is the one event with no
``FloaterManager`` call site of its own: ``game/enemies/combat.py``'s
``ProjectileArc._impact`` pushes ``(wx, wy)`` onto
``RunState.splash_impact_events`` through ``resolve_combat``'s optional
``on_splash_impact`` callback (the ``on_enemy_death`` layering pattern —
``game/enemies`` still imports NO ``game/core``); ``spawn_splash_impact_events``
here drains that ledger into ``_play`` next to ``spawn_death_events``. The
Crater GameObject's own continuous fade mark keeps spawning unconditionally
either way — this only adds an optional ADDITIONAL one-shot at the same point.

**ESV-6** is the plan's final phase — it re-points a subset of the ESV-5
dispatch sites at manifest-authored anchors (VISUAL ONLY, D4) and closes the
plan's §6 item 1 floater dead-data gap. A new host-wired handle,
``self.cs``, joins ``self.assets``/``self.scene`` (same ``None``-degrades-
never-raises contract); a new private helper, ``_anchored(obj, name, wx,
wy)``, resolves ``obj``'s manifest ``name`` anchor via
``game.anchors.anchor_world_point`` and falls back to the input point
UNCHANGED when the store/cs/animator/anchor is absent (ESV-1). **fix-anchor-
origin-parity** replaced the point's resolution: `anchor_world_point` returns
the exact absolute world point on the sprite AS DRAWN (through
`engine.render.sprite_anchor_screen`, the same geometry the renderer uses to
place the sprite) rather than a delta added to a base point that used to
disagree with where the sprite is actually centred (see `game/anchors.py`'s
module docstring for the measured root cause) — "anchor wins outright": an
authored anchor resolves to the exact handle point, never a nudge on top of
a different base. ``watch_enemies`` anchors both attack
events on the firing enemy's ``muzzle``; ``watch_buildings`` anchors
``building_destroyed`` on the destroyed building's ``impact``.
``enemy_death``/``splash_impact`` and the three building-celebration events
are DELIBERATELY left unanchored (ground decals / tile celebrations with no
single owning sprite — see the ESV-6 brief §1.2). A 10th trigger event,
``projectile_hit``, is added: ``game/enemies/combat.py``'s
``ProjectileHoming._impact`` pushes the TARGET's ``impact``-anchored point
onto ``RunState.projectile_hit_events`` through ``resolve_combat``'s new
optional ``on_projectile_hit`` callback, drained here by
``spawn_projectile_hit_events``; the 9th event, ``defender_fire``, gets its
first real call site the same way — ``_fire``/``_fire_splash`` already
compute the muzzle-anchored spawn point for the projectile itself, and
``resolve_combat``'s new optional ``on_defender_fire`` callback fires with
that SAME point (never recomputed), drained by
``spawn_defender_fire_events``. Both new rows ship INERT, like every prior
convergence step. Finally, the seven floater colour/lifetime module
constants (income/upkeep/XP/painter/boost) are DELETED — the four floater
spawn sites now read ``self._vfx_params.floaters`` (``engine.vfx.
FloaterParams``, built by ``_params_from_balance`` from
``procedural.floaters`` — live since ESV-3a but never read until now), so a
designer's edit in the ``vfx`` balancing form finally reaches the game.

**fix-anchor-offset-and-bullet-sprites (post-ESV live-testing follow-up),
Fix 2**: the projectile dot's colour/size/lift move from two module
constants (``_PROJECTILE_STONE``/``_PROJECTILE_SHELL``, the last un-ported
cosmetic constants in this file) into ``data/balancing/vfx.json``'s
``procedural.projectile`` block (``engine.vfx.ProjectileParams``, read off
``self._vfx_params.projectile`` — not ``VfxSystem`` state, like ESV-3b's four
scene-object dataclasses and ESV-6's ``floaters``: a projectile is a
continuous in-flight object the game owns, not a particle any list owns).
``submit_projectiles`` also gains a sprite branch: two SHARED slots
(``vfx_projectile``/``vfx_shell``, every defender/every mortar respectively —
NOT per-building art) swap in as a ``HudSprite`` once imported, using the
same "has art" signal ``engine.vfx.spawn_play_once`` uses
(``assets.animation_total_ms(slot, "idle")`` returning ``None`` means no art
yet, E-37) so the two paths can never disagree about what "imported" means.
This is NOT a trigger-table event — no ``triggers`` row, no ``PlayOnceVfx`` —
projectiles stay continuous, like beams and lightning.

**feat-projectile-anchored-flight**: ``submit_projectiles`` DROPS the
draw-time lift — it is now a pure projection of ``p.transform.world_pos``.
The lift moved into the SPAWN POINT (`game/enemies/combat.py`'s `_fire`,
via `game.anchors.projectile_point`), which is what let it double-count
against an authored `muzzle` anchor before this fix (the dot rendered ~19px
above the handle even when the anchor already encoded the height). Unanchored
play is unaffected — the same lift lands at the same screen pixel, just
computed once at spawn instead of every draw. The mortar's `ProjectileArc`
path (`_fire_splash`) is untouched.
"""
import math    # feature-storm-acolyte-multi-build: the polygon-ring helper
import random  # 10H bolt jitter / 10J particle spread (stdlib — pure)

from engine.core import Health, SpriteAnimator
from engine.render import (
    HudLines, HudRect, HudSprite, block_center_offset, fit_factor,
)
from game.anchors import anchor_world_point
from engine.render.fonts import layout_h
from engine.vfx import (
    AnnounceParams, BeamParams, BurstParams, CraterParams, DrummerAuraParams,
    FloaterParams, GoldParams, LightningParams, MuzzleParams,
    ProjectileParams, ShardBurstParams, SlashParams, SplatterParams,
    VfxParams, VfxSystem, spawn_play_once,
)
from game.buildings.components import BeamAttacker, Nameplate, TierState
from game.core.lightning import LightningCaster
from game.core.phases import GamePhase

from .widgets import (
    submit_bar, submit_centered, submit_text
)
from . import widgets
from .strings import T

# Income/upkeep/XP/painter/boost floater colours + lifetimes are
# data/balancing/vfx.json procedural.floaters now (ESV-6, closing the plan's
# §6 item 1 dead-data gap — this file used to carry seven module constants
# here that duplicated that JSON block without ever reading it) — see
# _params_from_balance below; the four spawn sites read self._vfx_params.
# floaters.

# Sun Scorcher beam colour ramp, mortar crater scorch colour and the boss
# announce colour/alpha are now in data/balancing/vfx.json (ESV-3b) — see
# _params_from_balance below.

# -- 10G boss: announcement + HP-bar constants ------------------------------
# UT-5: the two banner lines, the boss-bar label and its hp/max readout are
# `data/ui/strings.json` templates now (`effects.*`), resolved through T() at
# the draw site. They get no widget id: this module is FX, not a screen — it
# has no `ids` dict and every one of these positions is computed inline from
# the view size or a world point, and the anchor-rect convention says an id
# needs a STORED rect first.
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
# Bolt colour ramp, jitter, segment count, flash + ground-marker params are
# now in data/balancing/vfx.json procedural.lightning (ESV-3b) — see
# _params_from_balance below.
# -- /10H --

# -- feature-storm-acolyte-multi-build: per-caster charge bar chrome. Code
# constants beside HP_BAR_W/HP_BAR_H (the established bar-chrome precedent —
# these are not gameplay tunables, just fixed screen-pixel bar geometry) --
_CHARGE_BAR_W, _CHARGE_BAR_H = 28, 4      # same footprint as a building HP bar
_CHARGE_BAR_SLATE = (70, 70, 90)          # empty/just-fired ramp start
_CHARGE_BAR_READY_YELLOW = (255, 240, 80)  # ramp end == hud.py's ready colour
_CHARGE_BAR_LIFT = 8   # px below the HP-bar baseline, so the two don't overlap
# -- /feature-storm-acolyte-multi-build --

# -- Drummer buff-range indicator + buffed-enemy arrow (very-simple placeholder
# visuals): the arrow's SHAPE/colour are code chrome (like HP_BAR_*'s bar
# geometry above) — only its swappable ART (the vfx_buff_arrow slot) is a
# designer lever. The ring's colour/pulse ARE balancing (procedural.
# drummer_aura), since it has no image slot to swap.
BUFF_ARROW_SLOT = "vfx_buff_arrow"
_BUFF_ARROW_W, _BUFF_ARROW_H = 10, 8   # base-zoom px, fixed screen size
_BUFF_ARROW_GAP = 3                    # px above the HP-bar anchor point
_BUFF_ARROW_GOLD = (255, 200, 50)      # placeholder colour == widgets.C_GOLD
# -- /Drummer buff-range indicator + buffed-enemy arrow --

# -- 10J FX: spark/gold/death-shard/muzzle/slash/splatter params live in
# data/balancing/vfx.json now (ESV-3a) — see _params_from_balance below. The
# projectile dot fallback (colour/size/lift, procedural.projectile) is now
# there too — see the fix-anchor-offset-and-bullet-sprites brief's Fix 2.
# -- /10J --


def _color(c):
    return tuple(c)


def _ramp(stops):
    """A `procedural.*.ramp`/`colors` object — named `stop_0`/`stop_1`/
    `stop_2` keys, not a bare JSON array of arrays (the editor's recursive
    balancing form has no widget for a nested array — see
    `data/schemas/vfx.schema.json`'s `$defs.ramp`) — into the engine's
    3-tuple-of-colour-tuples shape."""
    return (_color(stops["stop_0"]), _color(stops["stop_1"]),
            _color(stops["stop_2"]))


def _params_from_balance(vfx):
    """Turn the validated ``vfx.json`` dict into ``engine.vfx`` dataclasses.

    The ONE place the JSON key names and the engine's dataclass fields meet —
    ``engine.vfx`` never learns a key name (D5). Returns ``(spark_presets,
    vfx_params)``: ``spark_presets`` is a ``{kind: BurstParams}`` dict —
    spark preset keys (``place``/``level1``/``level2``/``tier``) are game
    vocabulary, so the engine never sees them; the caller resolves a kind to
    its ``BurstParams`` before calling ``VfxSystem.emit_burst`` (the existing
    ``.get(kind, presets["place"])`` fallback, kept here)."""
    proc = vfx["procedural"]

    spark = proc["spark"]
    spark_shared = dict(
        gravity=spark["gravity"], ramp=_ramp(spark["ramp"]),
        vx_min=spark["vx_min"], vx_max=spark["vx_max"],
        vy_min=spark["vy_min"], vy_max=spark["vy_max"],
        size_w=spark["size_w"], size_h=spark["size_h"])
    spark_presets = {
        key: BurstParams(life=preset["life"], count=preset["count"],
                         **spark_shared)
        for key, preset in spark["presets"].items()}

    death = proc["death_burst"]
    death_burst = ShardBurstParams(
        life=death["life"], count=death["count"], gravity=death["gravity"],
        colors=_ramp(death["colors"]),
        vx_min=death["vx_min"], vx_max=death["vx_max"],
        vy_min=death["vy_min"], vy_max=death["vy_max"],
        size_w_min=death["size_w_min"], size_w_max=death["size_w_max"],
        size_h_min=death["size_h_min"], size_h_max=death["size_h_max"])

    mz = proc["muzzle"]
    muzzle = MuzzleParams(
        life=mz["life"], life_strong=mz["life_strong"],
        count=mz["count"], count_strong=mz["count_strong"],
        gravity=mz["gravity"], ramp=_ramp(mz["ramp"]),
        smoke_color=_color(mz["smoke_color"]), smoke_chance=mz["smoke_chance"],
        vx_min=mz["vx_min"], vx_max=mz["vx_max"],
        vy_min=mz["vy_min"], vy_max=mz["vy_max"],
        size_w=mz["size_w"], size_h=mz["size_h"])

    sl = proc["slash"]
    slash = SlashParams(
        life=sl["life"], colors=_ramp(sl["colors"]),
        lines_min=sl["lines_min"], lines_max=sl["lines_max"],
        ox_min=sl["ox_min"], ox_max=sl["ox_max"],
        oy_min=sl["oy_min"], oy_max=sl["oy_max"],
        size=sl["size"], size_large=sl["size_large"])

    gh = proc["gold_highlight"]
    gold = GoldParams(
        life=gh["life"], fade_in=gh["fade_in"], hold=gh["hold"],
        fill_color=_color(gh["fill_color"]),
        border_color=_color(gh["border_color"]),
        fill_alpha=gh["fill_alpha"], border_width=gh["border_width"])

    sp = proc["splatter"]
    splatter = SplatterParams(
        color=_color(sp["color"]), alpha=sp["alpha"],
        radius_px=sp["radius_px"], jitter=sp["jitter"])

    # -- ESV-3b: beam / crater / lightning / announce --------------------
    bm = proc["beam"]
    beam = BeamParams(
        colors=_ramp(bm["colors"]), width_base=bm["width_base"],
        origin_lift_tiles=bm["origin_lift_tiles"])

    cr = proc["crater"]
    crater = CraterParams(
        color=_color(cr["color"]), alpha=cr["alpha"], life=cr["life"],
        segments=cr["segments"])

    lp = proc["lightning"]
    lightning = LightningParams(
        bolt_segments=lp["bolt_segments"], bolt_jitter_px=lp["bolt_jitter_px"],
        bolt_color_start=_color(lp["bolt_color_start"]),
        bolt_color_end=_color(lp["bolt_color_end"]),
        bolt_width=lp["bolt_width"], bolt_life=lp["bolt_life"],
        flash_radius_px=lp["flash_radius_px"],
        flash_color=_color(lp["flash_color"]), flash_alpha=lp["flash_alpha"],
        marker_color=_color(lp["marker_color"]),
        marker_fill_alpha=lp["marker_fill_alpha"],
        marker_outline_width=lp["marker_outline_width"],
        marker_life=lp["marker_life"], marker_segments=lp["marker_segments"])

    an = proc["announce"]
    announce = AnnounceParams(
        color=_color(an["color"]), max_alpha=an["max_alpha"])
    # -- /ESV-3b -----------------------------------------------------------

    # -- ESV-6: floaters (closes the plan's §6 item 1 dead-data gap) -------
    fl = proc["floaters"]
    floaters = FloaterParams(
        upkeep_color=_color(fl["upkeep_color"]),
        xp_color=_color(fl["xp_color"]), xp_life=fl["xp_life"],
        painter_finished_color=_color(fl["painter_finished_color"]),
        painter_lost_color=_color(fl["painter_lost_color"]),
        painter_life=fl["painter_life"],
        boost_color=_color(fl["boost_color"]))
    # -- /ESV-6 --------------------------------------------------------------

    # -- fix-anchor-offset-and-bullet-sprites Fix 2: projectile fallback dot -
    pr = proc["projectile"]
    projectile = ProjectileParams(
        stone_color=_color(pr["stone_color"]),
        shell_color=_color(pr["shell_color"]),
        stone_size=pr["stone_size"], shell_size=pr["shell_size"],
        lift_frac=pr["lift_frac"])
    # -- /Fix 2 ----------------------------------------------------------

    # -- Drummer buff-range telegraph ring --------------------------------
    da = proc["drummer_aura"]
    drummer_aura = DrummerAuraParams(
        color=_color(da["color"]), alpha_min=da["alpha_min"],
        alpha_max=da["alpha_max"], pulse_period_s=da["pulse_period_s"],
        segments=da["segments"])
    # -- /Drummer buff-range telegraph ring --------------------------------

    return spark_presets, VfxParams(
        death_burst=death_burst, muzzle=muzzle, slash=slash, gold=gold,
        splatter=splatter, beam=beam, crater=crater, lightning=lightning,
        announce=announce, floaters=floaters, projectile=projectile,
        drummer_aura=drummer_aura)


def _triggers_from_balance(vfx):
    """Turn ``vfx.json``'s top-level ``triggers`` object into a plain
    ``{event: (sprite_slot, procedural)}`` dict — the ONE place a trigger-
    table EVENT NAME is read (ESV-5), mirroring ``_params_from_balance`` for
    the procedural side; nothing downstream (``_play``'s callers) learns a
    key name, they just pass the event string they already know."""
    return {event: (row["sprite_slot"], row["procedural"])
            for event, row in vfx["triggers"].items()}


def _polygon_ring(cx, cy, r, segments):
    """A regular ``segments``-gon of radius ``r`` in WORLD units, centred at
    ``(cx, cy)``, starting at the top and stepping clockwise — the same shape
    the lightning impact-flash octagon has always drawn (feature-storm-
    acolyte-multi-build generalises that inline 8-point literal into this one
    shared helper). A world-space N-gon projects to the iso 2:1 ground
    ellipse (the same reason the flash octagon reads as light on the ground
    rather than a flat shape); every "round" world-unit ground marker in this
    file goes through here now: the lightning blast marker, the mortar
    crater, and the flash itself."""
    return [(cx + r * math.sin(2 * math.pi * i / segments),
             cy - r * math.cos(2 * math.pi * i / segments))
            for i in range(segments)]


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


class FloaterManager:
    """Income/upkeep floaters spawned at payday + per-building/per-enemy HP bars.

    ``spawn_income_events`` is called once when the phase enters INCOME; it reads
    ``state.income_events`` (filled by ``run_payday``) so it never re-derives the
    payday math. Gated by ``ui.FX.income_floaters_enabled``; floater lifetime is
    the income phase duration (``core.PhaseLoop.income_phase_duration``).
    """

    def __init__(self, ui_balance, core_balance, vfx_balance):
        self._enabled = ui_balance["FX"]["income_floaters_enabled"]
        self._life = core_balance["PhaseLoop"]["income_phase_duration"]
        # feature-storm-acolyte-multi-build: submit_lightning_charge_bars
        # reads each caster's own tier cooldown ceiling straight off core.
        self._core_balance = core_balance
        self._floaters = []
        # -- 10G boss announcement: timings from ui.FX.boss_announce; the age
        # clock is None while no announcement runs.
        self._announce = ui_balance["FX"]["boss_announce"]
        self._announce_age = None
        # -- 10J FX state --
        self._gore_enabled = ui_balance["FX"]["gore_enabled"]
        self._building_alive = {} # id(building) -> alive (death watcher)
        self._enemy_cooldowns = {}  # id(enemy) -> last EnemyCombat.cooldown
        self.log = None           # GameLog, wired by the host
        # ESV-3a: the particle/gold/slash/splatter emitters live in
        # engine.vfx now. rng is the stdlib `random` MODULE (not a fresh
        # Random()) so draws keep coming from the same global stream the old
        # inline random.uniform/randint calls used — byte-identical output.
        self._spark_presets, vfx_params = _params_from_balance(vfx_balance)
        self._vfx = VfxSystem(vfx_params, rng=random)
        # ESV-3b: beam/crater/lightning/announce params are not VfxSystem
        # state (the scene already owns the crater/lightning fade clocks —
        # engine/vfx/params.py's module docstring) — held here instead, read
        # straight off by submit_beams/submit_craters/submit_lightning/
        # submit_announce. `self._rng` is the SAME `random` module `self._vfx`
        # was given — submit_lightning is the one draw that consumes random
        # numbers, and it must share the global stream, not a second handle.
        self._vfx_params = vfx_params
        self._rng = random
        # -- /10J --
        # -- ESV-5/6: sprite one-shot trigger table + its three host-wired
        # handles. Any of the three being None degrades `_play`/`_anchored`
        # to the procedural / unanchored branch, never raises — every
        # bare-constructed FloaterManager in the existing test suite keeps
        # working unchanged.
        self._triggers = _triggers_from_balance(vfx_balance)
        self.assets = None   # AssetStore, wired by the host
        self.scene = None    # Scene, wired by the host
        self.cs = None       # CoordinateSystem, wired by the host (ESV-6)
        # -- /ESV-5/6 --
        # Drummer buff-range telegraph: a manager-owned seconds clock, the
        # hud.py `self._clock` XP-pulse precedent, driving the ring's smooth
        # sine breathe (submit_drummer_auras) — accumulated in update(dt).
        self._clock = 0.0

    def spawn_income_events(self, state):
        if not self._enabled:
            return
        for col, row, amount, kind in state.income_events:
            color = (widgets.C_GOLD if kind == "income"
                     else self._vfx_params.floaters.upkeep_color)
            text = (T("effects.floater_gain", amount=amount) if amount >= 0
                    else T("effects.floater_loss", amount=amount))
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, color, self._life))

    def spawn_xp_events(self, state):
        """Drain ``state.xp_events`` (filled by the Session's XP award sites)
        into short purple floaters. Called every frame — XP is granted mid-combat,
        not once at a phase edge like income. The prototype's ``xp_icon`` sprite
        has no slot in this repo, so the floater is text-only (10J)."""
        fl = self._vfx_params.floaters
        for wx, wy, amount in state.xp_events:
            self._floaters.append(
                _Floater(wx, wy, T("effects.floater_xp", amount=amount),
                         fl.xp_color, fl.xp_life))
        state.xp_events.clear()

    def spawn_painter_events(self, state):
        """Drain ``state.painter_events`` (filled by the payday Painter slot +
        revive) into 1.5s message floaters — gold "painting finished", red
        "painting lost!". Called on the INCOME edge beside the income floaters."""
        fl = self._vfx_params.floaters
        for col, row, text, kind in state.painter_events:
            color = (fl.painter_finished_color if kind == "finished"
                     else fl.painter_lost_color)
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text, color, fl.painter_life))
            if self.log is not None and kind == "lost":  # 10J game log
                self.log.post(text)
        state.painter_events.clear()

    def spawn_boost_events(self, state):
        """Drain ``state.boost_events`` (filled by the payday boost slot) into white
        per-turn boost floaters over each buffed defender — prototype white text.
        Called on the INCOME edge beside the income floaters."""
        for col, row, text in state.boost_events:
            self._floaters.append(
                _Floater(col + 0.5, row + 0.5, text,
                         self._vfx_params.floaters.boost_color, self._life))
        state.boost_events.clear()

    # -- 10J FX: sparks, gold highlights, death bursts, muzzle/slash, blood --

    # -- ESV-5: the trigger-table dispatch seam ------------------------------

    _SPARK_KINDS = ("spark_place", "spark_level", "spark_tier")

    def _play(self, event, wx, wy, **kw):
        """Consult the trigger table: a bound sprite slot with art spawns a
        PlayOnceVfx; otherwise the named procedural kind runs; an empty row
        (or an event absent from the table) is a silent no-op (E-37). ``**kw``
        carries the per-kind extras the procedural branch needs (``preset``
        for the spark burst, ``large=`` for the slash, ``strong=`` for the
        muzzle)."""
        sprite_slot, procedural = self._triggers.get(event, ("", ""))
        if sprite_slot and self.assets is not None and self.scene is not None:
            vfx = spawn_play_once(self.scene, self.assets, sprite_slot, wx, wy)
            if vfx is not None:
                return
        self._run_procedural(procedural, wx, wy, **kw)

    def _run_procedural(self, kind, wx, wy, **kw):
        """The procedural fallback a trigger row names. ``kind`` absent from
        every branch below (``""``, an unrecognised string, or ``"crater"`` —
        whose visual is the Crater GameObject's own UNCONDITIONAL continuous
        fade mark, spawned independently in ``game/enemies/combat.py`` no
        matter what this table says) degrades to a silent no-op, never a
        raise (E-37)."""
        if kind in self._SPARK_KINDS:
            preset = kw.get("preset")
            if preset is not None:
                self._vfx.emit_burst(preset, wx, wy)
        elif kind == "death_burst":
            self._vfx.emit_shards(wx, wy)
        elif kind == "slash":
            self._vfx.emit_slash(wx, wy, large=kw.get("large", False))
        elif kind == "muzzle":
            self._vfx.emit_muzzle(wx, wy, strong=kw.get("strong", False))
        elif kind == "splatter":
            self._vfx.add_splatters([(wx, wy)])

    # -- /ESV-5 ---------------------------------------------------------------

    # -- ESV-6: the anchor helper --------------------------------------------

    def _anchored(self, obj, name, wx, wy):
        """``obj``'s manifest ``name`` anchor point, or ``(wx, wy)``
        UNCHANGED when the store/cs/animator/anchor is absent — so a
        manifest with no ``anchors`` key leaves every caller numerically
        identical (ESV-1). "Anchor wins outright" (fix-anchor-origin-
        parity): an authored anchor resolves to the exact handle point,
        never a delta nudging `(wx, wy)`. VISUAL ONLY (D4) — never call this
        on a value that feeds a damage/range/splash expression."""
        point = anchor_world_point(self.assets, self.cs, obj, name)
        return (wx, wy) if point is None else point

    # -- /ESV-6 ---------------------------------------------------------------

    def spawn_building_vfx(self, col, row, kind):
        """Placement/upgrade celebration (prototype ``spawn_building_vfx``,
        game.py:619-626): always a spark burst; ``place``/``tier`` add the
        gold tile highlight. ``kind`` in place / level1 / level2 / tier.
        ESV-5: routed through the trigger table — ``place``/``tier`` map 1:1
        to their own event, ``level1``/``level2`` collapse to the single
        ``building_level_up`` event (they differ only by PRESET, not by
        effect identity; the preset lookup below is unchanged either way)."""
        preset = self._spark_presets.get(kind, self._spark_presets["place"])
        wx, wy = col + 0.5, row + 0.5
        event = {"place": "building_placed",
                 "tier": "building_tier_up"}.get(kind, "building_level_up")
        self._play(event, wx, wy, preset=preset)
        if kind in ("place", "tier"):
            self._vfx.emit_gold(col, row)

    def watch_buildings(self, scene, log=None):
        """Building-death watcher (called every frame): a non-base building
        whose ``alive`` flipped to False this frame bursts 14 purple shards
        (prototype ``BuildingDeathEffect``) and logs the kill when it carries
        a custom name (prototype game.py:710-717). ESV-6: the burst is
        anchored on the destroyed building's ``impact`` handle (absent -> the
        unanchored tile centre, unchanged)."""
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
            wx, wy = self._anchored(b, "impact", wx, wy)
            self._play("building_destroyed", wx, wy)
            np = b.get_component(Nameplate)
            if log is not None and np is not None and np.custom_name:
                log.post(T("game_log.building_killed",
                           name=np.custom_name))
        # drop stale ids so a long run can't grow the map unbounded
        if len(self._building_alive) > 2 * len(seen) + 16:
            self._building_alive = {
                k: v for k, v in self._building_alive.items() if k in seen}

    def watch_enemies(self, scene):
        """Enemy attack FX watcher (called every frame during ENEMY): an
        ``EnemyCombat.cooldown`` that RESET (grew) while the enemy is blocked
        means an attack just landed — raider/boss show a melee slash, the
        rest a muzzle spray, strong for the siege cannon (prototype
        enemy.py:222 / siege_cannon.py:109 / raider.py:48 / boss.py:104).
        ESV-6: both events are anchored on the FIRING enemy's ``muzzle``
        handle — computed ONCE, before the melee/ranged branch, since both
        share it (absent -> the unanchored world point, unchanged)."""
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
            wx, wy = self._anchored(e, "muzzle", *e.transform.world_pos)
            etype = getattr(e, "ETYPE", "standard")
            if etype in ("raider", "boss"):
                self._play("enemy_attack_melee", wx, wy,
                          large=(etype == "boss"))
            else:
                self._play("enemy_attack_ranged", wx, wy,
                          strong=(etype == "siege"))
        if len(self._enemy_cooldowns) > 2 * len(seen) + 16:
            self._enemy_cooldowns = {
                k: v for k, v in self._enemy_cooldowns.items() if k in seen}

    def spawn_death_events(self, state, gore_on):
        """Drain ``state.enemy_death_events`` (filled by the Session death /
        base-hit callbacks) into ground blood splatters. Gated by
        ``ui.FX.gore_enabled`` AND the settings toggle — both must be on
        (prototype game.py:1898-99); the ledger drains either way. ESV-5:
        dispatched ONE POINT AT A TIME through the trigger table — a batch of
        simultaneous deaths has no single shared spawn point for the
        sprite-one-shot branch, so each point gets its own ``_play`` call;
        the procedural fallback (``self._vfx.add_splatters([(wx, wy)])`` per
        point) extends the SAME list in the SAME order a single batched
        ``add_splatters(events)`` call would have, so the no-art landing
        condition stays byte-identical."""
        if not state.enemy_death_events:
            return
        events, state.enemy_death_events = state.enemy_death_events, []
        if not (self._gore_enabled and gore_on):
            return
        for wx, wy in events:
            self._play("enemy_death", wx, wy)

    def spawn_splash_impact_events(self, state):
        """Drain ``state.splash_impact_events`` (filled by ``game/enemies/
        combat.py``'s ``ProjectileArc._impact`` through ``resolve_combat``'s
        optional ``on_splash_impact`` callback) into the ``splash_impact``
        trigger — an OPTIONAL additional one-shot at a mortar shell's landing
        point. The Crater GameObject's own continuous fade mark keeps
        spawning unconditionally regardless of this ledger; this call adds
        nothing when the row has no art AND no procedural kind wired for it
        beyond the crater itself (E-37 no-op). ESV-5."""
        if not state.splash_impact_events:
            return
        events, state.splash_impact_events = state.splash_impact_events, []
        for wx, wy in events:
            self._play("splash_impact", wx, wy)

    def spawn_defender_fire_events(self, state):
        """Drain ``state.defender_fire_events`` (filled by ``game/enemies/
        combat.py``'s ``_fire``/``_fire_splash`` through ``resolve_combat``'s
        optional ``on_defender_fire`` callback, at the point THOSE FUNCTIONS
        already compute for the projectile's muzzle-anchored spawn — no
        anchor work needed here) into the ``defender_fire`` trigger. The
        shipped row stays INERT (``sprite_slot``/``procedural`` both ``""``)
        — the ledger fills every shot, ``_play`` no-ops (E-37); a designer
        binding art is ESV-6's convergence demo. ESV-6."""
        if not state.defender_fire_events:
            return
        events, state.defender_fire_events = state.defender_fire_events, []
        for wx, wy in events:
            self._play("defender_fire", wx, wy)

    def spawn_projectile_hit_events(self, state):
        """Drain ``state.projectile_hit_events`` (filled by ``game/enemies/
        combat.py``'s ``ProjectileHoming._impact`` through ``resolve_combat``'s
        optional ``on_projectile_hit`` callback, at the TARGET's ``impact``
        anchor) into the ``projectile_hit`` trigger — the plan's promised 10th
        event, and the first consumer of the ``impact`` anchor + the
        ``vfx_hit``/``vfx_explosion`` slots (only the homing path; the
        mortar keeps its own ``splash_impact`` event, §1.2). Shipped INERT,
        like ``defender_fire``. ESV-6."""
        if not state.projectile_hit_events:
            return
        events, state.projectile_hit_events = state.projectile_hit_events, []
        for wx, wy in events:
            self._play("projectile_hit", wx, wy)

    def clear_splatters(self):
        """Previous round's blood clears when the next wave starts (prototype
        ``clear_splatters`` on End Turn, game.py:815)."""
        self._vfx.clear_splatters()

    # -- /10J -----------------------------------------------------------------

    def clear(self):
        self._floaters.clear()
        self._announce_age = None
        self._vfx.clear()  # -- 10J: particles / gold / slashes / splatters

    def update(self, dt):
        self._clock += dt
        for f in self._floaters:
            f.age += dt
        self._floaters = [f for f in self._floaters if f.age < f.life]
        # -- 10G boss: advance the announcement clock --
        if self._announce_age is not None:
            self._announce_age += dt
            a = self._announce
            if self._announce_age >= a["fade_in"] + a["hold"] + a["fade_out"]:
                self._announce_age = None
        self._vfx.update(dt)  # -- 10J: particles / gold / slashes --

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
        but over the tiles. Delegates to the ``VfxSystem`` (ESV-3a)."""
        self._vfx.submit_splatters(renderer, cs)

    def submit_gold_highlights(self, renderer):
        """The gold diamond fill + border on freshly built / tier-advanced
        tiles (prototype fill alpha <= 90, border alpha <= 200). Delegates to
        the ``VfxSystem`` (ESV-3a)."""
        self._vfx.submit_gold_highlights(renderer)

    def submit_projectiles(self, renderer, cs, scene):
        """In-flight shots (10J): the plain defender stone as a small light
        dot, the mortar shell darker and larger (prototype's procedural
        projectile art; 9E left them logical-only). Read live off the scene
        like the HP bars — homing shots track their target every frame.

        fix-anchor-offset-and-bullet-sprites Fix 2: two SHARED slots
        (``vfx_projectile`` for every defender's stone, ``vfx_shell`` for a
        mortar's shell — never per-building art) swap in as a ``HudSprite``
        once imported; each slot's own art-vs-no-art state is independent.
        The "has art" signal is the SAME one ``engine.vfx.spawn_play_once``
        uses — ``assets.animation_total_ms(slot, "idle")`` returning
        ``None`` means no imported art (E-37) — so the two paths can never
        disagree about what "imported" means. Not a trigger-table event:
        projectiles are continuous in-flight objects, like beams and
        lightning, so this never spawns a ``PlayOnceVfx``. ``self.assets``
        is ``None`` in every bare-constructed test and degrades to the dot,
        never raises.

        feat-projectile-anchored-flight: the draw-time lift is GONE — this
        is now a pure projection of ``p.transform.world_pos``. The cosmetic
        lift moved into the ENDPOINT: `game/enemies/combat.py`'s `_fire`
        (via `game.anchors.projectile_point`) now spawns an unanchored
        defender shot already raised by ``lift_frac``, exactly where this
        function used to raise it at draw time — a no-op for unanchored
        play, an anchor now genuinely reachable. The mortar shell keeps
        whatever height `_fire_splash` gives it (untouched — §2.4)."""
        pr = self._vfx_params.projectile
        zoom = cs.camera.zoom
        for p in scene.by_tag("projectile"):
            wx, wy = p.transform.world_pos
            cx, cy = cs.world_to_screen(wx, wy)
            shell = p.name == "shell"
            slot = "vfx_shell" if shell else "vfx_projectile"
            color = pr.shell_color if shell else pr.stone_color
            size = max(2, int((pr.shell_size if shell else pr.stone_size)
                              * zoom))
            dest = (int(cx - size / 2), int(cy - size / 2))
            has_art = (self.assets is not None
                      and self.assets.animation_total_ms(slot, "idle")
                      is not None)
            if has_art:
                renderer.submit_hud(HudSprite(slot, dest, (size, size)))
            else:
                renderer.submit_hud(HudRect(
                    (dest[0], dest[1], size, size),
                    color, border_radius=size // 2))

    def submit_fx(self, renderer, cs):
        """Screen-space particle FX: sparks / death shards / muzzle motes as
        small filled rects, melee slashes as diagonal lines. Offsets are
        base-zoom pixels around the anchor, scaled by the live zoom.
        Delegates to the ``VfxSystem`` (ESV-3a)."""
        self._vfx.submit_hud(renderer, cs)

    def submit_beams(self, renderer, cs, scene):
        """A per-tier colored line from each firing Sun Scorcher to its target
        (Phase 10B). Reads the live ``BeamAttacker._target`` the combat sweep
        sets — so the beam shows only while the beam is actually engaging and
        vanishes during its target-death cooldown. Screen-space HudLines (no
        alpha glow — 10J). Params from ``self._vfx_params.beam`` (ESV-3b) — the
        clamp to ``len(colors) - 1`` is geometry (the ramp is a fixed 3-stop
        shape), not itself a tunable. Draws no random numbers."""
        bp = self._vfx_params.beam
        for b in scene.by_tag("combat"):
            beam = b.get_component(BeamAttacker)
            if beam is None:
                continue
            target = getattr(beam, "_target", None)
            if target is None or not getattr(target, "alive", False):
                continue
            tier = b.get_component(TierState).current_tier
            color = bp.colors[min(tier, len(bp.colors) - 1)]
            ox, oy = cs.world_to_screen(b.transform.wx + 0.5, b.transform.wy + 0.5)
            tx, ty = cs.world_to_screen(target.transform.wx + 0.5,
                                        target.transform.wy + 0.5)
            # crystal-ball height: origin_lift_tiles tile-heights above centre
            top = int(cs.geometry.tile_h * cs.camera.zoom * bp.origin_lift_tiles)
            renderer.submit_hud(HudLines(
                ((int(ox), int(oy) - top), (int(tx), int(ty))),
                color, width=bp.width_base + tier))

    def submit_craters(self, renderer, cs, scene):
        """A fading world-space scorch where each mortar shell landed (Phase
        10B). Purely cosmetic — the ``Crater`` GameObjects age + self-despawn in
        the scene; since 10J the fill is alpha-FILLED and fades by alpha
        (prototype's SRCALPHA ground ellipse). feature-storm-acolyte-multi-
        build: a ``cp.segments``-gon (the shared ``_polygon_ring`` helper),
        not the old 4-point diamond — the mortar's splash is Euclidean in
        TILE space, so this ring is the EXACT damage-area shape, a real
        fidelity fix, not just cosmetics. Params from
        ``self._vfx_params.crater`` (ESV-3b); the fade LIFETIME itself is on
        the ``Crater``'s own ``CraterFade`` component, not read here. Draws no
        random numbers."""
        cp = self._vfx_params.crater
        for c in scene.by_tag("crater"):
            frac = c.fade_frac
            r = c.radius
            cx, cy = c.transform.world_pos
            pts = _polygon_ring(cx + 0.5, cy + 0.5, r, cp.segments)
            renderer.submit_overlay_polys(
                pts, cp.color + (int(cp.alpha * frac),))

    def submit_drummer_auras(self, renderer, cs, scene):
        """A pulsing world-space ring around every ALIVE Drummer, sized to
        its own live ``DrummerAura.support_range`` — always visible while
        the Drummer is alive (no click/toggle needed, per the user's own
        design call), so the ring can never disagree with the real buff
        area it telegraphs. Uses the SAME ``_polygon_ring`` world-unit N-gon
        technique ``submit_craters`` draws the mortar scorch with, but reads
        the radius off the live component every frame instead of a spawned
        GameObject's own state — there is no separate fade clock, the ring
        simply stops being drawn the frame the Drummer dies.

        Purely a placeholder telegraph: colour/alpha bounds/segments come
        from ``self._vfx_params.drummer_aura`` (balancing-tunable, ESV-3b
        style — not a swappable sprite, unlike the buff arrow below), and
        the alpha breathes smoothly between them on a
        ``pulse_period_s``-second sine cycle off this manager's own
        ``self._clock`` (the ``hud.py`` XP-bar level-up pulse shape)."""
        from game.enemies.components import DrummerAura

        dp = self._vfx_params.drummer_aura
        t = 0.5 + 0.5 * math.sin(
            self._clock * (2 * math.pi / dp.pulse_period_s))
        alpha = int(dp.alpha_min + (dp.alpha_max - dp.alpha_min) * t)
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            aura = e.get_component(DrummerAura)
            if aura is None:
                continue
            wx, wy = e.transform.world_pos
            pts = _polygon_ring(wx + 0.5, wy + 0.5, aura.support_range,
                                dp.segments)
            renderer.submit_overlay_polys(pts, dp.color + (alpha,))

    # -- 10H: lightning + cheat menu ---------------------------------------

    def submit_lightning(self, renderer, cs, scene):
        """Bolt + ground marker for each live ``"lightning_fx"`` object (Phase
        10H, prototype ``effects.py LightningEffect``): (1) a jagged
        screen-space polyline from the top of the screen (y=0) down to the
        impact point — horizontal jitter re-rolled every SUBMITTED frame
        (through ``self._rng`` — the shared injected stdlib ``random``, never a
        fresh ``Random()``, ESV-3b §2.2), colour fading start -> end over the
        bolt life; (2) a fading world-space polygon RING sized to the REAL
        blast radius (feature-storm-acolyte-multi-build's shared
        ``_polygon_ring`` helper, replacing the old 4-point diamond — a ring
        reads as light lying on the isometric ground rather than a flat
        rotated box; the damage circle itself is a Euclidean circle in the
        PROJECTED PIXEL plane, so the world-space ring under-covers it
        slightly vertically, same as the diamond did, only far less —
        visual only, the damage maths is unchanged). The alpha impact-flash
        circle is 10J (no per-pixel alpha in
        the HUD/overlay pass). Params from ``self._vfx_params.lightning``
        (ESV-3b); the fade LIFETIMES (``bolt_life``/``marker_life``) are on the
        FX object's own ``LightningFXFade`` component, not read here — the FX
        objects age + self-despawn in the scene on the host's ENEMY-scaled sim
        dt; here we only draw them."""
        lp = self._vfx_params.lightning
        for fx in scene.by_tag("lightning_fx"):
            wx, wy = fx.transform.world_pos
            bolt = fx.bolt_frac
            if bolt > 0:
                sx, sy = cs.world_to_screen(wx, wy)
                pts = []
                for i in range(lp.bolt_segments + 1):
                    t = i / lp.bolt_segments
                    jitter = (self._rng.uniform(-lp.bolt_jitter_px,
                                                lp.bolt_jitter_px)
                              if 0 < i < lp.bolt_segments else 0.0)
                    pts.append((int(sx + jitter), int(sy * t)))
                # start -> end along the fade, darkening out (no alpha).
                progress = 1.0 - bolt
                color = tuple(
                    int((s + (e - s) * progress) * bolt)
                    for s, e in zip(lp.bolt_color_start, lp.bolt_color_end))
                renderer.submit_hud(HudLines(tuple(pts), color,
                                             width=lp.bolt_width))
            if bolt > 0:
                # 10J: the expanding alpha impact flash (prototype
                # effects.py:222-290). A world-unit polygon ring projects to
                # the 2:1 ground ellipse — the flash keeps its own fixed
                # 8-gon (feature-storm-acolyte-multi-build's shared
                # `_polygon_ring` helper generalises this literal; only the
                # ground MARKER below and the mortar crater are data-driven).
                fr = (1.0 - bolt) * (lp.flash_radius_px
                                     / (cs.geometry.tile_w / 2.0))
                if fr > 0:
                    pts = _polygon_ring(wx, wy, fr, 8)
                    renderer.submit_overlay_polys(
                        pts, lp.flash_color + (int(lp.flash_alpha * bolt),))
            frac = fx.fade_frac
            if frac > 0:
                r = fx.radius_tiles
                # feature-storm-acolyte-multi-build: a polygon ring, not a
                # 4-point diamond — the ring's radius is the REAL blast
                # radius, so it reads as round light on the ground instead of
                # a flat rotated box (the damage circle itself is unchanged,
                # visual only).
                pts = _polygon_ring(wx, wy, r, lp.marker_segments)
                # 10J: alpha-filled ground marker fading out (prototype fill);
                # the outline keeps the old colour-fade (lines carry no alpha)
                renderer.submit_overlay_polys(
                    pts, lp.marker_color + (int(lp.marker_fill_alpha * frac),))
                renderer.submit_overlay_lines(
                    pts, tuple(int(ch * frac) for ch in lp.marker_color),
                    width=lp.marker_outline_width, closed=True)

    # -- /10H ---------------------------------------------------------------

    def submit_hp_bars(self, renderer, cs, scene):
        """A red/green bar over every LIVE non-base building below full HP
        (prototype hides the bar at full HP). A building killed but not kidnapped
        sticks around until the round-end revive with its sprite hidden
        (``BuildingSprite``) — an empty bar floating over a bare tile is exactly
        what that hide is for, so dead buildings are skipped too.

        fix-anchor-origin-parity, "anchor wins outright" (designer's
        decision): an authored ``hp_bar`` anchor REPLACES the flat
        ``cy - tile_h*zoom`` baseline outright (the bar's reference point
        becomes the exact handle point, `cs.world_to_screen(anchor_world_
        point(...))`) rather than nudging it (ESV-1's old D3 compose rule).
        No anchor -> the flat baseline exactly as before (D3 unchanged)."""
        zoom = cs.camera.zoom
        tile_h = cs.geometry.tile_h
        assets = getattr(renderer, "assets", None)
        for b in scene.by_tag("building"):
            if getattr(b, "building_type", None) == "base":
                continue
            if not getattr(b, "alive", True):
                continue
            health = b.get_component(Health)
            if health is None or health.hp >= health.max_hp:
                continue
            w, h = 28, 4
            point = anchor_world_point(assets, cs, b, "hp_bar")
            if point is not None:
                x_c, y_c = cs.world_to_screen(*point)
            else:
                cx, cy = cs.world_to_screen(b.transform.wx + 0.5,
                                            b.transform.wy + 0.5)
                x_c, y_c = cx, cy - tile_h * zoom  # a little above the tile centre
            x = int(x_c - w / 2)
            y = int(y_c)
            submit_bar(renderer, x, y, w, h, health.hp / health.max_hp,
                       bg=widgets.C_HP_RED, fill=widgets.C_HP_GREEN, border=(0, 0, 0))

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
            # BR-3/D2: a boss staging its second phase is alive but shows NO
            # bar — it is untouchable, so a draining bar would be a lie.
            if (not getattr(e, "alive", False)
                    or not getattr(e, "targetable", True)):
                continue
            key = (round(e.transform.wx), round(e.transform.wy))
            groups.setdefault(key, []).append(e)

        zoom = cs.camera.zoom
        assets = getattr(renderer, "assets", None)
        for group in groups.values():
            slot = 0
            for e in group:
                health = e.get_component(Health)
                if health is None or health.hp >= health.max_hp:
                    continue
                w = getattr(e, "HP_BAR_W", _ENEMY_BAR_FALLBACK[0])
                h = getattr(e, "HP_BAR_H", _ENEMY_BAR_FALLBACK[1])
                pad = getattr(e, "HP_BAR_PAD", _ENEMY_BAR_FALLBACK[2])
                # fix-anchor-origin-parity, "anchor wins outright": an
                # authored `hp_bar` anchor REPLACES `_sprite_top`'s baseline
                # outright (the bar's reference point becomes the exact
                # handle point) rather than composing on top of it (ESV-1's
                # old D3 compose rule). No anchor -> `_sprite_top` exactly as
                # before (D3 unchanged, footprint fit still load-bearing).
                point = anchor_world_point(assets, cs, e, "hp_bar")
                if point is not None:
                    x_c, y_c = cs.world_to_screen(*point)
                else:
                    cx, cy = cs.world_to_screen(e.transform.wx + 0.5,
                                                e.transform.wy + 0.5)
                    # Hang the bar off the sprite's head: its BOTTOM edge
                    # sits `pad` above the drawn top edge. The sprite grows
                    # with the camera, so both terms ride the zoom — but the
                    # bar itself stays a fixed screen size (every other bar
                    # in this file does).
                    top = _sprite_top(renderer, cs, e, cy, zoom)
                    x_c, y_c = cx, top - pad * zoom
                x = int(x_c - w / 2)
                y = int(y_c) - h - slot * _ENEMY_BAR_STACK
                submit_bar(renderer, x, y, w, h, health.hp / health.max_hp,
                           bg=widgets.C_HP_RED, fill=widgets.C_HP_GREEN)
                slot += 1

    def submit_buff_arrows(self, renderer, cs, scene):
        """A little golden arrow above any ALIVE enemy carrying an active
        buff (``BuffState.sources`` non-empty — today always a Drummer's
        aura, NE-3, but this deliberately keys off "any active buff" rather
        than the source type, per the user's own design call). Shown
        independently of the HP bar's own "hide at full HP" rule — a
        buffed-but-undamaged enemy still gets the arrow.

        Anchored off the SAME ``hp_bar`` point (or its ``_sprite_top``
        fallback) ``submit_enemy_hp_bars`` uses, offset one arrow-height +
        gap above it — a deliberately SIMPLER placeholder than that method:
        it does not stack multiple enemies sharing a tile, since a buffed
        unit's arrow is a status flag, not a competing bar.

        Interchangeable placeholder art (E-37 shape): the ``vfx_buff_arrow``
        slot draws as a real sprite once imported; with no art yet it draws
        a small procedural golden triangle instead, so the feature is
        visible today with zero art asset required."""
        from game.enemies.components import BuffState

        zoom = cs.camera.zoom
        assets = getattr(renderer, "assets", None)
        has_art = (assets is not None
                   and assets.animation_total_ms(BUFF_ARROW_SLOT, "idle")
                   is not None)
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            buffs = e.get_component(BuffState)
            if buffs is None or not buffs.sources:
                continue
            h = getattr(e, "HP_BAR_H", _ENEMY_BAR_FALLBACK[1])
            pad = getattr(e, "HP_BAR_PAD", _ENEMY_BAR_FALLBACK[2])
            point = anchor_world_point(assets, cs, e, "hp_bar")
            if point is not None:
                x_c, y_c = cs.world_to_screen(*point)
            else:
                cx, cy = cs.world_to_screen(e.transform.wx + 0.5,
                                            e.transform.wy + 0.5)
                top = _sprite_top(renderer, cs, e, cy, zoom)
                x_c, y_c = cx, top - pad * zoom
            y = int(y_c) - h - _BUFF_ARROW_GAP
            w = _BUFF_ARROW_W
            if has_art:
                renderer.submit_hud(HudSprite(
                    BUFF_ARROW_SLOT,
                    (int(x_c - w / 2), y - _BUFF_ARROW_H), (w, _BUFF_ARROW_H)))
            else:
                pts = ((int(x_c - w / 2), y),
                       (int(x_c), y + _BUFF_ARROW_H),
                       (int(x_c + w / 2), y))
                renderer.submit_hud(HudLines(pts, _BUFF_ARROW_GOLD, width=2))

    # -- feature-storm-acolyte-multi-build: per-caster charge bars ----------

    def submit_lightning_charge_bars(self, renderer, cs, scene):
        """One bar per alive ``lightning_source`` whose caster is STILL
        CHARGING — the ``submit_hp_bars`` pattern (fixed screen-pixel size,
        never zoom-scaled, anchored through ``cs.world_to_screen``): hidden
        entirely once ready, matching the house "HP bar hides at full HP"
        rule. Fill fraction is ``1 - cooldown / tier_cooldown`` (that
        caster's OWN tier reads its own cooldown ceiling off
        ``core.LightningStrike``); colour lerps from a dim slate toward the
        HUD's ready-yellow as it fills, so a nearly-charged acolyte reads
        visibly yellow before the bar disappears. Drawn ``_CHARGE_BAR_LIFT``
        px below the HP-bar baseline (same anchor point) so the two never
        fully overlap on a damaged, still-charging acolyte."""
        zoom = cs.camera.zoom
        tile_h = cs.geometry.tile_h
        assets = getattr(renderer, "assets", None)
        cooldowns = self._core_balance["LightningStrike"]["cooldown"]
        for b in scene.by_tag("lightning_source"):
            if not getattr(b, "alive", False):
                continue
            caster = b.get_component(LightningCaster)
            if caster is None or caster.cooldown <= 0:
                continue   # ready -> hidden (the HP-bar-at-full-HP rule)
            tier_cd = cooldowns[b.tier_number() - 1]
            frac = 1.0 - (caster.cooldown / tier_cd if tier_cd else 0.0)
            w, h = _CHARGE_BAR_W, _CHARGE_BAR_H
            point = anchor_world_point(assets, cs, b, "hp_bar")
            if point is not None:
                x_c, y_c = cs.world_to_screen(*point)
            else:
                cx, cy = cs.world_to_screen(b.transform.wx + 0.5,
                                            b.transform.wy + 0.5)
                x_c, y_c = cx, cy - tile_h * zoom
            x = int(x_c - w / 2)
            y = int(y_c) + _CHARGE_BAR_LIFT
            fill = tuple(int(a + (r - a) * frac) for a, r in
                        zip(_CHARGE_BAR_SLATE, _CHARGE_BAR_READY_YELLOW))
            submit_bar(renderer, x, y, w, h, frac,
                       bg=widgets.C_UI_BORDER, fill=fill, border=(0, 0, 0))

    # -- /feature-storm-acolyte-multi-build ---------------------------------

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
        ``ui.FX.boss_announce`` timings (unchanged — not this phase's
        concern). Since 10J the fade is a real text alpha (RGBA ``HudText``);
        the colour + alpha ceiling are ``self._vfx_params.announce`` (ESV-3b).
        Ignores the camera; drawn over the game surface. Draws no random
        numbers."""
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
        ap = self._vfx_params.announce
        color = ap.color + (int(ap.max_alpha * k),)
        cx = view_w // 2
        # layout_h: a screen-centred layout position (engine/render/fonts.py).
        cy = view_h // 2 - layout_h("xl") - 6
        submit_centered(renderer, T("effects.announce_line1"), cx, cy, "xl",
                        color)
        submit_centered(renderer, T("effects.announce_line2"), cx,
                        cy + layout_h("xl") + 8, "xl", color)

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
        # BR-3/D2: the HUD bar vanishes for a boss in its second phase too —
        # same `targetable` gate as the overhead bars above.
        boss = next((b for b in scene.by_tag("boss")
                     if getattr(b, "alive", False)
                     and getattr(b, "targetable", True)), None)
        if boss is None:
            return
        health = boss.get_component(Health)
        w, h = _BOSS_HUD_BAR_W, _BOSS_HUD_BAR_H
        x = view_w // 2 - w // 2
        y = view_h - _BOSS_HUD_BAR_LIFT
        ratio = health.hp / health.max_hp if health.max_hp else 0.0
        submit_bar(renderer, x, y, w, h, ratio,
                   bg=widgets.C_HP_RED, fill=widgets.C_HP_GREEN, border=(0, 0, 0))
        submit_text(renderer, T("effects.boss_bar_label"), (x - 10, y - 2),
                    "md", widgets.C_HP_RED, align="right")
        submit_text(renderer, T("effects.boss_bar_hp", hp=health.hp,
                                max_hp=health.max_hp),
                    (x + w + 10, y - 2), "md", widgets.C_UI_TEXT)
