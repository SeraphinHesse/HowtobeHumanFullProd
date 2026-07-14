# EnemyReworkPLAN.md — enemy sizing, footprints, and breakable formations

> ## ⚠ The parity obligations in this doc are VOID (2026-07-14)
>
> Written while the prototype migration was live. **It is complete.** Every
> instruction below to update `tools/tests/balancing_parity_map.json`, to keep
> `test_balancing_parity` green, or to retag a moved key `DROPPED:` — **skip
> it**: that test, that map, and the whole `migration` tier are deleted. Moving,
> renaming, retuning or dropping a balancing value now needs nothing but a valid
> schema. The rest of the plan (the phases, the engine/game work) stands.

Phased, agent-executable plan (same family as `EngineBuildPLAN.md` /
`MIGRATION_PLAN.md` / `AgentDispatchPLAN.md`). Base branch: `Development`.
Runnable via `/execute-plan-phases planning/EnemyReworkPLAN.md ER-1-ER-5` or
phase-by-phase with `/execute-phase`. Packages touched: **engine + game + editor
+ data** (each phase names its own scope). Requirements vocabulary: SPEC.md
`E-*` / `G-*` / `ED-*` / `D-*`.

## Context

Enemies are visually and mechanically stuck at "one tile, one sprite, dies at
zero HP". Four things are wrong or missing:

1. **Enemies render at the wrong size.** Newly imported enemy art draws far too
   big for the world it stands in.
2. **There is no large "enemy group" unit** — a formation that reads as many
   soldiers moving as one body.
3. **Death-spawning is Boss-only and not toggleable** — a designer cannot say
   "this unit bursts into smaller units" without new code.
4. **Every enemy is one tile.** A boss or a marching column cannot be physically
   bigger than a peasant.

This plan fixes the sizing bug at its root, then builds the three gameplay
features on top of it, in an order where each phase is independently shippable.

### The sizing bug, precisely (why phase ER-1 exists)

Exploration of the live code, not assumption:

- **Render size has no scale concept at all.** `engine/render/renderer.py:81-86`
  is the whole of it: `w = frame.frame_w * zoom`, `h = frame.frame_h * zoom`.
  The sole input is the manifest entry's frame size.
- **Frame-size precedence is manifest entry > registry**
  (`engine/assets/store.py:44-54`), and **both importers write the frame size
  from the *category***: `editor/asset_import.py:26` and
  `editor/panels/details.py:266,288` both call `registry.frame_size(slot_key)`,
  which returns the owning **category's** size. The `enemies` category in
  `data/slots.json` is **64×96**. So anything re-imported through the editor is
  declared 64×96 and draws three tiles tall. **That is the "too big" bug.** The
  migrated prototype enemies escape it only because
  `tools/migrate_prototype_assets.py` preserved their native sizes (walkers
  22×26, raiders 12×18, siege 36×28, bosses 72×56 … 124×96).
- **Sub-frame-size art cannot import at all.** `editor/asset_import.py:29-32`
  computes `cols, rows = w // fw, h // fh` and raises `ValueError` when the image
  is smaller than one frame — a 16×16 PNG against a 64×96 frame yields 0 columns.
- **There is no per-slot frame-size override.** Frame size is a per-category
  property on the category object in `data/slots.json`; no editor widget writes
  it. Changing one enemy's size today means changing *every* enemy's size.
- **The anchor rule has a cliff.** `anchor = tile_h * (2 if frame.frame_h > tile_h
  else 1)` (`renderer.py:86`, `tile_h` = 32): art ≤32px tall anchors one
  tile-height down, art >32px anchors two. A re-import that crosses 32px silently
  teleports the sprite by a whole tile-height.
- **`era_sizes` / `sprite_w` / `sprite_h` in `data/balancing/enemies.json` are
  dead data** — no `.py` file reads them. They are migration parity artefacts and
  are removed in ER-1.

## User decisions (binding)

1. **Footprint-driven auto-fit.** An enemy's on-screen size derives from its tile
   footprint, not from raw sheet pixels — not explicit per-slot render sizes, and
   not an importer-only fix.
2. **Pad and centre, never upscale.** Art smaller than its declared frame is
   padded and centred at import, not rejected and not blown up.
