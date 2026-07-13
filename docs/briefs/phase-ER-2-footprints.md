# Phase ER-2 Brief — Footprint Clearance Pathing

> Coordination artifact for the ER-1..ER-4 subagent batch. Planner filled §1–§4;
> the coder treats §3 as a HARD boundary and §2 as a contract; the reviewer
> verifies the diff against §1/§2/§4. Source plan: `planning/EnemyReworkPLAN.md`
> (Context; decisions **D5** — footprints are a pathfinding property, not an
> occupancy one — and **D6** — one cached flow field per footprint; Phase ER-2;
> Risks). Branch: `phase-ER-2-footprints` (under the ER umbrella).
>
> **This brief EXTENDS the plan doc in three places** (marked ⚠ ADDITION inline).
> Where they conflict, this brief wins.

**Phase goal:** an enemy with `footprint: 2` only ever stands where all four of
its tiles are passable. It routes around one-tile gaps a 1×1 slips through and
attacks whatever blocks it, through the existing block-and-attack model. It never
enters `TileOccupancy` (D5). `footprint: 1` behaviour is **byte-identical to
today** — that is the hard invariant of this phase.

---

## Known repo state (verified against current source — do NOT re-derive)

**ER-2 stacks on ER-1**, which is complete on `phase-ER-1-render-sizing` but not
yet on the umbrella. Read any file ER-1 changed with
`git show phase-ER-1-render-sizing:<path>`. All line citations to
`game/enemies/enemy.py` below are **ER-1's version**.

- **`footprint` already exists in data and is already read.** `data/balancing/
  enemies.json` + `data/schemas/enemies.schema.json` carry a **required**
  `footprint` (integer 1..8) and `sprite_scale` (number 0.1..8) on all four
  `EnemyTypes` blocks (`Standard`, `Raider`, `SiegeCannon`, `Boss`) — every one is
  `footprint: 1` today. `Enemy.STAT_SUBTREE` was made real
  (`Enemy=("Standard",)`, `Raider=("Raider",)`, `SiegeCannon=("SiegeCannon",)`,
  `Boss=("Boss",)`), and `Enemy.__init__` resolves its balance block through it at
  `enemy.py:99-101` (`block = enemies_balance["EnemyTypes"]; for seg in
  self.STAT_SUBTREE: block = block[seg]`), reading `block["footprint"]` /
  `block["sprite_scale"]` **directly, with no `.get()` default** (the root
  `CLAUDE.md` forbids a py+json dual value store).
  → **ER-2 adds NO data key and touches NO schema.** The `block` local is already
  in scope one line above the component list. You only pass it into `PathAgent`.
- `game/map/pathfinder.py`: `_dijkstra(tilemap, start_col, start_row, goals,
  ignore_walls)` `:76-109`; `_build_flow_field(tilemap, ignore_walls)` `:112-157`;
  `_ensure_flow_field(tilemap, ignore_walls)` `:160-178` — cache is
  `tilemap._flow_cache = (version, {})` keyed on `getattr(tilemap,
  "_path_version", 0)`, and the **inner dict is keyed on `ignore_walls`**
  (`:176-178`). `_field_path` `:181-192`, `find_path` `:195-205`,
  `find_path_ignoring_walls` `:208-215`, `_goal_tiles` `:218-225`,
  `_find_path_to_goals` `:228-236`, and the three `find_path_to_nearest_*`
  variants `:239-263` (fresh forward Dijkstras — ~one boss per wave).
- **Every call site passes `(tilemap, col, row)` positionally** (`enemy.py:139,141,
  228,231`; `components.py:164`; `tools/tests/*`). A trailing `footprint=1`
  default is safe everywhere.
- `game/enemies/components.py`: `PathAgent` `:43-207`. Declared fields
  `reached_base`/`blocked`/`goal_is_base`/`repath_on_kill` `:64-67`; transients in
  `on_added` `:69-81`. **The block test `:115-155`** reads `wp = wps[mv.index]` →
  `tm.get(tc, tr)` → `occ.alive` for the SINGLE next waypoint tile, with
  `is_base` (`:117`) exempting the base occupant. **The wall-edge test
  `_wall_edge_ahead` `:185-201`** checks ONE edge via `get_wall_between(prev_wp,
  next_wp)`, gated `index >= 1`. `_repath` `:157-170` re-derives
  `goal_is_base = path[-1] == (tm.base_col, tm.base_row)`.
- `game/enemies/combat.py`: `_enemy_tile` `:231-234` (`round(wx), round(wy)`),
  `_chebyshev` `:236-239`, `_euclid_sq` `:241-244`, `_predict_lead` `:253-273`,
  `ProjectileArc._impact` splash test `:158-165`, and the two `in_range` sites
  `:324` (`_update_defender`) and `:361` (`_update_beam`).
- `game/enemies/spawner.py`: `self._rng.choice(spawn_tiles)` at **seven** sites —
  `:113` (standard), `:154`/`:155`/`:157`/`:159` (boss round), `:171` (raiders),
  `:181` (siege). `spawn_tiles = tilemap.spawning_tiles()` (`:89`) is a **list of
  `Tile` objects** (each with `.col`/`.row`/`.state`), not coords.
- `game/map/tile_map.py`: `get(col,row)` `:209-212` returns `None` out of bounds;
  `weight(tile)` `:203-205`; `impassable_weight` `:199-201` = `999`;
  `get_wall_between(c1,r1,c2,r2)` `:548`; `_bump_path_version` `:214-218`.
  `data/balancing/map.json Pathfinding.content_weights`: `base_building: 0`,
  `buildable_tile: 1`, `combat_tile: 1`, `spawning_tile: 1`, `defence_building: 2`,
  `impassable: 999`. **A BACKGROUND tile is impassable; the base tile is not.**
