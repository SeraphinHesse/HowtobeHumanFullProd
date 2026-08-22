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
from dataclasses import dataclass   # VA-2: the resolved TriggerRow

from engine.coords import FRONT_RANK
from engine.core import Health, SpriteAnimator
from engine.render import (
    HudLines, HudRect, HudSprite, RenderItem, block_center_offset, fit_factor,
)
from game.anchors import anchor_world_point, sprite_center_world
from engine.render.fonts import layout_h
from engine.vfx import (
    AnnounceParams, BeamParams, BurstParams, CraterParams, DrummerAuraParams,
    FloaterParams, GoldParams, LightningParams, MuzzleParams,
    ProjectileParams, ShardBurstParams, SlashParams, SplatterParams,
    VfxParams, VfxSystem, spawn_play_once,
)
from game.buildings.components import BeamAttacker, Nameplate, TierState
# feat-projectile-variant-select: read-only, at DRAW time, purely to reach a
# live shot's `_shooter` for "level" variant mode — the same shape this module
# already uses on BeamAttacker._target above. No cycle: game/enemies/ imports
# game/buildings/ + engine/, never game/ui/.
from game.enemies.combat import ProjectileArc, ProjectileHoming
from game.core.lightning import LightningCaster
from game.core.phases import GamePhase
from game import vfx_variants

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
# The "lost a life" banner reuses the boss announce's fade/hold/fade timings
# and its centred two-line layout, with its own independent clock and its own
# colour (the HP red — this is a loss, not a warning). Its copy stays a code
# constant here rather than joining the `effects.*` string ids: `strings.json`
# is a closed schema set, so adding two ids is a coupled data+schema change
# that this feature deliberately does not make.
_LIFE_LOST_L1 = "YOU"
_LIFE_LOST_L2 = "LOST 1 LIFE"

# -- feat-sniper-tracer: the Sniper's cosmetic bullet -------------------------
# The Sniper's hit lands INSTANTLY on its cooldown (game/enemies/components.py
# EnemyCombat — "there is no ranged damage concept"); this tracer is the visual
# that was left as a follow-up art pass there. It is purely a UI object: a
# straight muzzle -> victim-sheet-centre flight drawn off this manager's own
# list, never a scene GameObject and never a damage/range expression (D4).
#
# Base-zoom WORLD tiles per second. A module constant rather than a
# `procedural.projectile` key: adding one is a coupled vfx.json + schema +
# editor-form change for a value with no gameplay reach, and this file already
# keeps cosmetic copy/geometry constants of exactly this kind (the two
# `_LIFE_LOST_*` lines above). It is deliberately fast — a rifle round reads
# as a streak, not a lobbed stone.
_TRACER_SPEED_TILES = 14.0
_TRACER_MIN_LIFE = 0.06     # degeneracy floor for a point-blank shot
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
# Several floaters can share one anchor point — most commonly several boost
# buildings buffing the same defender, all landing on that defender's tile in
# the same payout beat. `FloaterManager.submit` STACKS them vertically at
# spawn height (the `submit_enemy_hp_bars` per-tile-group precedent above,
# applied to text instead of bars) rather than letting them draw on top of
# each other. Fixed screen-pixel code chrome, not balancing, like every other
# bar/arrow geometry constant in this file — sized to the "md" floater font's
# line height so stacked rows never overlap.
_FLOATER_STACK_STEP = 14
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

# BossUpgradeTimelinePLAN D20: the RED twin of the arrow above, for an enemy
# carrying an active SLOW (ANY source contributing a negative `move_speed` —
# today the two boss upgrades `mortar_slow`/`stormpriest_slow`, but keyed off
# the STAT, never the source). Same swappable-art rule (E-37) and the same
# "colour/shape are code chrome, only the ART is a designer lever" line
# _BUFF_ARROW_GOLD draws. It reuses the buff arrow's own W/H/GAP deliberately:
# the two are the same badge in two colours, so a second set of geometry
# constants would be two homes for one number.
DEBUFF_ARROW_SLOT = "vfx_debuff_arrow"
_DEBUFF_ARROW_RED = (220, 40, 40)      # placeholder colour
# The two arrows are gated INDEPENDENTLY (`buff_signs`, not `buff_total`'s
# netted sign) and sit in two DIFFERENT spots so they can show TOGETHER on
# one enemy — buffed by a Drummer AND slowed by a mortar at once is a real,
# expected state, not an edge case to net away. Gold stays centred above the
# hp bar (`_buff_arrow_anchor`); red sits to its LEFT, vertically centred on
# the bar (`_debuff_arrow_anchor`) — not above it, so it can never sit on top
# of the bar the way a naive shared-anchor placement would.

# Digger underground telegraph (player-feedback rework): two placeholder
# arrows, the vfx_buff_arrow pattern applied to a raw WORLD point instead of
# a live enemy's own screen anchor (its sprite is hidden while submerged).
DIGGER_MARKER_SLOT = "vfx_digger_marker"
DIGGER_DIRECTION_SLOT = "vfx_digger_direction"
_DIGGER_MARKER_W, _DIGGER_MARKER_H = 12, 10    # base-zoom px
_DIGGER_MARKER_GAP = 4                         # px above the entry tile centre
_DIGGER_MARKER_COLOR = (150, 95, 40)           # placeholder dirt-brown
_DIGGER_DIRECTION_LEN, _DIGGER_DIRECTION_W = 16, 8  # base-zoom px
_DIGGER_DIRECTION_GAP = 4                      # px above the marker
_DIGGER_DIRECTION_COLOR = (255, 205, 60)       # placeholder gold-yellow
# -- /Drummer buff-range indicator + buffed-enemy arrow --

# -- 10J FX: spark/gold/death-shard/muzzle/slash/splatter params live in
# data/balancing/vfx.json now (ESV-3a) — see _params_from_balance below. The
# projectile dot fallback (colour/size/lift, procedural.projectile) is now
# there too — see the fix-anchor-offset-and-bullet-sprites brief's Fix 2.
# -- /10J --


def _source_column(source):
    """``source``'s LIVE master column (its colour), or None.

    Colour IS ``SpriteAnimator.column`` (MasterSheetColumnsPLAN B1), stamped
    at placement and carried through every upgrade — so the object that
    spawns a vfx already knows the column that vfx should be cut at. The
    ``-1`` "no driver" sentinel, a source without an animator, and no source
    at all all answer None, which leaves the manifest entry's stored column
    in charge (D3)."""
    if source is None:
        return None
    getter = getattr(source, "get_component", None)
    if getter is None:
        return None
    animator = getter(SpriteAnimator)
    if animator is None:
        return None
    column = getattr(animator, "column", -1)
    return column if isinstance(column, int) and column >= 0 else None


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
        boost_color=_color(fl["boost_color"]), income_life=fl["income_life"])
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


@dataclass(frozen=True)
class TriggerRow:
    """One resolved ``triggers`` row (VA-2). Was a bare
    ``(sprite_slot, procedural)`` tuple through ESV-6; became a dataclass when
    ``variant_select`` and ``draw_in_front`` joined it, because a 5-tuple at
    the unpack site is where a field silently ends up read as the wrong one.

    The defaults are the "event absent from the table" row, and they are the
    INERT ones: no sprite, no procedural kind, and ``draw_in_front`` matching
    what every effect did before VA-2 (D10)."""

    sprite_slot: str = ""
    procedural: str = ""
    variant_mode: str = vfx_variants.RANDOM
    misc_key: str = ""
    draw_in_front: bool = True


