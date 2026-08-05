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
from engine.render.item import RenderItem
from game.buildings.components import RoundStats
from game.map.pathfinder import (
    _wall_blocks, block_covers, block_tiles, face_edges,
    find_path_to_nearest_defence, find_path_to_nearest_economic,
    find_path_to_nearest_non_base_building, internal_edges,
)
from game.map.tiles import CONDITION_MODIFIER_KEY, TileCondition

# Chunk 4: hunt-string ("EnemyTypes.<type>.hunts") -> the goal-set pathfinder
# query it dispatches to. "base" is NOT in here — it is handled separately by
# Enemy.on_spawn, which never routes a base hunt through this dict; every
# other value re-arms PathAgent.repath_on_kill and is consulted here both by
# on_spawn's non-base branch and by _repath below, so the two can never
# disagree about which query a given hunt string means.
_HUNT_QUERIES = {
    "economic": find_path_to_nearest_economic,
    "defence": find_path_to_nearest_defence,
    "any_non_base": find_path_to_nearest_non_base_building,
}

# debug-mode-telemetry (Phase 3): the optional level-2 damage hook
# EnemyCombat.update() consults at its one enemy-attacks-a-building site.
# ``EnemyCombat.update(dt)`` runs inside ``Scene.update``'s generic component
# sweep (``Component.update``'s signature is fixed — dt only), which executes
# BEFORE ``game.enemies.combat.resolve_combat`` each frame (game/main.py:
# pre_sim -> scene.update -> resolve_combat) — so ``resolve_combat``'s own
# ``on_damage=None`` parameter physically cannot reach this call site. This
# module-level setter is the equivalent seam, mirroring
# ``game/ui/widgets.py``'s ``set_skin_hit_test`` precedent: unset by default
# (a bare ``EnemyCombat.update()`` stays byte-identical — one ``is not None``
# check when off), installed by ``game/main.py`` only when the recorder's
# level is >= 2, using the SAME ``on_damage(attacker_kind, target_kind, dmg,
# target_hp_after)`` shape ``resolve_combat``'s own parameter uses.
_damage_hook = None


def set_damage_hook(fn):
    """Install (or clear, ``fn=None``) the optional level-2 debug damage hook
    ``EnemyCombat.update()`` calls at its one enemy-attacks-a-building site."""
    global _damage_hook
    _damage_hook = fn


# debug-mode-telemetry (Phase 5): the SIBLING seam for the edge-wall attack
# branch of the same method. A wall is a map-owned ``WallEdge``, not a
# GameObject: it carries no ``Health`` and no ``RoundStats``, so its damage is
# invisible to BOTH ``resolve_combat(on_damage=…)`` and ``_damage_hook``'s
# ``(attacker, target, dmg, target_hp_after)`` shape — a wall has no
# ``building_type`` target and no single ``(col, row)``, it spans an EDGE
# between two tiles. Hence its own hook with its own shape,
# ``(attacker_kind, (c1, r1, c2, r2), dmg, hp_after, broke)``. Unset by
# default, installed by ``game/main.py`` only at recorder level >= 2 — one
# ``is not None`` check when off, exactly like ``_damage_hook``.
_wall_damage_hook = None


def set_wall_damage_hook(fn):
    """Install (or clear, ``fn=None``) the optional level-2 debug wall-damage
    hook ``EnemyCombat.update()`` calls at its edge-wall attack site."""
    global _wall_damage_hook
    _wall_damage_hook = fn


# Kidnapping (Art/enemies): the carried-sprite world offset. Pure iso
# arithmetic, no engine change — world_to_screen is
# ix = (wx-wy)*half_w, iy = (wx+wy)*half_h and depth_key = (layer, wx+wy, wy)
# (engine/coords/system.py), so a world offset of (-d, +d): moves the sprite
# exactly 2*d*half_w px LEFT on screen with zero vertical change, leaves the
# depth (wx+wy) identical and raises wy, so the carried building sorts AFTER
# the carrier and draws IN FRONT of it. A cosmetic module constant (the
# AOE_TRAVEL_TIME / CRATER_LIFE precedent), not balancing.
CARRY_OFFSET_TILES = 0.25


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


def _min_speed_fraction(tm):
    """``TileConditions.min_speed_fraction`` (BP-1) — the floor under a
    terrain-penalised enemy's speed, as a fraction of its OWN base speed.
    Same duck-typed ``balance`` guard as ``_condition_mods``; **0.0 when
    absent**, which collapses the floor back to the plain ``max(0, …)`` clamp,
    so headless tilemap stubs stay byte-identical."""
    bal = getattr(tm, "balance", None)
    if bal is None:
        return 0.0
    return bal.get("TileConditions", {}).get("min_speed_fraction", 0.0)