- `engine/core/movement.py:23-26`: `Movement.update` **early-returns on empty
  waypoints** and never sets `arrived`. So a unit that gets `[]` from the
  pathfinder stands still forever — it can NOT fire a phantom base hit. This is
  the safe failure mode for an unpathable footprint (§1.5).
- `engine/physics/occupancy.py` — `TileOccupancy` is one-occupant-per-tile and is
  what BUILDING PLACEMENT relies on. **D5: enemies must never enter it.** ER-2
  does not import it, read it or write it.
- **`tools/tests/test_flow_field.py:113-121`** monkeypatches
  `pathfinder._build_flow_field` with a stub of arity **2** (`def counted(tm,
  ignore_walls)`). Adding a third positional argument to `_build_flow_field`
  breaks it. See §4 — you must widen that stub.

Requirement IDs in play: **G-3** (capability, never class), **G-7** (every tunable
from `data/balancing/`), **E-11** (all state in components), **E-12/E-30**
(Movement), plus the `game/PERF.md` flow-field invariant.

---

## 1. Behavioral spec

### 1.1 THE convention: anchor = the block's MIN corner (binding)

⚠ **ADDITION 1 — the plan doc never states where the N×N block sits relative to
the anchor tile. It is fixed here, and every consumer must use this one
definition.**

> A unit of footprint **N** whose tile is **(c, r)** occupies the block
> **`{(c+i, r+j) | 0 ≤ i < N, 0 ≤ j < N}`**.
> The unit's tile — its `Transform.world_pos`, every `Movement` waypoint, every
> path element, its spawn tile — is always the block's **minimum-column,
> minimum-row corner**. The block extends **right and down** from it.

Why min-corner and not centre:

1. **An even N has no centre tile.** Footprint 2 is the whole point of this phase
   (ER-4's `Formation`); its centre falls on a tile *corner*. A centre-anchored
   convention is undefinable for even N without a half-tile transform, which would
   put non-integer tile coords into `find_path`, `Movement.waypoints`,
   `TileMap.get` and the spawner. Min-corner keeps every coordinate an integer.
2. **It is already the repo's 2×2 convention, everywhere.** `TileMap._find_2x2`
   anchors 2×2 blocks at the min corner (`anchor_c_max = self.cols - 2`,
   `tile_map.py:388-389`); the editor's `start_area` marker **is** section (0,0) at
   its min corner (`game/map/CLAUDE.md`); unlock chunks anchor min-corner. A second,
   contradictory convention in the same package would be a bug factory.
3. **N = 1 collapses to identity**: the block is `{(c, r)}` — the tile itself. Every
   predicate below degenerates to today's expression, which is what makes the
   byte-identity invariant (§1.4) provable rather than hoped for.

**Consequence to accept, not fix (report it, do not touch the renderer):** ER-1
draws the sprite centred on the *anchor tile's* diamond centre, scaled to
`N * tile_w` wide. For N = 2 the logical block extends half a tile down-right of
where the sprite's centre lands. That is a **cosmetic** half-tile offset, fixable
only in the render layer (`engine/render/renderer.py` / the `SpriteAnimator`
construction), both of which are **ER-1-owned and outside ER-2's scope**. Do not
attempt it here. Flag it in the PR for ER-4/ER-5.

**Block centre (combat only, §1.3):** `(c + (N−1)/2, r + (N−1)/2)`. For N = 1 that
is exactly `(c, r)`.

### 1.2 Passability for a size-N unit (binding, exhaustive)

A size-N unit may stand at anchor `(c, r)` **iff all three hold**:

1. **In bounds** — `tilemap.get(c+i, r+j) is not None` for every `0 ≤ i,j < N`.
2. **All passable** — every one of those N² tiles has
   `tilemap.weight(tile) < tilemap.impassable_weight`.
3. **No wall inside the body** — unless `ignore_walls`, no live wall edge
   (`get_wall_between(...) is not None and .hp > 0`) sits on any **internal edge**
   of the block: any pair of 4-adjacent tiles both inside the block. (N = 1 has
   none.)

**Moving** from anchor `A = (c, r)` to a 4-adjacent anchor `B = (c+dc, r+dr)`
additionally requires no live wall on any **face edge** — the N edges the body
sweeps across:

| step | face edges (`k` = 0 … N−1) |
|---|---|
| `dc = +1` | `(c+N−1, r+k) — (c+N, r+k)` |
| `dc = −1` | `(c, r+k) — (c−1, r+k)` |
| `dr = +1` | `(c+k, r+N−1) — (c+k, r+N)` |
| `dr = −1` | `(c+k, r) — (c+k, r−1)` |

For N = 1 the face is the single edge `(c,r)—(c+dc,r+dr)` — **exactly today's
`_wall_blocks(tilemap, col, row, nc, nr)` argument list**. Wall keys are
order-independent (`tile_map._wall_key`), so the face-edge set is symmetric in
A/B — **one helper serves both the forward `_dijkstra` and the reverse
`_build_flow_field`**, which is what keeps their edge rules byte-identical (the
`game/PERF.md` equivalence proof depends on that).

*Why internal edges too:* a wall running through the middle of a 2×2 body would
otherwise let a formation straddle it. The union {face edges of the step} ∪
{internal edges of the destination block} is exactly the set of wall edges a size-N
body crosses or straddles when it steps A→B. (The source block's internal edges
were already checked when that anchor was accepted.)

**Cost of entering a block** = `max(weight(t) for t in block)` — the body is slowed
by the worst terrain under it, so a 2×2 avoids a pond even if only one of its four
tiles is the pond. For N = 1 this is exactly `tilemap.weight(tilemap.get(c,r))`.

### 1.3 Goal semantics: a size-N unit reaches a goal when its BLOCK COVERS it

⚠ **ADDITION 2 — the plan doc is silent on goals. This is load-bearing: get it
wrong and a 2×2 can never reach the hole.**

The base tile is BUILT and occupied. Under a naive "anchor must equal the goal
tile" rule, a footprint-2 unit could only ever reach the base if the 2×2 block
*anchored at the base* were entirely clear — a property no map guarantees, and if
it fails, **every** 2×2 gets `[]` from `find_path` and stands still for the whole
round. That is a silent, total failure of ER-4.

The physically correct rule is also the robust one:

> A size-N unit **has reached goal tile `g`** when `g` lies **inside its block**:
> `g ∈ block(anchor, N)`. Equivalently, the goal anchor set for a logical goal
> `(gc, gr)` is `{(gc−i, gr−j) | 0 ≤ i,j < N}`.

A 2×2 body standing next to the hole is *on* the hole. For N = 1 the expanded set
is `{(gc, gr)}` — **identical to today**. This applies uniformly to:

- the base flow field (multi-source reverse Dijkstra: seed **every** base-covering
  anchor at distance 0; for N = 1 that is the single base tile → byte-identical),
- `_dijkstra`'s goal set (expand the caller's `goals` before the search),
- `PathAgent._repath`'s `goal_is_base` re-derivation (the final anchor's block
  covers the base, rather than equalling it — N = 1 identical).