_NO_TRIGGER = TriggerRow()


def _triggers_from_balance(vfx):
    """Turn ``vfx.json``'s top-level ``triggers`` object into a plain
    ``{event: TriggerRow}`` dict — the ONE place a trigger-table EVENT NAME is
    read (ESV-5), mirroring ``_params_from_balance`` for the procedural side;
    nothing downstream (``_play``'s callers) learns a key name, they just pass
    the event string they already know."""
    return {
        event: TriggerRow(
            sprite_slot=row["sprite_slot"],
            procedural=row["procedural"],
            variant_mode=row["variant_select"]["mode"],
            misc_key=row["variant_select"]["misc_key"],
            draw_in_front=row["draw_in_front"],
        )
        for event, row in vfx["triggers"].items()
    }


def _triggers_by_type_from_balance(vfx):
    """Turn ``vfx.json``'s top-level ``triggers_by_type`` object into a plain
    ``{type_key: {event: TriggerRow}}`` dict — the per-TYPE twin of
    ``_triggers_from_balance`` above, and the ONE place the open table's key
    names are read.

    ``.get`` rather than ``[...]``: every bare-constructed ``FloaterManager``
    in the test suite hands this a hand-pinned balance dict, and a table that
    predates the key must degrade to "no per-type rows" rather than raise —
    the same degrade-never-raise contract ``self.assets is None`` keeps for
    the sprite branch of ``_play``."""
    return {
        type_key: {
            event: TriggerRow(
                sprite_slot=row["sprite_slot"],
                procedural=row["procedural"],
                variant_mode=row["variant_select"]["mode"],
                misc_key=row["variant_select"]["misc_key"],
                draw_in_front=row["draw_in_front"],
            )
            for event, row in events.items()
        }
        for type_key, events in vfx.get("triggers_by_type", {}).items()
    }