# -- /10I --


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
    * ``repath_on_kill`` — on unblocking (the blocker died), on arriving at a
      dead non-base goal, or the moment the committed target dies to ANYONE,
      re-run this unit's hunt query (``_HUNT_QUERIES[hunt]``, default
      ``find_path_to_nearest_non_base_building`` — Chunk 4 generalised this
      from a hardcoded boss-only call) from the current tile and reload the
      waypoints — the prototype boss's ``_repath``-after-kill
      (``boss.py:108-114``) mapped onto the block-and-attack model.

    BP-3 adds ``target_col``/``target_row``: the victim the agent has COMMITTED
    to, so it can watch that one building instead of re-litigating the board
    after every swing. ``-1`` is the default-off sentinel (no target — walking
    at the base), which is what keeps the other four enemy types byte-identical.

    Chunk 4 adds ``hunt`` (JSON-safe: a declared field, resolved at
    construction from ``EnemyTypes.<type>.hunts``, exactly like ``footprint``)
    — what this unit paths toward on spawn and re-targets to on a kill.
    ``"base"`` is the default and keeps every type that never opts in
    byte-identical; any other value is looked up in the module-level
    ``_HUNT_QUERIES`` dict by both ``Enemy.on_spawn`` and ``_repath`` below.
    """

    reached_base: bool = False
    blocked: bool = False
    goal_is_base: bool = True     # arrival counts as a base breach (10G)
    repath_on_kill: bool = False  # re-route to the next nearest building (10G)
    footprint: int = 1            # the unit occupies footprint × footprint tiles
    target_col: int = -1          # the building we committed to hunt (BP-3)
    target_row: int = -1          # -1 = none: we are walking at the base
    carrying: bool = False        # kidnapping (Art/enemies): inert while True
    hunt: str = "base"            # what this unit hunts on spawn (Chunk 4)

    def on_added(self, owner):
        self._owner = owner
        self._tilemap = None      # set by Enemy at construction
        self._real_speed = 0.0    # cached move speed for block/unblock gating
        self._target = None       # the building we are stopped attacking
        self._wall_target = None  # (c1,r1,c2,r2) edge wall we are attacking, or None
        # Chunk 3: this unit's own {forest, mountain, pond} path-weight
        # profile (EnemyTypes.<type>.condition_path_weights), set by Enemy at
        # construction beside _tilemap — a transient (E-11) because a dict is
        # not JSON-safe component state. None until Enemy sets it (headless
        # component-only tests) falls back to the map's own weights, exactly
        # like every find_path* call's cond_weights=None default.
        self._cond_weights = None
        # -- 10I: condition of the tile last ARRIVED at (prototype
        # enemy.py:111-114 / 191-192). GRASS at spawn; the spawn tile's own
        # condition is never applied (waypoint 0 IS the spawn tile — update()
        # only reads arrived tiles from waypoint index 1 on).
        self._current_condition = TileCondition.GRASS
        self._last_index = 0
        # -- /10I --

    def update(self, dt):
        # Kidnapping (Art/enemies): a carrier is inert — no blocker scan, no
        # wall scan, no re-path, no condition-speed write. Movement (a
        # separate component) keeps driving the waypoints ``begin_kidnap``
        # loaded, on the speed it set.
        if self.carrying:
            return
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
        # -- BP-3: the committed target died — to US or, just as often, to a
        # defender while we were still walking to it (boss rounds are crowded).
        # Pick a new victim NOW rather than marching on to the corpse and only
        # noticing on arrival. Gated on `not blocked` so that while we are
        # punching something the unblock branch below stays the single re-path
        # site; a blocker in the way is worth killing whatever happened to the
        # target.
        if (self.repath_on_kill and not self.blocked
                and not self._target_alive(tm)):
            self._repath(owner, tm, mv)
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
        # A standing wall on the face we're crossing (prev -> next waypoint)
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
        occ = self._blocker_ahead(tm, tc, tr)
        now_blocked = occ is not None
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
                # -- 10G boss: the blocker died — hunt the next nearest
                # building instead of resuming the stale route.
                if self.repath_on_kill:
                    self._repath(owner, tm, mv)
            # 10I: while walking, speed is the condition-modified value every
            # frame (mountain/forest −0.4 t/s; replaces the plain
            # ``_real_speed`` restore — identical when the condition is GRASS).
            mv.speed = self._condition_speed()

    def _blocker_ahead(self, tm, tc, tr):
        """The first live, non-base building standing anywhere in the
        DESTINATION BLOCK — the tiles the body will occupy once it steps onto
        the next anchor (ER-2). Scan order is row-major and deterministic.
        The base exemption is per TILE of the block, not per waypoint: a
        footprint-2 unit whose block covers the base must attack the other
        occupant in its block, never the BaseBuilding. footprint=1 -> exactly
        today's single-tile ``tm.get(tc, tr)`` test."""
        for c, r in block_tiles(tc, tr, self.footprint):
            if c == tm.base_col and r == tm.base_row:
                continue
            tile = tm.get(c, r)
            occ = tile.occupant if tile is not None else None
            if occ is not None and getattr(occ, "alive", False):
                return occ
        return None

    def adopt_goal(self, path, tm):
        """Derive the goal state from a freshly computed ``path`` — the ONE
        site that decides what the agent is hunting. ``Boss.on_spawn`` and
        ``_repath`` both call it, so the two can never drift apart.

        ``goal_is_base`` is True when the path's last ANCHOR's block covers the
        base (ER-2 — a size-N body has arrived once it covers the hole; at
        footprint 1 that is ``path[-1] == (base_col, base_row)``). Since BP-2
        the boss only ever gets a base-covering path when no other building is
        alive, so this flips True exactly once, at the end of its rampage.

        ``target_col``/``target_row`` remember the victim (BP-3) so the agent
        can notice it dying — to us or to anyone else — instead of re-deriving
        the whole board every time it swings. They are declared fields, not a
        stashed ``self._target_col``, because all state lives in components
        (E-11) and the editor's inspector reads them."""
        if not path:
            self.target_col = self.target_row = -1
            return
        self.goal_is_base = block_covers(path[-1][0], path[-1][1],
                                         self.footprint,
                                         tm.base_col, tm.base_row)
        if self.goal_is_base:
            self.target_col = self.target_row = -1
        else:
            self.target_col, self.target_row = int(path[-1][0]), int(path[-1][1])

    def _target_alive(self, tm):
        """Is the building we committed to still standing? ``target_col < 0``
        (no target — we are walking at the base) reads as alive, so the
        dead-target watch in ``update`` never fires on the final approach.

        ``target_col``/``target_row`` are the goal-covering ANCHOR
        (``adopt_goal`` reads them off ``path[-1]``), not necessarily the
        building's own tile — at footprint 1 they are the same tile, but a
        footprint-N anchor's block can cover the goal from up to N-1 tiles
        away. Scanning the whole block (like ``_blocker_ahead`` already does)
        instead of just the anchor tile is what keeps this from misreading an
        empty anchor tile as "target dead" while the real target stands one
        tile over — that false read used to fire the dead-target repath every
        frame, short-circuiting ``update`` before it ever reached
        ``_blocker_ahead`` again, freezing the boss beside a still-alive
        neighbour it could no longer see."""
        if self.target_col < 0:
            return True
        for c, r in block_tiles(self.target_col, self.target_row,
                                self.footprint):
            tile = tm.get(c, r)
            occ = tile.occupant if tile is not None else None
            if occ is not None and getattr(occ, "alive", False):
                return True
        return False

    def _repath(self, owner, tm, mv):
        """Re-route from the current tile to the next victim, reloading
        ``Movement`` and re-deriving the goal (10G / BP-2). No path at all (a
        fully sealed board) leaves the agent standing with NO target — the next
        unblock/arrival retries, and the cleared target is what stops the
        dead-target watch from re-pathing every frame forever."""
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        query = _HUNT_QUERIES.get(self.hunt, find_path_to_nearest_non_base_building)
        path = query(tm, col, row, footprint=self.footprint,
                     cond_weights=self._cond_weights)
        self.adopt_goal(path, tm)
        if not path:
            return
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        # BP-4: do NOT rewind. path[0] is the tile we are STANDING IN (we
        # snapped `col`/`row` off the transform with round()), but the body is
        # somewhere inside that tile, not on its centre. Aiming at path[0] would
        # walk us BACK to that centre before setting off — the visible half-tile
        # reverse after every kill (measured: col 11.000 -> 10.705 in the second
        # after a kill). We are already inside path[0] and path[1] is 4-adjacent
        # to it, so heading straight for path[1] is always a legal step and is
        # what "carry on from where I am" means. Index 1 also keeps
        # `_wall_edge_ahead` happy: it reads wps[index-1] = path[0] as the tile
        # we are crossing FROM, which is exactly true.
        mv.index = 1 if len(path) >= 2 else 0
        mv.arrived = False
        # BP-4: a re-path is the one place _current_condition genuinely goes
        # stale — it used to stay pinned to the pre-repath tile until the index
        # climbed back to 2. Re-read it from the tile underfoot, and resync
        # _last_index so update()'s waypoint-change gate starts from here.
        self._last_index = mv.index
        tile = tm.get(col, row)
        if tile is not None:
            self._current_condition = tile.condition

    # -- 10I: condition-modified move speed ---------------------------------

    def _condition_speed(self):
        """``max(real × min_speed_fraction, real − enemy_speed_penalty)`` for
        the tile last arrived at (prototype ``enemy.py:345-354``; the −0.4×32 px
        was pixel-space).

        BP-1 — the floor replaces the prototype's ``max(0, …)`` clamp, which was
        not a slowdown but a LATCH: the penalty is a flat 0.4 t/s and the boss
        moves at 0.3–0.45, so eras 0–3 computed exactly 0.0 — and a unit at
        speed 0 never advances ``Movement.index``, which is the only thing that
        refreshes ``_current_condition``, so it stayed 0 forever. The boss was
        the one unit in the game slower than its own terrain penalty. Flooring
        at a fraction of the unit's OWN speed fixes it where a multiplicative
        penalty would have moved every type's numbers: at the shipped 0.5 the
        four normal types are byte-identical (their ``real − 0.4`` still wins —
        walker 0.8, raider 2.3, siege 0.6, formation 0.5), and only the boss
        moves, off 0.0 and onto 0.15–0.225. Pinned by
        ``test_boss.TestConditionSpeedFloor``."""
        mods = _condition_mods(getattr(self, "_tilemap", None),
                               self._current_condition)
        penalised = self._real_speed - mods.get("enemy_speed_penalty", 0)
        floor = self._real_speed * _min_speed_fraction(
            getattr(self, "_tilemap", None))
        return max(floor, penalised)

    # -- /10I --

    def _wall_edge_ahead(self, tm, wps, index, tc, tr):
        """The ``(c1,r1,c2,r2)`` of the FIRST live wall the body would cross or
        straddle stepping to the next anchor: the FACE edges first (they sit in
        front of it), then the destination block's INTERNAL edges. Returning
        only the first makes a 2×2 chew through a face one segment at a time —
        ``EnemyCombat`` drains ``_wall_target``, and when that edge dies the next
        frame's scan returns the next one. footprint=1 -> exactly today's single
        prev->next edge. Meaningful only once the enemy has left the first
        waypoint (``index >= 1``); guarded so a headless tilemap stub without
        ``get_wall_between`` never trips."""
        if index < 1:
            return None
        if getattr(tm, "get_wall_between", None) is None:
            return None
        pw = wps[index - 1]
        pc, pr = round(pw[0]), round(pw[1])
        n = self.footprint
        if n == 1:      # the face IS the single crossed edge; no internals
            return ((pc, pr, tc, tr)
                    if _wall_blocks(tm, pc, pr, tc, tr) else None)
        for e in face_edges(pc, pr, tc, tr, n) + internal_edges(tc, tr, n):
            if _wall_blocks(tm, *e):
                return e
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
        self._kidnap_victim = None  # transient stash for a pending kidnap

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
                    dmg = self._effective_dmg(pa)  # 10I
                    broke = tm.damage_wall(*wall, dmg)
                    # debug-mode-telemetry (Phase 5, level 2 only): fired at
                    # exactly the site the wall's HP is spent. `hp_after` is
                    # read back through the public `get_wall_between`; a broken
                    # edge is deleted, so it reports 0.
                    if _wall_damage_hook is not None:
                        edge = tm.get_wall_between(*wall)
                        _wall_damage_hook(getattr(owner, "ETYPE", None), wall,
                                         dmg, 0 if edge is None else edge.hp,
                                         bool(broke))
                self.cooldown = self.attack_speed
            return
        target = pa._target
        if target is None or not getattr(target, "alive", False):
            return
        self.cooldown -= dt
        if self.cooldown <= 0:
            dmg = self._effective_dmg(pa)   # 10I: mountain/forest +10%
            health = target.get_component(Health)
            health.damage(dmg)
            rs = target.get_component(RoundStats)
            if rs is not None:
                rs.dmg_taken_this_round += dmg
            # debug-mode-telemetry (Phase 3, level 2 only): fired at exactly
            # the RoundStats credit site above.
            if _damage_hook is not None:
                _damage_hook(getattr(owner, "ETYPE", None),
                            getattr(target, "building_type", None),
                            dmg, health.hp)
            self.cooldown = self.attack_speed
            # Kidnapping (Art/enemies): a killing blow on a kidnap-capable
            # type ARMS the transition here; this component never touches the
            # scene — the combat sweep's kidnap pass (combat.py) owns the
            # actual retag/carry via begin_kidnap. Never the wall-attack
            # branch above: walls carry no sprite and no tile.
            if not getattr(target, "alive", False):
                kidnap = owner.get_component(Kidnap)
                if (kidnap is not None and kidnap.enabled
                        and not kidnap.pending and not kidnap.active):
                    kidnap.pending = True
                    self._kidnap_victim = target