Only anchors whose block is passable can ever be *popped* (they can only be
relaxed through §1.2), so a covering anchor that the unit cannot legally occupy is
never returned. The sole exception is a start that is already a goal anchor — which
mirrors today's `find_path(tm, base_col, base_row) == [(base)]`.

### 1.4 Combat measures from the footprint CENTRE

Plan ER-2, `game/enemies/combat.py` bullet: *"Chebyshev range and target
acquisition measure from the footprint's centre, not its anchor corner, so a 2×2 is
not engaged from an unfair corner."*

- **Chebyshev range** (`_chebyshev`, feeding `:324` and `:361`): distance from the
  defender's tile to the enemy's **block centre** `(round(wx) + (N−1)/2,
  round(wy) + (N−1)/2)`. The `round()` of the anchor is **kept** — dropping it would
  change the in-range set for existing 1×1 enemies mid-tile and is NOT allowed.
  At N = 1 the offset is `0.0` and the value is numerically identical to today's
  `max(|ec−cx|, |er−cy|)` (an int-valued float; both call sites only compare it
  with `<= rng`).
- **Target acquisition** (`_euclid_sq`, `:330`): measure to the enemy's centre in
  **world** coords (`wx + off, wy + off`, un-rounded — as today). N = 1 → `off = 0`
  → byte-identical.
- **AOE splash + lead** (`ProjectileArc._impact` `:158-165`, `_predict_lead`
  `:253-273`): both measure/aim at the enemy's world centre. N = 1 → `off = 0` →
  byte-identical. (Leaving `_predict_lead` on the anchor while the splash test uses
  the centre would bias every mortar shell half a tile off a formation — do both or
  neither. Do both.)

`RangeSensor`/`engine.physics.grid.query_chebyshev` are **not** in scope: nothing in
the enemy path reads them for targeting (the sweep does its own Chebyshev), and
they are engine files.

### 1.5 Spawning

A footprint-N enemy spawns only on a tile whose whole N×N block is **in the spawn
zone** (every block tile is itself a SPAWNING tile, which also makes it in-bounds
and passable — `spawning_tile` weight is 1). If **no** spawn tile qualifies, fall
back to the unfiltered pick: an enemy is never dropped from the wave and the
spawner never raises. `footprint == 1` **must take the byte-identical
`self._rng.choice(spawn_tiles)` path** — same list, same single rng draw, so the
deterministic-composition fixtures in `test_enemies.py` / `test_boss.py` are
untouched. **The clearance filter itself must consume ZERO rng draws.**

### 1.6 Failure modes that must stay safe

- A size-N unit with no legal path gets `[]` → `Movement.waypoints = []` →
  `Movement.update` early-returns (`engine/core/movement.py:23-26`) → `arrived`
  stays False → `PathAgent` never sets `reached_base`. It stands still. **No
  phantom base hit.** Pin this with a test (§4).
- **No `TileOccupancy` writes anywhere in this diff (D5).** Enemies do not block
  each other; two footprint-2 units may overlap. That is intended.

---

## 2. Architecture plan

### 2.1 `game/map/pathfinder.py` — the one definition of the convention

Add **five public helpers** (public, not `_`-prefixed: `components.py` and
`spawner.py` import them — one source of truth for §1.1/§1.2, no re-derivation).
Put them directly after `_wall_blocks` (`:59`).