3. **One generalised `death_spawn` mechanic**, toggleable per enemy type, with
   the Boss's existing 10G swarm re-expressed in it rather than kept beside it.
4. **Clearance pathing only** for footprints. A 2×2 enemy needs all four tiles
   passable, but does **not** enter `TileOccupancy` and does **not** block other
   units.

## 1. Architecture decisions

```
  data/slots.json ──────────► per-slot frame_w/frame_h override  (D1)
        │                          (how a sheet is SLICED)
        ▼
  engine/assets/registry ──► SlotRegistry.frame_size()
        │
  data/balancing/enemies.json ─► footprint + sprite_scale        (D2)
        │                          (how big it DRAWS)
        ▼
  game/enemies/enemy.py ──► SpriteAnimator(fit_tiles=, scale=)
        │
        ▼
  engine/render/renderer.py ─► downscale-only width fit + anchor (D2, D3)
```

### Decisions (with rationale)

- **D1 — Slicing and drawing are separate concerns.** The frame size says how to
  cut the sheet; the footprint says how big the thing is in the world. Today they
  are the same number, which is exactly why the bug exists. `data/slots.json` slot
  entries (bare strings today) gain an optional object form carrying `frame_w` /
  `frame_h`; a bare string keeps inheriting the category size, so every existing
  slot is untouched.
  *Why not a manifest-only fix:* the manifest is written **by** the importer from
  the registry — the wrong number originates in the registry, so that is where the
  override belongs.

- **D2 — Render size is a downscale-only width fit against the footprint box.**
  This is where the two binding decisions (1 and 2) meet, and the resolution must
  be explicit:

  ```
  target_w = footprint_tiles * tile_w            # 1 -> 64px, 2 -> 128px
  scale    = min(1.0, target_w / frame_w) * sprite_scale
  ```

  A 124×96 boss at footprint 1 is scaled down to 64px wide — **this is what
  actually fixes "too big"**; nothing can ever exceed its footprint's width. A
  128×128 formation sprite at footprint 2 lands at exactly 2×2 tiles, scale 1.0.
  A 16×16 walker is **not** blown up (decision 2) — it renders 16px and small;
  `sprite_scale` (per type, default 1.0, may exceed 1) is the deliberate knob to
  bump it up.
  *Why not upscale-to-fit:* it would silently magnify every low-res sprite and
  contradicts decision 2. The consequence — tiny art stays tiny — is a listed risk.

- **D3 — The anchor cliff becomes continuous.** The `frame_h > tile_h` branch is
  replaced by a rule that keeps the art's bottom on the tile at any frame height.
  This touches **every** sprite, not just enemies, so it must be pixel-pinned
  against buildings / deco / tiles before merge.
  *Why now:* ER-1 changes enemy frame heights. Leaving the cliff in place means
  the first re-import that crosses 32px moves the sprite a whole tile and looks
  like a new bug.

- **D4 — Breaking formation IS dying.** Rather than a separate "break" state
  machine, an enemy's death threshold becomes data: `at_hp_fraction`. A unit with
  `at_hp_fraction: 0.5` dies at half HP and spawns its children; the Boss with
  `at_hp_fraction: 0.0` dies at zero, exactly as today. One code path, one editor
  form, one toggle.
  *Why not a separate mechanic:* two near-identical systems (Boss swarm + formation
  break) would drift, and the Session's death-stash handshake would need a second
  duck-typed contract.

- **D5 — Footprints are a pathfinding property, not an occupancy one.** Per
  decision 4, a size-N enemy may only stand where its whole N×N block is passable.
  It never enters `TileOccupancy`.
  *Why not occupancy:* `engine/physics/occupancy.py` is one-occupant-per-tile and
  is what the **building placement** path relies on; writing moving enemies into it
  would couple locomotion to placement and invite tile-leak bugs on despawn.

- **D6 — One cached flow field per footprint.** `game/map/pathfinder.py` caches a
  reverse-Dijkstra field keyed by `TileMap._path_version`; `_ensure_flow_field`
  already keys its cache dict on `ignore_walls`. The key becomes
  `(ignore_walls, footprint)`. This preserves the PERF invariant (`game/PERF.md`):
  **one Dijkstra per topology change per footprint, never one per enemy.**