class DeathSpawn(Component):
    """The generalised death-spawn mechanic (ER-3, plan D4) — absorbs 10G's
    ``BossState``. Balancing (``EnemyTypes/<type>/death_spawn``) is resolved
    into these fields at construction, exactly like ``Health.max_hp`` /
    ``EnemyCombat.dmg``.

    * ``at_hp_fraction`` — the unit is dead once ``hp <= max_hp * this``.
      ``Enemy.alive`` is the ONE evaluation site (``enemy.py``). 0.0 restores
      the plain ``Health.is_dead`` rule byte-for-byte.
    * ``counts`` — the RESOLVED spawn row for THIS unit's era, already clamped
      at construction ({"raiders": n, "regular": n, "siege": n}).
    * ``era`` — the era index the unit resolved (the Boss's; 0 for everything
      else). Kept because the Boss still reads it (``Boss.era``).
    * ``death_spawned`` — the one-shot burst guard. ``Session.on_enemy_death``
      sets it through ``Enemy.mark_death_spawned()`` the first time a death is
      reported, so a double-death frame can never double-burst.
    """

    era: int = 0
    enabled: bool = False
    at_hp_fraction: float = 0.0
    spawn_hp_fraction: float = 1.0
    counts: dict = {}
    death_spawned: bool = False


