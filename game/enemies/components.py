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
    find_path_ignoring_walls, find_path_to_nearest_defence,
    find_path_to_nearest_economic, find_path_to_nearest_non_base_building,
    find_path_to_nearest_structure, internal_edges,
)
from game.map.tiles import CONDITION_MODIFIER_KEY, TileCondition

from .dirt_pile import spawn_dirt_pile

# Chunk 4: hunt-string ("EnemyTypes.<type>.hunts") -> the goal-set pathfinder
# query it dispatches to. "base" is NOT in here — it is handled separately by
# Enemy.on_spawn, which never routes a base hunt through this dict; every
# other value re-arms PathAgent.repath_on_kill and is consulted here both by
# on_spawn's non-base branch and by _repath below, so the two can never
# disagree about which query a given hunt string means.
# NE-0: "defence" now means every ATTACK-CAPABLE building (defence,
# aoe_defence, storm_priest, sun_scorcher) and "structure" is the new category
# for every non-economy, non-boost, non-base building — both are predicate
# widenings inside game/map/pathfinder.py, so this table only gained one row.
_HUNT_QUERIES = {
    "economic": find_path_to_nearest_economic,
    "defence": find_path_to_nearest_defence,
    "structure": find_path_to_nearest_structure,
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


# NE-3 (Drummer): how long ONE source's contribution survives after the
# Drummer stops sustaining it — the D7 "4 seconds after leaving the radius"
# decay. A cosmetic-tier module constant (the CARRY_OFFSET_TILES /
# AOE_TRAVEL_TIME precedent), deliberately NOT a balancing leaf: the design's
# own variable list names nine Drummer knobs and this is not one of them.
BUFF_DECAY_SECONDS = 4.0


def buff_total(owner, key):
    """The summed ACTIVE buff bonus ``key`` on ``owner`` (NE-3).

    THE single read path for a buffed stat. ``0.0`` for an owner with no
    ``BuffState`` (a building, a stub, a headless component-only test) and for
    the overwhelmingly common no-contributions case, so every read site costs
    one component scan plus one dict-truthiness test when nothing is buffing
    anything.
    """
    if owner is None:
        return 0.0
    bs = owner.get_component(BuffState)
    if bs is None or not bs.sources:
        return 0.0
    return bs.total(key)


# Kidnapping (Art/enemies): the carried-sprite world offset. Pure iso
# arithmetic, no engine change — world_to_screen is
# ix = (wx-wy)*half_w, iy = (wx+wy)*half_h and depth_key = (layer, wx+wy, wy)
# (engine/coords/system.py), so a world offset of (-d, +d): moves the sprite
# exactly 2*d*half_w px LEFT on screen with zero vertical change, leaves the
# depth (wx+wy) identical and raises wy, so the carried building sorts AFTER
# the carrier and draws IN FRONT of it. A cosmetic module constant (the
# AOE_TRAVEL_TIME / CRATER_LIFE precedent), not balancing.
CARRY_OFFSET_TILES = 0.25


# -- NE-1: block-to-block Chebyshev distance --------------------------------

def block_distance(col, row, footprint, tcol, trow, tfootprint):
    """Chebyshev distance between two N×N blocks given by their MIN-corner
    anchors (``game/map/pathfinder.py``'s block convention — the body extends
    right and down from the anchor).

    A per-axis clamp to each block's span, then Chebyshev across the axes —
    the same "distance to the NEAREST TILE of the block, not to its centre"
    rule ``game/enemies/combat.py``'s ``_chebyshev`` uses for the defender
    range gate. At ``footprint == tfootprint == 1`` it collapses to plain
    ``max(|dc|, |dr|)`` over the two anchor tiles.
    """
    dc = max(tcol - (col + footprint - 1), col - (tcol + tfootprint - 1), 0)
    dr = max(trow - (row + footprint - 1), row - (trow + tfootprint - 1), 0)
    return max(dc, dr)


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

    NE-2 adds ``no_melee`` (default off — every existing type byte-identical):
    the halt-and-attack scan is skipped ENTIRELY. Routing is untouched — the
    unit still walks the ordinary weighted path, around or through buildings
    exactly as today — it just never physically STOPS for one. It exists
    because the Digger has no attack outside digging: a Digger that halted on
    an incidental blocker en route to its claimed target would stand there
    forever dealing 0 damage to something that can therefore never die. A
    permanent soft-lock, not a slow fight.

    NE-1 adds the RANGED STAND-OFF pair, both default-off so every pre-NE-1
    type keeps the byte-identical melee path:

    * ``stand_off_range`` — halt this many tiles short of the COMMITTED target
      and open fire from there instead of closing to melee. ``0`` (every type
      but the Sniper) never runs the check at all.
    * ``in_range`` — we have halted and are firing. It is the ranged twin of
      ``blocked``: ``EnemyCombat`` ticks on ``blocked or in_range``, so the
      attack clock, the damage application and the kidnap arming are ONE code
      path, not two. A stand-off unit typically never reaches ``blocked`` —
      it stops before anything can physically block it.
    """

    reached_base: bool = False
    blocked: bool = False
    goal_is_base: bool = True     # arrival counts as a base breach (10G)
    repath_on_kill: bool = False  # re-route to the next nearest building (10G)
    footprint: int = 1            # the unit occupies footprint × footprint tiles
    target_col: int = -1          # the building we committed to hunt (BP-3)
    target_row: int = -1          # -1 = none: we are walking at the base
    carrying: bool = False        # kidnapping (Art/enemies): inert while True
    frozen: bool = False          # BR-3 second phase: inert, and NOT attacking
    hunt: str = "base"            # what this unit hunts on spawn (Chunk 4)
    no_melee: bool = False        # NE-2: never HALT to punch a blocker
    stand_off_range: int = 0      # NE-1: halt this far from the target, 0 = off
    in_range: bool = False        # NE-1: halted at stand-off, firing

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
        # BR-3: a boss in its delayed second phase is frozen in place — the
        # `carrying` precedent exactly (inert agent, Movement.speed already
        # zeroed by the transition). EnemyCombat checks the same flag, so a
        # boss frozen mid-swing stops swinging.
        if self.frozen:
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
        # -- NE-1: the ranged stand-off. Measured EVERY frame against the
        # COMMITTED target's block (BP-3's target_col/target_row), BEFORE the
        # wall/blocker scan below — so a stand-off unit halts on geometry and
        # normally never enters `blocked` at all. `stand_off_range == 0` (every
        # type but the Sniper) short-circuits on the first comparison, which is
        # what keeps the melee path byte-identical.
        if self.stand_off_range > 0 and self.target_col >= 0:
            dist = block_distance(
                round(owner.transform.wx), round(owner.transform.wy),
                self.footprint, self.target_col, self.target_row,
                self.footprint)
            if dist <= self.stand_off_range:
                if not self.in_range:
                    self.in_range = True
                    # Drop any melee engagement we were mid-way through: from
                    # here EnemyCombat resolves the victim from the COMMITTED
                    # target, so a stale `_target`/`_wall_target` would have us
                    # shooting the last thing that happened to block us.
                    self.blocked = False
                    self._target = None
                    self._wall_target = None
                    mv.speed = 0.0
                    self._set_anim(owner, "attack")
                return
            # Out of range ⇒ not firing. An unconditional assignment rather
            # than an edge-triggered branch: `_repath` is the only way a unit
            # ever LEAVES range (a building target does not move), and it
            # already clears the flag itself, so a branch here would be dead
            # code pretending to be a state machine.
            self.in_range = False
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
        # NE-2: `no_melee` skips the halt-and-attack scan WHOLESALE — both the
        # wall-edge scan and the blocker scan below. It is not "attack for 0
        # damage": the unit simply never stops, so `blocked` stays False, no
        # `_target`/`_wall_target` is ever latched and `EnemyCombat` (which
        # ticks only while blocked) never runs. Routing is untouched above this
        # line, so a Digger still walks the same weighted path everything else
        # would. Default-off, hence one bool check for every other type.
        if self.no_melee:
            self._wall_target = None
            self._target = None
            self.blocked = False
            mv.speed = self._condition_speed()
            return
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

    def committed_target(self, tm):
        """The first LIVE occupant standing in the block we committed to hunt
        (BP-3's ``target_col``/``target_row``), or ``None``.

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
        neighbour it could no longer see.

        NE-1 promoted this out of ``_target_alive`` (which is now one line over
        it) because a ranged stand-off unit needs the OBJECT, not just the
        liveness bit: it never touches a blocker, so ``_target`` is never set
        for it and ``EnemyCombat`` resolves its victim from here instead. Same
        scan, same dead-occupant safety, one implementation."""
        if self.target_col < 0:
            return None
        for c, r in block_tiles(self.target_col, self.target_row,
                                self.footprint):
            tile = tm.get(c, r)
            occ = tile.occupant if tile is not None else None
            if occ is not None and getattr(occ, "alive", False):
                return occ
        return None

    def _target_alive(self, tm):
        """Is the building we committed to still standing? ``target_col < 0``
        (no target — we are walking at the base) reads as alive, so the
        dead-target watch in ``update`` never fires on the final approach."""
        return self.target_col < 0 or self.committed_target(tm) is not None

    def _repath(self, owner, tm, mv):
        """Re-route from the current tile to the next victim, reloading
        ``Movement`` and re-deriving the goal (10G / BP-2). The hunt query
        itself already falls back from "nearest prey" to "any reachable
        prey" to "the base" (walls respected) — so an entirely EMPTY result
        here means even the base is unreachable respecting walls, exactly
        the "base enclosed" case ``Enemy.on_spawn`` has always handled by
        retrying with ``find_path_ignoring_walls`` (a path to the base that
        treats wall edges as passable, letting this agent cross into a wall
        edge and hand off to the existing wall-attack machinery —
        ``_wall_edge_ahead``/``EnemyCombat`` — instead of standing there). A
        WallBuilder's perimeter wall next to a pond sealing the last gap out
        of the player's territory is the concrete case that hits this: this
        agent used to have no such retry, so it just stood there. A path
        still empty even ignoring walls (nothing anywhere is reachable)
        leaves the agent standing with NO target AND no waypoints,
        explicitly idled rather than left mid-``"walk"`` — the next
        unblock/arrival retries, and the cleared target is what stops the
        dead-target watch from re-pathing every frame forever.

        NE-1: this is also the ONE site that drops ``in_range``. It has to
        happen HERE and not on the next frame's distance check, because the
        dead-target watch calls ``_repath`` and RETURNS — so a stand-off unit
        would spend that frame still flagged in-range while already committed
        to a target it may be six tiles from, i.e. exactly one free
        out-of-range shot per re-target."""
        if self.in_range:
            self.in_range = False
            self._set_anim(owner, "walk")
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        query = _HUNT_QUERIES.get(self.hunt, find_path_to_nearest_non_base_building)
        path = query(tm, col, row, footprint=self.footprint,
                     cond_weights=self._cond_weights)
        if not path:
            path = find_path_ignoring_walls(tm, col, row, footprint=self.footprint,
                                            cond_weights=self._cond_weights)
        self.adopt_goal(path, tm)
        if not path:
            mv.waypoints = []
            mv.index = 0
            mv.arrived = False
            self._set_anim(owner, "idle")
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
        ``test_boss.TestConditionSpeedFloor``.

        NE-3: this is also THE read site for a ``move_speed`` buff. The
        Drummer's aura raises the unit's OWN base speed
        (``_real_speed * (1 + bonus)``) BEFORE the terrain penalty and the
        floor are applied, so a buffed unit keeps the same relationship to
        both. Writing a bonus into ``Movement.speed`` directly would be
        overwritten by this method on the very next walking frame — this is
        the only durable place to put it."""
        real = self._real_speed
        bonus = buff_total(getattr(self, "_owner", None), "move_speed")
        if bonus:
            real *= (1.0 + bonus)
        mods = _condition_mods(getattr(self, "_tilemap", None),
                               self._current_condition)
        penalised = real - mods.get("enemy_speed_penalty", 0)
        floor = real * _min_speed_fraction(getattr(self, "_tilemap", None))
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
    ``_atk_timer`` starts at 0). Ticks while ``PathAgent.blocked`` **or, since
    NE-1, ``PathAgent.in_range``** (the ranged stand-off); damage goes through
    the building's ``Health`` and accrues on its ``RoundStats`` (guard-safe —
    every ``Building`` carries one).

    NE-1 deliberately added NO second attack path: the gate widened by one
    ``or``, and the only other change is WHERE the victim comes from. The
    blocker scan sets ``PathAgent._target``; a stand-off unit never runs that
    scan, so it resolves the victim from its COMMITTED target instead
    (``PathAgent.committed_target``) — after which the cooldown tick, the
    condition-modified damage, the ``RoundStats`` credit, the debug hook and
    the kidnap arming are all the same lines they always were. There is no
    "ranged damage" concept: the hit lands instantly on cooldown, exactly like
    a melee swing, minus the adjacency requirement (a projectile-travel visual
    is a follow-up art pass, not a mechanic)."""

    dmg: int = 0
    attack_speed: float = 1.0
    cooldown: float = 0.0

    def on_added(self, owner):
        self._owner = owner
        self._kidnap_victim = None  # transient stash for a pending kidnap

    # -- NE-3: buffed stats (the Drummer aura's read sites) ------------------

    @property
    def buffed_dmg(self):
        """``dmg`` scaled by the summed ``BuffState`` ``dmg`` contributions.

        THE one place a buff touches outgoing damage: ``Enemy.dmg`` (base
        hits + the combat sweep's telemetry) and ``_effective_dmg`` (the
        blocking-building and edge-wall attacks, which layer the tile
        condition's own bonus on top of this) both read it, so an aura can
        never reach one and miss the other. With no contributions it returns
        ``self.dmg`` unchanged — byte-identical to pre-NE-3."""
        bonus = buff_total(getattr(self, "_owner", None), "dmg")
        if not bonus:
            return self.dmg
        return max(1, int(self.dmg * (1.0 + bonus)))

    @property
    def buffed_attack_speed(self):
        """Seconds between attacks, shortened by the summed ``BuffState``
        ``attack_speed`` contributions: ``attack_speed / (1 + bonus)``.

        The leaf is an INTERVAL, so a positive bonus has to DIVIDE — +10%
        attack speed means the same unit swings 10% more often, not 10%
        slower. THE one place the attack clock is reset from, both in the
        wall branch and in the building branch below."""
        bonus = buff_total(getattr(self, "_owner", None), "attack_speed")
        if not bonus:
            return self.attack_speed
        return self.attack_speed / (1.0 + bonus)

    # -- 10I: condition-modified attack damage -------------------------------

    def _effective_dmg(self, pa):
        """``max(1, int(dmg × (1 + enemy_dmg_bonus)))`` for the owner's current
        tile condition (prototype ``enemy.py:356-365``). Applied to BOTH the
        blocking-building and edge-wall attacks — never to base hits (lives
        mode costs one life flat).

        NE-3: it starts from ``buffed_dmg``, not the raw field, so a Drummer's
        aura and a mountain tile compound the way a designer would expect."""
        base = self.buffed_dmg
        mods = _condition_mods(getattr(pa, "_tilemap", None),
                               getattr(pa, "_current_condition", None))
        bonus = mods.get("enemy_dmg_bonus", 0)
        if bonus:
            return max(1, int(base * (1.0 + bonus)))
        return base

    # -- /10I --

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        pa = owner.get_component(PathAgent)
        # BR-3: `frozen` (the delayed second phase) disables this component
        # wholesale — the boss keeps whatever `blocked` state it stopped in,
        # so the flag has to be read here and not inferred from PathAgent.
        if pa is None or pa.frozen or not (pa.blocked or pa.in_range):
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
                self.cooldown = self.buffed_attack_speed   # NE-3
            return
        target = pa._target
        if target is None and pa.in_range:
            # NE-1: the stand-off case. `_blocker_ahead` never ran (we halted
            # on distance, not on contact), so the victim is the committed
            # target. `committed_target` returns None for a dead/absent
            # occupant, which the SAME guard below already handles — a ranged
            # unit can no more hit a corpse than a melee one can.
            tm = getattr(pa, "_tilemap", None)
            if tm is not None:
                target = pa.committed_target(tm)
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
            self.cooldown = self.buffed_attack_speed   # NE-3
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


# -- NE-2: the Digger's burrow state machine --------------------------------
#
# Plain strings, so `BurrowAgent.state` stays declared JSON-safe component
# state (E-11) the editor's inspector can read straight out.
BURROW_WALKING = "walking"      # above ground, walking at the committed target
BURROW_SUBMERGED = "submerged"  # underground: untargetable, no waypoints
BURROW_EMERGE = "emerge"        # surfaced this frame; re-targets on the next

#: animation rows the machine plays. Missing manifest rows are graceful by
#: construction (SpriteAnimator holds a name string and the renderer falls back
#: to idle) — the BR-3 `endphase` precedent, so no placeholder rows are added.
DIG_ANIM = "dig"
EMERGE_ANIM = "emerge"


class BurrowAgent(Component):
    """The Digger's ``WALKING -> SUBMERGED -> EMERGE -> WALKING`` machine (NE-2).

    Only the Digger carries one, and carrying one IS what makes a unit a
    burrower — the exclusive-claim scan below identifies its rivals by
    "has a BurrowAgent", not by class or ``ETYPE``, so a future second burrower
    shares the claim pool for free.

    It is spliced BETWEEN ``PathAgent`` and ``Movement`` in the component list
    (``Enemy.nav_components``): after the agent has made its walk/halt decision
    for the frame, before the locomotion that would act on it — so a submerge
    takes effect the same frame, exactly the reason ``PathAgent`` itself sits
    ahead of ``Movement``.

    * **WALKING** — ordinary ``PathAgent`` movement toward the committed target
      (``hunts: "structure"``). Each frame it measures Chebyshev distance from
      the unit's tile to the target's BLOCK; at ``<= dig_range_tiles`` it
      submerges. It also watches the target's liveness itself, because the
      Digger deliberately runs with ``PathAgent.repath_on_kill`` OFF: the
      agent's generic re-path would re-run the hunt with no claim exclusion and
      would happily accept the empty-goal-set fallback to the base.
    * **SUBMERGED** — ``PathAgent.frozen`` (the BR-3/`carrying` precedent:
      inert agent, inert ``EnemyCombat``) with the waypoints dropped, so
      ``Movement`` cannot advance an index or fire a phantom arrival. Progress
      is a pure internal lerp from the entry point to the target tile over
      ``dig_range_tiles / dig_speed`` seconds — no visible waypoints, and the
      unit is exactly ON its target when the clock runs out. ``Digger.
      targetable`` reads this state, so combat, projectiles, the storm and both
      HP bars drop it at once (the duck-typed contract BR-3 built for the boss).
      **The Digger's own ``SpriteAnimator`` is also hidden entirely** (``visible
      = False``, ``engine.core.SpriteAnimator``) rather than merely held on its
      dig pose — only the dirt-pile decal marks the spot. Blanking ``slot_key``
      instead would be WRONG (it resolves to the grey-X placeholder); the
      generic ``visible`` flag is the seam this needed.
    * **EMERGE** — entered by the clock expiring (deal the one big hit, having
      snapped onto the target tile) OR, per D5, the instant the target dies to
      anything else (surface where we are, deal NOTHING). Either way the NEXT
      tick re-targets. Splitting it across two ticks is deliberate: it makes
      EMERGE an observable state a one-shot emerge animation can play in, and
      the claim it is about to release is released one frame later, which
      changes nothing (it is releasing it either way). The sprite becomes
      ``visible`` again immediately.

    **``emerge_cooldown`` (config) / ``cooldown_remaining`` (runtime) — a
    minimum surface timer**, counted from the moment it comes up (a strike OR
    a D5 no-damage interrupt both count) to the moment it is next ALLOWED to
    dig back in. It does **not** change anything else about the cycle: on
    emerging the Digger still immediately releases its claim and walks toward
    its next target exactly as before — the cooldown only holds off the
    ``_tick_walking`` submerge check (even once already standing on a new,
    in-range target) until ``cooldown_remaining`` drains to zero. ``0.0``
    (the default) is a no-op, so a hand-built headless Digger with no balancing
    behind it stays byte-identical to before this existed.

    No target after exclusion ⇒ **stand down**: visible, idle, harmless, with
    no waypoints and no claim. Diggers only build towards buildings; they do
    NOT fall back to attacking the hole.
    """

    state: str = BURROW_WALKING
    dig_range_tiles: int = 6      # submerge trigger distance (Chebyshev tiles)
    dig_speed: float = 1.0        # tiles/sec while burrowed (== move_speed)
    dig_timer: float = 0.0        # seconds left underground
    dig_duration: float = 0.0     # what dig_timer started at (the lerp base)
    start_wx: float = 0.0         # where we went under (the lerp origin)
    start_wy: float = 0.0
    emerge_cooldown: float = 0.0     # min seconds on the surface before re-digging
    cooldown_remaining: float = 0.0  # counts down from emerge_cooldown on emerge
    min_target_distance_tiles: int = 0  # prefer a target this far away (Chebyshev)

    def on_added(self, owner):
        self._owner = owner

    # -- the tick ----------------------------------------------------------

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        pa = owner.get_component(PathAgent)
        mv = owner.get_component(Movement)
        if pa is None or mv is None or pa.carrying:
            return
        tm = getattr(pa, "_tilemap", None)
        if tm is None:
            return
        if self.state == BURROW_SUBMERGED:
            self._tick_submerged(dt, owner, pa, mv, tm)
        elif self.state == BURROW_EMERGE:
            self.retarget(owner, pa, mv, tm)
        else:
            self._tick_walking(dt, owner, pa, mv, tm)

    def _tick_walking(self, dt, owner, pa, mv, tm):
        # The minimum-surface-time gate: ticks down every frame it's above
        # ground, regardless of target state, so it also drains while stood
        # down with nothing to claim.
        if self.cooldown_remaining > 0:
            self.cooldown_remaining = max(0.0, self.cooldown_remaining - dt)
        if pa.target_col < 0:
            return                       # stood down: nothing left to claim
        if not pa._target_alive(tm):
            self.retarget(owner, pa, mv, tm)
            return
        if (self.cooldown_remaining <= 0
                and self.distance_to_target(owner, pa) <= self.dig_range_tiles):
            self._submerge(owner, pa, mv, tm)

    def _tick_submerged(self, dt, owner, pa, mv, tm):
        # Pin the sprite clock so the dig pose holds: SpriteAnimator.update
        # already ran this frame and always advances its own clock, whatever
        # animation is set (the `Kidnap.frozen` finding).
        anim = owner.get_component(SpriteAnimator)
        if anim is not None:
            anim.anim_time_ms = 0.0
        # D5 — the target died to someone else while we were under it. Surface
        # NOW, where we are, dealing nothing. Mirrors PathAgent's own
        # block-scanning liveness test rather than re-deriving one.
        if not pa._target_alive(tm):
            self._emerge(owner, pa, tm, strike=False)
            return
        self.dig_timer -= dt
        self._advance_underground(owner, pa)
        if self.dig_timer <= 0:
            self._emerge(owner, pa, tm, strike=True)

    # -- transitions -------------------------------------------------------

    def _submerge(self, owner, pa, mv, tm):
        self.state = BURROW_SUBMERGED
        speed = self.dig_speed if self.dig_speed > 0 else 1.0
        self.dig_duration = max(1e-6, float(self.dig_range_tiles) / speed)
        self.dig_timer = self.dig_duration
        # It only digs into TILES and emerges under buildings — never dig
        # starting on a tile a (possibly unrelated) building already occupies.
        # The route to the real target is a traversable weight, not
        # impassable, and `no_melee` never halts for a blocker, so the walk
        # can legitimately cross another building's tile first. Relocating
        # here is invisible either way: `visible` flips False in this same
        # call, below.
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        tile = tm.get(col, row)
        if tile is not None and tile.occupant is not None:
            col, row = self._nearest_clear_tile(tm, col, row)
            owner.transform.wx = float(col)
            owner.transform.wy = float(row)
        self.start_wx = float(owner.transform.wx)
        self.start_wy = float(owner.transform.wy)
        pa.frozen = True
        pa.blocked = False
        mv.speed = 0.0
        # Drop the route rather than merely zeroing the speed: the underground
        # lerp writes the transform directly, and a still-loaded waypoint list
        # could otherwise let `Movement.advance` cross an arrival threshold and
        # latch `arrived` on a path we are no longer walking.
        mv.waypoints = []
        mv.index = 0
        mv.arrived = False
        self._set_anim(owner, DIG_ANIM)
        # Not just held on the dig pose — fully hidden. Only the dirt pile
        # decal marks the spot while burrowed, restored the instant it
        # emerges (see `_emerge`).
        anim = owner.get_component(SpriteAnimator)
        if anim is not None:
            anim.visible = False
        spawn_dirt_pile(getattr(owner, "_scene", None),
                        round(self.start_wx), round(self.start_wy),
                        self.dig_duration * 1000.0)

    def _advance_underground(self, owner, pa):
        """Lerp the transform from the entry point to the target tile. The unit
        is invisible-to-gameplay here (untargetable, no waypoints), so this is
        the whole of "movement continues internally" — and it lands the body
        exactly on the target when the clock reaches zero."""
        if self.dig_duration <= 0:
            t = 1.0
        else:
            t = min(1.0, max(0.0, 1.0 - self.dig_timer / self.dig_duration))
        owner.transform.wx = self.start_wx + (pa.target_col - self.start_wx) * t
        owner.transform.wy = self.start_wy + (pa.target_row - self.start_wy) * t

    def _emerge(self, owner, pa, tm, strike):
        self.state = BURROW_EMERGE
        self.dig_timer = 0.0
        # The cooldown counts from the moment it comes up (both a strike and
        # a D5 no-damage interrupt count as "coming up") to the moment it is
        # allowed to dig back in — enforced by `_tick_walking`'s gate above.
        self.cooldown_remaining = self.emerge_cooldown
        pa.frozen = False
        anim = owner.get_component(SpriteAnimator)
        if anim is not None:
            anim.visible = True
        self._set_anim(owner, EMERGE_ANIM)
        if not strike:
            return                       # D5: surfaced where we are, no damage
        owner.transform.wx = float(pa.target_col)
        owner.transform.wy = float(pa.target_row)
        target = self._target_building(tm, pa)
        if target is not None:
            self._strike(owner, pa, target)

    def _strike(self, owner, pa, target):
        """The eruption hit — ``EnemyCombat.update()``'s single-target damage
        application, verbatim (Health.damage + the RoundStats credit + the
        level-2 telemetry hook at exactly that credit site), on the Digger's
        ``dmg`` instead of a cooldown-gated swing. No kidnap arming: Diggers
        ship ``kidnapping: false`` and do not carry buildings home."""
        combat = owner.get_component(EnemyCombat)
        if combat is None:
            return
        dmg = combat._effective_dmg(pa)
        health = target.get_component(Health)
        if health is None:
            return
        health.damage(dmg)
        rs = target.get_component(RoundStats)
        if rs is not None:
            rs.dmg_taken_this_round += dmg
        if _damage_hook is not None:
            _damage_hook(getattr(owner, "ETYPE", None),
                         getattr(target, "building_type", None),
                         dmg, health.hp)

    # -- re-targeting + the exclusive claim --------------------------------

    def retarget(self, owner, pa, mv, tm):
        """Claim the nearest unclaimed structure and walk at it; return whether
        one was found.

        The ONE site that re-runs the hunt for a burrower, so the claim
        exclusion can never be bypassed. ``PathAgent.adopt_goal`` still owns
        deriving ``goal_is_base``/``target_col``/``target_row`` from the fresh
        path — and ``goal_is_base`` True is precisely how the base fallback
        inside ``find_path_to_nearest_structure`` announces "nothing left to
        hunt", which is what makes the stand-down branch below correct rather
        than a guess.

        ``min_target_distance_tiles`` prefers a claim at least that far
        (Chebyshev) from the Digger's own tile, falling back to the plain
        nearest unclaimed structure when nothing clears it — see
        ``find_path_to_nearest_structure``'s ``min_distance``."""
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        path = find_path_to_nearest_structure(
            tm, col, row, footprint=pa.footprint,
            cond_weights=pa._cond_weights, exclude=self.claimed_tiles(owner),
            min_distance=self.min_target_distance_tiles)
        pa.adopt_goal(path, tm)
        self.state = BURROW_WALKING
        if not path or pa.goal_is_base:
            # Stand down (NE-2): every structure is gone or already claimed.
            # goal_is_base is forced back off — a stale True would fire a
            # phantom base breach the moment Movement reported an arrival.
            pa.goal_is_base = False
            pa.target_col = pa.target_row = -1
            mv.waypoints = []
            mv.index = 0
            mv.arrived = False
            mv.speed = 0.0
            self._set_anim(owner, "idle")
            return False
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        # BP-4's no-rewind rule: we are already inside path[0], and path[1] is
        # 4-adjacent, so heading straight there is always a legal step.
        mv.index = 1 if len(path) >= 2 else 0
        mv.arrived = False
        pa._last_index = mv.index
        tile = tm.get(col, row)
        if tile is not None:
            pa._current_condition = tile.condition
        mv.speed = pa._condition_speed()
        self._set_anim(owner, "walk")
        return True

    def claimed_tiles(self, owner):
        """``{(col, row)}`` every OTHER live burrower has committed to.

        A claim is nothing but another Digger's ``PathAgent.target_col/_row``,
        so it is released for free the moment that Digger re-targets (its own
        target moves) or dies (it drops off ``by_tag("enemy")``, which also
        excludes retagged kidnappers and corpses). No registry, nothing to leak.

        ``Enemy._scene`` absent (a hand-built headless enemy) reads as "no
        rivals" — single-Digger behaviour, never a crash."""
        scene = getattr(owner, "_scene", None)
        if scene is None:
            return frozenset()
        claimed = set()
        for other in scene.by_tag("enemy"):
            if other is owner or not getattr(other, "alive", True):
                continue
            if other.get_component(BurrowAgent) is None:
                continue
            opa = other.get_component(PathAgent)
            if opa is not None and opa.target_col >= 0:
                claimed.add((opa.target_col, opa.target_row))
        return claimed

    # -- helpers -----------------------------------------------------------

    def distance_to_target(self, owner, pa):
        """Chebyshev tiles from the unit's tile to the NEAREST tile of the
        target's block (``PathAgent.target_col/_row`` is the goal ANCHOR, which
        for a footprint-N target can sit up to N-1 tiles off the body — the
        same reason ``_target_alive`` scans the block instead of the anchor)."""
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        return min(max(abs(c - col), abs(r - row))
                   for c, r in block_tiles(pa.target_col, pa.target_row,
                                           pa.footprint))

    @staticmethod
    def _target_building(tm, pa):
        for c, r in block_tiles(pa.target_col, pa.target_row, pa.footprint):
            tile = tm.get(c, r)
            occ = tile.occupant if tile is not None else None
            if occ is not None and getattr(occ, "alive", False):
                return occ
        return None

    @staticmethod
    def _nearest_clear_tile(tm, col, row):
        """The nearest ``(c, r)`` with no building occupant, by an expanding
        Chebyshev ring search from ``(col, row)`` — the ``_find_2x2``
        expanding-window precedent (``game/map/CLAUDE.md``) applied to a
        single tile instead of a 2x2 block. Falls back to ``(col, row)``
        itself if literally nothing on the board qualifies (never expected on
        a real map — the whole spawn/combat zone can't be built solid — but a
        graceful no-op beats a crash)."""
        limit = max(tm.cols, tm.rows)
        for radius in range(limit):
            if radius == 0:
                ring = [(col, row)]
            else:
                ring = []
                for dc in range(-radius, radius + 1):
                    ring.append((col + dc, row - radius))
                    ring.append((col + dc, row + radius))
                for dr in range(-radius + 1, radius):
                    ring.append((col - radius, row + dr))
                    ring.append((col + radius, row + dr))
            for c, r in ring:
                tile = tm.get(c, r)
                if tile is not None and tile.occupant is None:
                    return c, r
        return col, row

    @staticmethod
    def _set_anim(owner, name):
        anim = owner.get_component(SpriteAnimator)
        if anim is not None and anim.animation != name:
            anim.set_animation(name)


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

    BR-3 adds the BOSS's staged second phase on top (``EnemyTypes.Boss.
    second_phase``; every other type still resolves ``death_spawn`` into the
    fields above and leaves these at their defaults):

    * ``delayed`` — the phase switch. False is the historical one-frame burst,
      byte-for-byte.
    * ``spawn_delay`` — seconds between two children (PER child, not a total).
    * ``phase_started`` / ``phase_complete`` — the two-bit state machine.
      ``Enemy.alive`` stays True from the threshold crossing until
      ``phase_complete``; ``Enemy.targetable`` is False for that whole window.
    * ``phase_timer`` — seconds until the next child. Ticked by
      ``Spawner._advance_second_phases`` on the speed-scaled sim dt (the
      ``Corpse`` fade-clock rule), never on wall time.
    * ``pending`` — the remaining children as a flat list of etype strings, in
      ``SWARM_TYPES`` order; the phase ends when it and the frame's due list
      are both empty.

    All of it is declared JSON-safe component state (E-11) — the LOGIC lives
    in ``Enemy.advance_second_phase`` + the Spawner, never here.
    """

    era: int = 0
    enabled: bool = False
    at_hp_fraction: float = 0.0
    spawn_hp_fraction: float = 1.0
    counts: dict = {}
    death_spawned: bool = False
    delayed: bool = False
    spawn_delay: float = 0.0
    phase_started: bool = False
    phase_complete: bool = False
    phase_timer: float = 0.0
    pending: list = []


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


class BuffState(Component):
    """The PASSIVE buff ledger every enemy carries (NE-3) — the game's first
    status-effect mechanism.

    It is on EVERY enemy type's component list, the ``Kidnap`` shape: a
    declared field that is usually inert. Empty it costs one dict-truthiness
    test per frame in ``update`` and one in ``buff_total``.

    **It never scans the scene and never decides who to buff.** A source
    (today only ``DrummerAura``) calls ``apply``; this component owns
    everything after that: the per-source bookkeeping, the decay clock, and —
    critically — BOTH halves of the HP grant, so the shrink can never disagree
    with the grow.

    ``sources`` maps a SOURCE ID (the buffing ``GameObject.id`` — a uuid hex,
    which is why the whole ledger stays JSON-safe, E-11) to one contribution::

        {"hp": int,            # ABSOLUTE hp points this source granted
         "dmg": float,         # FRACTION, e.g. 0.15 = +15%
         "move_speed": float,  # FRACTION
         "attack_speed": float,# FRACTION (a bonus SHORTENS the interval)
         "decay": float}       # seconds left before this source is dropped

    Two rules follow from keying by source (D7):

    * **Stacking is additive.** ``total(key)`` sums every live contribution,
      so two Drummers in range are exactly twice one Drummer.
    * **Decay is per source.** ``apply`` re-pins that ONE source's ``decay``
      to ``BUFF_DECAY_SECONDS`` every frame it is sustained, so "start a 4s
      countdown when the unit leaves the radius" needs no leave event at all:
      it is simply the frame nothing re-pinned it. A Drummer that DIES stops
      re-pinning too, and its buff fades on the same 4s clock — which is why
      the clock lives here and not on the aura.

    ``hp`` is stored as an ABSOLUTE amount, not a fraction, because it is the
    one stat that is applied to the ledger (``Health``) rather than read
    through at use time: the exact number granted is the exact number that
    must come back off.
    """

    sources: dict = {}

    def on_added(self, owner):
        self._owner = owner

    # -- read side ---------------------------------------------------------

    def total(self, key):
        """The summed live contribution for ``key`` (see ``buff_total``, the
        guarded module-level front door every read site actually uses)."""
        if not self.sources:
            return 0.0
        return sum(c[key] for c in self.sources.values())

    @property
    def base_max_hp(self):
        """This unit's UNBUFFED max HP — ``Health.max_hp`` minus every live
        hp grant. Every source sizes its own grant off this, never off the
        already-buffed max, so N Drummers give exactly N x the fraction
        instead of compounding into each other."""
        h = self._health()
        if h is None:
            return 0
        return h.max_hp - int(self.total("hp"))

    # -- write side (called by DrummerAura) --------------------------------

    def apply(self, source, hp_fraction, dmg, move_speed, attack_speed,
              decay=BUFF_DECAY_SECONDS):
        """Install or REFRESH ``source``'s contribution and re-pin its decay.

        D6 — the hp grant heals: a NEW contribution (or a changed amount)
        raises ``Health.max_hp`` AND ``Health.hp`` by the same delta, so the
        buff is real survivability, not headroom. Refreshing an UNCHANGED
        amount touches ``Health`` not at all — which is what stops a Drummer
        standing next to a unit from healing it to full every frame."""
        amount = int(round(self.base_max_hp * hp_fraction))
        cur = self.sources.get(source)
        if cur is None:
            self.sources[source] = {"hp": amount, "dmg": dmg,
                                    "move_speed": move_speed,
                                    "attack_speed": attack_speed,
                                    "decay": decay}
            self._grant_hp(amount)
            return
        if cur["hp"] != amount:
            self._grant_hp(amount - cur["hp"])
            cur["hp"] = amount
        cur["dmg"] = dmg
        cur["move_speed"] = move_speed
        cur["attack_speed"] = attack_speed
        cur["decay"] = decay

    def update(self, dt):
        """Tick every contribution's decay clock and drop the expired ones.

        A source is dropped exactly ``BUFF_DECAY_SECONDS`` after the last
        frame that re-pinned it (D7). Dropping it un-applies its hp grant:
        max HP shrinks by that source's own amount and current HP clamps down
        if it now sits above the new max (D6)."""
        if not self.sources:
            return
        expired = []
        for source, contribution in self.sources.items():
            contribution["decay"] -= dt
            if contribution["decay"] <= 0:
                expired.append(source)
        for source in expired:
            self._grant_hp(-self.sources.pop(source)["hp"])

    # -- the ONE place Health is touched -----------------------------------

    def _grant_hp(self, delta):
        """Move max HP by ``delta`` and carry current HP with it (D6). The
        single site for both directions, so grant and un-grant are provably
        symmetric: a positive delta heals by the same amount it adds, a
        negative one shrinks the ceiling and clamps only if we are now over
        it (a unit already damaged below the new max keeps its HP)."""
        if not delta:
            return
        h = self._health()
        if h is None:
            return
        h.max_hp = max(1, h.max_hp + delta)
        if delta > 0:
            h.hp += delta
        elif h.hp > h.max_hp:
            h.hp = h.max_hp

    def _health(self):
        owner = getattr(self, "_owner", None)
        return None if owner is None else owner.get_component(Health)


class DrummerAura(Component):
    """The Drummer's support aura (NE-3) — the only thing that writes into a
    ``BuffState`` today. Lives ONLY on ``Drummer`` instances.

    Every frame it scans ``scene.by_tag("enemy")`` and re-applies THIS
    drummer's contribution (keyed by its own ``GameObject.id``) to every unit
    whose tile is within Chebyshev ``support_range``. It does no bookkeeping
    of its own: "who is buffed", "how long since they left" and "give the HP
    back" all belong to ``BuffState``, which is what makes a dead Drummer's
    buff fade correctly on its own 4s clock.

    Cost is ``drummers x enemies`` tile tests per frame; drummers are a
    handful per wave by design (``count_start`` 1-3), so this stays well under
    the per-frame path queries the same wave already pays.

    The scene comes from ``Enemy._scene``, a transient the ``Spawner`` sets
    just before ``scene.spawn`` (E-11 allows underscore attrs past the
    GameObject seal). With no scene — a headless construction test — the aura
    is simply inert.
    """

    support_range: int = 1
    hp_increase: float = 0.0
    dmg_increase: float = 0.0
    move_speed_increase: float = 0.0
    attack_speed_increase: float = 0.0

    def on_added(self, owner):
        self._owner = owner

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        scene = getattr(owner, "_scene", None)
        if scene is None:
            return
        # A drummer that has been killed this frame (or is mid-second-phase)
        # stops sustaining: its contributions then age out on the normal 4s
        # clock instead of being re-pinned by a corpse.
        if not getattr(owner, "alive", True):
            return
        col = round(owner.transform.wx)
        row = round(owner.transform.wy)
        reach = self.support_range
        source = owner.id
        for other in scene.by_tag("enemy"):
            if other is owner:
                continue           # a Drummer supports OTHERS, never itself
            if (abs(round(other.transform.wx) - col) > reach
                    or abs(round(other.transform.wy) - row) > reach):
                continue
            buffs = other.get_component(BuffState)
            if buffs is None:
                continue
            buffs.apply(source, self.hp_increase, self.dmg_increase,
                        self.move_speed_increase, self.attack_speed_increase)