## 2. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| ER-1 | Render sizing: per-slot frame size, footprint fit, anchor fix, pad-and-centre import | done |
| ER-2 | Footprint clearance pathing (2×2 enemies) | done |
| ER-3 | Generalised toggleable `death_spawn` (Boss re-expressed) | done |
| ER-4 | The `Formation` enemy type (128×128, footprint 2, breaks at 50%) | done |
| ER-5 | Editor surfacing + docs (+ both carried-over defects) | done |

**ER-1..ER-4 shipped together** (branch `phase-ER-1-ER-4-umbrella`). Three
corrections to this document that the phases made, recorded so the text below is
not read as still authoritative:

- **D3's anchor rule as written was unimplementable.** "Keep the art's bottom on
  the tile" would move every 64×96 building UP 32px. The rule actually shipped is
  the one the old two-branch cliff was already expressing: **the frame's centre
  sits on the tile's centre**. It is continuous in `frame_h` and byte-identical at
  `frame_h ∈ {32, 96}` — i.e. at every non-enemy world frame that exists.
- **ER-3's `spawns` is NOT a `oneOf` union.** A type-less schema node crashes
  `editor/panels/balancing.py` for the whole enemies domain. `spawns` is always an
  ARRAY of per-era rows; the flat map is just the 1-row case.
- **ER-1's parity-map instruction was wrong for `_py_only`.** `DROPPED:` strings
  are only understood by the main mapping table; the `_py_only` consumer indexes
  `entry["path"]` and raises on a string. Those entries were deleted, not retagged.

Both issues carried out of that batch were **fixed in ER-5** (see its section):

- ~~A death on a wave's LAST frame ends the round before its children appear.~~
  Fixed: the wave-clear check now also consults `Scene.queued_by_tag("enemy")`.
- ~~Even footprints draw 16px above their logical block centre.~~ Fixed:
  `engine.render.block_center_offset` draws a `fit_tiles`-wide unit on its block
  centre. (The plan's "even footprints" framing was imprecise — the error is
  `(N−1) · tile_h/2`, i.e. zero only at N=1, and 32px at N=3. Horizontal error is
  zero for every N, which is why it read as "floating" rather than "misplaced".)

---

### Phase ER-1 — Render sizing

Branch: `phase-ER-1-render-sizing`. Packages: **engine + data + editor** (thin
`game/enemies` hook).

**Goal**: an enemy's on-screen size derives from its tile footprint, never from
raw sheet pixels; undersized art imports cleanly, padded and centred; the anchor
cliff is gone.

**Files** — modified:
- `data/schemas/slots.schema.json` + `data/slots.json` — slot entries in
  `groups[].slots[]` accept an object form `{key, frame_w, frame_h}` beside the
  existing bare-string form (string = inherit the category size).
- `engine/assets/registry.py` — `SlotRegistry.frame_size(slot_key)` prefers the
  per-slot override, falls back to the category.
- `engine/core/sprite_animator.py` — `SpriteAnimator` gains `fit_tiles: float = 0.0`
  and `scale: float = 1.0`, passed into the emitted `RenderItem`. **Engine-generic
  names only** — no game vocabulary in `engine/` (engine hard rule).
- `engine/render/item.py` — `RenderItem` gains `fit_tiles` + `scale`.
- `engine/render/renderer.py` — the sizing block applies D2's downscale-only width
  fit; `fit_tiles == 0.0` keeps today's behaviour **byte-identical**, so buildings,
  tiles, deco and HUD sprites are untouched. Separately, the D3 anchor fix.
- `editor/asset_import.py` (`import_idle_sheet`) and `editor/panels/details.py`
  (the multi-row importer) — art smaller than one frame is **padded and centred**
  (bottom-anchored) into the declared frame instead of raising `ValueError`.
  Pillow is already a dependency.
- `data/balancing/enemies.json` + `data/schemas/enemies.schema.json` — add
  `footprint` (integer, default 1) and `sprite_scale` (number, default 1.0) per
  enemy type; **delete the dead `era_sizes` / `sprite_w` / `sprite_h`**.