```python
def block_tiles(col, row, footprint=1):
    """The tiles a size-N unit anchored at (col, row) occupies. The anchor is the
    block's MIN corner: the block extends right and down (ER-2 §1.1). N=1 -> just
    the anchor tile."""
    return [(col + i, row + j)
            for j in range(footprint) for i in range(footprint)]


def block_covers(col, row, footprint, tc, tr):
    """True if tile (tc, tr) lies inside the block anchored at (col, row)."""
    return (col <= tc < col + footprint) and (row <= tr < row + footprint)


def internal_edges(col, row, footprint=1):
    """Every edge BETWEEN two tiles of the block (N=1 -> none). A live wall on one
    of these runs through the unit's body, so it may not stand here."""
    edges = []
    for j in range(footprint):
        for i in range(footprint):
            if i + 1 < footprint:
                edges.append((col + i, row + j, col + i + 1, row + j))
            if j + 1 < footprint:
                edges.append((col + i, row + j, col + i, row + j + 1))
    return edges


def face_edges(col, row, ncol, nrow, footprint=1):
    """The edges a size-N body sweeps stepping from anchor (col,row) to the
    4-adjacent anchor (ncol,nrow) — the whole leading face, not one edge (ER-2
    §1.2). Symmetric in the two anchors (wall keys are order-independent), so the
    forward Dijkstra and the reverse flow field share it. N=1 -> exactly the single
    edge (col,row)-(ncol,nrow), i.e. today's ``_wall_blocks`` arguments."""
    dc, dr = ncol - col, nrow - row
    if abs(dc) + abs(dr) != 1:          # defensive: only cardinal steps exist
        return [(col, row, ncol, nrow)]
    out = []
    for k in range(footprint):
        if dc == 1:
            out.append((col + footprint - 1, row + k, col + footprint, row + k))
        elif dc == -1:
            out.append((col, row + k, col - 1, row + k))
        elif dr == 1:
            out.append((col + k, row + footprint - 1, col + k, row + footprint))
        else:
            out.append((col + k, row, col + k, row - 1))
    return out


def block_passable(tilemap, col, row, footprint=1, ignore_walls=False):
    """ER-2 §1.2: every tile of the block is in bounds and under the impassable
    threshold, and (unless ignore_walls) no live wall sits on an internal edge.
    N=1 collapses to today's ``tile is not None and weight(tile) < impassable``."""
    impassable = tilemap.impassable_weight
    for c, r in block_tiles(col, row, footprint):
        tile = tilemap.get(c, r)
        if tile is None or tilemap.weight(tile) >= impassable:
            return False
    if not ignore_walls and footprint > 1:
        for e in internal_edges(col, row, footprint):
            if _wall_blocks(tilemap, *e):
                return False
    return True


def block_weight(tilemap, col, row, footprint=1):
    """Cost of ENTERING the block: the worst tile under the body. N=1 -> exactly
    ``tilemap.weight(tilemap.get(col, row))``."""
    return max(tilemap.weight(tilemap.get(c, r))
               for c, r in block_tiles(col, row, footprint))


def _face_blocked(tilemap, col, row, ncol, nrow, footprint=1):
    return any(_wall_blocks(tilemap, *e)
               for e in face_edges(col, row, ncol, nrow, footprint))
```

**Threaded signatures** — every one gains a trailing `footprint=1`:

```python
def _dijkstra(tilemap, start_col, start_row, goals, ignore_walls, footprint=1)
def _build_flow_field(tilemap, ignore_walls, footprint=1)
def _ensure_flow_field(tilemap, ignore_walls, footprint=1)
def _field_path(tilemap, start_col, start_row, ignore_walls, footprint=1)
def find_path(tilemap, start_col, start_row, footprint=1)
def find_path_ignoring_walls(tilemap, start_col, start_row, footprint=1)
def _find_path_to_goals(tilemap, start_col, start_row, goals, footprint=1)
def find_path_to_nearest_economic(tilemap, start_col, start_row, footprint=1)
def find_path_to_nearest_defence(tilemap, start_col, start_row, footprint=1)
def find_path_to_nearest_building(tilemap, start_col, start_row, footprint=1)
```

**`_dijkstra` (`:76-109`)** — three edits, no reordering of the skip conditions
(they are pure predicates):

- expand the goal set once at the top (§1.3):
  `goals = {(gc - i, gr - j) for gc, gr in goals
            for i in range(footprint) for j in range(footprint)}`
  (N=1 → the same set.)
- the neighbour gate `:95-102` becomes:
  ```python
  if not ignore_walls and _face_blocked(tilemap, col, row, nc, nr, footprint):
      continue
  if not block_passable(tilemap, nc, nr, footprint, ignore_walls):
      continue
  nd = cost + block_weight(tilemap, nc, nr, footprint)
  ```
  (`block_passable` subsumes the old `tile is None` and `w >= impassable` skips.)
- nothing else. `_reconstruct` is unchanged — paths are sequences of **anchors**.

**`_build_flow_field` (`:112-157`)** — multi-source seed + block rules:

```python
seeds = [(tilemap.base_col - i, tilemap.base_row - j)
         for i in range(footprint) for j in range(footprint)]   # N=1 -> [base]
heap = [(0, c, r) for c, r in seeds]
heapq.heapify(heap)
...
while heap:
    cost, col, row = heapq.heappop(heap)
    if (col, row) in dist:
        continue
    dist[(col, row)] = cost
    if not block_passable(tilemap, col, row, footprint, ignore_walls):
        continue                 # a start-only leaf: no forward edge may enter it
    w = block_weight(tilemap, col, row, footprint)
    for nc, nr in _neighbors(col, row, tilemap):
        if (nc, nr) in dist:
            continue
        if not ignore_walls and _face_blocked(tilemap, col, row, nc, nr, footprint):
            continue
        nd = cost + w
        ...
```

`_neighbors` (`:43-48`) stays as-is — it enumerates candidate **anchors**, and an
anchor whose block hangs off the map is rejected by `block_passable`, not by the
neighbour bound. Do NOT tighten `_neighbors` to `cols - footprint`; that would
change nothing and would break its N=1 identity.

The reverse-edge equivalence proof in the module docstring still holds verbatim
with "tile" → "block": relaxing neighbour `v` from a settled `u` costs
`block_weight(u)`, the block a forward walker *enters* stepping v→u; face edges are
symmetric. **Update the docstring** (`:1-23`) to say so.

**`_ensure_flow_field` (`:160-178`)** — D6, the whole change is the key:

```python
key = (ignore_walls, footprint)
if key not in fields:
    fields[key] = _build_flow_field(tilemap, ignore_walls, footprint)
return fields[key]
```

