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
from game.map.pathfinder import find_path_to_nearest_building


class PathAgent(Component):
    """Walks a precomputed tile path toward the base, stopping to attack a
    living non-base building that sits on the next path tile. ``reached_base``
    is the prototype's ``reached_base`` (consumed by the combat sweep, which
    applies base damage + despawns). Gates ``Movement`` by zeroing its speed
    while blocked and restoring it on unblock — the path (``Movement.waypoints``)
    is never discarded, so no re-path is needed when the blocker dies (the route
    already runs through that now-passable tile).

    10G adds two default-off flags (Standard/Raider/Siege stay byte-identical):

    * ``goal_is_base`` — ``reached_base`` is only set on ``Movement.arrived``
      when True. A hunter whose path ENDS on a targeted building (the boss)
      must never count arrival there as a base breach — the phantom-base-hit
      hazard the 10F raider/siege deferral documented.
    * ``repath_on_kill`` — on unblocking (the blocker died) or on arriving at a
      dead non-base goal, re-run ``find_path_to_nearest_building`` from the
      current tile and reload the waypoints — the prototype boss's
      ``_repath``-after-kill (``boss.py:108-114``) mapped onto the
      block-and-attack model."""

    reached_base: bool = False
    blocked: bool = False
    goal_is_base: bool = True     # arrival counts as a base breach (10G)
    repath_on_kill: bool = False  # re-route to the next nearest building (10G)

    def on_added(self, owner):
        self._owner = owner
        self._tilemap = None      # set by Enemy at construction
        self._real_speed = 0.0    # cached move speed for block/unblock gating
        self._target = None       # the building we are stopped attacking
        self._wall_target = None  # (c1,r1,c2,r2) edge wall we are attacking, or None

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        tm = getattr(self, "_tilemap", None)
        if owner is None or tm is None or self.reached_base:
            return
        mv = owner.get_component(Movement)
        if mv is None:
            return
        if mv.arrived:
            # -- 10G boss: arrival only breaches when the path goal IS the
            # base. A non-base goal (the hunted building died en route with no
            # blocker contact) re-paths instead of firing a phantom base hit.
            if self.goal_is_base:
                self.reached_base = True
            else:
                self._repath(owner, tm, mv)
            return
        wps = mv.waypoints
        if not wps or mv.index >= len(wps):
            return
        wp = wps[mv.index]
        tc, tr = round(wp[0]), round(wp[1])
        is_base = (tc == tm.base_col and tr == tm.base_row)
        # A standing wall on the edge we're crossing (prev -> next waypoint)
        # blocks FIRST (it sits before the next tile): the enemy stops on the
        # near side and attacks it (EnemyCombat drives the damage). Only the
        # walls-ignoring path (base enclosed) ever crosses a live wall — a normal
        # find_path already routes around them (10E).
        wall_edge = self._wall_edge_ahead(tm, wps, mv.index, tc, tr)
        if wall_edge is not None:
            self._wall_target = wall_edge
            self._target = None
            if not self.blocked:
                self.blocked = True
                mv.speed = 0.0
                self._set_anim(owner, "attack")
            return
        self._wall_target = None
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
                # -- 10G boss: the blocker died — hunt the next nearest
                # building instead of resuming the stale route.
                if self.repath_on_kill:
                    self._repath(owner, tm, mv)

    def _repath(self, owner, tm, mv):
        """Re-route to the nearest alive building (base included) from the
        current tile, reloading ``Movement`` and re-deriving ``goal_is_base``
        (10G). No path at all (fully sealed board) leaves the agent standing —
        the next unblock/arrival retries."""
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        path = find_path_to_nearest_building(tm, col, row)
        if not path:
            return
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        mv.index = 0
        mv.arrived = False
        self.goal_is_base = path[-1] == (tm.base_col, tm.base_row)

    @staticmethod
    def _wall_edge_ahead(tm, wps, index, tc, tr):
        """The ``(c1,r1,c2,r2)`` of a live wall on the edge from the previous
        waypoint to the next, or None. Meaningful only once the enemy has left
        the first waypoint (``index >= 1``); guarded so a headless tilemap stub
        without ``get_wall_between`` never trips."""
        if index < 1:
            return None
        get_wall = getattr(tm, "get_wall_between", None)
        if get_wall is None:
            return None
        pw = wps[index - 1]
        pc, pr = round(pw[0]), round(pw[1])
        w = get_wall(pc, pr, tc, tr)
        if w is not None and getattr(w, "hp", 0) > 0:
            return (pc, pr, tc, tr)
        return None

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
        wall = getattr(pa, "_wall_target", None)
        if wall is not None:
            # Attacking a perimeter edge wall (10E): damage goes to the map-owned
            # WallEdge via ``TileMap.damage_wall`` (walls carry no Health /
            # RoundStats). The wall breaking is observed by PathAgent next frame
            # (get_wall_between -> None -> unblock, resume the same path).
            self.cooldown -= dt
            if self.cooldown <= 0:
                tm = getattr(pa, "_tilemap", None)
                if tm is not None:
                    tm.damage_wall(*wall, self.dmg)
                self.cooldown = self.attack_speed
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
    """Boss-only state: the era index + the one-shot death-swarm guard. LIVE
    since 10G — ``Session.on_enemy_death`` sets ``death_spawned`` the first
    time the boss's death is reported, so the swarm can never double-spawn."""

    era: int = 0
    death_spawned: bool = False