- `tools/tests/balancing_parity_map.json` — retag the deleted keys as
  `DROPPED:<reason>` (the parity test asserts coverage both ways and will fail
  loudly otherwise).
- `game/enemies/enemy.py` — thread `footprint` / `sprite_scale` from balancing
  into the `SpriteAnimator`.

**Tests**: `test_render.py` — the fit math (124×96 at footprint 1 → 64px wide;
128×128 at footprint 2 → 128px; a 16×16 frame is never upscaled) and that
`fit_tiles=0` is pixel-identical to today. Anchor continuity across the old 32px
cliff. `test_assets_registry.py` — a per-slot override beats the category, a bare
string still inherits. `test_editor_asset_import.py` — a 16×16 PNG into a 64×96
slot imports centred, no raise. `test_balancing_data.py` +
`test_balancing_parity.py` stay green.

**Exit gate**: `py tools/smoke.py` and
`py -m unittest discover -s tools/tests -t .` — zero new failures against the
known `Development` baseline.
**Quick Test**: `py game/main.py`, play into round 1 — walkers, raiders and siege
sit **on** their tile at a sane size, and a boss no longer overflows its tile.
Then `py editor/main.py`, import a 16×16 PNG onto `enemy_stage_1_v1` and see it
centred in the preview rather than rejected.
**Docs**: `engine/render/CLAUDE.md` (fit + anchor), `engine/assets/CLAUDE.md`
(per-slot override), `data/CLAUDE.md` (slots.json shape).

---

### Phase ER-2 — Footprint clearance pathing

Branch: `phase-ER-2-footprints`. Packages: **game** (`map` + `enemies`).

**Goal**: an enemy with `footprint: 2` only ever stands where all four tiles are
passable. It routes around gaps a 1×1 slips through and attacks whatever blocks
it, via the existing block-and-attack model. **No `TileOccupancy` writes** (D5).

**Files** — modified:
- `game/map/pathfinder.py` — `_dijkstra` / `_build_flow_field` / `_ensure_flow_field`
  take a `footprint` (default 1, preserving byte-identical single-tile behaviour).
  Passability for a size-N unit: every tile of the N×N block from the anchor is
  in-bounds with `weight < impassable`, and no wall edge crosses the block. The
  field cache key becomes `(ignore_walls, footprint)` (D6).
- `game/enemies/components.py` — `PathAgent` gains `footprint`; its block test
  scans the whole N×N block ahead rather than one tile, and its wall-edge test
  covers every edge the block crosses.
- `game/enemies/enemy.py` — thread `footprint` from balancing into `PathAgent`.
- `game/enemies/combat.py` — Chebyshev range and target acquisition measure from
  the footprint's **centre**, not its anchor corner, so a 2×2 is not engaged from
  an unfair corner.
- `game/enemies/spawner.py` — a footprint-N enemy spawns only on a tile whose N×N
  block fits the map and lies in the spawn zone.

**Tests**: new `test_footprint_path.py` — a 2×2 unit refuses a one-tile gap that a
1×1 takes; `footprint=1` paths are byte-identical to today's fixtures; the field
cache rebuilds exactly once per `_path_version` bump per footprint. Existing
`test_flow_field.py`, `test_enemies.py`, `test_boss.py` stay green.

**Exit gate**: the two gate commands, zero new failures.
**Quick Test**: build a line of buildings with a single one-tile gap. A walker
threads the gap; a 2×2 unit does not — it stops and attacks a blocking building
instead.
**Docs**: `game/map/CLAUDE.md` (footprint-aware flow field + the `_path_version`
invariant), `game/enemies/CLAUDE.md`.

---

### Phase ER-3 — Generalised toggleable `death_spawn`

Branch: `phase-ER-3-death-spawn`. Packages: **data + game** (`enemies` + `core`).

**Goal**: one death-spawn mechanic, per type, toggleable in balancing — with the
Boss's existing 10G swarm re-expressed in it and **no behaviour change**.

**Shape** (an optional block on any enemy type):

```json
"death_spawn": {
  "enabled": true,
  "at_hp_fraction": 0.5,
  "spawn_hp_fraction": 0.8,
  "spawns": { "standard": 8 }
}
```