The `(version, {})` cache-on-the-tilemap structure and the `getattr(tilemap,
"_path_version", 0)` guard are unchanged. Keep `_build_flow_field` as a **module-level
global lookup** inside `_ensure_flow_field` (do not inline / do not bind it into a
local) — `test_flow_field.TestCacheReuse` monkeypatches that module attribute, and
the new rebuild-count test does the same.

**PERF invariant (`game/PERF.md`) restated for the reviewer:** one Dijkstra per
topology change **per (ignore_walls, footprint) pair**, never one per enemy. With
footprints 1 and 2 that is at most 4 cached fields per `_path_version`. Nothing in
this diff may add a per-enemy Dijkstra.

### 2.2 `game/enemies/components.py` — `PathAgent` only (`:43-207`)

**New declared field** beside `:64-67` (JSON-safe int, E-11):

```python
footprint: int = 1    # ER-2: the unit occupies footprint x footprint tiles
```

**Block test (`:115-155`)** — widen the single-tile scan to the destination block.
The next waypoint `(tc, tr)` is the next **anchor**; the tiles the body will occupy
are `block_tiles(tc, tr, self.footprint)`:

```python
wp = wps[mv.index]
tc, tr = round(wp[0]), round(wp[1])
wall_edge = self._wall_edge_ahead(tm, wps, mv.index, tc, tr)   # see below
if wall_edge is not None:
    ...unchanged...
self._wall_target = None
occ = self._blocker_ahead(tm, tc, tr)
now_blocked = occ is not None
if now_blocked:
    self._target = occ
    ...unchanged...
```

with

```python
def _blocker_ahead(self, tm, tc, tr):
    """The first live, non-base building standing anywhere in the destination
    block (ER-2). Scan order is row-major and deterministic. footprint=1 ->
    exactly today's single-tile ``tm.get(tc, tr)`` test."""
    for c, r in block_tiles(tc, tr, self.footprint):
        if c == tm.base_col and r == tm.base_row:
            continue                       # the base is never a blocker (:117)
        tile = tm.get(c, r)
        occ = tile.occupant if tile is not None else None
        if occ is not None and getattr(occ, "alive", False):
            return occ
    return None
```

Note the `is_base` exemption becomes **per tile of the block**, not per waypoint —
a footprint-2 unit whose block covers the base must attack the *other* occupant in
its block, never the BaseBuilding.

**Wall test — `_wall_edge_ahead` (`:185-201`)** becomes footprint-aware. Keep it a
`@staticmethod`? No — it needs `self.footprint`; make it a normal method (its only
caller is `:123`). Keep the `index >= 1` gate and the `get_wall_between`
`getattr` guard verbatim (headless stubs).

```python
def _wall_edge_ahead(self, tm, wps, index, tc, tr):
    """The (c1,r1,c2,r2) of the first live wall the body would cross or straddle
    stepping to the next anchor: the FACE edges first (they sit in front), then the
    destination block's INTERNAL edges. footprint=1 -> exactly today's single
    prev->next edge. Meaningful only once the enemy has left the first waypoint
    (index >= 1); guarded so a tilemap stub without get_wall_between never trips."""
    if index < 1:
        return None
    if getattr(tm, "get_wall_between", None) is None:
        return None
    pw = wps[index - 1]
    pc, pr = round(pw[0]), round(pw[1])
    n = self.footprint
    for e in face_edges(pc, pr, tc, tr, n) + internal_edges(tc, tr, n):
        if _wall_blocks(tm, *e):
            return e
    return None
```

Returning the **first** live wall (face edges in order, then internals) makes a
2×2 chew through the wall segments of a face one at a time: `EnemyCombat` drains
`_wall_target` (`:247-259`, unchanged); when that edge dies, the next frame's scan
returns the next one. `_wall_blocks` is imported from `game.map.pathfinder` (which
`components.py` already imports from, `:22`).

**`_repath` (`:157-170`)** — thread the footprint and use §1.3's cover rule:

```python
path = find_path_to_nearest_building(tm, col, row, footprint=self.footprint)
...
self.goal_is_base = block_covers(path[-1][0], path[-1][1], self.footprint,
                                 tm.base_col, tm.base_row)
```
(N=1 → `path[-1] == (base_col, base_row)` — identical.)

**Do not touch `BossState` (`:273-279`) or `EnemyCombat` (`:210-270`)** — ER-3
owns `BossState` → `DeathSpawn`.

### 2.3 `game/enemies/enemy.py` — exactly TWO hunks

⚠ **ADDITION 3 — ER-2 needs a second hunk in `enemy.py` that the dispatch note did
not allocate.** Without it the footprint never reaches `find_path` at spawn time
and the phase is untestable in-game (unit-test-only), and ER-4's `Formation`
(which inherits `Enemy.on_spawn`) would path as a 1×1. The hunk is 3 lines inside
`Enemy.on_spawn` — **7 lines above** ER-3's `alive` (`:150-152`) and 45 above the
`Boss` class body, so the merge stays clean.

1. **`:104`** — the `PathAgent()` construction line, inside the component list. The
   `block` local ER-1 added at `:99-101` is already in scope:
   ```python
   PathAgent(footprint=int(block["footprint"])),
   ```
   Direct index, no `.get()` default (schema-required key; a code-side default
   would reintroduce the py+json dual store the root `CLAUDE.md` forbids).
2. **`:137-145`, `Enemy.on_spawn`** — the two path calls only:
   ```python
   fp = self.get_component(PathAgent).footprint
   path = find_path(self._tilemap, self._col, self._row, footprint=fp)
   if not path:
       path = find_path_ignoring_walls(self._tilemap, self._col, self._row,
                                       footprint=fp)
   ```
   Read the footprint back off the component — do **not** stash a
   `self._footprint` attribute (E-11: state lives in components).

