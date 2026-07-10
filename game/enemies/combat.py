"""Combat resolution (Phase 9E): defender fire, projectiles, base/death.

The type-agnostic combat sweep the host (and tests) call each frame AFTER
``scene.update(dt)``. It ports the prototype's three combat concerns onto clean
architecture:

1. **Defender fire** — every combatant (selected by the ``"combat"`` tag, never
   by class, per SPEC G-3) keeps its sticky target if it is still alive and in
   Chebyshev range, else acquires the nearest in-range enemy by Euclidean world
   distance (game-side tiebreak). On its cooldown it spawns a ``Projectile``;
   the reset interval is clamped to ``DefenceBuildings.globals.min_attack_speed``.
2. **Base arrival** — an enemy whose ``PathAgent.reached_base`` is set is
   consumed at the base. With no ``on_base_hit`` callback (9E tests) it deals its
   ``dmg`` straight to the base's ``Health`` (+ its ``RoundStats``). With a
   callback (9F ``Session``) the sweep hands off exactly ONE arrival per frame,
   then despawns it and bails — the prototype's ``_update_enemy_phase`` returns
   on the first base hit, so lives/HP/game-over/round-wipe stays a core concern
   and ``game/enemies`` never imports ``game/core``.
3. **Death cleanup** — any enemy with a dead ``Health`` is despawned.

**Projectiles** travel then deal GUARANTEED damage on arrival if the target is
still alive (prototype ``defence_building.Projectile``): a shot in flight is
wasted only if its target dies first — never a collision/accuracy miss. Travel
time = ``distance / projectile_speed_tiles``. They are logical GameObjects with
no sprite in 9E (real stone art is the 10J FX sweep).
"""
import math

from engine.core import Component, GameObject, Health, SpriteAnimator, Transform
from game.buildings.components import Attacker, RoundStats
from .components import PathAgent


class ProjectileHoming(Component):
    """A homing shot: moves toward its (live) target and, when its travel timer
    expires, applies guaranteed damage if the target still lives, then despawns
    itself. Target / shooter / scene are transient refs (not serialized)."""

    dmg: int = 0
    speed: float = 1.0
    timer: float = 0.0

    def on_added(self, owner):
        self._proj = owner
        self._target = None
        self._shooter = None
        self._scene = None

    def launch(self, target, shooter, scene):
        self._target = target
        self._shooter = shooter
        self._scene = scene
        px, py = self._proj.transform.world_pos
        tx, ty = target.transform.world_pos
        dist = math.hypot(tx - px, ty - py)
        self.timer = dist / self.speed if self.speed > 0 else 0.0

    def update(self, dt):
        proj = getattr(self, "_proj", None)
        target = getattr(self, "_target", None)
        if proj is None:
            return
        if target is not None:
            tx, ty = target.transform.world_pos
            px, py = proj.transform.world_pos
            dx, dy = tx - px, ty - py
            d = math.hypot(dx, dy)
            step = self.speed * dt
            if d > 1e-9 and step < d:
                proj.transform.wx = px + dx / d * step
                proj.transform.wy = py + dy / d * step
            else:
                proj.transform.wx, proj.transform.wy = tx, ty
        self.timer -= dt
        if self.timer <= 0:
            self._impact()

    def _impact(self):
        target = getattr(self, "_target", None)
        shooter = getattr(self, "_shooter", None)
        scene = getattr(self, "_scene", None)
        if target is not None and getattr(target, "alive", False):
            target.get_component(Health).damage(self.dmg)
            if shooter is not None:
                rs = shooter.get_component(RoundStats)
                if rs is not None:
                    rs.dmg_dealt_this_round += self.dmg
        if scene is not None:
            scene.despawn(self._proj)


class Projectile(GameObject):
    """A defender's in-flight shot (logical only in 9E; no sprite)."""

    def __init__(self, wx, wy, dmg, speed):
        super().__init__(
            name="projectile",
            tags=("projectile",),
            transform=Transform(wx=wx, wy=wy, layer="entities"),
            components=[ProjectileHoming(dmg=dmg, speed=speed)],
        )


