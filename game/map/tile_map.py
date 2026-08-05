"""Runtime tile grid (Phase 9C): zones, 2×2 unlock + spawn recede, occupancy.

Wraps an ``engine.tilemap.TileMapDoc`` into a live grid of ``Tile`` objects and
ports the prototype's ``src/map/tile_map.py`` unlock / recede / weight-refresh
logic. Balancing (``data/balancing/map.json``) is injected as a plain dict;
``load_map_balance`` reads it directly until 9D's ``game/core/balance.py``
generalises the loader.

Grid is indexed ``_grid[row][col]`` (prototype-exact); ``get(col, row)`` swaps.
Unlock sections anchor at the map's 2×2 ``start_area`` marker when placed (its
min corner is section (0,0)), falling back to the base (the buildable min
corner) rather than the prototype's hardcoded constants, so the math is
map-driven. Pure Python — no pygame.
"""
from dataclasses import dataclass

from game.core.balance import load_balance
from .spawn_deco import spawn_tree_slots
from .tiles import (
    CONDITION_CATEGORY, CONDITION_LABEL, CONDITION_STATE_LABEL,
    CONDITION_WEIGHT_KEY, Tile, TileCondition, TileState,
)


@dataclass
class WallEdge:
    """One perimeter wall segment on the shared grid edge between two tiles
    (Phase 10E, prototype ``src/map/tile_map.py`` ``WallEdge``). Owned by a
    WallBuilder building; removed when that builder dies. ``owner`` is the
    building GameObject — duck-typed, no ``game.buildings`` import (keeps the map
    layer free of the building layer, avoiding an import cycle)."""

    col_a: int
    row_a: int
    col_b: int
    row_b: int
    hp: int
    max_hp: int
    owner: object


def _wall_key(c1, r1, c2, r2):
    """Order-independent key for the edge between (c1,r1) and (c2,r2) so the same
    physical edge maps to one dict slot regardless of argument order."""
    return (c1, r1, c2, r2) if (c1, r1) < (c2, r2) else (c2, r2, c1, r1)


# Map-file legend code -> runtime zone state. Only the three ZONE codes carry a
# gameplay state; every other code is a BACKGROUND kind (forest/cliff/ocean and
# any editor-added background type) — resolved via `.get(code, BACKGROUND)`.
_CODE_STATE = {
    "b": TileState.BUILDABLE,
    "c": TileState.COMBAT,
    "s": TileState.SPAWNING,
}

# Runtime zone state -> legend code, the reverse mapping: when unlock/recede
# changes a tile's zone, `set_tile_state` records the new code in
# `terrain_overrides` so the GROUND VISUAL follows (unlocked tiles render
# buildable, a backfilled background block renders spawning). BUILT and
# BACKGROUND have no code — nothing ever converts TO them at runtime except
# the base seed, which keeps its painted ground under the sprite.
_STATE_CODE = {
    TileState.BUILDABLE: "b",
    TileState.COMBAT: "c",
    TileState.SPAWNING: "s",
}

BASE_CONTENT_KEY = "base_building"


def load_map_balance(data_dir):
    """Load + schema-validate ``data/balancing/map.json`` (the pathfinder /
    unlock tuning). Thin shim over the centralised loader (9D); kept because
    tests and ``game.map`` re-export this name.
    """
    return load_balance(data_dir, "map")


def _resolve_condition_slot(registry, condition, state, variant_idx):
    """The art slot for ``condition`` in its CURRENT zone ``state``, at the
    tile's stable ``variant_idx`` — or None when there is no registry /
    condition label / state label / group / slots.

    Two-axis lookup: `CONDITION_LABEL[condition]` selects the condition's
    top-level group, `CONDITION_STATE_LABEL[state]` selects the state's leaf
    family WITHIN it. ``variant_idx % len(variants)`` keeps the index
    well-defined even when a state's pool is smaller than another's (e.g.
    Spawning starts with fewer/no imported variants) — same shape as
    ``game.enemies.enemy.variant_slot``, so dropping a new variant in via the
    editor grows the pool with NO code change. Pure — callers own the index."""
    if registry is None:
        return None
    cond_label = CONDITION_LABEL.get(condition)
    state_label = CONDITION_STATE_LABEL.get(state)
    if cond_label is None or state_label is None:
        return None
    try:
        variants = registry.group_slots(
            CONDITION_CATEGORY, (cond_label, state_label))
    except KeyError:
        return None
    return variants[variant_idx % len(variants)] if variants else None