**Do NOT touch** `Boss.on_spawn` (`:222-237`) — it is inside the `Boss` class body,
which ER-3 owns, and it needs no change: the Boss is `footprint: 1`, so its
`find_path_to_nearest_building(...)` and its `path[-1] == (base_col, base_row)`
are already correct under the N=1 identity. Nothing else in `enemy.py`.

### 2.4 `game/enemies/combat.py` (ER-2 owns outright)

`PathAgent` is already imported (`:35`); no new imports are needed.

```python
def _enemy_footprint(enemy):
    """The enemy's footprint, guard-safe for the bare-bones stub enemies the
    combat tests build (no PathAgent -> 1)."""
    get = getattr(enemy, "get_component", None)
    pa = get(PathAgent) if get is not None else None
    return getattr(pa, "footprint", 1) or 1


def _fp_offset(enemy):
    """(N-1)/2 — the anchor->block-centre offset on each axis. N=1 -> 0.0."""
    return (_enemy_footprint(enemy) - 1) / 2.0


def _enemy_tile(enemy):                    # UNCHANGED (:231-234) — the ANCHOR
    wx, wy = enemy.transform.world_pos
    return (round(wx), round(wy))


def _enemy_center_world(enemy):
    """The block centre in world coords (un-rounded). N=1 -> world_pos."""
    wx, wy = enemy.transform.world_pos
    off = _fp_offset(enemy)
    return (wx + off, wy + off)


def _chebyshev(center_tile, enemy):
    """Defender tile -> enemy FOOTPRINT CENTRE (ER-2), so a 2x2 is not engaged
    from an unfair corner. N=1: the anchor IS the centre and the value is
    numerically identical to today's int Chebyshev."""
    ec, er = _enemy_tile(enemy)
    off = _fp_offset(enemy)
    return max(abs(ec + off - center_tile[0]), abs(er + off - center_tile[1]))
```

- `_euclid_sq(a, b)` (`:241-244`) → replace with `_euclid_sq_to_enemy(defender,
  enemy)` using `_enemy_center_world(enemy)` for the enemy side and
  `defender.transform.world_pos` for the defender. Update the one call site
  (`:330`). N = 1 → identical.
- `ProjectileArc._impact` (`:158-165`): the splash radius test uses
  `_enemy_center_world(enemy)` instead of `enemy.transform.world_pos`.
- `_predict_lead` (`:253-273`): start from `_enemy_center_world(target)` and shift
  the read waypoint by the same `off`, so the aim point is the predicted **centre**
  (consistent with the splash test above). N = 1 → `off = 0` → byte-identical.
- **Nothing else.** `_update_beam`'s highest-HP pick, the cooldown/ramp model, the
  base-arrival handoff and the death sweep are untouched.

### 2.5 `game/enemies/spawner.py` — ONE spawn-tile choke point

Refactor **all seven** `self._rng.choice(spawn_tiles)` sites (`:113`, `:154`,
`:155`, `:157`, `:159`, `:171`, `:181`) into a single helper. ER-4 adds a new
composition branch to these same functions — one choke point makes that merge
clean.

```python
from .enemy import ENEMY_CLASSES, create_enemy       # ENEMY_CLASSES is new here


def _footprint_of(balance, etype):
    """The etype's footprint from balancing (G-7), resolved through the class's
    STAT_SUBTREE — so ER-4's Formation needs no change here."""
    block = balance["EnemyTypes"]
    for seg in ENEMY_CLASSES[etype].STAT_SUBTREE:
        block = block[seg]
    return block["footprint"]
```

On `Spawner`:

```python
def _pick_spawn_tile(self, spawn_tiles, etype):
    """THE one spawn-tile pick. A footprint-N enemy needs its whole NxN block
    inside the spawn zone (ER-2 §1.5). footprint 1 takes the byte-identical
    unfiltered choice — same list, same single rng draw, so the deterministic
    composition fixtures are untouched. The filter consumes NO rng."""
    fp = _footprint_of(self._balance, etype)
    if fp <= 1:
        return self._rng.choice(spawn_tiles)
    clear = self._clear_spawn_tiles(spawn_tiles, fp)
    return self._rng.choice(clear or spawn_tiles)   # never drop an enemy

def _clear_spawn_tiles(self, spawn_tiles, footprint):
    """Spawn tiles whose whole NxN block is itself spawn zone. Computed ONCE per
    round per footprint (a spawn band can be thousands of tiles on a 1024^2 map)."""
    hit = self._clear_cache.get(footprint)
    if hit is None:
        zone = {(t.col, t.row) for t in spawn_tiles}
        hit = [t for t in spawn_tiles
               if all(b in zone
                      for b in block_tiles(t.col, t.row, footprint))]
        self._clear_cache[footprint] = hit
    return hit
```

`self._clear_cache = {}` in `__init__` and **reset at the top of `begin_round`**
(the spawn zone recedes between rounds). `block_tiles` imports from
`game.map.pathfinder` (`game/enemies` already imports `game/map`; it must keep
importing nothing from `game/core`). Membership in the spawn-tile set implies
in-bounds and passable (`spawning_tile` weight 1), so no extra bounds check.

Then every `(self._rng.choice(spawn_tiles), "<etype>")` becomes
`(self._pick_spawn_tile(spawn_tiles, "<etype>"), "<etype>")`.

**Do NOT touch `spawn_death_swarm` (`:235-251`)** — ER-3 owns it. It spawns at the
dead boss's tile and picks no spawn tile, so it needs nothing from ER-2.

---

## 3. File scope + shared-file contract

**ER-2 and ER-3 run CONCURRENTLY off the umbrella. Region ownership is BINDING.**