# -- targeting helpers ----------------------------------------------------

def _enemy_tile(enemy):
    wx, wy = enemy.transform.world_pos
    return (round(wx), round(wy))


def _chebyshev(center_tile, enemy):
    ec, er = _enemy_tile(enemy)
    return max(abs(ec - center_tile[0]), abs(er - center_tile[1]))


def _euclid_sq(a, b):
    ax, ay = a.transform.world_pos
    bx, by = b.transform.world_pos
    return (ax - bx) ** 2 + (ay - by) ** 2


def attack_interval(defender, min_attack_speed):
    """Seconds between shots, clamped by the shared ``min_attack_speed`` floor
    (prototype ``_effective_attack_speed``; boosts/penalties land 10B/10D)."""
    return max(min_attack_speed, defender.attack_speed())


# -- the sweep ------------------------------------------------------------

def resolve_combat(scene, tilemap, dt, buildings_balance, on_base_hit=None,
                   on_enemy_death=None):
    globals_ = buildings_balance["DefenceBuildings"]["globals"]
    min_atk = globals_["min_attack_speed"]
    proj_speed = globals_["projectile_speed_tiles"]

    enemies = [e for e in scene.by_tag("enemy") if e.alive]
    for defender in scene.by_tag("combat"):
        _update_defender(defender, scene, enemies, dt, min_atk, proj_speed)

    _resolve_base_arrivals(scene, tilemap, on_base_hit)

    for enemy in scene.by_tag("enemy"):
        if not enemy.alive:
            # 10A: the session counts the kill + awards XP here. Base arrivals
            # left through `on_base_hit` above and were already despawned, so
            # they can never reach this sweep — no double award.
            if on_enemy_death is not None:
                on_enemy_death(enemy)
            scene.despawn(enemy)


def _update_defender(defender, scene, enemies, dt, min_atk, proj_speed):
    attacker = defender.get_component(Attacker)
    if attacker is None or not getattr(defender, "alive", True):
        return
    center = (defender.col, defender.row)
    rng = defender.range_tiles()
    in_range = [e for e in enemies if _chebyshev(center, e) <= rng]

    target = getattr(attacker, "_target", None)
    if target is not None and target not in in_range:
        target = None
    if target is None and in_range:
        target = min(in_range, key=lambda e: _euclid_sq(defender, e))
    attacker._target = target
    attacker.has_target = target is not None
    # Play the attack animation while engaging a target (e.g. the stone
    # thrower's throw), idle otherwise — mirrors the enemy PathAgent's
    # walk/attack switch and the prototype's `_animating` state.
    _set_defender_anim(defender, "attack" if target is not None else "idle")

    attacker.cooldown -= dt
    if target is not None and attacker.cooldown <= 0:
        _fire(defender, target, scene, proj_speed)
        attacker.cooldown = attack_interval(defender, min_atk)


def _set_defender_anim(defender, name):
    anim = defender.get_component(SpriteAnimator)
    if anim is not None and anim.animation != name:
        anim.set_animation(name)


def _fire(defender, target, scene, proj_speed):
    bx, by = defender.transform.world_pos
    proj = Projectile(bx, by, defender.damage(), proj_speed)
    proj.get_component(ProjectileHoming).launch(target, defender, scene)
    scene.spawn(proj)


def _resolve_base_arrivals(scene, tilemap, on_base_hit=None):
    base_tile = tilemap.get(tilemap.base_col, tilemap.base_row)
    base = base_tile.occupant if base_tile is not None else None
    for enemy in scene.by_tag("enemy"):
        pa = enemy.get_component(PathAgent)
        if pa is None or not pa.reached_base:
            continue
        if on_base_hit is not None:
            # 9F: hand off ONE arrival to the session (lives/HP/game-over/wipe),
            # despawn it, and stop — the prototype returns on the first hit.
            on_base_hit(enemy)
            scene.despawn(enemy)
            return
        if base is not None:
            base.get_component(Health).damage(enemy.dmg)
            rs = base.get_component(RoundStats)
            if rs is not None:
                rs.dmg_taken_this_round += enemy.dmg
        scene.despawn(enemy)
