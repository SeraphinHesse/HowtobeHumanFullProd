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
from game.map.tiles import CONDITION_MODIFIER_KEY, TileCondition


# -- 10I: tile-condition modifier lookup (shared by both components) --------

def _condition_mods(tm, condition):
    """The ``TileConditions.modifiers`` sub-dict for ``condition``, or ``{}``.
    Duck-typed + fully guarded so headless tilemap stubs without ``balance``
    (and GRASS, which has no modifiers entry) stay neutral."""
    bal = getattr(tm, "balance", None)
    if bal is None:
        return {}
    key = CONDITION_MODIFIER_KEY.get(condition)
    if key is None:
        return {}
    return bal.get("TileConditions", {}).get("modifiers", {}).get(key, {})

# -- /10I --


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
        self._wall_target = None  # (c1,r1,c2,r2) edge wall we are attacking, or None
        # -- 10I: condition of the tile last ARRIVED at (prototype
        # enemy.py:111-114 / 191-192). GRASS at spawn; the spawn tile's own
        # condition is never applied (waypoint 0 IS the spawn tile — update()
        # only reads arrived tiles from waypoint index 1 on).
        self._current_condition = TileCondition.GRASS
        self._last_index = 0
        # -- /10I --

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
        # -- 10I: refresh the current condition when a waypoint was passed —
        # the tile ARRIVED at is waypoints[index-1]. Index 1 means "arrived at
        # waypoint 0" = the spawn tile itself, which never applies (prototype
        # enemy.py:191-192), hence the index >= 2 gate.
        if mv.index != self._last_index:
            self._last_index = mv.index
            if mv.index >= 2:
                pw = wps[mv.index - 1]
                arrived = tm.get(round(pw[0]), round(pw[1]))
                if arrived is not None:
                    self._current_condition = arrived.condition
        # -- /10I --
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
                self._set_anim(owner, "walk")
            # 10I: while walking, speed is the condition-modified value every
            # frame (mountain/forest −0.4 t/s; replaces the plain
            # ``_real_speed`` restore — identical when the condition is GRASS).
            mv.speed = self._condition_speed()

    # -- 10I: condition-modified move speed ---------------------------------

    def _condition_speed(self):
        """``max(0, real − enemy_speed_penalty)`` for the tile last arrived at
        (prototype ``enemy.py:345-354``; the −0.4×32 px was pixel-space). The
        ``max(0, …)`` clamp is prototype-exact: a 0.5 t/s SiegeCannon crawls
        at 0.1 on mountain/forest."""
        mods = _condition_mods(getattr(self, "_tilemap", None),
                               self._current_condition)
        return max(0.0, self._real_speed - mods.get("enemy_speed_penalty", 0))

    # -- /10I --

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

    # -- 10I: condition-modified attack damage -------------------------------

    def _effective_dmg(self, pa):
        """``max(1, int(dmg × (1 + enemy_dmg_bonus)))`` for the owner's current
        tile condition (prototype ``enemy.py:356-365``). Applied to BOTH the
        blocking-building and edge-wall attacks — never to base hits (lives
        mode costs one life flat)."""
        mods = _condition_mods(getattr(pa, "_tilemap", None),
                               getattr(pa, "_current_condition", None))
        bonus = mods.get("enemy_dmg_bonus", 0)
        if bonus:
            return max(1, int(self.dmg * (1.0 + bonus)))
        return self.dmg

    # -- /10I --

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
                    tm.damage_wall(*wall, self._effective_dmg(pa))  # 10I
                self.cooldown = self.attack_speed
            return
        target = pa._target
        if target is None or not getattr(target, "alive", False):
            return
        self.cooldown -= dt
        if self.cooldown <= 0:
            dmg = self._effective_dmg(pa)   # 10I: mountain/forest +10%
            target.get_component(Health).damage(dmg)
            rs = target.get_component(RoundStats)
            if rs is not None:
                rs.dmg_taken_this_round += dmg
            self.cooldown = self.attack_speed


class BossState(Component):
    """Boss-only state (era index + one-shot death-swarm guard). Present for the
    zeroed boss branch; boss behaviour (era stats, swarm, announcement) lands in
    10G. Never spawned live in 9E."""

    era: int = 0
    death_spawned: bool = False