### Files ER-2 owns outright

| File | Change |
|---|---|
| `game/map/pathfinder.py` | module docstring `:1-23`; the five new public helpers + `_face_blocked` (after `:59`); `_dijkstra` `:76-109`; `_build_flow_field` `:112-157`; `_ensure_flow_field` `:160-178`; `_field_path` `:181-192`; `find_path` `:195-205`; `find_path_ignoring_walls` `:208-215`; `_find_path_to_goals` `:228-236`; the three `find_path_to_nearest_*` `:239-263` |
| `game/enemies/combat.py` | `_enemy_tile`/`_chebyshev`/`_euclid_sq` `:231-244` + the new footprint helpers; `_update_defender`'s acquisition `:330`; `ProjectileArc._impact` `:158-165`; `_predict_lead` `:253-273` |
| `tools/tests/test_footprint_path.py` | **new** |
| `tools/tests/test_flow_field.py`, `tools/tests/test_pathfinder.py` | ER-2-owned; see §4 (the `_counting` stub arity **must** be widened) |
| `game/map/CLAUDE.md`, `game/enemies/CLAUDE.md` | docs (§4) |

### Shared files — ER-2's regions ONLY

| File | ER-2 owns | Owned by others — DO NOT TOUCH |
|---|---|---|
| `game/enemies/components.py` | **`PathAgent` only (`:43-207`)**: the `footprint` field (`:64-67`), the block test (`:115-155`) + new `_blocker_ahead`, `_wall_edge_ahead` (`:185-201`), `_repath` (`:157-170`), the import line `:22` | **ER-3**: `BossState` (`:273-279`) → `DeathSpawn`. Also leave `EnemyCombat` (`:210-270`) alone. ~70 lines and a class boundary apart. |
| `game/enemies/enemy.py` | **exactly two hunks**: `PathAgent(...)` at **`:104`**, and the two path calls inside `Enemy.on_spawn` at **`:139-142`** (see §2.3) | **ER-3**: `alive` (`:150-152`) and the **whole `Boss` class body** (`:186-256`, incl. `Boss.on_spawn`). **ER-4**: the `Formation` subclass + `ENEMY_CLASSES` (`:259-266`). |
| `game/enemies/spawner.py` | the seven `rng.choice(spawn_tiles)` sites (`:113`, `:154-159`, `:171`, `:181`), the new `_pick_spawn_tile`/`_clear_spawn_tiles`/`_footprint_of` helpers, `__init__`'s `_clear_cache`, `begin_round`'s cache reset, the import line `:21` | **ER-3**: `spawn_death_swarm` (`:235-251`), the last function in the file. |

### Files ER-2 must NOT touch (hard boundary)

`game/core/session.py` · `data/balancing/enemies.json` ·
`data/schemas/enemies.schema.json` · `tools/tests/balancing_parity_map.json` ·
`data/slots.json` · `engine/**` (especially `engine/physics/occupancy.py` — **D5**) ·
`editor/**` · `game/ui/**` · `game/main.py` · `game/map/tile_map.py` ·
`game/buildings/**` · `tools/tests/test_enemies.py` · `tools/tests/test_boss.py`
(ER-3/ER-4 own those two; ER-2 must keep them green **without editing them**).

**No schema and no balancing edits at all.** `footprint` already exists and is
already required (ER-1). If you find yourself opening `enemies.json`, stop.

---

## 4. Exit gate + Quick Test

### Gate (both commands, from the repo root)

```
py tools/smoke.py
py -m unittest discover -s tools/tests -t .
```

**ZERO NEW failures** against the umbrella baseline. Compare failure **names**, not
counts.

Umbrella baseline: **908 tests, 18 failures, 1 skip** —
- 6 × `test_balancing_parity`,
- 10 × editor/Qt-environment,
- `test_details_panel::test_too_small_sheet_rejected` (ER-1 legitimately replaces
  this one),
- `test_combat_speed::test_2x_spawns_the_wave_faster_than_1x` (timing-flaky; re-run
  before you call it a regression).

> ⚠ **Worktree caveat.** `test_balancing_parity` **SKIPS** inside a git worktree —
> it derives the prototype path from the repo's *parent* directory, which a worktree
> does not have. If you are working in a worktree you will see **12 failures, 7
> skips**, not 18/1. That is the same baseline, not an improvement. Do not "fix"
> the missing 6.

Data did not change → the smoke test's schema validation is a pass-through, but run
it anyway (it also boots the game headless, which is what catches a broken spawner).

### Tests to write (named, not optional)

**`tools/tests/test_footprint_path.py`** — NEW. Reuse `test_flow_field.py`'s
`synth(terrain_rows, base=...)` helper shape (a `TileMapDoc` from raw legend rows +
`TileMap(doc, BALANCE)`; `rng=None` keeps every tile GRASS, which is what makes
exact costs assertable).

1. **The headline: a 2×2 refuses a gap a 1×1 takes.** A wall of BACKGROUND (`f`)
   with a single one-tile hole between the spawn side and the base side.
   `find_path(tm, s, footprint=1)` is non-empty and threads the hole;
   `find_path(tm, s, footprint=2)` is `[]` (fully sealed variant) **or** routes
   around it (open a two-tile gap elsewhere and assert the 2×2 takes *that* one and
   never anchors where its block would overlap the `f` wall — assert every anchor in
   the returned path satisfies `block_passable(tm, c, r, 2, False)`).
2. **`footprint=1` is byte-identical.** For a mixed-weight map (reuse
   `TestForwardEquivalence.ROWS` — mountain/pond/forest + a live wall edge), assert
   `find_path(tm, c, r) == find_path(tm, c, r, footprint=1)` and that both equal a
   direct `_dijkstra(..., {base}, ignore_walls=False)` in cost, endpoints and
   contiguity. Same for `find_path_ignoring_walls` and each
   `find_path_to_nearest_*`.