class TileMap:
    def __init__(self, doc, balance, rng=None, registry=None):
        self._doc = doc
        self._balance = balance
        # Kept on the instance (not just a local) so `set_tile_state` can
        # re-resolve condition art on every zone transition AFTER this
        # constructor returns. Deliberately left None until the end of
        # __init__ (assigned right after the condition-art init pass below):
        # the base tile's own early `set_tile_state(..., BUILT)` call a few
        # lines down must NOT re-resolve art from a not-yet-rolled
        # `condition_variant_idx` — that pass, not this seam, owns the
        # tile's FIRST resolve. This keeps `registry`-without-`rng` (a
        # headless-fixture-only combination; the real game always passes
        # both) behaving exactly as it did before set_tile_state gained an
        # art seam: every slot stays None.
        self._registry = None
        self.cols = doc.cols
        self.rows = doc.rows
        # A map may have NO hole (editor allows it with a warning). base_col/row
        # are None then and no BUILT base tile is seeded. Such a map is not
        # winnable but must not crash.
        has_base = doc.base is not None
        self.base_col = doc.base["col"] if has_base else None
        self.base_row = doc.base["row"] if has_base else None

        # Unlock sections anchor at the map's 2×2 START AREA marker when one
        # is placed: the marker's min corner IS section (0,0) — the starting
        # buildable pocket the designer painted under it. Maps without a
        # marker (editor warns, never blocks) fall back to the legacy
        # base-derived anchoring: section grid offset one row up so the HOLE
        # is the BOTTOM-LEFT tile of its own section (0,0).
        start = doc.start_area
        if start is not None:
            self._sec_col_origin = start["col"]
            self._sec_row_origin = start["row"]
        else:
            self._sec_col_origin = self.base_col if has_base else 0
            self._sec_row_origin = (
                self.base_row - 1 if has_base else 0)

        # -- Spawnable background: the designer-painted spawn reserve --------
        # `doc.spawnable_background` is {(col, row): purchase}; inverted ONCE
        # here into `purchase -> [(col, row), …]` so the nth successful tile
        # purchase is a single O(1) dict hit at unlock time. This is ONE pass
        # over the MARKS (a handful of painted cells), never a pass over the
        # map — the O(strip)/never-O(map) invariant this module lives by.
        # `_reserve_max` is the highest purchase number painted (0 when the
        # map has no marks at all), which is what lets `do_unlock` tell
        # "the reserve still has unreleased batches" from "the reserve is
        # exhausted, hand back to the implicit recede".
        self._reserve = {}
        for (mark_col, mark_row), purchase in doc.spawnable_background.items():
            self._reserve.setdefault(purchase, []).append((mark_col, mark_row))
        self._reserve_max = max(self._reserve, default=0)
        self._unlock_purchases = 0

        # -- Despawnable spawn: the designer-painted despawn schedule --------
        # `doc.despawnable_spawn` is the exact mirror of the reserve above,
        # inverted the same way and for the same reason: ONE pass over the
        # MARKS, never over the map, so the nth purchase is an O(1) dict hit.
        # `_despawn_max` is the highest despawn number painted (0 when none).
        self._despawn = {}
        for (mark_col, mark_row), purchase in doc.despawnable_spawn.items():
            self._despawn.setdefault(purchase, []).append((mark_col, mark_row))
        self._despawn_max = max(self._despawn, default=0)
        # the purchase number after which no painted mark of EITHER kind can fire
        self._scripted_max = max(self._reserve_max, self._despawn_max)
        # the spawn-reserve batches, ascending n, retired one per purchase
        # afterwards — the tiles the reserve released die in the order they
        # were born. `_retire_cursor` is how many have already been retired.
        self._retire_batches = sorted(self._reserve)
        self._retire_cursor = 0

        # Round gate for the damage-weight discount (dormant: nothing calls
        # set_round until 9F/10F). Defence-range coverage function is wired by
        # core in 10I; None keeps the range-affects-path feature dormant.
        self.round_num = 1
        self._defence_coverage_fn = None

        # Ground-visual sync: `{(col, row): code}` of tiles whose runtime zone
        # diverged from the painted terrain (unlock/recede). The host feeds it
        # to `band_render_items(code_overrides=…)` so the ground layer follows
        # zone changes WITHOUT mutating the shared map doc (a new game builds
        # a fresh TileMap → empty overrides → pristine terrain). `on_zone_change`
        # is a host-wired callable (e.g. GroundCache.invalidate), fired on every
        # zone-code write; None keeps headless fixtures inert.
        self.terrain_overrides = {}
        self.on_zone_change = None

        # Perimeter edge walls placed by WallBuilder buildings (10E). Keyed by
        # `_wall_key`. One WallEdge per edge — if two builders cover the same
        # edge the later placement overwrites (last-placed owns it); documented
        # as acceptable in the prototype.
        self.wall_edges = {}
        # DEFENCE_RANGE_PATH_WEIGHT_ADD lives in the buildings domain and is
        # wired in 10I; 0 keeps the coverage add inert in 9C (and coverage is
        # empty anyway, so it never fires).
        self._defence_range_add = 0

        # Flow-field invalidation seam (game/PERF.md): the pathfinder caches
        # ONE shared base flow field per `_path_version`; EVERY weight or
        # blocking mutation must bump the counter (`_bump_path_version`) or a
        # stale cached path becomes a correctness bug. Bumpers: zone changes
        # (`set_tile_state`), occupant/content-key writes
        # (`set_tile_content`), wall add/remove/death (mid-HP hits keep
        # `_wall_blocks` true, so they do NOT bump), and the three pre-query
        # weight producers below when their flag SETS actually change. All
        # underscore transients — TileMap is a plain class, not a GameObject.
        self._path_version = 0
        self._flow_cache = None
        self._dmg_reduced_prev = set()
        self._defence_covered_prev = set()
        # buildings-overwrite-tileweights rework: a building's `alive` flag
        # now changes its tile's weight (dead = additive again), so a death
        # must bump the flow field exactly like the other two producers.
        self._overwrite_prev = set()

        # Seed the runtime grid from terrain codes; the base occupies its tile.
        # An incremental per-state index (`_by_state`) is built in the SAME pass:
        # `built_tiles()` / `buildable_tiles()` / `spawning_tiles()` return from
        # it in O(result) instead of scanning all rows×cols. On a 1024²+ map a
        # full scan is ~1M iterations, and the in-round HUD ran several PER
        # FRAME (income + tile counter) — the sole cause of a static-camera large
        # map dropping to ~2 fps. INVARIANT: every tile-state write goes through
        # `set_tile_state` so this index stays consistent (see the setter).
        self._by_state = {s: set() for s in TileState}
        self._grid = []
        for r in range(self.rows):
            row_tiles = []
            for c in range(self.cols):
                t = Tile(c, r, _CODE_STATE.get(
                    doc.terrain[r][c], TileState.BACKGROUND))
                row_tiles.append(t)
                self._by_state[t.state].add(t)
            self._grid.append(row_tiles)
        if has_base:
            base_tile = self.get(self.base_col, self.base_row)
            self.set_tile_state(base_tile, TileState.BUILT)
            self.set_tile_content(base_tile, None, BASE_CONTENT_KEY)

        # -- 10I: tile-condition roll (prototype tile_map.py:69-91) ---------
        # ONE weighted draw per eligible tile, ONCE at map construction —
        # conditions never re-roll or change during a run. Ineligible (stay
        # GRASS): BACKGROUND-at-init tiles and the starting unlocked pocket
        # incl. the base ("so the base is always reachable"). Prototype-exact
        # quirk carried over: a BACKGROUND tile that later recedes into play
        # (spawn band) stays GRASS forever — the roll never revisits it.
        # ``rng`` is BOTH the on-switch and the determinism seam: the host
        # passes the module ``random`` (live roll) or a ``random.Random(seed)``
        # (deterministic tests); ``None`` skips the roll entirely, keeping
        # every pre-10I headless fixture (which asserts exact path costs on
        # all-GRASS grids) byte-stable. One-time O(map) init pass — NOT a
        # per-frame scan (perf invariant).
        if rng is not None:
            chances = balance["TileConditions"]["spawn_chances"]
            conds = (TileCondition.GRASS, TileCondition.MOUNTAIN,
                     TileCondition.POND, TileCondition.FOREST)
            weights = [chances["grass"], chances["mountain"],
                       chances["pond"], chances["forest"]]
            for t in self.all_tiles():
                if (t.state == TileState.BACKGROUND
                        or self._is_unlocked_state(t.state)):
                    continue
                t.condition = rng.choices(conds, weights=weights)[0]
        # -- /10I --

        # -- Condition ART: one variant index per tile, rolled ONCE here ----
        # A SEPARATE pass from the roll above on purpose: the roll's
        # eligibility rules are prototype-exact gameplay (and every path-cost
        # fixture depends on them), whereas art covers every playable tile
        # including the starting pocket — so imported grass art isn't missing
        # a hole where the base sits. BACKGROUND tiles are terrain, not
        # conditions, and stay slotless. No registry (headless fixtures) or no
        # rng ⇒ every slot stays None ⇒ the terrain layer emits nothing.
        #
        # The variant INDEX is picked once, sized against the tile's own
        # INITIAL state's family, and never re-rolled — `set_tile_state`
        # re-resolves `condition_slot` at this same index against whatever
        # state's family is active, keeping "variant #2" stable across a
        # zone transition (buildable -> built -> combat -> …).
        if rng is not None and registry is not None:
            # -- Spawn-band deco: one packed roll per tile, folded into THIS
            # pass. Deliberately not a third O(map) walk (perf invariant,
            # game/map/CLAUDE.md): every tile is already visited here for
            # condition art, so the tree roll rides along for free. Family
            # size is hoisted out of the loop (one registry lookup, not one
            # per tile). Rolled for EVERY tile, BEFORE the BACKGROUND
            # `continue` below — a BACKGROUND tile is exactly the kind that
            # later backfills into SPAWNING (spawn recede), and it must
            # already carry its roll when that happens, since nothing
            # re-rolls it then. `spawn_deco.py` reads `tile.state` live at
            # emit time, so a tile's tree only ever actually draws while
            # SPAWNING — no `set_tile_state` hook needed for it to vanish on
            # COMBAT conversion.
            # Sized against the SHARED family definition (`spawn_deco.py`) —
            # never a local `group_slots` call, or the roll's modulus could
            # drift from the family the emitter actually indexes.
            n_tree = len(spawn_tree_slots(registry))
            tree_chance = balance["SpawnDeco"]["tree_chance"]

            for t in self.all_tiles():
                if n_tree and rng.random() < tree_chance:
                    t.spawn_deco_roll = rng.randrange(n_tree) * 2 + rng.randrange(2)
                if t.state == TileState.BACKGROUND:
                    continue
                cond_label = CONDITION_LABEL.get(t.condition)
                state_label = CONDITION_STATE_LABEL.get(t.state)
                family = ()
                if cond_label is not None and state_label is not None:
                    try:
                        family = registry.group_slots(
                            CONDITION_CATEGORY, (cond_label, state_label))
                    except KeyError:
                        family = ()
                t.condition_variant_idx = (
                    rng.randrange(len(family)) if family else 0)
                t.condition_slot = _resolve_condition_slot(
                    registry, t.condition, t.state, t.condition_variant_idx)
        # -- /condition art --

        # NOW it is safe to expose the registry to `set_tile_state`: every
        # tile's variant index (if any) is already rolled, so a runtime zone
        # transition re-resolving art will read a meaningful index instead of
        # the Tile default (0).
        self._registry = registry

    # -- balancing accessors ----------------------------------------------

    @property
    def balance(self):
        return self._balance

    @property
    def impassable_weight(self):
        return self._balance["Pathfinding"]["content_weights"]["impassable"]

    def weight(self, tile, cond_weights=None):
        """Dijkstra edge weight for `tile` under this map's balancing.
        ``cond_weights`` (Chunk 3) is passed straight through to
        ``Tile.pathfinding_weight`` — ``None`` keeps today's map-wide
        ``TileConditions.path_weights`` behaviour."""
        return tile.pathfinding_weight(
            self._balance, self._defence_range_add, cond_weights)

    # -- access -----------------------------------------------------------

    def get(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self._grid[row][col]
        return None

    def _bump_path_version(self):
        """Invalidate the pathfinder's cached base flow field. Called by every
        weight/blocking mutation (see the `_path_version` init note); cheap —
        the field itself rebuilds lazily on the next `find_path` query."""
        self._path_version += 1

    def set_tile_content(self, tile, occupant, content_key):
        """THE one seam for occupant/content-key writes (building placement,
        base attach, tile freeing — `game/buildings/registry.py` +
        `game/core/payday.py` route through here). A tile's content key IS
        its base pathfinding weight, so a key change invalidates the flow
        field; occupant-only changes don't (the two pre-query weight
        producers self-detect theirs)."""
        tile.occupant = occupant
        if tile.content_key != content_key:
            tile.content_key = content_key
            self._bump_path_version()

    def set_tile_state(self, tile, new_state):
        """THE one place a tile's zone/unlock state changes. Keeps the
        `_by_state` index consistent so the state queries stay O(result), and
        records the tile's new zone CODE in `terrain_overrides` (+ fires
        `on_zone_change`) so the ground visual follows the zone. A no-op when
        the state is unchanged; never write `tile.state` directly."""
        if tile.state == new_state:
            return
        self._by_state[tile.state].discard(tile)
        tile.state = new_state
        self._by_state[new_state].add(tile)
        # An empty tile's path weight derives from its zone — invalidate.
        self._bump_path_version()
        code = _STATE_CODE.get(new_state)
        if code is not None:
            if self._doc.terrain[tile.row][tile.col] == code:
                # back to the painted code — drop the override
                self.terrain_overrides.pop((tile.col, tile.row), None)
            else:
                self.terrain_overrides[(tile.col, tile.row)] = code
            if self.on_zone_change is not None:
                self.on_zone_change()
        # Condition ART is state-driven since the per-state restructuring:
        # re-resolve at the SAME variant index so a tile's art switches live
        # between buildable/built/combat/spawning looks as its zone actually
        # changes. Skipped for BACKGROUND (never gets condition art, same as
        # the init pass) and when there is no registry (headless fixtures).
        if self._registry is not None and new_state != TileState.BACKGROUND:
            tile.condition_slot = _resolve_condition_slot(
                self._registry, tile.condition, new_state,
                tile.condition_variant_idx)

    def all_tiles(self):
        for r in range(self.rows):
            for c in range(self.cols):
                yield self._grid[r][c]

    def spawning_tiles(self):
        return list(self._by_state[TileState.SPAWNING])

    def built_tiles(self):
        return list(self._by_state[TileState.BUILT])

    def buildable_tiles(self):
        return list(self._by_state[TileState.BUILDABLE])

    # -- tile unlocking (prototype tile_map.py:298-374) -------------------

    def _section_index(self, tile):
        """(col_section, row_section) of the fixed 2×2 grid. Anchored at the
        map's start_area marker when placed (the marker IS section (0, 0));
        otherwise so the base is the BOTTOM-LEFT tile of section (0, 0) (row
        origin one tile above the base). The starting buildable pocket is
        section (0, 0)."""
        return ((tile.col - self._sec_col_origin) // 2,
                (tile.row - self._sec_row_origin) // 2)

    def unlock_cost(self, tile):
        """BASE + (manhattan − 1) * MOD — cost scales with the 2×2-section
        Manhattan distance from the starting section (0, 0), direction-agnostic:
        sections ADJACENT to the start cost exactly ``base_unlock_cost`` and
        each further step adds ``unlock_cost_distance_mod``. The distance term
        is clamped ≥ 0 (section (0, 0) itself starts owned, never purchased)."""
        u = self._balance["TileUnlocking"]
        sc, sr = self._section_index(tile)
        dist = max(0, abs(sc) + abs(sr) - 1)
        return u["base_unlock_cost"] + dist * u["unlock_cost_distance_mod"]

    def get_chunk_for_tile(self, tile):
        """The fixed 2×2 chunk containing `tile` (aligned to the section grid —
        see `_section_index`; every playfield tile belongs to exactly one
        non-overlapping chunk)."""
        anchor_col = self._sec_col_origin + (
            (tile.col - self._sec_col_origin) // 2) * 2
        anchor_row = self._sec_row_origin + (
            (tile.row - self._sec_row_origin) // 2) * 2
        chunk = []
        for dc in range(2):
            for dr in range(2):
                t = self.get(anchor_col + dc, anchor_row + dr)
                if t is not None:
                    chunk.append(t)
        return chunk

    @staticmethod
    def _is_unlocked_state(state):
        return state in (TileState.BUILDABLE, TileState.BUILT)

    def can_unlock(self, tile):
        """Whether the tile's 2×2 chunk may be unlocked now. With
        ``adjacent_unlock_only`` a chunk COMBAT tile must be orthogonally
        edge-adjacent to an already-unlocked (BUILDABLE/BUILT) tile."""
        if not self._balance["TileUnlocking"]["adjacent_unlock_only"]:
            return True
        for t in self.get_chunk_for_tile(tile):
            if t.state != TileState.COMBAT:
                continue
            for nc, nr in ((t.col + 1, t.row), (t.col - 1, t.row),
                           (t.col, t.row + 1), (t.col, t.row - 1)):
                n = self.get(nc, nr)
                if n is not None and self._is_unlocked_state(n.state):
                    return True
        return False

    def _release_spawn_reserve(self, count):
        """Flip every designer-painted mark numbered `count` from BACKGROUND to
        SPAWNING — the spawnable-background reserve's nth batch, released on the
        player's nth successful tile purchase.

        A mark whose tile is NOT BACKGROUND (the designer repainted over it
        after painting the mark, or an earlier batch/recede already claimed it)
        is skipped SILENTLY — but it still counts as RELEASED: the batch is
        consumed either way, so the reserve always exhausts on schedule and the
        implicit recede takes over exactly when the numbering says it should.

        Routes every write through `set_tile_state`, never `tile.state`: that
        is the one place a zone change maintains `_by_state`, writes the "s"
        ground code into `terrain_overrides`, fires `on_zone_change`, bumps
        `_path_version` and re-resolves the tile's condition art."""
        for col, row in self._reserve.get(count, ()):
            t = self.get(col, row)
            if t is not None and t.state == TileState.BACKGROUND:
                self.set_tile_state(t, TileState.SPAWNING)

    def _despawn_spawn_reserve(self, count):
        """Flip every designer-painted despawn mark numbered `count` from
        SPAWNING to COMBAT — the despawnable-spawn schedule's nth batch, retired
        on the player's nth successful tile purchase.

        A mark whose tile is NOT SPAWNING (the designer repainted over it after
        painting the mark, or it was never a spawn tile in the first place) is
        skipped SILENTLY — but it still counts as FIRED: the batch is consumed
        either way, so the schedule always exhausts on schedule and the later
        stages take over exactly when the numbering says they should.

        Routes every write through `set_tile_state`, never `tile.state`: that
        is the one place a zone change maintains `_by_state`, writes the "c"
        ground code into `terrain_overrides`, fires `on_zone_change`, bumps
        `_path_version` and re-resolves the tile's condition art."""
        for col, row in self._despawn.get(count, ()):
            t = self.get(col, row)
            if t is not None and t.state == TileState.SPAWNING:
                self.set_tile_state(t, TileState.COMBAT)

    def _retire_spawn_reserve(self):
        """Retire ONE spawnable-background batch (ascending `n`), flipping the
        cells it released from SPAWNING back to COMBAT — the third stage, which
        runs once BOTH painted mark sets are exhausted, one batch per further
        purchase, so the tiles the reserve released die in the order they were
        born. Only reserve-released cells are ever eligible: legend-painted `s`
        tiles belong to the implicit recede, which owns them still.

        A cell that is NOT SPAWNING (repainted, already receded, or its release
        was itself silently skipped) is skipped SILENTLY — but the batch is
        consumed either way, so the retire stage always exhausts and can never
        wedge the implicit recede off forever.

        Routes every write through `set_tile_state`, never `tile.state`: that
        is the one place a zone change maintains `_by_state`, writes the "c"
        ground code into `terrain_overrides`, fires `on_zone_change`, bumps
        `_path_version` and re-resolves the tile's condition art."""
        n = self._retire_batches[self._retire_cursor]
        self._retire_cursor += 1
        for col, row in self._reserve.get(n, ()):
            t = self.get(col, row)
            if t is not None and t.state == TileState.SPAWNING:
                self.set_tile_state(t, TileState.COMBAT)

    def do_unlock(self, tile):
        """Convert the tile's 2×2 chunk's COMBAT tiles → BUILDABLE, then move
        the spawn band in three ordered stages: release this purchase's
        designer-painted spawnable-background batch, retire this purchase's
        designer-painted despawnable-spawn batch, and — only once BOTH painted
        mark sets are exhausted — retire one released reserve batch per further
        purchase, falling back to the implicit `_recede_spawn_after_unlock`
        only when those are exhausted too. Returns True if anything changed."""
        if not self.can_unlock(tile):
            return False
        chunk = self.get_chunk_for_tile(tile)
        converted = False
        for t in chunk:
            if t.state == TileState.COMBAT:
                self.set_tile_state(t, TileState.BUILDABLE)
                converted = True
        if converted:
            self._unlock_purchases += 1
            self._release_spawn_reserve(self._unlock_purchases)
            self._despawn_spawn_reserve(self._unlock_purchases)
            # Three stages, strictest precedence first. `>` not `>=`
            # deliberately: on the very purchase that fires the LAST painted
            # mark of either kind the designer's script is the whole move, so
            # nothing implicit runs; the later stages take over from the next
            # purchase on. Then the `elif`: a purchase that retires a reserve
            # batch is itself the whole move too, exactly as a purchase that
            # releases one is, so the implicit recede stays off for it and only
            # resumes once every retire batch is spent.
            # LOAD-BEARING: a map with no marks of EITHER kind has
            # `_scripted_max == 0` and an empty `_retire_batches`, so the guard
            # is true from the first purchase and the `elif` falls straight
            # through to the implicit recede — today's behaviour, bit for bit.
            # `spawn_recede_enabled: false` disables the implicit system
            # permanently, marks or no marks.
            if self._unlock_purchases > self._scripted_max:
                if self._retire_cursor < len(self._retire_batches):
                    self._retire_spawn_reserve()
                elif self._balance["TileUnlocking"]["spawn_recede_enabled"]:
                    self._recede_spawn_after_unlock(chunk)
        return converted

    # -- dynamic zone progression (prototype tile_map.py:377-438) ---------

    def _scan_2x2(self, predicate, ref_col, ref_row,
                  c_lo, c_hi, r_lo, r_hi):
        """Nearest 2×2 block (top-left anchor) satisfying `predicate` within the
        anchor window [c_lo, c_hi] × [r_lo, r_hi], by squared distance to
        (ref_col, ref_row). Returns (block, squared_distance) or (None, inf).
        Row-major scan + strict `<` best-update: the FIRST row-major block at the
        minimum distance wins (the invariant `_find_2x2` relies on to stay exact
        vs a whole-map scan)."""
        best = None
        best_d = float("inf")
        for r in range(r_lo, r_hi + 1):
            for c in range(c_lo, c_hi + 1):
                block = [self.get(c, r), self.get(c + 1, r),
                         self.get(c, r + 1), self.get(c + 1, r + 1)]
                if any(t is None or not predicate(t) for t in block):
                    continue
                cc, rr = c + 0.5, r + 0.5
                d = (cc - ref_col) ** 2 + (rr - ref_row) ** 2
                if d < best_d:
                    best_d, best = d, block
        return best, best_d

    def _find_2x2(self, predicate, ref_col, ref_row,
                  c_bounds=None, r_bounds=None):
        """Nearest 2×2 block (top-left anchor) whose four tiles all satisfy
        `predicate`, by squared distance to (ref_col, ref_row). `c_bounds` /
        `r_bounds` optionally clamp the block ANCHOR's col/row to an inclusive
        range — the dual-axis recede's axis-alignment constraint: a 2-tall
        block anchored at row r covers rows {r, r+1}, so anchors in
        (lo−1, hi) are EXACTLY the blocks whose rows overlap [lo, hi].

        The nearest match is almost always a few tiles from the reference, so we
        scan an EXPANDING square window instead of the whole map (an O(map) hitch
        on a 1024²+ map, and unlock calls this 2–3× per click). We accept a hit
        only once the window provably contains the global nearest: any anchor
        outside a Chebyshev-`radius` window is >radius from the reference, so when
        the best found squared distance ≤ (radius−2)² (the −2 absorbs the 0.5
        block-centre offsets) no outside block can be closer OR equal — hence the
        window holds every minimum-distance block and row-major-first *in it*
        equals row-major-first *globally*. Result is byte-identical to a full
        scan; the whole-CLAMPED-region window is the terminating fallback (with
        bounds, a no-match search stays O(strip), never O(map) — blocks outside
        the clamp are not candidates at all, so the early-accept proof holds
        unchanged)."""
        anchor_c_max = self.cols - 2
        anchor_r_max = self.rows - 2
        if anchor_c_max < 0 or anchor_r_max < 0:
            return None
        full_c_lo, full_c_hi = 0, anchor_c_max
        if c_bounds is not None:
            full_c_lo = max(full_c_lo, c_bounds[0])
            full_c_hi = min(full_c_hi, c_bounds[1])
        full_r_lo, full_r_hi = 0, anchor_r_max
        if r_bounds is not None:
            full_r_lo = max(full_r_lo, r_bounds[0])
            full_r_hi = min(full_r_hi, r_bounds[1])
        if full_c_lo > full_c_hi or full_r_lo > full_r_hi:
            return None
        ci = int(round(ref_col))
        ri = int(round(ref_row))
        radius = 8
        while True:
            c_lo = max(full_c_lo, ci - radius)
            c_hi = min(full_c_hi, ci + radius)
            r_lo = max(full_r_lo, ri - radius)
            r_hi = min(full_r_hi, ri + radius)
            best, best_d = self._scan_2x2(
                predicate, ref_col, ref_row, c_lo, c_hi, r_lo, r_hi)
            covers_all = (c_lo == full_c_lo and r_lo == full_r_lo
                          and c_hi == full_c_hi and r_hi == full_r_hi)
            if covers_all or (best is not None and best_d <= (radius - 2) ** 2):
                return best
            radius *= 2

    def _recede_spawn_after_unlock(self, chunk):
        """Push the spawn band one 2×2 block outward on BOTH axes: the nearest
        SPAWNING 2×2 horizontally aligned with the purchased chunk (block rows
        overlap the chunk's rows) AND the nearest vertically aligned one each
        convert to COMBAT, then each converted block backfills the nearest
        BACKGROUND 2×2 strictly BEHIND it — on the opposite side from the
        purchased chunk, on the block's own rows/cols (a clean band
        translation). An axis with no aligned spawning block is SKIPPED (a
        single-edge spawn band only ever recedes on its own axis). Both
        conversions happen before either backfill so the second axis can
        neither re-find the first axis's converted block (already COMBAT) nor
        immediately re-convert its fresh backfill (not yet SPAWNING). Never
        touches BUILDABLE/BUILT tiles; degrades silently when nothing behind
        qualifies (map edge) — the band shrinks by one block, the intended
        fallback (the prototype logged and fell back to ANY background block,
        which is exactly the wrong-side placement this rule removes)."""
        if not chunk:
            return
        ref_c = sum(t.col for t in chunk) / len(chunk)
        ref_r = sum(t.row for t in chunk) / len(chunk)
        row_lo = min(t.row for t in chunk)
        row_hi = max(t.row for t in chunk)
        col_lo = min(t.col for t in chunk)
        col_hi = max(t.col for t in chunk)
        spawning = lambda t: t.state == TileState.SPAWNING

        converted = []
        for axis, axis_bounds in (
                ("col", {"r_bounds": (row_lo - 1, row_hi)}),   # x axis
                ("row", {"c_bounds": (col_lo - 1, col_hi)})):  # y axis
            block = self._find_2x2(spawning, ref_c, ref_r, **axis_bounds)
            if block is None:
                continue   # no aligned spawn band on this axis — skip it
            if axis == "col":
                sign = (sum(t.col for t in block) / 4) - ref_c
            else:
                sign = (sum(t.row for t in block) / 4) - ref_r
            for t in block:
                self.set_tile_state(t, TileState.COMBAT)
            converted.append((block, axis, sign))
        for block, axis, sign in converted:
            self._backfill_spawn_behind(block, axis, sign)

    def _backfill_spawn_behind(self, spawn_block, axis, sign):
        """Replace one converted spawn block: the BACKGROUND 2×2 nearest to it
        STRICTLY BEHIND it — beyond the block along the recede `axis` in the
        `sign` direction (away from the purchased chunk), anchor pinned to the
        block's own cross-axis anchor so the band translates cleanly. `sign`
        == 0 (exotic painted overlap: block centred on the chunk along the
        recede axis) keeps the cross-axis pin but drops the direction clamp.
        Degrades silently when nothing qualifies (map edge): no backfill, the
        band shrinks by one block."""
        anchor_col = min(t.col for t in spawn_block)
        anchor_row = min(t.row for t in spawn_block)
        sc = sum(t.col for t in spawn_block) / 4
        sr = sum(t.row for t in spawn_block) / 4
        if axis == "col":
            bounds = {"r_bounds": (anchor_row, anchor_row)}
            if sign > 0:
                bounds["c_bounds"] = (anchor_col + 2, self.cols)
            elif sign < 0:
                bounds["c_bounds"] = (-self.cols, anchor_col - 2)
        else:
            bounds = {"c_bounds": (anchor_col, anchor_col)}
            if sign > 0:
                bounds["r_bounds"] = (anchor_row + 2, self.rows)
            elif sign < 0:
                bounds["r_bounds"] = (-self.rows, anchor_row - 2)
        bg_pred = lambda t: t.state == TileState.BACKGROUND
        bg_block = self._find_2x2(bg_pred, sc, sr, **bounds)
        if bg_block is None:
            return
        for t in bg_block:
            self.set_tile_state(t, TileState.SPAWNING)

    # -- round gate + dormant weight drivers (prototype tile_map.py:117-150) --

    def set_round(self, n):
        self.round_num = n

    def refresh_damage_weight_reductions(self):
        """Mark the top-N damage-dealing built tiles for a weight discount so
        later waves route over them. Dormant in 9C: no occupant reports damage
        and nothing calls ``set_round`` (round gate), so this is a no-op — but
        it is ported whole for 9F/10F to activate by wiring its producers.

        Runs before EVERY pathfinder query (`_pre_query_refresh`), so it is
        also the flow-field invalidation point for both its inputs (round
        gate + last-round damage): the field is bumped only when the flagged
        SET actually changes, never per query."""
        dmg_cfg = self._balance["Pathfinding"]["damage_reduction"]
        candidates = []
        for t in self.built_tiles():
            t.damage_weight_reduced = False
            occ = t.occupant
            if occ is None or not getattr(occ, "alive", False):
                continue
            if t.content_key == BASE_CONTENT_KEY:
                continue
            dmg = getattr(occ, "damage_dealt_last_round", 0)
            if dmg > 0:
                candidates.append((dmg, t))
        flagged = set()
        if self.round_num > dmg_cfg["min_round"] and candidates:
            candidates.sort(key=lambda dt: dt[0], reverse=True)
            for _, t in candidates[:int(dmg_cfg["top_n"])]:
                t.damage_weight_reduced = True
                flagged.add((t.col, t.row))
        if flagged != self._dmg_reduced_prev:
            self._dmg_reduced_prev = flagged
            self._bump_path_version()

    def refresh_defence_range_coverage(self, covered_set):
        """Mirror ``covered_set`` into the per-tile `defence_range_covered`
        flags. Change-detected (it runs before every pathfinder query): an
        unchanged set — the common case — is a no-op; otherwise only the
        symmetric difference is touched and the flow field invalidates
        (covered tiles carry a weight add, so coverage changes re-route)."""
        covered = set(covered_set)
        if covered == self._defence_covered_prev:
            return
        for col, row in covered ^ self._defence_covered_prev:
            t = self.get(col, row)
            if t is not None:
                t.defence_range_covered = (col, row) in covered
        self._defence_covered_prev = covered
        self._bump_path_version()

    def refresh_building_overwrite_flags(self):
        """Change-detect the set of tiles whose LIVE occupant currently
        OVERWRITES (rather than adds to) the terrain condition weight
        (buildings-overwrite-tileweights rework — `Tile._overwrites_
        condition`), and bump the flow field only when that set actually
        changed. This is a NEW hazard the rework introduces: `content_key`
        used to survive a building's death untouched, so nothing needed to
        bump on death; now the occupant's `alive` flag is part of the
        weight calculation itself, so a building dying (tile weight reverts
        from overwrite to additive) must invalidate the cached field exactly
        like the other two pre-query producers above.

        Short-circuits to a no-op scan when no overwrite can EVER be active
        under the current balancing (master switch off, every per-building
        override off, every per-condition override off) — headless fixtures
        and any run with the whole feature off pay nothing beyond the one
        bool + two dict reads."""
        pf = self._balance["Pathfinding"]
        tc = self._balance["TileConditions"]
        if (not pf["buildings_overwrite_tileweights"]
                and not any(pf["content_weight_overwrites"].values())
                and not any(tc["path_weight_overwritable"].values())):
            return
        flagged = set()
        for t in self.built_tiles():
            ck = CONDITION_WEIGHT_KEY.get(t.condition)
            if ck is None:
                continue
            # Reuses Tile's own resolution rather than re-deriving the OR of
            # the three switches here — one source of truth for "does this
            # tile currently overwrite", shared with `pathfinding_weight`.
            if t._overwrites_condition(self._balance, ck):
                flagged.add((t.col, t.row))
        if flagged != self._overwrite_prev:
            self._overwrite_prev = flagged
            self._bump_path_version()

    # -- edge walls (10E, prototype tile_map.py:152-252) ------------------

    def get_wall_between(self, c1, r1, c2, r2):
        """The ``WallEdge`` on the edge between two tiles, or None. The
        pathfinder's ``_wall_blocks`` reads this; before any WallBuilder is
        placed ``wall_edges`` is empty, so every edge stays passable."""
        return self.wall_edges.get(_wall_key(c1, r1, c2, r2))

    def damage_wall(self, c1, r1, c2, r2, amount):
        """Reduce a wall's HP by ``amount``. Removes it + returns True if HP drops
        to <= 0 (it broke); else False. False when there is no wall on that edge
        (prototype ``damage_wall``)."""
        key = _wall_key(c1, r1, c2, r2)
        edge = self.wall_edges.get(key)
        if edge is None:
            return False
        edge.hp -= amount
        if edge.hp <= 0:
            del self.wall_edges[key]
            # Only the DEATH transition changes pathing (`_wall_blocks` is
            # hp>0) — a mid-HP hit never invalidates the flow field.
            self._bump_path_version()
            return True
        return False

    @staticmethod
    def _is_player_territory(tile):
        """Player territory = a BUILDABLE or BUILT tile (the same test unlocking
        uses to seed adjacency)."""
        return tile is not None and tile.state in (
            TileState.BUILDABLE, TileState.BUILT)

    @staticmethod
    def _is_combat_zone(tile):
        """COMBAT or SPAWNING — the zones enemies actually traverse. Walls are
        only placed on player-tile edges facing these tiles."""
        return tile is not None and tile.state in (
            TileState.COMBAT, TileState.SPAWNING)

    def _exterior_combat_tiles(self):
        """BFS from every SPAWNING tile through COMBAT/SPAWNING tiles only, never
        crossing player territory or BACKGROUND. Returns the set of (col, row)
        combat tiles reachable from the spawn zone — the 'exterior' side. Combat
        tiles enclosed by player territory are excluded (prototype
        ``_exterior_combat_tiles``)."""
        visited = set()
        queue = []
        for tile in self.spawning_tiles():
            pos = (tile.col, tile.row)
            if pos not in visited:
                visited.add(pos)
                queue.append(pos)
        head = 0
        while head < len(queue):
            col, row = queue[head]
            head += 1
            for nc, nr in ((col + 1, row), (col - 1, row),
                           (col, row + 1), (col, row - 1)):
                if (nc, nr) in visited:
                    continue
                nb = self.get(nc, nr)
                if nb is None or self._is_player_territory(nb):
                    continue
                if not self._is_combat_zone(nb):
                    continue   # skip BACKGROUND — enemies never come from there
                visited.add((nc, nr))
                queue.append((nc, nr))
        return visited

    def place_walls_for_builder(self, builder):
        """Raise walls on the outermost perimeter only: edges where a player tile
        faces an exterior combat tile (reachable from the spawn zone). Interior
        concavities and the base pocket's inner edges are excluded. A snapshot of
        the placed edges is frozen onto the builder so ``rebuild_walls`` can
        restore destroyed segments without re-deriving the perimeter (prototype
        ``place_walls_for_builder``). ``builder`` is duck-typed: ``wall_hp()`` +
        ``set_wall_snapshot()``."""
        wall_hp = builder.wall_hp()
        exterior = self._exterior_combat_tiles()
        snapshot = []
        for tile in self.all_tiles():
            if not self._is_player_territory(tile):
                continue
            for nc, nr in ((tile.col + 1, tile.row), (tile.col - 1, tile.row),
                           (tile.col, tile.row + 1), (tile.col, tile.row - 1)):
                if (nc, nr) not in exterior:
                    continue   # not exterior-facing — skip
                key = _wall_key(tile.col, tile.row, nc, nr)
                self.wall_edges[key] = WallEdge(
                    tile.col, tile.row, nc, nr, wall_hp, wall_hp, builder)
                snapshot.append([tile.col, tile.row, nc, nr])
        builder.set_wall_snapshot(snapshot)
        if snapshot:
            self._bump_path_version()   # new blocking edges re-route paths

    def remove_walls_for_builder(self, builder):
        """Remove every wall owned by ``builder`` (called when it dies)."""
        owned = [k for k, e in self.wall_edges.items() if e.owner is builder]
        for key in owned:
            del self.wall_edges[key]
        if owned:
            self._bump_path_version()   # edges opened — paths may shorten

    def rebuild_walls(self):
        """Restore destroyed wall segments from each alive WallBuilder's frozen
        snapshot (missing edges recreated at full HP; surviving edges reset to
        ``max_hp``). Never re-derives the perimeter, so walls do not expand if the
        player unlocks more tiles after placement (prototype ``rebuild_walls``).
        Duck-typed: ``building_type`` / ``alive`` / ``wall_hp()`` /
        ``wall_snapshot()``."""
        for tile in self.built_tiles():
            b = tile.occupant
            if (b is None or getattr(b, "building_type", None) != "wall_builder"
                    or not getattr(b, "alive", False)):
                continue
            snapshot = b.wall_snapshot()
            if not snapshot:
                continue
            wall_hp = b.wall_hp()
            for c1, r1, c2, r2 in snapshot:
                key = _wall_key(c1, r1, c2, r2)
                edge = self.wall_edges.get(key)
                if edge is None:
                    self.wall_edges[key] = WallEdge(
                        c1, r1, c2, r2, wall_hp, wall_hp, b)
                    # A destroyed edge came back — blocking changed. Healing
                    # a surviving edge (else-branch) never does (alive→alive).
                    self._bump_path_version()
                else:
                    edge.hp = edge.max_hp

    # -- occupancy sync to engine physics (E-32) --------------------------

    def sync_occupancy(self, occupancy):
        """FULL-REBUILD mirror of every occupied tile into an
        ``engine.physics.TileOccupancy``. Occupancy is *occupant* driven (an
        object standing on the tile); BACKGROUND impassability is a
        pathfinding-weight concern, not occupancy.

        NOT on the per-placement path: placing/attaching a building only changes
        ONE tile, so those seams call ``occupancy.set`` directly (a full
        ``all_tiles`` scan here is an O(map) hitch on large maps). Kept for a
        from-scratch resync of the whole grid if a caller ever needs one."""
        for t in self.all_tiles():
            if t.occupant is not None:
                occupancy.set((t.col, t.row), t.occupant)
            else:
                occupancy.clear((t.col, t.row))
