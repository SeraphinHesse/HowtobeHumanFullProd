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
    CONDITION_BY_MAP_KEY, CONDITION_CATEGORY, CONDITION_LABEL,
    CONDITION_STATE_LABEL, CONDITION_WEIGHT_KEY, Tile, TileCondition, TileState,
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


def _condition_family(registry, condition, state):
    """The variant family (a tuple of slot keys, possibly empty) for
    ``condition`` in zone ``state`` — the ONE two-axis lookup both the variant
    ROLL and the slot RESOLVE go through, so the pool a tile's index is sized
    against can never disagree with the pool that index is read from.

    ``()`` whenever there is no registry, no condition/state label (BACKGROUND
    and SPAWNING have no state label at all — see ``CONDITION_STATE_LABEL``),
    or no such group. Pure."""
    if registry is None:
        return ()
    cond_label = CONDITION_LABEL.get(condition)
    state_label = CONDITION_STATE_LABEL.get(state)
    if cond_label is None or state_label is None:
        return ()
    try:
        return registry.group_slots(
            CONDITION_CATEGORY, (cond_label, state_label))
    except KeyError:
        return ()


def _resolve_condition_slot(registry, condition, state, variant_idx):
    """The art slot for ``condition`` in its CURRENT zone ``state``, at the
    tile's stable ``variant_idx`` — or None when there is no registry /
    condition label / state label / group / slots.

    Two-axis lookup (shared with the variant roll — `_condition_family`):
    `CONDITION_LABEL[condition]` selects the condition's top-level group,
    `CONDITION_STATE_LABEL[state]` selects the state's leaf family WITHIN it.
    ``variant_idx % len(variants)`` keeps the index well-defined even when a
    state's pool is smaller than another's (e.g. Built carries fewer imported
    variants than Combat) — same shape as ``game.enemies.enemy.variant_slot``,
    so dropping a new variant in via the editor grows the pool with NO code
    change. Pure — callers own the index."""
    variants = _condition_family(registry, condition, state)
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
        # Kept for the DEFERRED condition roll (`_roll_condition`), which fires
        # long after this constructor returns — when a spawn tile converts to
        # combat. `None` is the same all-GRASS headless-fixture escape hatch it
        # is for the init roll: no rng, no deferred roll either, so every
        # pre-existing fixture stays byte-identical.
        self._rng = rng
        # The weighted-draw table, built once here rather than per conversion.
        # `spawn_chances` is indexed DIRECTLY — a missing key is invalid data
        # and must fail loud (D-2).
        _chances = balance["TileConditions"]["spawn_chances"]
        self._cond_choices = (TileCondition.GRASS, TileCondition.MOUNTAIN,
                              TileCondition.POND, TileCondition.FOREST)
        self._cond_weights = [_chances["grass"], _chances["mountain"],
                              _chances["pond"], _chances["forest"]]
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
        # `doc.spawnable_background` is {(col, row): stage}; inverted ONCE
        # here into `stage -> [(col, row), …]` so firing a stage's batch is a
        # single O(1) dict hit at unlock time. This is ONE pass over the MARKS
        # (a handful of painted cells), never a pass over the map — the
        # O(strip)/never-O(map) invariant this module lives by.
        # `_reserve_max` is the highest stage number painted (0 when the map
        # has no marks at all), which is what lets `do_unlock` tell "the
        # reserve still has unreleased batches" from "the reserve is
        # exhausted, hand back to the implicit recede".
        self._reserve = {}
        for (mark_col, mark_row), stage in doc.spawnable_background.items():
            self._reserve.setdefault(stage, []).append((mark_col, mark_row))
        self._reserve_max = max(self._reserve, default=0)
        # Raw tally of successful purchases. Since stage zones landed it gates
        # NOTHING (the stage counter below does) — kept because "how many 2×2s
        # has this run bought" is still a useful, cheap thing to know.
        self._unlock_purchases = 0

        # -- Despawnable spawn: the designer-painted despawn schedule --------
        # `doc.despawnable_spawn` is the exact mirror of the reserve above,
        # inverted the same way and for the same reason: ONE pass over the
        # MARKS, never over the map, so firing a stage's batch is an O(1) dict
        # hit. `_despawn_max` is the highest stage number painted (0 when none).
        self._despawn = {}
        for (mark_col, mark_row), stage in doc.despawnable_spawn.items():
            self._despawn.setdefault(stage, []).append((mark_col, mark_row))
        self._despawn_max = max(self._despawn, default=0)
        # the stage at or beyond which no painted mark of EITHER kind can fire
        self._scripted_max = max(self._reserve_max, self._despawn_max)
        # the spawn-reserve batches, ascending n, retired one per purchase
        # afterwards — the tiles the reserve released die in the order they
        # were born. `_retire_cursor` is how many have already been retired.
        self._retire_batches = sorted(self._reserve)
        self._retire_cursor = 0

        # -- Stage zones: the designer-painted STAGE counter ------------------
        # `doc.stage_zones` is {(col, row): stage}, marks painted on COMBAT
        # tiles. Kept FLAT here (not inverted like the two overlays above)
        # because the lookup runs the other way round: `_advance_stage` asks
        # "what stage is painted under THIS tile", four tiles per purchase.
        # Still ONE pass over the MARKS, never over the map.
        # `_stage` is the run's stage counter: starts at 0, only ever advanced
        # by `_advance_stage`, never decreases. It — not the purchase tally —
        # is what drives the release/despawn batches and gates the retire and
        # recede stages.
        self._stage_zones = {
            (mark_col, mark_row): stage
            for (mark_col, mark_row), stage in doc.stage_zones.items()
        }
        self._stage = 0

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
        # `_wall_key`. One WallEdge per edge — first claim wins: a newly-placed
        # builder only raises walls on perimeter edges nobody currently owns,
        # and never touches or reassigns an edge another WallBuilder already
        # owns (its HP/max_hp/ownership are left untouched).
        self.wall_edges = {}
        # Buildings currently IN TRANSIT between two tiles (Building Movement).
        # A plain list of duck-typed order objects — `types.SimpleNamespace`s
        # carrying `building` / `from_col` / `from_row` / `to_col` / `to_row` /
        # `rounds_left`, built by `game/buildings/movement.py` and ticked down
        # by payday. Deliberately NOT a game.buildings import: the map layer
        # duck-types the order exactly like `wall_edges` duck-types its
        # `owner`. Both endpoints of a live order sit at BUILDABLE with no
        # occupant (enemies still path through them at the ordinary
        # `buildable_tile` weight); `is_moving` is what bars them from hosting
        # a new building while the move runs.
        self.moving_orders = []
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
        # The last set OBJECT handed to `refresh_defence_range_coverage` (not
        # its value — that is `_prev` above). The wired coverage producer
        # returns an identical object while nothing has changed, which is the
        # per-query fast path; None can never alias a real input.
        self._defence_covered_src = None
        # buildings-overwrite-tileweights rework: a building's `alive` flag
        # now changes its tile's weight (dead = additive again), so a death
        # must bump the flow field exactly like the other two producers.
        self._overwrite_prev = set()

        # PRE-QUERY MEMO CLOCK (perf). The three producers above run from
        # `pathfinder._pre_query_refresh` before EVERY pathfinding query, and
        # each is an O(built tiles) sweep — three sweeps per spawned enemy, and
        # a batch/death-swarm releases many enemies in ONE frame. `_sim_frame`
        # is an OPT-IN frame clock: None means "no host is driving frames, never
        # memoise" (headless fixtures, editor stubs and every test that mutates
        # a tilemap between two `find_path` calls keep the old run-every-query
        # behaviour). A host that calls `begin_sim_frame()` once per frame
        # (`Session.pre_sim`) gets the producers run at most ONCE per frame; the
        # worst staleness is one frame of soft weight preferences (damage
        # discount, coverage add, overwrite flags — none of them change
        # PASSABILITY), which is why memoising them is safe at all.
        self._sim_frame = None
        self._pre_query_frame = None

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

        # -- Spawn reserve -> tree deco flag ---------------------------------
        # Stamp the painted `spawnable_background` marks onto their tiles so
        # the tree emitter can draw the reserve's treeline while those tiles
        # are still BACKGROUND (`spawn_deco.py`). O(marks), never an O(map)
        # walk (perf invariant) — the same one-pass-over-the-marks shape the
        # `_reserve` inversion above uses, and the same `None` guard: a
        # TileMap built DIRECTLY from a hand-made doc never went through
        # `validate_doc`, so an out-of-bounds mark must be skipped rather than
        # raise on `None`.
        for (mark_col, mark_row) in doc.spawnable_background:
            t = self.get(mark_col, mark_row)
            if t is not None:
                t.spawn_reserved = True

        if has_base:
            base_tile = self.get(self.base_col, self.base_row)
            self.set_tile_state(base_tile, TileState.BUILT)
            self.set_tile_content(base_tile, None, BASE_CONTENT_KEY)

        # -- 10I: tile-condition roll (prototype tile_map.py:69-91) ---------
        # ONE weighted draw per tile, fired the moment that tile ENTERS PLAY —
        # a tile's condition is decided exactly once and never changes after
        # that. For a tile painted `c` (combat) the moment is right here, at
        # map construction. For a tile that starts SPAWNING or BACKGROUND it is
        # its SPAWNING -> COMBAT conversion, handled by `_roll_condition` off
        # `set_tile_state`; the spawn band itself is deliberately condition-free
        # (it is a staging area — plain ground plus trees), and so `s -> c` and
        # `f -> s -> c` both land a real, rolled condition. This REPLACES the
        # prototype-exact quirk where such a tile stayed GRASS forever.
        # Permanently ineligible (stay GRASS): the starting unlocked pocket
        # incl. the base ("so the base is always reachable").
        # ``rng`` is BOTH the on-switch and the determinism seam: the host
        # passes the module ``random`` (live roll) or a ``random.Random(seed)``
        # (deterministic tests); ``None`` skips the roll entirely, keeping
        # every pre-10I headless fixture (which asserts exact path costs on
        # all-GRASS grids) byte-stable. One-time O(map) init pass — NOT a
        # per-frame scan (perf invariant).
        #
        # PAINTED CONDITIONS come FIRST and are applied UNCONDITIONALLY —
        # deliberately OUTSIDE the ``rng is not None`` gate below. A painted
        # mark is deterministic AUTHORING, not a roll, so the all-GRASS
        # headless-fixture escape hatch (``rng=None``) must not suppress it.
        # This costs nothing for every existing fixture: a doc with no marks
        # carries an EMPTY dict (``TileMapDoc.__post_init__``), so the loop
        # body never runs and those maps stay byte-identical.
        #
        # A painted mark WINS EVERYWHERE, with no exceptions: BACKGROUND and
        # SPAWNING tiles and the starting unlocked pocket incl. the base take
        # the painted condition too, even though the ROLL skips all of them.
        # This is a deliberate, user-chosen rule, NOT an oversight — the
        # eligibility rules govern the ROLL; they never governed a designer's
        # explicit mark. A marked cell is `condition_rolled` from the start, so
        # the DEFERRED roll cannot overwrite it either: a painted spawn tile
        # carries its condition (weight, modifiers) while it is spawning and
        # keeps exactly that condition after it converts to combat.
        # ``CONDITION_BY_MAP_KEY`` is indexed DIRECTLY (never ``.get``): an
        # unknown name is invalid data and must fail loud (D-2). O(marks),
        # never an O(map) walk (perf invariant, game/map/CLAUDE.md).
        # The `None` guard is the same defence-in-depth every other painted
        # overlay's consumer carries (`_release_spawn_reserve` /
        # `_despawn_spawn_reserve`): `validate_doc` already bounds-checks every
        # mark at load, but a `TileMap` built DIRECTLY from a hand-made doc
        # (the headless-fixture pattern) never passes through it, and `Tile`
        # uses `__slots__` — so an out-of-bounds mark would raise a bare
        # AttributeError on `None` instead of being skipped.
        painted = doc.tile_conditions
        for (col, row), name in painted.items():
            t = self.get(col, row)
            if t is not None:
                t.condition = CONDITION_BY_MAP_KEY[name]
                # A mark DECIDES the tile — the deferred roll below must never
                # revisit it, exactly as the roll loop's `in painted` skip
                # keeps the init roll off it.
                t.condition_rolled = True
        if rng is not None:
            for t in self.all_tiles():
                # A painted cell is never rolled — THAT skip is what "locks
                # the tile out of the tile generation process": the
                # designer's mark is final and no draw can overwrite it.
                if (t.col, t.row) in painted:
                    continue
                # BACKGROUND and SPAWNING are PENDING, not exempt: a tile
                # that is not in play yet does not decide its condition here.
                # `_roll_condition` decides it at the moment the tile converts
                # to COMBAT, so `s -> c` and `f -> s -> c` both land a real
                # condition instead of staying GRASS forever (which is what
                # the old "receded-into-play tiles stay GRASS, prototype-exact"
                # quirk did). `condition_rolled` stays False for exactly this
                # set — that flag, not the state, is what the deferred roll
                # reads.
                if t.state in (TileState.BACKGROUND, TileState.SPAWNING):
                    continue
                # The starting unlocked pocket incl. the base is EXEMPT, not
                # pending: it stays GRASS forever, so it is marked decided.
                t.condition_rolled = True
                if self._is_unlocked_state(t.state):
                    continue
                t.condition = self._roll_condition_value(rng)
        # -- /10I --

        # -- Condition ART: one variant index per tile, rolled ONCE here ----
        # A SEPARATE pass from the roll above on purpose: the roll's
        # eligibility rules are prototype-exact gameplay (and every path-cost
        # fixture depends on them), whereas art covers every playable tile
        # including the starting pocket — so imported grass art isn't missing
        # a hole where the base sits. BACKGROUND and SPAWNING tiles are
        # terrain, not conditions, and stay slotless: neither has an entry in
        # `CONDITION_STATE_LABEL`, so skipping them here only saves the work —
        # `_resolve_condition_slot` would return None for them anyway. Their
        # variant index is picked later, by `_roll_condition`, together with
        # the condition it belongs to. No registry (headless fixtures) or no
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
            # per tile). Rolled for EVERY tile, BEFORE the state `continue`
            # below — a BACKGROUND tile is exactly the kind that later enters
            # the spawn band (the designer-painted `spawnable_background`
            # reserve, or an implicit backfill behind a recede), and it must
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
                if t.state in (TileState.BACKGROUND, TileState.SPAWNING):
                    continue
                family = _condition_family(registry, t.condition, t.state)
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

    # -- tile conditions ---------------------------------------------------

    def _roll_condition_value(self, rng):
        """ONE weighted draw from `TileConditions.spawn_chances`. The single
        expression of the roll — the init pass and the deferred conversion
        roll both go through it, so they cannot drift."""
        return rng.choices(self._cond_choices, weights=self._cond_weights)[0]

    def _roll_condition(self, tile):
        """Decide `tile`'s condition NOW, if it has not been decided yet.

        THE deferred half of the condition roll: a tile that was not in play at
        map construction (SPAWNING, or BACKGROUND that later joined the spawn
        band) carries no condition until it converts to COMBAT, and this is
        where it gets one. Called from `set_tile_state` on exactly that
        transition, which covers every route in — the designer's despawn
        schedule, the retire stage and the implicit dual-axis recede all route
        through that one seam, so none of them needs its own hook.

        Idempotent by `Tile.condition_rolled`: a tile whose condition the init
        roll already decided, that a painted mark claimed, or that this method
        already rolled is left ALONE. `self._rng is None` (headless fixtures)
        skips it entirely, exactly as it skips the init roll.

        The variant index is picked here too, against the tile's NEW
        (condition, state) family — the tile skipped the init art pass, so this
        is its first and only variant roll. `set_tile_state` resolves the slot
        from it immediately after."""
        if self._rng is None or tile.condition_rolled:
            return
        tile.condition = self._roll_condition_value(self._rng)
        tile.condition_rolled = True
        family = _condition_family(self._registry, tile.condition, tile.state)
        tile.condition_variant_idx = (
            self._rng.randrange(len(family)) if family else 0)

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

    def begin_sim_frame(self):
        """Advance the pre-query memo clock one frame (see `_sim_frame`).

        The HOST calls this once per frame, before the sim (`Session.pre_sim`).
        The first call switches the memo ON for this tilemap; a tilemap nobody
        calls it on never memoises."""
        self._sim_frame = 0 if self._sim_frame is None else self._sim_frame + 1

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
        # A tile ENTERING PLAY decides its condition here — the deferred half
        # of the init roll, for every tile that was SPAWNING or BACKGROUND at
        # map construction. Must run BEFORE the art re-resolve below, which
        # reads the condition and variant index it writes. A tile whose
        # condition is already decided (rolled at init, or painted) is left
        # untouched, so this is a no-op on every other transition.
        if new_state == TileState.COMBAT:
            self._roll_condition(tile)
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

    def is_moving(self, col, row):
        """True if ``(col, row)`` is either endpoint of a live move order.

        Both the origin a moving building vacated and the destination it is
        headed for are ordinary BUILDABLE tiles for pathfinding purposes — an
        enemy walks through them at the normal weight — but neither may host a
        new building until the move lands. O(orders), and orders are a handful
        at most."""
        return any((o.from_col, o.from_row) == (col, row)
                   or (o.to_col, o.to_row) == (col, row)
                   for o in self.moving_orders)

    # -- tile unlocking (prototype tile_map.py:298-374) -------------------

    def _section_index(self, tile):
        """(col_section, row_section) of the fixed 2×2 grid. Anchored at the
        map's start_area marker when placed (the marker IS section (0, 0));
        otherwise so the base is the BOTTOM-LEFT tile of section (0, 0) (row
        origin one tile above the base). The starting buildable pocket is
        section (0, 0)."""
        return ((tile.col - self._sec_col_origin) // 2,
                (tile.row - self._sec_row_origin) // 2)

    def unlock_cost(self, tile, run_state=None, boss_upgrades_balance=None):
        """BASE + (manhattan − 1) * MOD — cost scales with the 2×2-section
        Manhattan distance from the starting section (0, 0), direction-agnostic:
        sections ADJACENT to the start cost exactly ``base_unlock_cost`` and
        each further step adds ``unlock_cost_distance_mod``. The distance term
        is clamped ≥ 0 (section (0, 0) itself starts owned, never purchased).

        ``run_state``/``boss_upgrades_balance`` are BU-3's standard optional
        trailing pair (see ``game/core/boss_upgrades.py``'s threading-pattern
        section): with both present, the ``tile_discount`` boss upgrade cuts
        the price by its ``discount_pct`` per pick, additively (D4), floored at
        0 — a tile CAN become free, unlike a wall (that is why this floor and
        ``wall_cost_discount``'s differ). Without the pair — every caller that
        predates BU-3, every headless fixture — the returned figure is
        byte-identical to before. The map layer still imports nothing from
        ``game.buildings``; ``game.core`` it already imports (``load_balance``
        at module scope), and this one is deferred anyway for the same
        cycle reason every other BU-3 hook site defers it."""
        u = self._balance["TileUnlocking"]
        sc, sr = self._section_index(tile)
        dist = max(0, abs(sc) + abs(sr) - 1)
        cost = u["base_unlock_cost"] + dist * u["unlock_cost_distance_mod"]
        if run_state is None or boss_upgrades_balance is None:
            return cost
        from game.core import boss_upgrades
        return boss_upgrades.discounted(
            cost, run_state, boss_upgrades_balance, "tile_discount",
            "discount_pct", 20, floor=0)

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
        SPAWNING — the spawnable-background reserve's nth batch, released when
        the run's stage counter reaches n.

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
        when the run's stage counter reaches n.

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
        runs once the stage counter has spent BOTH painted mark sets, one batch
        per further purchase, so the tiles the reserve released die in the order
        they were born. Only reserve-released cells are ever eligible:
        legend-painted `s` tiles belong to the implicit recede, which owns them
        still.

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

    def _advance_stage(self, chunk):
        """Advance the run's STAGE counter to the highest stage-zone number
        painted under the bought chunk's four tiles, firing every batch the
        jump passes over. Returns True iff the stage actually moved.

        The stage is the designer's own clock, and stage zones are the ONLY
        thing that winds it: a chunk with no painted cell under it leaves the
        counter exactly where it was (the number of 2×2s bought is irrelevant),
        and a zone numbered BELOW the current stage never winds it backwards.

        A jump of more than one — stage 2 straight to stage 5 — fires batches
        3, 4 and 5 in ASCENDING order, release before despawn within each. That
        catch-up is load-bearing, not a nicety: it is what still guarantees both
        painted mark sets exhaust on schedule (and therefore that the retire
        stage and the implicit recede can never be wedged off forever) however
        coarsely the designer numbered the zones.

        Every write lands through `_release_spawn_reserve`/
        `_despawn_spawn_reserve`, so it inherits their `set_tile_state` routing
        and their skip-silently-but-still-consume-the-batch rule."""
        new_stage = self._stage
        for t in chunk:
            painted = self._stage_zones.get((t.col, t.row))
            if painted is not None and painted > new_stage:
                new_stage = painted
        if new_stage <= self._stage:
            return False
        for k in range(self._stage + 1, new_stage + 1):
            self._release_spawn_reserve(k)
            self._despawn_spawn_reserve(k)
        self._stage = new_stage
        return True

    def do_unlock(self, tile):
        """Convert the tile's 2×2 chunk's COMBAT tiles → BUILDABLE, then move
        the spawn band. THREE sources can move it, in strict precedence:
        the designer's stage zones (this purchase advanced the stage counter →
        every skipped release/despawn batch fires, ascending); else, once the
        stage has spent every painted mark, the retire stage (one released
        reserve batch per further purchase); else the implicit
        `_recede_spawn_after_unlock`. Returns True if anything changed."""
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
            advanced = self._advance_stage(chunk)
            # `not advanced` first: a purchase that moved the designer's stage
            # counter is itself the whole move — its placement is the designer's
            # statement, so nothing implicit piles on top of it. Then
            # `_stage >= _scripted_max` ("the stage has passed every painted
            # release/despawn mark, so none can ever fire again") gates the two
            # implicit stages, and the `elif` keeps them exclusive: a purchase
            # that retires a reserve batch is likewise the whole move, and the
            # recede only resumes once every retire batch is spent.
            # LOAD-BEARING: a map with no marks of ANY of the three kinds has
            # `_scripted_max == 0`, an empty `_retire_batches`, and `advanced`
            # always False (nothing can ever paint a stage), so the guard is
            # true from the first purchase and the `elif` falls straight through
            # to the implicit recede — today's behaviour, bit for bit.
            # `spawn_recede_enabled: false` disables the implicit system
            # permanently, marks or no marks.
            if not advanced and self._stage >= self._scripted_max:
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
        (covered tiles carry a weight add, so coverage changes re-route).

        The identity check comes FIRST so the common case costs nothing at
        all: `game/buildings/coverage.py`'s wired producer hands back the SAME
        set object while its signature is unchanged, so an unmoved coverage
        set skips the O(|covered|) copy and compare as well as the mirroring.
        It is checked against `_defence_covered_src` (the last INPUT object)
        rather than `_defence_covered_prev` (a defensive copy of its value) —
        the two are deliberately different objects. A caller that builds a
        fresh set per call just falls through to the value compare, exactly as
        before; the producer never mutates a set it has already returned, so
        remembering its identity here cannot go stale."""
        if covered_set is self._defence_covered_src:
            return
        self._defence_covered_src = covered_set
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
        concavities and the base pocket's inner edges are excluded. A newly-placed
        builder only claims perimeter edges nobody currently owns — an edge
        already owned by another WallBuilder is left completely untouched (not
        even added to this builder's own snapshot), so a later placement can
        never override an earlier builder's walls or progress. A snapshot of the
        edges this builder actually claimed is frozen onto it so ``rebuild_walls``
        can restore destroyed segments without re-deriving the perimeter
        (prototype ``place_walls_for_builder``). ``builder`` is duck-typed:
        ``wall_hp()`` + ``set_wall_snapshot()``."""
        wall_hp = builder.wall_hp()
        exterior = self._exterior_combat_tiles()
        snapshot = []
        # Player territory only — read straight off the `_by_state` index rather
        # than scanning every tile on the map (a click must not cost O(cols*rows)).
        # Sorted by (row, col) so the snapshot keeps `all_tiles()` order: the sets
        # iterate in identity-hash order, which would otherwise vary per run.
        player_tiles = sorted(
            self._by_state[TileState.BUILDABLE] | self._by_state[TileState.BUILT],
            key=lambda t: (t.row, t.col))
        for tile in player_tiles:
            for nc, nr in ((tile.col + 1, tile.row), (tile.col - 1, tile.row),
                           (tile.col, tile.row + 1), (tile.col, tile.row - 1)):
                if (nc, nr) not in exterior:
                    continue   # not exterior-facing — skip
                key = _wall_key(tile.col, tile.row, nc, nr)
                if key in self.wall_edges:
                    continue   # already owned by another builder — hands off
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