class Kidnap(Component):
    """Kidnapping (Art/enemies): per-type toggle (``EnemyTypes.<type>.
    kidnapping``) plus the carry-home state machine. ``EnemyCombat`` only
    ARMS ``pending`` on a killing blow (guard-safe, never touches the scene);
    ``begin_kidnap`` (``kidnap.py``) is the ONE site that flips ``pending`` ->
    ``active``, retags the owner to ``"kidnapper"`` and loads the walk-home
    waypoints — the combat sweep's kidnap pass is what calls it.

    * ``enabled`` — resolved at construction from balancing, like every other
      per-type stat.
    * ``pending`` — ``EnemyCombat`` just landed the killing blow; the sweep
      will transition this frame.
    * ``active`` — carrying, walking home.
    * ``frozen`` — pin the sprite clock at frame 0 (the sheet has no
      ``kidnap`` row, so there is nothing to actually animate).
    * ``slot_key``/``fit_tiles``/``scale`` — the carried building's own
      ``SpriteAnimator`` fields, copied once at the transition.
    """

    enabled: bool = False
    pending: bool = False
    active: bool = False
    frozen: bool = False
    slot_key: str = ""
    fit_tiles: float = 0.0
    scale: float = 1.0

    def on_added(self, owner):
        self._owner = owner
        self._scene = None  # set by begin_kidnap; the despawn-on-arrival seam

    def update(self, dt):
        if not self.active:
            return
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        # Re-pin the sprite clock at frame 0 every frame: SpriteAnimator.update
        # (which ran earlier in the component list) always advances its own
        # clock regardless of what animation is set, so this is what actually
        # locks the frame when the sheet has no `kidnap` row.
        if self.frozen:
            anim = owner.get_component(SpriteAnimator)
            if anim is not None:
                anim.anim_time_ms = 0.0
        mv = owner.get_component(Movement)
        if mv is not None and (mv.arrived or not mv.waypoints):
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(owner)

    def render_items(self, transform):
        """One extra RenderItem for the carried building's sprite, offset
        ``(-CARRY_OFFSET_TILES, +CARRY_OFFSET_TILES)`` in world space so it
        draws to the carrier's left and IN FRONT of it (see the module
        constant's derivation above). ``Scene.render_items`` collects this
        generically alongside the carrier's own ``SpriteAnimator`` item — no
        new GameObject, no engine change."""
        if not self.active or not self.slot_key:
            return
        wx, wy = transform.world_pos
        yield RenderItem(
            self.slot_key,
            (wx - CARRY_OFFSET_TILES, wy + CARRY_OFFSET_TILES),
            layer=transform.layer,
            animation="idle",
            anim_time_ms=0,
            fit_tiles=self.fit_tiles,
            scale=self.scale,
        )