3. **D6 cache: one build per `_path_version` bump PER footprint.** Monkeypatch
   `pathfinder._build_flow_field` with a **3-arg** counting stub recording
   `(ignore_walls, footprint)`. Query many starts at footprint 1 and 2 → exactly
   **2** builds. Bump the version (`tm.set_tile_state(...)`) → query both again →
   exactly **2** more. Never one per query, never one per enemy. Assert the cache
   dict is keyed on `(ignore_walls, footprint)`.
4. **Walls vs a block.** (a) A live wall on an edge *inside* a 2×2's candidate
   block makes that anchor unusable (`block_passable(...) is False`) while both its
   tiles remain individually passable. (b) A wall on one edge of a two-edge face
   blocks the 2×2's step across that face (the pathfinder routes around) while a
   1×1 crossing the *other* edge of that face is unaffected. (c) `ignore_walls=True`
   ignores both internal and face walls.
5. **The safe failure mode.** A footprint-2 unit with no legal path gets `[]` from
   both `find_path` and `find_path_ignoring_walls`; drive a `PathAgent` +
   `Movement` through a few `update(dt)` calls with empty waypoints and assert
   `reached_base` stays **False** (no phantom base hit).
6. **The block-cover goal rule (§1.3).** A 2×2 whose block cannot be anchored *on*
   the base still reaches it: assert the returned path's last anchor satisfies
   `block_covers(anchor, 2, base_col, base_row)`, and that at footprint 1 the last
   anchor **equals** the base tile.
7. **PathAgent block test.** A building in the *second* column of a 2×2's
   destination block blocks it (`pa.blocked` True, `pa._target` is that building)
   where the same building leaves a 1×1 on the same waypoint unblocked.
8. **Spawner clearance.** With an injected deterministic `rng` and a spawn band
   only 1 tile thick, a footprint-2 etype falls back to the unfiltered pick (does
   not crash, does not drop the enemy); with a 2-thick band it only ever picks
   anchors whose 2×2 block is entirely spawn zone. And: at footprint 1 the queue
   composed under a seeded `rng` is **identical** to the pre-ER-2 composition (pin
   the rng draw count).
9. **Real-map sanity (do not skip this one — it is what protects ER-4).** Load the
   shipped active map (`engine.tilemap.load_active_map(REPO / "data")`) + real
   balancing, build a `TileMap`, and assert a **footprint-2** unit spawned on a
   real spawn tile gets a **non-empty** path to the base. If this fails, the
   shipped map cannot support 2×2 units at all — **stop and report it**, do not
   paper over it.

**Existing tests that must stay green:**
- `tools/tests/test_flow_field.py` — **one required edit**: `TestCacheReuse._counting`
  (`:113-121`) stubs `_build_flow_field` with arity 2. `_ensure_flow_field` now calls
  it with three positional args → `TypeError`. Widen the stub to
  `def counted(tm, ignore_walls, footprint=1)`. The assertion (`len(calls) == 1`) is
  unchanged and still meaningful. **This is the one test edit ER-2 is authorised to
  make in an existing file** — nothing else in that file may change.
- `tools/tests/test_pathfinder.py` — ⚠ **the plan doc omits this from ER-2's
  regression list. It is added here.** All 5 `find_path*` variants + exact costs run
  through the code you are changing. It must pass **unmodified**.
- `tools/tests/test_enemies.py`, `tools/tests/test_boss.py`,
  `tools/tests/test_tile_conditions.py`, `tools/tests/test_structure.py`,
  `tools/tests/test_buildings_placement.py`, `tools/tests/test_combat*.py` — must pass
  **unmodified**. (`test_enemies`/`test_boss` are ER-3/ER-4 territory: keeping them
  green without touching them is the proof of the N=1 identity.)

### Quick Test (verbatim from `planning/EnemyReworkPLAN.md` ER-2)

> Build a line of buildings with a single one-tile gap. A walker threads the gap; a
> 2×2 unit does not — it stops and attacks a blocking building instead.

**Practical note:** no shipped enemy type has `footprint: 2` until ER-4, so a live
in-game Quick Test of the 2×2 half needs a temporary local edit
(`data/balancing/enemies.json` → `EnemyTypes.SiegeCannon.footprint: 2`, play a
round, then **revert it — it must not appear in the diff**). Say in the PR exactly
what you verified: smoke test / full unittest run / live `py game/main.py` with the
temporary footprint bump / static read only.

### Docs to update (package docs only — not the root router)

- **`game/map/CLAUDE.md`** — the "Perf invariants that live here" section: the flow
  field is now **footprint-aware**; the cache key is `(ignore_walls, footprint)`;
  the `_path_version` invariant is unchanged and still absolute (**one Dijkstra per
  topology change per footprint, never one per enemy**). Add the ER-2 convention in
  one paragraph: anchor = the block's min corner; passability = whole block in
  bounds, under `impassable`, no wall on an internal edge; a step also clears the
  whole face; the goal is reached when the block **covers** it; footprint 1 is the
  identity case.
- **`game/enemies/CLAUDE.md`** — under Rules: `PathAgent.footprint` (from
  `EnemyTypes.<type>.footprint`, G-7), the block-wide blocker scan, the face+internal
  wall scan, the spawner's clearance filter (with its unfiltered fallback), and the
  combat sweep measuring range/acquisition/splash from the footprint **centre**. State
  D5 explicitly: **footprints never enter `TileOccupancy`; enemies do not block each
  other.** Note the known cosmetic half-tile sprite offset for even footprints
  (§1.1) as an open item for ER-4/ER-5.
</content>
</invoke>