def _aura_phase_ms(col, row, total_ms):
    """A stable per-TILE animation phase offset, in ms, inside a track of
    ``total_ms``.

    So a cluster of boosters does not pulse in lockstep. Derived from the tile
    coordinates and NEVER from ``self._rng``: that handle is the shared global
    ``random`` stream, and drawing from it once per booster per FRAME would
    desync every downstream roll — the same argument
    ``vfx_variants.resolve``'s <2-variant short-circuit makes. A tile
    derivation also needs no per-building state, survives save/load, and is
    identical on every machine.

    Two knock-on effects, both harmless: a booster MOVED by Building Movement
    re-phases (its sprite is absent for the whole move anyway), and two
    boosters can never share a tile, so no two auras can collide on a phase.
    """
    total = max(1, int(total_ms))
    return ((col * 73856093) ^ (row * 19349663)) % total


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

    ``begin_payout`` is called once when the phase enters INCOME; it reads
    ``state.income_events``/``state.painter_events``/``state.boost_events``
    (filled by ``run_payday``) so it never re-derives the payday math, and
    queues them as three ordered beats — boost, economy(+painter), upkeep —
    released one at a time by ``update(dt)``, ``core.PhaseLoop.
    payout_stagger_interval`` apart, each beat dropped when it has nothing to
    show (only boost/upkeep legitimately can). The income/upkeep floaters
    (not boost/painter) are gated by ``ui.FX.income_floaters_enabled``;
    lifetime is ``vfx.json procedural.floaters.income_life`` — independent of
    ``core.PhaseLoop.income_phase_duration``, which is the payout phase's own
    hold time after its last beat, not a floater's lifetime. The HUD love
    counter (``love_display``) rides the same beat queue for its two-segment
    animation — see ``begin_payout``/``update``.
    """

    def __init__(self, ui_balance, core_balance, vfx_balance):
        self._enabled = ui_balance["FX"]["income_floaters_enabled"]
        # feature-storm-acolyte-multi-build: submit_lightning_charge_bars
        # reads each caster's own tier cooldown ceiling straight off core.
        self._core_balance = core_balance
        self._floaters = []
        # -- Payout-phase sequencing: the boost/economy(+painter)/upkeep
        # beat queue `begin_payout` fills, drained one beat at a time by
        # `update(dt)` — the game/enemies/spawner.py `_queue`/`_timer`
        # pattern. Each queued entry is `(floaters, love_target_or_None)`;
        # `_payout_timer` counts down `core.PhaseLoop.payout_stagger_interval`
        # between releases.
        self._payout_queue = []
        self._payout_timer = 0.0
        # -- Animated love counter: a linear ramp from whatever is currently
        # DISPLAYED toward a target, `love_counter_anim_duration` seconds.
        # Two drivers: begin_payout's two beat releases (an explicit
        # segment each), and the generic per-frame watcher in update() for
        # every other love change. `_love_known` is the last value the
        # animator has either reached or already been told to head toward —
        # while a payout sequence is queued the generic watcher stays quiet,
        # since the queued segments already account for the pending change.
        self._love_display = None
        self._love_known = None
        self._love_anim_start = 0.0
        self._love_anim_target = None
        self._love_anim_elapsed = 0.0
        self._love_anim_duration = ui_balance["FX"]["love_counter_anim_duration"]
        # -- 10G boss announcement: timings from ui.FX.boss_announce; the age
        # clock is None while no announcement runs.
        self._announce = ui_balance["FX"]["boss_announce"]
        self._announce_age = None
        # The "LOST 1 LIFE" banner's own clock, independent of the boss one
        # (both can legitimately be up at once) — same timings, no `enabled`
        # gate: `boss_announce.enabled` is a boss-FX toggle, and a life loss
        # must always be signposted.
        self._life_lost_age = None
        # -- 10J FX state --
        self._gore_enabled = ui_balance["FX"]["gore_enabled"]
        self._building_alive = {} # id(building) -> alive (death watcher)
        self._enemy_cooldowns = {}  # id(enemy) -> last EnemyCombat.cooldown
        # feat-sniper-tracer: live cosmetic bullets, each a dict of
        # from/to world points + age/life + the slot it draws. Advanced in
        # update(), drawn by submit_projectiles, dropped by clear().
        self._tracers = []
        self.log = None           # GameLog, wired by the host
        # vfx-projectile-spritesheets: a persistent ms clock for the beam's
        # has-art HudSprite (a looping "idle" track needs a monotonic
        # anim_time_ms, the same role _announce_age plays for the boss
        # banner's fade — but this one never resets).
        self._beam_clock_ms = 0.0
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
        # The OPEN per-type table beside the closed global one. Nothing
        # dispatches off it automatically — `submit_boost_auras` names the
        # (building_type, "boost_aura") pairs it reads.
        self._triggers_by_type = _triggers_by_type_from_balance(vfx_balance)
        # A monotonic ms clock for the continuous boost auras, the
        # `_beam_clock_ms` shape: it never resets, because
        # Manifest.current_frame wraps modulo the track total, so a
        # forever-growing anim_time_ms is exactly what loops an idle track.
        self._aura_clock_ms = 0.0
        self.assets = None   # AssetStore, wired by the host
        self.scene = None    # Scene, wired by the host
        self.cs = None       # CoordinateSystem, wired by the host (ESV-6)
        # -- /ESV-5/6 --
        # Drummer buff-range telegraph: a manager-owned seconds clock, the
        # hud.py `self._clock` XP-pulse precedent, driving the ring's smooth
        # sine breathe (submit_drummer_auras) — accumulated in update(dt).
        self._clock = 0.0

    def begin_payout(self, state):
        """Called once on the INCOME phase edge (``main.py``), replacing the
        old three separate ``spawn_income_events``/``spawn_painter_events``/
        ``spawn_boost_events`` calls. Builds three ordered payout beats —
        boost, economy (income-kind ``income_events`` entries + Painter's
        finish/lost message), upkeep (upkeep-kind ``income_events``
        entries) — and queues them for staggered release by ``update(dt)``.

        A beat's PRESENCE in the queue mirrors ``payday.py`` step 12's
        ``phase_timer`` formula exactly (boost iff ``state.boost_events`` was
        non-empty, upkeep iff any real upkeep entry exists, economy always) —
        so the queue's shape agrees with how long ``run_payday`` already
        decided the phase should stay open, independent of
        ``ui.FX.income_floaters_enabled``. That flag only decides whether the
        income/upkeep-derived floaters *within* a beat are built — never
        whether the beat/pause/counter-checkpoint happens — matching
        ``spawn_income_events``'s old gating (boost/painter were never
        gated by it either).
        """
        fl = self._vfx_params.floaters
        boost_has_events = bool(state.boost_events)
        upkeep_has_events = any(kind == "upkeep"
                                 for _, _, _, kind in state.income_events)

        boost_beat = []
        for col, row, text in state.boost_events:
            boost_beat.append(_Floater(
                col + 0.5, row + 0.5, text, fl.boost_color, fl.income_life))
        state.boost_events.clear()

        economy_beat = []
        if self._enabled:
            for col, row, amount, kind in state.income_events:
                if kind == "income":
                    economy_beat.append(_Floater(
                        col + 0.5, row + 0.5,
                        T("effects.floater_gain", amount=amount),
                        widgets.C_GOLD, fl.income_life))
        for col, row, text, kind in state.painter_events:
            color = (fl.painter_finished_color if kind == "finished"
                     else fl.painter_lost_color)
            economy_beat.append(
                _Floater(col + 0.5, row + 0.5, text, color, fl.painter_life))
            if self.log is not None:  # 10J game log
                self.log.post(text)
        state.painter_events.clear()

        upkeep_beat = []
        if self._enabled:
            for col, row, amount, kind in state.income_events:
                if kind == "upkeep":
                    upkeep_beat.append(_Floater(
                        col + 0.5, row + 0.5,
                        T("effects.floater_loss", amount=amount),
                        fl.upkeep_color, fl.income_life))

        beats = []
        if boost_has_events:
            beats.append((boost_beat, None))
        beats.append((economy_beat, state.payout_love_after_economy))
        if upkeep_has_events:
            beats.append((upkeep_beat, state.love))

        self._payout_queue = beats
        self._release_next_payout_beat()

    def _release_next_payout_beat(self):
        """Pop and spawn the next queued payout beat (the ``game/enemies/
        spawner.py`` timed-``_queue`` pattern) — called once immediately from
        ``begin_payout`` and again from ``update(dt)`` each time the stagger
        pause elapses. A beat carrying a love target arms the counter
        animation toward it (``_start_love_anim``); ``None`` (the boost
        beat) leaves the counter alone."""
        if not self._payout_queue:
            return
        floaters, love_target = self._payout_queue.pop(0)
        self._floaters.extend(floaters)
        if love_target is not None:
            self._start_love_anim(love_target)
        if self._payout_queue:
            self._payout_timer = (
                self._core_balance["PhaseLoop"]["payout_stagger_interval"])

    def _start_love_anim(self, target):
        """Arm a new linear ramp on the displayed love counter, from
        wherever it currently sits (never from its old TARGET — a retarget
        mid-flight must not jump) to ``target``, over
        ``love_counter_anim_duration``. ``_love_known`` records that this
        target is now accounted for, so ``update``'s generic watcher doesn't
        also fire for the same change."""
        if self._love_display is None:
            self._love_display = target        # fresh game: no count-from-0
        else:
            self._love_anim_start = self._love_display
        self._love_anim_target = target
        self._love_anim_elapsed = 0.0
        self._love_known = target

    @property
    def love_display(self):
        """The HUD's animated love counter — ``int`` when unset (before the
        first ``update(dt, state)`` call, which should never actually be
        observed in the running game)."""
        return 0 if self._love_display is None else round(self._love_display)

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

    def spawn_building_respawn_events(self, state):
        """Drain ``state.building_respawn_events`` (filled by the payday
        revive slot, VA-4) — one effect per building that came BACK from
        dead, at its tile. Called on the INCOME edge beside the income /
        painter / boost floaters.

        The ledger carries the building's tier, so this is the one event
        whose ``level`` variant mode works without an object in hand (D4's
        variant-0 fallback covers the rest). The shipped row plays the
        ``spark_respawn`` preset — the same burst mechanism
        ``place``/``level``/``tier`` use — until a designer imports art into
        ``vfx_respawn``.
        """
        for event in state.building_respawn_events:
            col, row, tier = event[:3]
            # The reviving building's own colour column, when the ledger
            # carries one (a pre-colour ledger row, and every hand-built test
            # triple, is 3 long -> None -> the manifest's stored column wins).
            column = event[3] if len(event) > 3 else None
            self._play("building_respawn", col + 0.5, row + 0.5, level=tier,
                       column=column,
                       preset=self._spark_presets.get(
                           "respawn", self._spark_presets["place"]))
        state.building_respawn_events.clear()

    # -- 10J FX: sparks, gold highlights, death bursts, muzzle/slash, blood --

    # -- ESV-5: the trigger-table dispatch seam ------------------------------

    _SPARK_KINDS = ("spark_place", "spark_level", "spark_tier",
                    "spark_respawn")

    def _play(self, event, wx, wy, source=None, level=None, column=None, **kw):
        """Consult the trigger table: a bound sprite slot with art spawns a
        PlayOnceVfx; otherwise the named procedural kind runs; an empty row
        (or an event absent from the table) is a silent no-op (E-37). ``**kw``
        carries the per-kind extras the procedural branch needs (``preset``
        for the spark burst, ``large=`` for the slash, ``strong=`` for the
        muzzle).

        ``source`` (VA-2) is the building/enemy the event came FROM, when the
        call site has one — it feeds ``"level"`` variant mode and nothing
        else. It is keyword-only-by-position and NOT part of ``**kw`` on
        purpose: ``**kw`` is forwarded verbatim to ``_run_procedural``, and a
        stray ``source=`` arriving there would land in an emitter call.
        Only ``watch_buildings``/``watch_enemies`` pass it; the other five
        events carry a bare world point, so level mode resolves to variant 0
        there (D4).

        ``column`` is the LIVE master column to cut the sprite at — the
        SPAWNING object's colour, so a vfx sheet whose columns are the
        building colours plays in the colour of the building it came from
        (MasterSheetColumnsPLAN: colour IS ``SpriteAnimator.column``). Given
        explicitly by a call site that holds the column without the object
        (the respawn ledger); otherwise read off ``source``. ``None`` — the
        answer for every event that carries a bare world point — leaves the
        manifest entry's own stored column in charge (D3), so nothing that
        predates this changed. Named, never part of ``**kw``, for the same
        reason ``source`` is: ``**kw`` goes verbatim to an emitter call.
        """
        row = self._triggers.get(event, _NO_TRIGGER)
        if row.sprite_slot and self.assets is not None and self.scene is not None:
            # `getattr`, not `.registry`: `self.assets` is a duck-typed
            # host-wired handle (the `self.log`/`self.scene` precedent) that
            # tests and tools stub with far less than a real AssetStore. A
            # stub without a registry resolves the slot unchanged — the same
            # degrade-never-raise contract every other read of this handle
            # keeps.
            slot = vfx_variants.resolve(
                getattr(self.assets, "registry", None), row.sprite_slot,
                row.variant_mode, row.misc_key, rng=self._rng, source=source,
                level=level)
            if column is None:
                column = _source_column(source)
            vfx = spawn_play_once(
                self.scene, self.assets, slot, wx, wy, column=column,
                rank=FRONT_RANK if row.draw_in_front else -1)
            if vfx is not None:
                return
        self._run_procedural(row.procedural, wx, wy, **kw)

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

    def spawn_building_vfx(self, col, row, kind, source=None):
        """Placement/upgrade celebration (prototype ``spawn_building_vfx``,
        game.py:619-626): always a spark burst; ``place``/``tier`` add the
        gold tile highlight. ``kind`` in place / level1 / level2 / tier.
        ESV-5: routed through the trigger table — ``place``/``tier`` map 1:1
        to their own event, ``level1``/``level2`` collapse to the single
        ``building_level_up`` event (they differ only by PRESET, not by
        effect identity; the preset lookup below is unchanged either way).

        ``source`` is the building the celebration is FOR, when the call site
        has one (every one of them does — the panel holds the object it just
        placed or upgraded). Only its COLOUR is read from it: these three
        events keep resolving their variant at index 0 (D4), so the object is
        deliberately NOT passed on as ``source=`` — a `building_placed` sheet
        cut in the building's colour is the ask, a silent switch of variant
        mode is not."""
        preset = self._spark_presets.get(kind, self._spark_presets["place"])
        wx, wy = col + 0.5, row + 0.5
        event = {"place": "building_placed",
                 "tier": "building_tier_up"}.get(kind, "building_level_up")
        self._play(event, wx, wy, column=_source_column(source), preset=preset)
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
            self._play("building_destroyed", wx, wy, source=b)
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
            # `blocked or in_range` — the SAME gate `EnemyCombat.update` ticks
            # its cooldown on (NE-1). It used to read `blocked` alone, which
            # silently excluded the one type that never touches its victim:
            # a Sniper halts at stand-off (`in_range`), so every shot it fired
            # was FX-less. Widened here rather than special-cased so the two
            # gates cannot drift apart again.
            if (last is None or ec.cooldown <= last
                    or pa is None or not (pa.blocked or pa.in_range)):
                continue
            wx, wy = self._anchored(e, "muzzle", *e.transform.world_pos)
            etype = getattr(e, "ETYPE", "standard")
            if etype in ("raider", "boss"):
                self._play("enemy_attack_melee", wx, wy, source=e,
                          large=(etype == "boss"))
            else:
                self._play("enemy_attack_ranged", wx, wy, source=e,
                          strong=(etype == "siege"))
            # feat-sniper-tracer: the ranged type also throws a visible bullet
            # from that same muzzle point to the victim it just hit.
            if etype == "sniper":
                self._spawn_tracer(e, pa, wx, wy)
        if len(self._enemy_cooldowns) > 2 * len(seen) + 16:
            self._enemy_cooldowns = {
                k: v for k, v in self._enemy_cooldowns.items() if k in seen}

    def _tracer_slot(self):
        """The slot the Sniper's bullet draws: the MAX-LEVEL variant of the
        shared ``vfx_projectile`` family, never ``vfx_shell``.

        ``vfx_projectile``/``vfx_shell`` are two independent shared slots
        (``data/CLAUDE.md``) — the stone every defender throws and the shell
        only a mortar lobs — and a rifle round is the former's family, at its
        top variant (``vfx_projectile_v9`` as authored today). Resolved
        through ``vfx_variants.max_variant`` rather than by naming that key
        here, so authoring a tenth variant moves this with it. Falls back to
        the base slot with no registry in hand (E-37).
        """
        return vfx_variants.max_variant(
            getattr(self.assets, "registry", None), "vfx_projectile")

    def _spawn_tracer(self, enemy, pa, muzzle_wx, muzzle_wy):
        """Arm one cosmetic bullet for the shot ``watch_enemies`` just saw.

        FROM the muzzle point that watcher already resolved (``_anchored``'s
        ``muzzle`` handle, the unanchored world position when no handle is
        authored) — never recomputed here, so the bullet leaves exactly where
        the muzzle spray does. TO the victim's SHEET CENTRE
        (``game.anchors.sprite_center_world``), falling back to its plain
        world position when the store/animator cannot size it.

        The victim is resolved the SAME way ``EnemyCombat`` resolves it: the
        blocker scan's ``_target`` if one exists, else the committed target
        off the tilemap (a stand-off unit never runs that scan). No victim in
        hand -> no bullet, rather than a shot into empty space: the hit that
        just landed had a target by construction, so a miss here means the
        watcher is looking at a frame the combat sweep has already cleaned up.
        """
        target = getattr(pa, "_target", None)
        if target is None:
            tm = getattr(pa, "_tilemap", None)
            if tm is not None:
                target = pa.committed_target(tm)
        if target is None:
            return
        point = sprite_center_world(self.assets, self.cs, target)
        if point is None:
            point = target.transform.world_pos
        tx, ty = point
        dist = math.hypot(tx - muzzle_wx, ty - muzzle_wy)
        self._tracers.append({
            "from": (muzzle_wx, muzzle_wy),
            "to": (tx, ty),
            "age": 0.0,
            "life": max(_TRACER_MIN_LIFE, dist / _TRACER_SPEED_TILES),
            "slot": self._tracer_slot(),
        })

    def submit_tracers(self, renderer, cs):
        """Draw every live Sniper bullet at its lerped point between muzzle
        and victim centre.

        Same two-branch draw as ``submit_projectiles``: the imported sheet as
        a ``HudSprite`` at ITS OWN authored frame size (never the dot's), the
        procedural stone dot when the slot has no art yet — resolved with the
        same ``animation_total_ms(slot, "idle") is None`` signal every other
        has-art site uses (E-37), so the two can never disagree about what
        "imported" means. Called from ``submit_projectiles`` so the host's
        draw order is untouched.
        """
        if not self._tracers:
            return
        pr = self._vfx_params.projectile
        zoom = cs.camera.zoom
        for t in self._tracers:
            frac = 1.0 if t["life"] <= 0 else min(1.0, t["age"] / t["life"])
            (fx, fy), (tx, ty) = t["from"], t["to"]
            cx, cy = cs.world_to_screen(fx + (tx - fx) * frac,
                                       fy + (ty - fy) * frac)
            slot = t["slot"]
            has_art = (self.assets is not None
                      and self.assets.animation_total_ms(slot, "idle")
                      is not None)
            if has_art:
                fw, fh = self.assets.frame_size(slot)
                w, h = max(2, int(fw * zoom)), max(2, int(fh * zoom))
                renderer.submit_hud(HudSprite(
                    slot, (int(cx - w / 2), int(cy - h / 2)), (w, h)))
            else:
                dot = max(2, int(pr.stone_size * zoom))
                renderer.submit_hud(HudRect(
                    (int(cx - dot / 2), int(cy - dot / 2), dot, dot),
                    pr.stone_color, border_radius=dot // 2))

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
        self._life_lost_age = None
        self._vfx.clear()  # -- 10J: particles / gold / slashes / splatters
        self._tracers.clear()   # feat-sniper-tracer
        self._payout_queue = []
        self._payout_timer = 0.0
        self._love_display = None
        self._love_known = None
        self._love_anim_target = None

    def update(self, dt, state=None):
        self._clock += dt
        for f in self._floaters:
            f.age += dt
        self._floaters = [f for f in self._floaters if f.age < f.life]
        # -- 10G boss: advance the announcement clock (and the life-lost
        # banner's own, which shares the same timings) --
        a = self._announce
        total = a["fade_in"] + a["hold"] + a["fade_out"]
        if self._announce_age is not None:
            self._announce_age += dt
            if self._announce_age >= total:
                self._announce_age = None
        if self._life_lost_age is not None:
            self._life_lost_age += dt
            if self._life_lost_age >= total:
                self._life_lost_age = None
        self._vfx.update(dt)  # -- 10J: particles / gold / slashes --
        # feat-sniper-tracer: advance the cosmetic bullets and drop the landed
        # ones — the `self._floaters` age/life cull above, applied to flight.
        if self._tracers:
            for t in self._tracers:
                t["age"] += dt
            self._tracers = [t for t in self._tracers if t["age"] < t["life"]]
        # vfx-projectile-spritesheets: the beam's has-art HudSprite anim clock.
        self._beam_clock_ms += dt * 1000.0
        # The boost auras' looping anim clock (submit_boost_auras).
        self._aura_clock_ms += dt * 1000.0
        # -- Payout-phase sequencing: release the next queued beat once the
        # stagger pause elapses.
        if self._payout_queue:
            self._payout_timer -= dt
            if self._payout_timer <= 0:
                self._release_next_payout_beat()
        # -- Animated love counter: advance the current segment, then (only
        # once no payout beats remain queued, so we don't fight the segments
        # begin_payout already armed) watch for any other love change and
        # animate to it. `state=None` (a bare test construction) skips the
        # watcher entirely — no caller relies on love_display then. --
        if self._love_anim_target is not None:
            self._love_anim_elapsed += dt
            frac = (1.0 if self._love_anim_duration <= 0 else
                    min(1.0, self._love_anim_elapsed / self._love_anim_duration))
            self._love_display = (self._love_anim_start + frac * (
                self._love_anim_target - self._love_anim_start))
            if frac >= 1.0:
                self._love_anim_target = None
        if state is not None:
            if self._love_display is None:
                self._love_display = state.love
                self._love_known = state.love
            elif not self._payout_queue and state.love != self._love_known:
                self._start_love_anim(state.love)

    @property
    def active(self):
        return len(self._floaters)

    def submit(self, renderer, cs):
        # Several floaters can share one exact anchor point — most commonly
        # several boost buildings buffing the same defender, all landing on
        # its tile in the same payout beat. Group by anchor (spawn order
        # preserved, `self._floaters` is append-only until culled) and give
        # each one in a group its own vertical slot, the `submit_enemy_hp_
        # bars` per-tile-group precedent applied to floater text.
        groups = {}
        for f in self._floaters:
            groups.setdefault((f.wx, f.wy), []).append(f)
        for group in groups.values():
            for slot, f in enumerate(group):
                frac = f.age / f.life if f.life else 1.0
                cx, cy = cs.world_to_screen(f.wx, f.wy)
                y = (int(cy) - 20 - int(36 * frac)   # rise over its lifetime
                     - slot * _FLOATER_STACK_STEP)   # stack above its group
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

    def _projectile_slot(self, p, shell):
        """The vfx slot in-flight projectile ``p`` draws this frame, resolved
        ONCE per shot (feat-projectile-variant-select).

        The BASE slot is unchanged and stays here rather than in the trigger
        row: ``vfx_shell`` for a mortar's shell, ``vfx_projectile`` for every
        defender's stone. Those two are independent shared slots by design
        (``data/CLAUDE.md``), and one row carries one ``sprite_slot``, so the
        row contributes only ``variant_select`` — which of the base slot's
        interchangeable ``_v<k>`` variants actually plays.

        **Resolved once and cached, never per frame.** ``submit_projectiles``
        runs for every live shot on every frame; calling ``resolve`` there
        would re-roll ``"random"`` mode each frame (a bullet that flickers
        through its whole flight) and — worse — draw from ``self._rng`` once
        per projectile per frame, desyncing the shared stream from what the
        game did before this feature. ``game/vfx_variants.resolve``'s
        ``len(variants) < 2`` short-circuit hides that today, but it stops
        firing the moment a designer authors the second variant this feature
        exists to let them author. The cache is an underscore transient on the
        GameObject (E-11, explicitly allowed by ``GameObject.__setattr__``);
        it lives and dies with the shot, so it needs no invalidation.

        ``source=`` is the FIRING BUILDING, so ``"level"`` mode gives tier 1 /
        2 / 3 their own bullet art: both projectile components already retain
        it as ``_shooter``, and it is read only on the resolve frame. A shot
        whose component or shooter is missing (a hand-built test projectile)
        resolves to variant 0 under ``"level"``, the same D4 fallback the five
        point-only events take.
        """
        slot = getattr(p, "_vfx_slot", None)
        if slot is not None:
            return slot
        base = "vfx_shell" if shell else "vfx_projectile"
        row = self._triggers.get("projectile", _NO_TRIGGER)
        shooter = None
        for cls in (ProjectileHoming, ProjectileArc):
            comp = p.get_component(cls)
            if comp is not None:
                shooter = getattr(comp, "_shooter", None)
                break
        # `getattr(..., "registry", None)`, not `.registry`: `self.assets` is
        # the same duck-typed host-wired handle `_play` guards this way, and
        # is None outright in every bare-constructed test.
        slot = vfx_variants.resolve(
            getattr(self.assets, "registry", None), base, row.variant_mode,
            row.misc_key, rng=self._rng, source=shooter)
        p._vfx_slot = slot
        return slot

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
        disagree about what "imported" means. Still never spawns a
        ``PlayOnceVfx``: projectiles are continuous in-flight objects, like
        beams and lightning. ``self.assets`` is ``None`` in every
        bare-constructed test and degrades to the dot, never raises.

        feat-projectile-variant-select: which of a slot's interchangeable
        VARIANTS draws now comes from the ``projectile`` trigger row's
        ``variant_select``, through ``_projectile_slot`` below — resolved
        ONCE per shot, never per frame.

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
            slot = self._projectile_slot(p, shell)
            color = pr.shell_color if shell else pr.stone_color
            dot = max(2, int((pr.shell_size if shell else pr.stone_size)
                             * zoom))
            has_art = (self.assets is not None
                      and self.assets.animation_total_ms(slot, "idle")
                      is not None)
            if has_art:
                # Imported art draws at ITS OWN authored frame size, not at
                # the dot's — `stone_size`/`shell_size` describe the
                # procedural fallback below and were tuned for it, so reusing
                # them here silently downscaled every imported bullet (a
                # 64x64 sheet drew at 32 px; found live). Same
                # `assets.frame_size` sizing `submit_beams` uses for an
                # imported `vfx_beam`, and the same reason: no new balancing
                # key for a size the manifest already states.
                fw, fh = self.assets.frame_size(slot)
                w, h = max(2, int(fw * zoom)), max(2, int(fh * zoom))
                renderer.submit_hud(HudSprite(
                    slot, (int(cx - w / 2), int(cy - h / 2)), (w, h)))
            else:
                renderer.submit_hud(HudRect(
                    (int(cx - dot / 2), int(cy - dot / 2), dot, dot),
                    color, border_radius=dot // 2))
        # feat-sniper-tracer: enemy bullets ride the same draw beat as the
        # defenders' shots — they are the same kind of object, and hanging
        # them here keeps the host's draw list unchanged.
        self.submit_tracers(renderer, cs)

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
        shape), not itself a tunable. Draws no random numbers.

        **The owning building must be checked for ``alive`` too, not just the
        target (fix: lingering beam after Sun Scorcher destroyed).**
        ``_update_defender`` (``game/enemies/combat.py``) bails out before
        ``_update_beam`` runs at all once the defender itself is dead, so a
        killed Sun Scorcher's ``BeamAttacker._target`` is never cleared — it
        stays frozen on whatever it last locked. Dead buildings are not
        despawned (they revive at payday) and keep their ``"combat"`` tag, so
        without this guard the beam kept drawing from the destroyed
        building's tile for as long as its last target stayed alive.

        vfx-projectile-spritesheets: a designer-imported ``vfx_beam`` sheet
        REPLACES the line with a looping ``HudSprite`` at the target's screen
        point — the same has-art signal ``submit_projectiles`` already uses
        (``assets.animation_total_ms(slot, "idle") is not None``). A fixed
        sprite at a point, not a stretched/rotated beam texture: ``HudSprite``
        has no rotation support, so this is the same toggle shape the
        projectile dot already has, not a new engine primitive. Sized off the
        manifest's own frame size (``self.assets.frame_size``), zoom-scaled —
        no new balancing key. No art -> the HudLines line, byte-identical to
        before this existed."""
        bp = self._vfx_params.beam
        zoom = cs.camera.zoom
        has_art = (self.assets is not None
                  and self.assets.animation_total_ms("vfx_beam", "idle")
                  is not None)
        for b in scene.by_tag("combat"):
            beam = b.get_component(BeamAttacker)
            if beam is None:
                continue
            if not getattr(b, "alive", True):
                continue
            target = getattr(beam, "_target", None)
            if target is None or not getattr(target, "alive", False):
                continue
            tx, ty = cs.world_to_screen(target.transform.wx + 0.5,
                                        target.transform.wy + 0.5)
            if has_art:
                fw, fh = self.assets.frame_size("vfx_beam")
                size = (max(1, int(fw * zoom)), max(1, int(fh * zoom)))
                dest = (int(tx - size[0] / 2), int(ty - size[1] / 2))
                renderer.submit_hud(HudSprite(
                    "vfx_beam", dest, size, animation="idle",
                    anim_time_ms=int(self._beam_clock_ms)))
                continue
            tier = b.get_component(TierState).current_tier
            color = bp.colors[min(tier, len(bp.colors) - 1)]
            ox, oy = cs.world_to_screen(b.transform.wx + 0.5, b.transform.wy + 0.5)
            # crystal-ball height: origin_lift_tiles tile-heights above centre
            top = int(cs.geometry.tile_h * zoom * bp.origin_lift_tiles)
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

    def submit_boost_auras(self, renderer, cs, scene):
        """The always-on aura behind every live boost building, bound by
        ``triggers_by_type.<building_type>.boost_aura``.

        CONTINUOUS, so it deliberately does NOT go through ``_play``:
        ``PlayOnceVfx``'s despawn clock would respawn the object every frame
        (the VA-5 tile-highlight / ``triggers.projectile`` reasoning). Like
        ``submit_highlight`` it re-submits a plain ``RenderItem`` on the
        depth-sorted world layer each frame, and like ``submit_drummer_auras``
        above it walks the scene for live entities rather than being pushed a
        list of tiles.

        Four gates, in order, each a ``continue`` and never a raise:

        1. **No row / no slot** — a boost line a designer has not authored.
        2. **Hidden building** — ``BuildingSprite.hidden``, the SHARED
           predicate the sprite's own ``render_items`` early-returns on, so
           the aura cannot drift from the thing it sits behind (dead, and the
           placement ``reveal_delay``; kidnapped buildings are the dead case).
        3. **No art on the RESOLVED variant** — the usual
           ``animation_total_ms(slot, "idle") is not None`` probe (E-37), and
           deliberately on the resolved slot rather than the family stem:
           ``variant_select.mode "level"`` means variant N is the booster's
           GLOBAL level N, and a level whose art is not imported yet draws
           NOTHING rather than falling back to a lower level's sheet. That is
           the user's explicit call — a half-imported family should look
           half-imported, not silently reuse level 1 art at level 9.
        4. **``draw_in_front``** — false on every shipped row, so
           ``rank = -1`` puts the aura BEHIND the booster sharing its tile
           (the same mapping ``submit_highlight`` makes). True maps to
           ``FRONT_RANK``, which draws over every same-layer item rather than
           only winning an exact depth tie (fix/showinfront-always-wins).

        ``fit_tiles`` is deliberately left at its 0 default even though the
        art is cut 192x96 to cover a 3x3 block: with ``fit_tiles == 0`` the
        renderer blits the frame centred on the tile diamond's centre, and a
        3x3 iso block's bounding diamond is exactly 192x96 about that same
        centre — so the coverage lands with no offset at all. Setting
        ``fit_tiles=3`` would instead trigger ``block_center_offset`` and
        shift the blit by a tile, because the aura is addressed by its CENTRE
        tile, not a block min-corner.

        ``b.building_type`` is the only boost-type STRING spoken here, and it
        is spoken in ``game/`` — never in ``engine/vfx/`` (D5)."""
        from game.buildings.components import BuildingSprite

        if self.assets is None or not self._triggers_by_type:
            return
        registry = getattr(self.assets, "registry", None)
        for b in scene.by_tag("boost"):
            row = self._triggers_by_type.get(
                b.building_type, {}).get("boost_aura")
            if row is None or not row.sprite_slot:
                continue
            sprite = b.get_component(BuildingSprite)
            if sprite is None or sprite.hidden:
                continue
            slot = vfx_variants.resolve(
                registry, row.sprite_slot, row.variant_mode, row.misc_key,
                rng=self._rng, source=b)
            total = self.assets.animation_total_ms(slot, "idle")
            if total is None:
                continue
            phase = _aura_phase_ms(b.col, b.row, total)
            renderer.submit(RenderItem(
                slot, (b.col, b.row), animation="idle",
                anim_time_ms=int(self._aura_clock_ms + phase),
                rank=FRONT_RANK if row.draw_in_front else -1))

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

    def _hp_bar_rect(self, renderer, cs, e, zoom, assets):
        """``(x_c, bar_top, w, h)`` — the on-screen horizontal centre, TOP
        edge, width and height of `e`'s hp bar's own slot (slot 0; the arrow
        badges do not account for same-tile stacking, see
        ``submit_buff_arrows``'s docstring). The SAME ``hp_bar`` anchor point
        (or its ``_sprite_top`` fallback) ``submit_enemy_hp_bars`` uses.

        Factored out so the gold buff arrow and the red debuff arrow
        (BossUpgradeTimelinePLAN D20) can never drift apart on where the bar
        itself actually is, even though they now sit in two different spots
        relative to it."""
        w = getattr(e, "HP_BAR_W", _ENEMY_BAR_FALLBACK[0])
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
        return x_c, int(y_c) - h, w, h

    def _buff_arrow_anchor(self, renderer, cs, e, zoom, assets):
        """Where the gold buff badge hangs: centred above the hp bar, clear
        of its top edge by ``_BUFF_ARROW_GAP``."""
        x_c, bar_top, _w, _h = self._hp_bar_rect(renderer, cs, e, zoom, assets)
        return x_c, bar_top - _BUFF_ARROW_GAP

    def _debuff_arrow_anchor(self, renderer, cs, e, zoom, assets):
        """Where the red debuff badge hangs: to the LEFT of the hp bar,
        vertically centred on it — a different spot from the buff badge's
        (not merely a different colour at the same point), so the two can be
        shown TOGETHER without ever overlapping each other or the bar."""
        x_c, bar_top, w, h = self._hp_bar_rect(renderer, cs, e, zoom, assets)
        x = x_c - w / 2 - _BUFF_ARROW_GAP - _BUFF_ARROW_W / 2
        y = bar_top + h / 2 + _BUFF_ARROW_H / 2
        return x, y

    def _submit_arrow(self, renderer, x_c, y, slot, has_art, color):
        """Draw ONE arrow badge, ending exactly AT ``y`` and extending
        ``_BUFF_ARROW_H`` px upward from it — the imported sprite if the slot
        has art, else a procedural triangle outline pointing down at ``y``
        (E-37). Both branches occupy the SAME ``[y - H, y]`` span so neither
        can straddle (and overlap) whatever ``y`` was chosen to clear."""
        w = _BUFF_ARROW_W
        if has_art:
            renderer.submit_hud(HudSprite(
                slot, (int(x_c - w / 2), y - _BUFF_ARROW_H),
                (w, _BUFF_ARROW_H)))
        else:
            pts = ((int(x_c - w / 2), y),
                   (int(x_c), y - _BUFF_ARROW_H),
                   (int(x_c + w / 2), y))
            renderer.submit_hud(HudLines(pts, color, width=2))

    def submit_buff_arrows(self, renderer, cs, scene):
        """A little golden arrow above any ALIVE enemy carrying AT LEAST ONE
        source with a POSITIVE ``move_speed`` contribution — i.e. something
        is genuinely making it faster (today always a Drummer's aura, NE-3,
        but keyed off the STAT, never the source type). Shown independently
        of the HP bar's own "hide at full HP" rule — a buffed-but-undamaged
        enemy still gets the arrow.

        **Gated on ``buff_signs``, not ``buff_total``'s netted sign**
        (BossUpgradeTimelinePLAN D20 follow-up): an enemy simultaneously
        buffed by a Drummer AND slowed by a mortar is a real state the
        player should see BOTH indicators for, not the one that happens to
        win the sum. The gold and red arrows are independent booleans now,
        not the two signs of one aggregate.

        Anchored off the SAME ``hp_bar`` point (or its ``_sprite_top``
        fallback) ``submit_enemy_hp_bars`` uses, centred above it — a
        deliberately SIMPLER placeholder than that method: it does not stack
        multiple enemies sharing a tile, since a buffed unit's arrow is a
        status flag, not a competing bar.

        Interchangeable placeholder art (E-37 shape): the ``vfx_buff_arrow``
        slot draws as a real sprite once imported; with no art yet it draws
        a small procedural golden triangle instead, so the feature is
        visible today with zero art asset required."""
        from game.enemies.components import buff_signs

        zoom = cs.camera.zoom
        assets = getattr(renderer, "assets", None)
        has_art = (assets is not None
                   and assets.animation_total_ms(BUFF_ARROW_SLOT, "idle")
                   is not None)
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            has_buff, _has_slow = buff_signs(e, "move_speed")
            if not has_buff:
                continue
            x_c, y = self._buff_arrow_anchor(renderer, cs, e, zoom, assets)
            self._submit_arrow(renderer, x_c, y, BUFF_ARROW_SLOT, has_art,
                               _BUFF_ARROW_GOLD)

    def submit_debuff_arrows(self, renderer, cs, scene):
        """``submit_buff_arrows``'s RED twin (BossUpgradeTimelinePLAN D20):
        the same badge, to the LEFT of the hp bar instead of above it, above
        any ALIVE enemy carrying at least one source with a NEGATIVE
        ``move_speed`` contribution — an active slow.

        Keyed on the STAT, not on who applied it, exactly like its gold
        sibling: today's two writers are the boss upgrades ``mortar_slow``
        (#3) and ``stormpriest_slow`` (#7) through
        ``game.enemies.components.apply_slow`` (D19), but anything that ever
        slows an enemy gets the indicator for free. Interchangeable
        placeholder art (E-37): the ``vfx_debuff_arrow`` slot draws as a real
        sprite once imported, else a small procedural red triangle.

        Gated on ``buff_signs``, independently of the gold arrow above — an
        enemy that is BOTH speed-buffed and slowed shows both badges at
        once, in their two distinct spots, never overlapping each other or
        the bar."""
        from game.enemies.components import buff_signs

        zoom = cs.camera.zoom
        assets = getattr(renderer, "assets", None)
        has_art = (assets is not None
                   and assets.animation_total_ms(DEBUFF_ARROW_SLOT, "idle")
                   is not None)
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            _has_buff, has_slow = buff_signs(e, "move_speed")
            if not has_slow:
                continue
            x_c, y = self._debuff_arrow_anchor(renderer, cs, e, zoom, assets)
            self._submit_arrow(renderer, x_c, y, DEBUFF_ARROW_SLOT, has_art,
                               _DEBUFF_ARROW_RED)

    def submit_digger_telegraphs(self, renderer, cs, scene):
        """Two placeholder arrows over a burrowed Digger's CURRENT dig — the
        only visible trace of it while ``BurrowAgent.state ==
        BURROW_SUBMERGED`` hides its sprite entirely
        (``SpriteAnimator.visible = False``), alongside — never instead of —
        the existing dirt-pile decal (``game/enemies/dirt_pile.py``): a
        marker hovering over the entry tile (``start_wx``/``start_wy``,
        re-set every new hop by ``BurrowAgent._submerge`` — so it MOVES with
        each hop, never pinned to the original spawn dig) and a second arrow
        rotated to point at ``dest_col``/``dest_row``, the segment currently
        being dug. Both anchor off a raw WORLD point rather than the owner's
        own screen anchor (unlike ``submit_buff_arrows``): the Digger is
        untargetable and its sprite hidden here, so there is no live sprite
        silhouette to anchor against.

        Interchangeable placeholder art (E-37, the ``submit_buff_arrows``
        shape): ``vfx_digger_marker``/``vfx_digger_direction`` draw as real
        sprites once imported — unrotated at the anchor point, the
        ``submit_beams`` sprite toggle's own accepted limitation
        (``HudSprite`` carries no rotation) — and fall back to two small
        procedural triangles otherwise: a downward pin over the entry tile,
        and a chevron rotated (via ``atan2`` on the projected screen delta)
        toward the dig's real destination."""
        from game.enemies.components import BURROW_SUBMERGED, BurrowAgent

        assets = getattr(renderer, "assets", None)
        has_marker_art = (assets is not None and assets.animation_total_ms(
            DIGGER_MARKER_SLOT, "idle") is not None)
        has_direction_art = (assets is not None and assets.animation_total_ms(
            DIGGER_DIRECTION_SLOT, "idle") is not None)
        for e in scene.by_tag("enemy"):
            if not getattr(e, "alive", False):
                continue
            burrow = e.get_component(BurrowAgent)
            if burrow is None or burrow.state != BURROW_SUBMERGED:
                continue
            cx, cy = cs.world_to_screen(burrow.start_wx + 0.5,
                                        burrow.start_wy + 0.5)
            mw, mh = _DIGGER_MARKER_W, _DIGGER_MARKER_H
            my = int(cy) - _DIGGER_MARKER_GAP
            if has_marker_art:
                renderer.submit_hud(HudSprite(
                    DIGGER_MARKER_SLOT,
                    (int(cx - mw / 2), my - mh), (mw, mh)))
            else:
                pts = ((int(cx - mw / 2), my - mh), (int(cx), my),
                       (int(cx + mw / 2), my - mh))
                renderer.submit_hud(
                    HudLines(pts, _DIGGER_MARKER_COLOR, width=2))

            dx, dy = cs.world_to_screen(burrow.dest_col + 0.5,
                                        burrow.dest_row + 0.5)
            ddx, ddy = dx - cx, dy - cy
            length = math.hypot(ddx, ddy)
            if length < 1e-6:
                ux, uy = 0.0, -1.0    # degenerate (same tile): point "up"
            else:
                ux, uy = ddx / length, ddy / length
            acx = cx
            acy = my - mh - _DIGGER_DIRECTION_GAP
            aw, ah = _DIGGER_DIRECTION_LEN, _DIGGER_DIRECTION_LEN
            if has_direction_art:
                renderer.submit_hud(HudSprite(
                    DIGGER_DIRECTION_SLOT,
                    (int(acx - aw / 2), int(acy - ah / 2)), (aw, ah)))
            else:
                half = _DIGGER_DIRECTION_LEN / 2
                tip = (acx + ux * half, acy + uy * half)
                base_x, base_y = acx - ux * half, acy - uy * half
                px, py = -uy, ux
                hw = _DIGGER_DIRECTION_W / 2
                left = (base_x + px * hw, base_y + py * hw)
                right = (base_x - px * hw, base_y - py * hw)
                pts = tuple((int(x), int(y)) for x, y in (tip, left, right))
                renderer.submit_hud(
                    HudLines(pts, _DIGGER_DIRECTION_COLOR, width=2))

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
        # The life-lost banner shares this per-frame drain call rather than
        # getting a second host wiring line — `spawn_boss_events(state)` is
        # already the frame's "drain the announce-banner ledgers" hook and is
        # called once per frame from game/main.py with the live RunState.
        self.spawn_life_lost_events(state)
        if not state.boss_events:
            return
        state.boss_events.clear()
        if not self._announce["enabled"]:
            return
        self._announce_age = 0.0

    def spawn_life_lost_events(self, state):
        """Drain ``state.life_lost_events`` (one marker per CHARGED base hit,
        appended by ``Session.on_base_hit``) into the "YOU / LOST 1 LIFE"
        banner. Unlike the boss announcement there is no ``enabled`` gate —
        ``ui.FX.boss_announce.enabled`` is a boss-FX toggle and losing a life
        must always be signposted; only its TIMINGS are shared. Re-arming
        restarts the fade from 0 (the ledger can carry at most one entry per
        round by construction — see ``RunState.life_lost_events``)."""
        if not state.life_lost_events:
            return
        state.life_lost_events.clear()
        self._life_lost_age = 0.0

    def life_lost_active(self):
        """True while the "YOU / LOST 1 LIFE" banner is still on screen (its
        fade-in -> hold -> fade-out clock is running).

        The host uses this to hold the boss-upgrade cutscene back until the
        life-loss announcement has finished: losing a boss round queues both,
        and the modal used to open on top of the banner ~1.9s early
        (round_end_delay 1.4s vs the banner's 3.3s). The clock lives here, so
        the question is answered here rather than by main.py reaching into a
        private field."""
        return self._life_lost_age is not None

    def _announce_k(self, age):
        """The shared fade-in -> hold -> fade-out ramp (0..1) for an
        announcement clock, on the ``ui.FX.boss_announce`` timings."""
        a = self._announce
        if age < a["fade_in"]:
            k = age / a["fade_in"] if a["fade_in"] > 0 else 1.0
        elif age < a["fade_in"] + a["hold"]:
            k = 1.0
        else:
            out = age - a["fade_in"] - a["hold"]
            k = 1.0 - out / a["fade_out"] if a["fade_out"] > 0 else 0.0
        return max(0.0, min(1.0, k))

    def submit_announce(self, renderer, view_w, view_h):
        """The screen-centred "SOMETHING BIG / IS APPROACHING!" banner
        (prototype ``effects.py:292-337``): fade in -> hold -> fade out on the
        ``ui.FX.boss_announce`` timings (unchanged — not this phase's
        concern). Since 10J the fade is a real text alpha (RGBA ``HudText``);
        the colour + alpha ceiling are ``self._vfx_params.announce`` (ESV-3b).
        Ignores the camera; drawn over the game surface. Draws no random
        numbers.

        Also draws the "YOU / LOST 1 LIFE" banner off its own independent
        clock, in the same centred two-line style and on the same timings —
        one submit call site for both, so the host needs no second wiring
        line. Both can be up at once; the life-lost banner is drawn second
        (on top) because it is the more urgent of the two."""
        ap = self._vfx_params.announce
        cx = view_w // 2
        # widgets.announce_top_y is the ONE home for this banner's vertical
        # layout — hud.py hangs the lost-life icon off its companion
        # announce_bottom_y, and the two must not drift apart.
        cy = widgets.announce_top_y(view_h)
        if self._announce_age is not None:
            color = ap.color + (int(ap.max_alpha * self._announce_k(
                self._announce_age)),)
            submit_centered(renderer, T("effects.announce_line1"), cx, cy,
                            "xl", color)
            submit_centered(renderer, T("effects.announce_line2"), cx,
                            cy + layout_h("xl") + 8, "xl", color)
        if self._life_lost_age is not None:
            # widgets.C_HP_RED is read as an ATTRIBUTE at call time, never
            # import-bound — configure_palette() rebinds it (game/ui/CLAUDE.md).
            color = tuple(widgets.C_HP_RED[:3]) + (
                int(ap.max_alpha * self._announce_k(self._life_lost_age)),)
            submit_centered(renderer, _LIFE_LOST_L1, cx, cy, "xl", color)
            submit_centered(renderer, _LIFE_LOST_L2, cx, cy + layout_h("xl") + 8,
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
