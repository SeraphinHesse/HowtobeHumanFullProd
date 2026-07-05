"""Enemy state components (Phase 9E).

All authoritative enemy state lives here (engine E-11), mirroring the building
side (``game/buildings/components.py``). Two components drive the walker:

* ``PathAgent`` — the navigation brain. It owns the "am I walking or stopped to
  attack a blocking building" decision and gates the engine ``Movement``
  component that does the actual locomotion. It runs BEFORE ``Movement`` in the
  component list, so the halt decision it makes takes effect the same frame (no
  drift into a blocked tile). It caches an environment reference to the
  ``TileMap`` in ``_tilemap`` — a deliberate transient, exactly like
  ``Movement._owner`` (the E-11 guard is on GameObject, not Component).
* ``EnemyCombat`` — combat stats + the enemy-attacks-a-building clock. It ticks
  ONLY while ``PathAgent`` reports ``blocked`` (prototype ``enemy._do_attack``).

The prototype's pixel-space ``_do_move``/``_do_attack`` split maps onto these two
components; locomotion itself is the pure ``engine.physics.advance`` step wrapped
by ``engine.core.Movement``.
"""
from engine.core import Component, Health, Movement, SpriteAnimator
from game.buildings.components import RoundStats


class PathAgent(Component):
    """Walks a precomputed tile path toward the base, stopping to attack a
    living non-base building that sits on the next path tile. ``reached_base``
    is the prototype's ``reached_base`` (consumed by the combat sweep, which
    applies base damage + despawns). Gates ``Movement`` by zeroing its speed
    while blocked and restoring it on unblock — the path (``Movement.waypoints``)
    is never discarded, so no re-path is needed when the blocker dies (the route
    already runs through that now-passable tile)."""

    reached_base: bool = False
    blocked: bool = False

    def on_added(self, owner):
        self._owner = owner
        self._tilemap = None      # set by Enemy at construction
        self._real_speed = 0.0    # cached move speed for block/unblock gating
        self._target = None       # the building we are stopped attacking

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        tm = getattr(self, "_tilemap", None)
        if owner is None or tm is None or self.reached_base:
            return
        mv = owner.get_component(Movement)
        if mv is None:
            return
        if mv.arrived:
            self.reached_base = True
            return
        wps = mv.waypoints
        if not wps or mv.index >= len(wps):
            return
        wp = wps[mv.index]
        tc, tr = round(wp[0]), round(wp[1])
        is_base = (tc == tm.base_col and tr == tm.base_row)
        tile = tm.get(tc, tr)
        occ = tile.occupant if tile is not None else None
        now_blocked = (occ is not None and not is_base
                       and getattr(occ, "alive", False))
        if now_blocked:
            self._target = occ
            if not self.blocked:
                self.blocked = True
                mv.speed = 0.0
                self._set_anim(owner, "attack")
        else:
            self._target = None
            if self.blocked:
                self.blocked = False
                mv.speed = self._real_speed
                self._set_anim(owner, "walk")

    @staticmethod
    def _set_anim(owner, name):
        anim = owner.get_component(SpriteAnimator)
        if anim is not None and anim.animation != name:
            anim.set_animation(name)


class EnemyCombat(Component):
    """Enemy attack stats + the attack-a-blocking-building clock. ``cooldown``
    starts at 0 so the first hit lands the instant the enemy stops (prototype
    ``_atk_timer`` starts at 0). Ticks only while ``PathAgent.blocked``; damage
    goes through the building's ``Health`` and accrues on its ``RoundStats``
    (guard-safe — every ``Building`` carries one)."""

    dmg: int = 0
    attack_speed: float = 1.0
    cooldown: float = 0.0

    def on_added(self, owner):
        self._owner = owner

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        pa = owner.get_component(PathAgent)
        if pa is None or not pa.blocked:
            return
        target = pa._target
        if target is None or not getattr(target, "alive", False):
            return
        self.cooldown -= dt
        if self.cooldown <= 0:
            target.get_component(Health).damage(self.dmg)
            rs = target.get_component(RoundStats)
            if rs is not None:
                rs.dmg_taken_this_round += self.dmg
            self.cooldown = self.attack_speed


class BossState(Component):
    """Boss-only state (era index + one-shot death-swarm guard). Present for the
    zeroed boss branch; boss behaviour (era stats, swarm, announcement) lands in
    10G. Never spawned live in 9E."""

    era: int = 0
    death_spawned: bool = False