- **`at_hp_fraction`** — the unit dies when HP falls to or below this fraction of
  max (`0.0` = today's die-at-zero). Breaking formation *is* dying (D4).
- **`spawn_hp_fraction`** — children spawn at this fraction of their own max HP.
- **`enabled`** — the toggle.
- **`spawns`** must accept either a flat `{type: count}` map or the Boss's
  existing 5-entry per-era array, so `at_hp_fraction: 0.0` plus the era table
  reproduces 10G exactly.

**Files** — modified: `data/balancing/enemies.json`,
`data/schemas/enemies.schema.json`, `tools/tests/balancing_parity_map.json`
(`Boss/death_spawns` → its new path); `game/enemies/components.py` — a
`DeathSpawn` component absorbing `BossState`, keeping the one-shot
`death_spawned` guard and `mark_death_spawned()` as a **method** (the E-11
`GameObject.__setattr__` guard intercepts public property setters);
`game/enemies/enemy.py` — threshold death, `alive` becomes
`hp > max_hp * at_hp_fraction`; `game/enemies/spawner.py` — `spawn_death_swarm`
generalised to take a resolved spawn table plus `spawn_hp_fraction`;
`game/core/session.py` — `on_enemy_death` stashes for **any** type carrying an
enabled `death_spawn`, not just `ETYPE == "boss"`.

**Invariants that must survive**: quick-skip and lives-wipe despawns spawn
nothing; the swarm flush stays in `post_sim` **before** the wave-clear check; XP
is awarded per the existing `game/core/xp.py` table; `game/enemies` still imports
nothing from `game/core` (the callback seam).

**Tests**: `test_boss.py` stays green — the 10G swarm must be byte-identical
through the new path. New cases: `enabled: false` spawns nothing; a 50% threshold
break dies exactly once and spawns children at 80% HP; the one-shot guard holds
across a double-death frame.

**Exit gate**: the two gate commands, zero new failures.
**Quick Test**: reach a boss round — the swarm behaves exactly as before. Then
untick `enabled` in the editor's balancing panel, save, replay: no swarm.
**Docs**: `game/enemies/CLAUDE.md`, `data/CLAUDE.md`.

---

### Phase ER-4 — The `Formation` enemy type

Branch: `phase-ER-4-formation`. Packages: **data + game** (+ a `slots.json` group).

**Goal**: the new large unit — 128×128 art, footprint 2, more HP and damage than a
regular, which **dies at 50% HP and breaks into regular units at 80% HP each**,
simulating the formation scattering.

Follows the `/add-enemy` skill's shape:
- `game/enemies/enemy.py` — a `Formation(Enemy)` subclass (`ETYPE = "formation"`,
  `REGISTRY_GROUP = "Formation"`), registered in `ENEMY_CLASSES`.
- `game/enemies/spawner.py` — a branch flag and a composition rule (from which
  round it appears, and how many), in the same style as the 10F raider/siege rules.
- `data/balancing/enemies.json` + schema — an `EnemyTypes.Formation` block with
  its stats, `footprint: 2`, `sprite_scale`, and the ER-3 `death_spawn`
  (`at_hp_fraction: 0.5`, `spawn_hp_fraction: 0.8`, `spawns: {standard: N}`).
- `data/slots.json` — a `Formation` group with era children, carrying the ER-1
  per-slot **128×128** override.

Placeholder art is acceptable to land the phase — missing art falls back to the
grey-X placeholder and never crashes (E-23 / E-37).

**Tests**: `test_enemies.py` — construction, stat resolution, the 50% break
firing once, and the 2×2 clearance path. Spawner composition stays deterministic
under an injected `rng`.

**Exit gate**: the two gate commands, zero new failures.
**Quick Test**: reach the round the Formation first appears — it covers 2×2 tiles,
walks around single-tile gaps, and at half HP bursts into a cluster of walkers at
80% HP.
**Docs**: `game/enemies/CLAUDE.md`.

---

### Phase ER-5 — Editor surfacing + the two carried-over defects — DONE

Branch: `phase-ER-5`. Packages: **editor + engine + game** (the scope grew — see
below). Docs updated: `editor/panels/CLAUDE.md`, `engine/render/CLAUDE.md`,
`engine/core/CLAUDE.md`, `game/core/CLAUDE.md`.

**Goal**: a designer can tune all of the above without hand-editing JSON.

What the exploration found, and what changed as a result:

- **"Surfaces for free" was TRUE for the scalars, FALSE for array cardinality.**
  `footprint`, `sprite_scale` and every leaf of `death_spawn` already reached the
  designer as real, range-bounded widgets — verified by tracing each through the
  panel's type switch, and now pinned by a test. But `_build_array` rendered one
  section per row *already in the JSON* and had **no add/remove affordance**, so a
  1-row type could never be given a per-era `spawns` table. ER-5 adds **`+ Row` /
  `− Row` for arrays of objects, gated entirely by the schema's `minItems`/
  `maxItems`** — every pre-existing array (`tiers`, `scale_tiers`, `round_counts`)
  has `minItems == maxItems` and is therefore untouched. Add copies the last row
  (schema-valid by construction); remove pops the last (these tables are
  era-INDEXED).
- **Per-slot frame size is a TWO-FILE write.** The widget lands next to the offset
  spinboxes as planned, but `AssetStore.frame_size` resolves **manifest entry >
  registry**, so writing the `slots.json` override alone leaves an imported slot
  rendering at its old size. The handler writes the override, reloads the
  registries, **re-slices the sheet and re-saves the manifest entry**.
- **Both known issues were fixed here** (user's call), which pulled `engine/` and
  `game/` into an "editor" phase:
  - *Wave-clear race*: `Scene.queued_by_tag(tag)` (engine) + the wave-clear
    condition consulting it (`game/core/session.py`). It was a REAL bug for the
    10G boss from day one, not merely a latent one for Formations.
  - *Multi-tile render offset*: `engine.render.block_center_offset` — a `fit_tiles`
    unit draws on its block centre. A provable no-op at `fit_tiles` 0 and 1, so
    buildings/tiles/deco/HUD and every 1-tile enemy are byte-identical. The game's
    overhead HP bars call the same expression rather than restating it.

**Formation.footprint is deliberately 1**, not the 2 that ER-4 shipped — a designer
balance change (commit `111b694`) that ER-5 deliberately did not revert. **No enemy
in `data/` therefore has a footprint > 1 today**, which means ER-2's clearance
pathing and ER-5's block-centre fix are correct but DORMANT: both are covered by
unit tests, and neither can be seen in a live round until some type's footprint is
raised in the editor.

---

## Verification (every phase)

1. `py tools/smoke.py` — the universal gate (schema-validates all of `data/`, then
   boots the game headless).
2. `py -m unittest discover -s tools/tests -t .` — zero **new** failures against
   the known `Development` baseline.
3. If `data/` changed: schema validation passes and
   `tools/tests/balancing_parity_map.json` is updated in the **same** change.
4. If anything architectural changed: update the **package** `CLAUDE.md` named in
   the phase's Docs bullet — not the root router, not another package's doc.
5. State exactly what was verified: smoke test, live run, or static read only.
6. The PR states the phase's Quick Test scenario.

## Risks / open items

- **Tiny art stays tiny.** Downscale-only fit (D2) means a 16×16 sprite renders at
  16px until `sprite_scale` is raised. This is the direct consequence of binding
  decision 2 and is expected — but confirm it reads acceptably in-game after ER-1.
  If not, flipping to upscale-to-fit is a one-line change to the fit expression.
- **The anchor fix (D3) touches every sprite**, not just enemies. Pixel-pin
  buildings, deco and tiles before merging ER-1.
- **Footprints multiply the flow-field cache.** Each distinct footprint costs one
  more cached Dijkstra per topology change. With footprints 1 and 2 only, that is
  two fields — acceptable. Do not let footprints become a free-for-all.
- **The balancing parity gate fails loudly** if `era_sizes` / `sprite_w` /
  `sprite_h` are deleted without retagging them in
  `tools/tests/balancing_parity_map.json`.
- **Branch + lock protocol is SUSPENDED** (root `CLAUDE.md`): one new branch per
  phase, no `_lock` writes, no `/start-domain` or `/merge-domain`.
- **Open**: which rounds the Formation appears in, and its exact stat line, are
  placeholders in ER-4 pending a balance pass — the mechanic lands first, the
  numbers get tuned in the editor.
