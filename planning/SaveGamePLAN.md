<!-- status: IN PROGRESS — 6/7 phases (SG-1, SG-2, SG-3, SG-4, SG-5, SG-6 done) -->

# SaveGamePLAN.md — Save-Game System

Phased, agent-executable plan (same family as `MIGRATION_PLAN.md` /
`AgentDispatchPLAN.md`). Base branch: `Development`. Flat plan — one
orchestrator drives all 7 phases in order (rejected "large": the phases are
mostly sequential and several share one schema file, which is a real
merge-conflict risk if split across parallel worktree sections — see the
scale discussion this plan was scoped from).

## 1. Vision

The game currently has **no save/load at all** — every run lives only in
memory and is discarded on quit or "quit to menu". This plan adds:

- **Autosave every 5 rounds**, at the round-boundary (no enemies/projectiles
  alive, phase transitioning to `BUILDING`) — never mid-combat.
- **Up to 10 save slots**, each a fresh entry (loading a slot and continuing
  play does not overwrite it — the next autosave creates a new slot).
  Oldest **unpinned** slot is evicted first when a new autosave would exceed
  10; a slot can be **pinned** to exempt it from eviction.
- A new **Save Files** screen from the main menu (slot list: timestamp,
  round reached, a simple 2-color unlocked-tiles minimap, pin toggle, manual
  delete) plus a **Continue** button that loads the most recent slot
  directly.
- **Full-fidelity resume**: round/love/lives/XP/research state, every placed
  building (type, tier, HP, in-progress timers/snapshots), tile
  unlock/stage/condition state, perimeter walls, and buildings mid-move all
  resume exactly as saved — not just the "core" economy numbers.

## 2. Architecture

```
game/main.py (host)                    game/core/savegame.py (new, pure)
──────────────────                     ──────────────────────────────────
round-edge watcher (existing,          default_path / load_index / write_index
beside update_season) ──► on           load_slot / write_slot / delete_slot
round_num % 5 == 0:                    evict_oldest_unpinned(index, keep=10)
  assemble_save(session, tilemap)  ──► write_slot(doc) + update index
                                        (write_validated, gitignored scores/saves/)

Save Files screen (game/ui,            Loaded via game/main.py's
new) ── "load_save" intent ──►         build_gameplay_from_save(slot_id):
                                          load_slot → RunState.from_dict
                                          → TileMap.from_state(...)
                                          → rehydrate_building(...) per entry
                                          → Session wired exactly like
                                            build_gameplay(), state=BUILDING
```

**Serialization backbone — the one finding that shrinks this plan's scope**:
`engine/core`'s `GameObject`/`Component` classes already round-trip
generically (`engine/core/gameobject.py:79-96`,
`engine/core/component.py:97-107`) — every `Building`'s components
(`TierState`, `Health`, `Attacker`, `YieldEconomy`, `PainterProgress`,
`BoostReceiver`/`BoostEmitter`, `SplashAttacker`, `WallBuilderState`,
`BeamAttacker`, `RoundStats`, `Nameplate`, …) are JSON-safe by construction
and serialize field-by-field for free via `Component.to_dict()`. The only
gap: `GameObject.from_dict` returns a base `GameObject`, not the right
`Building` subclass ("components carry all state; subclasses are behavior
convenience"). So building rehydration is: look up the leaf class via
`game/buildings/research.py LEAF_CLASSES[building_type]`, construct a fresh
instance the normal way (`game/buildings/registry.py::create(building_type,
col, row, buildings_balance, tier_idx)`), then overwrite that instance's
component field values from the saved component dicts (matched by component
**type name**) rather than replacing the components list — this preserves
whatever wiring `create()`/`on_added()` already did while restoring exact
saved values. This is what makes "full fidelity" tractable: **zero new
per-building-type serialization code**, one generic helper used by all
twelve types.

### Decisions (with rationale)

- **D1 — Autosave fires only at the round-boundary** (`round_num % 5 == 0`,
  the same "round edge" `update_season`/ground-cache-invalidate already
  hooks in `game/main.py` per `game/core/CLAUDE.md`'s N1 section). No
  enemy/projectile/wave-queue state is ever serialized — the round loop
  guarantees the board is clear at this exact moment, which is what keeps
  "full fidelity" from also requiring `game/enemies` serialization.
- **D2 — Slots are gitignored per-machine runtime state**, the
  `highscores.json`/`keybindings.json` precedent (`data/CLAUDE.md`'s "three
  schemas with no `data/` content file" list — this plan adds a fourth):
  `scores/saves/<slot_id>.json` per slot + `scores/saves/index.json` (id
  list in creation order + pinned flags + lightweight per-slot summary for
  the Save Files screen list, so opening that screen does not have to load
  every slot's full body). Both validate through `write_validated`/
  `load_validated`; `tools/smoke.py::validate_data` already skips
  `data/schemas/`, so no smoke-test directory wiring is needed.
- **D3 — Every autosave is a new slot** (user decision) — never overwrites
  the slot it was loaded from. FIFO eviction deletes the oldest **unpinned**
  slot when a save would exceed 10. **If all 10 slots are pinned**, the new
  autosave is skipped with one logged warning — never silently deletes a
  pinned slot, never crashes.
- **D4 — Minimap stores no image bytes.** The save already needs the list of
  unlocked `(col, row)` tiles for `TileMap` restoration; the Save Files
  screen renders the minimap live from that same data as a small grid of
  filled rects (downsampled if the grid is large), staying pygame-free in
  `game/map`/`game/ui` per the existing layering rule — no new
  surface-capture code anywhere.
- **D5 — `mortar_slow_snapshot_ids` needs an id-scheme translation, not a
  straight dump.** `RunState.mortar_slow_snapshot_ids` stores Python
  `id(building)` values (raw object identity), which are memory addresses —
  meaningless across a save/load boundary. Phase 2 must translate this set
  to the buildings' stable `GameObject.id` (uuid) strings at save time, and
  Phase 3's rehydration must translate back to the *new* `id(building)` of
  the reconstructed objects at load time, matched by uuid. This is the one
  genuinely non-obvious wrinkle in "full fidelity" and must not be missed.
- **D6 — `RunState.boss_upgrade_choices` gains disk persistence**, which is
  a deliberate, documented change: today's `game/core/CLAUDE.md` states "No
  disk persistence, same as its predecessor" for this ledger. Full-fidelity
  resume requires it (the base-info popup's boss-choice history must survive
  a load), so Phase 2 updates that doc line alongside the code change.
- **D7 — `RunState.scripted_leveling` is NOT saved** — it mirrors whatever
  `progression_balance` says at `Session.__init__` time, so a load re-derives
  it from the currently-loaded balancing file (exactly like a fresh run),
  rather than trusting a possibly-stale saved copy if the designer edited
  `progression.json` between the save and the load.
- **D8 — Every other transient, drained-by-UI ledger on `RunState` is reset
  to its default on load**, per the exhaustive field table in Phase 2 —
  these are the fields `game/core/game_state.py` already comments "never
  serialized" (per-frame floater queues, one-shot cutscene/levelup requests,
  the payout-animation checkpoints). None of them carry information that
  matters at a round boundary; all are empty there in a live run too.

## 3. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| SG-1 | Data schema + slot storage primitives (`game/core/savegame.py`) | done |
| SG-2 | `RunState` + `Session` serialization | done |
| SG-3 | `Building`/`GameObject` rehydration helper | done |
| SG-4 | `TileMap` state serialization | done |
| SG-5 | Autosave wiring (`game/main.py` round-edge hook) | done |
| SG-6 | Save Files screen + main menu wiring | done |
| SG-7 | End-to-end verification | not started |

---

### SG-1 — Data schema + slot storage primitives

**Goal**: the slot/index file format and eviction mechanics exist and are
tested against hand-built dicts — no `RunState`/`TileMap`/`Building`
serialization yet.

**Files** — new: `data/schemas/savegame.schema.json`,
`data/schemas/saves_index.schema.json`, `game/core/savegame.py`,
`tools/tests/test_savegame.py`. Read first: `game/core/highscores.py`
(the shape to copy: `default_path`, tolerant `load_*`, raising `write_*`,
`_empty_doc`), `data/CLAUDE.md`'s "three schemas with no content file" list.

`savegame.schema.json`'s top-level envelope (sub-objects for `run_state`/
`tile_map`/`buildings` stay loosely typed here — SG-2/3/4 each own their own
`$defs` node when they land, added to this same file): `version`, `slot_id`,
`created_at`, `updated_at` (ISO-8601), `pinned` (bool), `map_id`, `round_num`
(int — duplicated from `run_state.round_num` deliberately, so the index can
show it without loading the full slot body), `unlocked_tiles` (array of
`[col, row]` — the minimap source, duplicated from `tile_map` for the same
reason), `run_state`, `session`, `tile_map`, `buildings` (array).
`saves_index.schema.json`: `version`, `slots` (array of `{slot_id, pinned,
created_at, round_num, thumbnail_cols, thumbnail_rows, unlocked_tiles}` —
enough for the Save Files screen's list + minimap with zero per-slot full
loads).

`game/core/savegame.py` (pure, the `highscores.py` shape): `default_path`
(→ `scores/saves/`), `load_index`/`write_index` (tolerant load, raising
write), `load_slot`/`write_slot`/`delete_slot`, `evict_for_new_slot(index,
keep=10)` (returns the slot id to delete, or `None` if every slot is
pinned — D3).

**Tests**: `tools/tests/test_savegame.py` — round-trip a hand-built slot
doc; index add/evict ordering (oldest-unpinned-first); the all-pinned
skip case; corrupt/missing file tolerance on load (mirrors
`test_highscores.py`'s shape).

**Exit gate**: `py tools/smoke.py` + `py -m pytest
tools/tests/test_savegame.py -q`.

---

### SG-2 — `RunState` + `Session` serialization

**Goal**: `RunState.to_dict()`/`RunState.from_dict()` exist and round-trip
every durable field exactly; `Session` gains matching save/restore for
`combat_speed_idx`.

**Files** — modified: `game/core/game_state.py` (add `to_dict`/`from_dict`),
`game/core/session.py` (thread `combat_speed_idx` through save/restore),
`game/core/CLAUDE.md` (update the `boss_upgrade_choices` "no disk
persistence" line per D6 above). New: extend `tools/tests/test_game_state.py`
(or a new `test_game_state_serialization` module) with the round-trip test.

**Field disposition** (exhaustive — every `RunState` field, save or reset):

| Save (round-trips exactly) | Reset to default on load |
|---|---|
| `round_num`, `season`, `love`, `base_lives`, `enemies_killed`, `buildings_placed`, `player_xp`, `village_level`, `xp_threshold`, `xp_threshold_inc`, `tiers_unlocked`, `unlocked_buildings`, `lightning_level`, `boss_upgrade_stacks`, `boss_upgrade_choices` (D6), `love_spent_on_tiles`, `used_painter_tiles` (set → list-of-`[col,row]` on the way out), `mortar_slow_snapshot_ids` (set of `id(building)` → list of GameObject uuids, D5), `boss_lives_snapshot`, `boss_love_snapshot`, `first_end_turn_cutscene_requested`, `tutorial_intros_shown`, `levelup_pending`, `phase` (saved as `BUILDING`; asserted at save time), `state` (saved as `GAMEPLAY`) | `phase_timer`, `income_events`, `painter_events`, `boost_events`, `building_respawn_events`, `xp_events`, `levelup_options`, `pending_boss_cutscene`, `boss_events`, `log_events`, `enemy_death_events`, `life_lost_events`, `pending_cutscene`, `splash_impact_events`, `defender_fire_events`, `projectile_hit_events`, `pending_enemy_intros`, `payout_love_start`, `payout_love_after_economy`, `scripted_leveling` (D7 — re-derived from `progression_balance` at load, not trusted from disk) |

A save taken outside a round-boundary (should never happen once SG-5 wires
the hook, but assert it defensively) raises loud rather than silently
saving a mid-combat snapshot that would be misleading on load.

**Tests**: construct a `RunState` with every save-column field set to a
non-default value, round-trip through `to_dict`/`from_dict`, assert equality
on every saved field and default-reset on every other field. A second test
seeds `mortar_slow_snapshot_ids` with real `id(building)` values against a
small building list and asserts the uuid translation round-trips.

**Exit gate**: `py tools/smoke.py` + `py -m pytest
tools/tests/test_game_state.py tools/tests/test_session.py -q`.

---

### SG-3 — `Building`/`GameObject` rehydration helper

**Goal**: a generic `save_building(building) -> dict` / `restore_building
(data, tilemap, buildings_balance) -> Building` pair, built on the existing
`GameObject.to_dict()`/`Component.to_dict()`/`component_from_dict`, that
round-trips one building of **every** type with zero per-type code.

**Files** — modified: `game/buildings/registry.py` (add
`save_building`/`restore_building`, beside the existing `create`/
`place_building`), `game/buildings/CLAUDE.md` (document the new
save/restore seam). New: `tools/tests/test_registry_savegame.py` (or extend
`test_registry.py`).

`save_building(building)`: `{"building_type": ..., "col": ..., "row": ...,
"gameobject": building.to_dict()}` — `building_type` comes off whichever
attribute `place_building` already reads to key `LEAF_CLASSES` (verify at
implementation time; do not re-derive from `SUBTREE` or any other proxy).

`restore_building(data, tilemap, buildings_balance)`: `registry.create(
data["building_type"], data["col"], data["row"], buildings_balance,
tier_idx=<read off the saved TierState component>)`, then for each saved
component dict, find the freshly-created building's own component of the
same type (by class name) and overwrite its field values from the saved
dict (`setattr` per field — never replace `building.components` wholesale).
A saved component type absent from the fresh instance (schema/version drift)
is a loud error, not a silent skip — this is exactly the D-2 "fail loud on
bad data" rule applied to save files.

**Tests**: one round-trip per entry in `LEAF_CLASSES` (parametrized over all
twelve types) — place a building, mutate a couple of component fields to
non-default values (e.g. damage a `Health`, advance a `TierState`), save,
restore, assert every component field matches. A dedicated test also covers
`mortar_slow_snapshot_ids`' uuid ⇄ `id()` translation working against
*this* helper's freshly-created objects (the real consumer of that
translation, alongside SG-2's isolated test).

**Exit gate**: `py tools/smoke.py` + `py -m pytest
tools/tests/test_registry.py tools/tests/test_registry_savegame.py -q`.

---

### SG-4 — `TileMap` state serialization

**Goal**: `TileMap` gains `save_state()`/`TileMap.apply_state(data,
buildings_balance)` (restoring INTO a freshly-constructed `TileMap(doc,
balance, rng, registry)` — never a bespoke reconstruction path) covering
tile-state deltas, conditions, the stage system, wall edges, and moving
orders.

**Files** — modified: `game/map/tile_map.py`, `game/map/CLAUDE.md`
(document the new save/restore seam and confirm no perf-invariant caches —
`_path_version`/`_flow_cache` — need explicit handling since they rebuild
naturally). New: extend `tools/tests/test_tile_map.py`.

`save_state()`: `{tile_deltas: [{col, row, state, content_key, condition,
condition_variant_idx}, ...]}` (only tiles whose runtime state differs from
the map doc's legend-derived initial state — most of the grid never
changes, so this stays small even on a 1024² map), `terrain_overrides`,
`stage`, `unlock_purchases`, `retire_cursor`, `wall_edges` (each edge's
`owner` written as the owning building's `GameObject.id` uuid, resolved back
to the live object after SG-3 rehydrates buildings), `moving_orders` (each
entry's `building` the same uuid reference, plus `from_col/from_row/to_col/
to_row/rounds_left`).

`apply_state(data, ...)`: replays every delta through the SAME public seams
`TileMap` already exposes for these mutations (`set_tile_state`, the wall
registry, `sync_occupancy`) — **never writes `_grid`/`wall_edges`/
`moving_orders` directly** — so `_path_version` bumps correctly and no new
cache-invalidation logic is needed. Order of operations at load time:
tiles restored first (state/condition), buildings placed via SG-3's
`restore_building` next (which naturally sets occupancy through the normal
placement path), THEN wall edges and moving orders restored (both need
their `owner` uuid resolved against the now-live buildings).

**Tests**: unlock a chunk, place a couple of buildings across types
including a `WallBuilder` (so a real wall-edge set exists) and one building
mid-move, save, build a fresh `TileMap` from the same map doc, apply the
saved state, assert the two tilemaps agree on every occupied tile's state/
content_key/condition, every wall edge's HP and owner, and the moving
order's tile pair.

**Exit gate**: `py tools/smoke.py` + `py -m pytest
tools/tests/test_tile_map.py -q`.

---

### SG-5 — Autosave wiring

**Goal**: the game actually writes a save file, unattended, every 5 rounds,
at the round boundary — using SG-1 through SG-4's primitives, assembled by
the host.

**Files** — modified: `game/main.py` (the round-edge watcher, beside the
existing `update_season`/ground-cache-invalidate call), `game/CLAUDE.md`
(document the new autosave hook alongside the existing "Host conventions"
round-edge watcher-chain note).

`main.py` builds one save document: `RunState.to_dict()` +
`Session.combat_speed_idx` + `TileMap.save_state()` + `[save_building(b) for
b in <every live building>]` + the minimap's `unlocked_tiles` list + slot
metadata (timestamp, `map_id`) — then calls `game/core/savegame.py`'s
write-with-eviction path. Fires exactly once per qualifying round edge (the
same "watcher chain" pattern `update_season` already uses to avoid firing
every frame).

**Tests**: a headless `tools/simrun.py`-style run (or a focused
`test_main`/`test_savegame_integration` test) that drives 5+ rounds and
asserts a slot file was written with the expected round number; a second
run to round 10+ asserts a SECOND, separate slot exists (D3 — new slot per
autosave, never an overwrite).

**Exit gate**: `py tools/smoke.py` + the new integration test file +
a live `py game/main.py` play to round 5, confirming a file lands under
`scores/saves/`.

---

### SG-6 — Save Files screen + main menu wiring

**Goal**: the player can see, load, pin, and delete saves from the main
menu.

**Files** — new: `game/ui/save_files_screen.py`. Modified:
`game/core/phases.py` (append `GameState.SAVE_FILES`, no existing ordinal
moves), `game/ui/main_menu.py` (`_ITEMS`/`_SLOT_IDS` gain **SAVE FILES** and
**CONTINUE** rows), `game/ui/shell.py` (`_MENU_STATES`/`_active_screen`
dispatch table gains the new screen; a new `"load_save"` intent carrying a
slot id), `game/main.py` (execute `"load_save"` via a new
`build_gameplay_from_save(slot_id)` sibling of `build_gameplay()`), `game/ui/CLAUDE.md`
(document the new screen per its "Shell + menus" conventions — "overlay ⇒
flag, full screen ⇒ state" applies here: SAVE_FILES earns a full `GameState`
member since it is reachable from the main menu and needs its own
back-navigation, the `HIGHSCORES` precedent).

`SaveFilesScreen` mirrors `game/ui/highscores_screen.py`'s construct →
`layout()` → `update()` → `hit()` → `submit()` shape: reads
`savegame.load_index()`, renders up to 10 rows (timestamp, round, a small
grid of filled rects for the minimap sized off each slot's
`unlocked_tiles`/`thumbnail_cols`/`thumbnail_rows`, a pin toggle, a delete
button), and returns a `("load_save", slot_id)` action on a row click
(outside the pin/delete controls).

`build_gameplay_from_save(slot_id)`: `savegame.load_slot(slot_id)` →
`RunState.from_dict(...)` → fresh `TileMap(doc, balance, rng, registry)` for
the saved `map_id` → `tile_map.apply_state(...)` → `restore_building(...)`
per saved building → `Session` wired exactly like `build_gameplay()` (same
callback/hook installation calls), landing in `GameState.GAMEPLAY` /
`GamePhase.BUILDING`. **CONTINUE** on the main menu is exactly this call
against the index's most-recently-created slot, no screen shown.

**Tests**: extend `tools/tests/test_ui_shell.py`/`test_main_menu.py`-style
coverage for the new intent + state wiring; a `test_ui_layout_export.py`
regenerate if `SAVE_FILES` needs a `data/ui/screens/` entry (confirm at
implementation time whether it is on-disk or code-only per `game/ui/
CLAUDE.md`'s two-tier screen convention — code-only, like `highscores.py`,
is the lighter default unless a designer specifically wants to skin it).

**Exit gate**: `py tools/smoke.py` + the touched UI test files + a live
`py game/main.py` pass: reach round 5, quit to menu, open SAVE FILES, see
the slot with correct round/minimap, load it, confirm the world matches;
pin a slot; fill 10 slots and confirm eviction; delete a slot manually.

**SG-6 implementation note — three deviations from this sketch, all
discovered mid-phase:**
1. **The load path reuses the checkpointed LOADING screen instead of a new
   `build_gameplay_from_save`.** `_build_gameplay_steps()` (the feature/
   loading-screen mechanism `game/CLAUDE.md` documents) already splits
   world construction into checkpointed closures; it gained an optional
   `restore_data` parameter instead of a parallel function, so a resumed
   save gets the same progress screen a new game does for free.
   `_apply_save_to_world(world, restore_data, buildings_balance)` (a new
   module-level function in `game/main.py`, not a method) does the actual
   restore: tiles -> buildings -> moving orders -> wire tiles/occupancy/
   scene -> `rebuild_walls()` -> `RunState`/`Session`. The file is
   `game/ui/save_files.py`, not `save_files_screen.py`.
2. **`TileMap.apply_state` had to split into `apply_tile_state(data)` and
   `apply_moving_orders(data, building_by_id)`.** `restore_building()`
   needs its tile's condition already restored (for stat computation), but
   moving-order restoration needs buildings already restored (for id
   lookups) — a genuine circular dependency the single combined method
   couldn't satisfy. `apply_tile_state` runs first (no building
   dependency), buildings restore next, `apply_moving_orders` runs last.
   Documented in `game/map/CLAUDE.md`.
3. **Walls are never saved at all.** Since autosave only fires at the
   round-boundary (D1), every WallBuilder's walls are always at full HP at
   that moment (payday's `rebuild_walls()` already ran that round) — so
   `_apply_save_to_world` just calls `rebuild_walls()` again after
   buildings are restored, re-deriving edges from each WallBuilder's own
   `wall_snapshot` component field. No `wall_edges` save/restore code
   exists; see §3a below.

Also landed as part of this phase: `tools/tests/test_save_files_ui.py` (9
tests — CONTINUE visibility x3, the 9-row on-screen arithmetic, `hit()` for
back/pin/delete/load, empty-index no-rows) and `tools/tests/
test_main_savegame.py` (`_apply_save_to_world` round-trip via two `_World`
instances, including a mid-move building). `game/ui/CLAUDE.md` and
`game/CLAUDE.md` document the wiring; `data/ui/screen_defaults.json`/
`screen_previews.json` and `test_ui_skinning.py`'s `main_menu` golden entry
were regenerated for the 9-row layout (only `main_menu` moved).

---

### SG-7 — End-to-end verification

**Goal**: confirm the whole feature works together, including the fidelity
edge cases D3/D5/D6 called out.

**Files**: none (verification only) — fix-forward into whichever phase's
files if something breaks.

**Tests / Quick Test script**:
1. Play to round 5 (autosave fires) with at least one `WallBuilder` placed
   and one building mid-move; quit to menu; **Continue**; verify round,
   love, lives, XP, unlocked tiles, every building (type/tier/HP), wall
   edges, and the in-progress move all match pre-quit state.
2. Pick a boss upgrade that uses a pick-time snapshot (`mortar_slow`); save,
   load, verify the upgrade's effect still applies to the same mortars
   (validates the D5 uuid translation end-to-end).
3. Fill all 10 slots; trigger an 11th autosave; confirm the oldest unpinned
   slot is gone and a new one exists.
4. Pin all 10 slots; trigger another autosave; confirm it is skipped with a
   logged warning, no crash, no slot deleted.
5. Manually delete a slot from the Save Files screen; confirm the index and
   the on-disk file both reflect it.

**Exit gate**: every phase's own gate already passed; this phase's gate is
the 5 live Quick Test scenarios above, run once by hand. No new automated
test file is expected here — SG-1 through SG-6 already carry the unit/
integration coverage; this phase is the human-observable confirmation that
they compose correctly. The single full `py tools/testgate.py check` happens
ONCE, in the main session, at `/commitpushpr` handoff — never here, never
per-phase (root `CLAUDE.md`'s Test Suite Policy).

## 3a. SG-4 implementation note: wall edges dropped from TileMap serialization

`TileMap.save_state()`/`apply_state()` (SG-4, implemented) do NOT capture
`wall_edges` as originally sketched in §2's architecture diagram. Discovered
during implementation: D1 (autosave only at the round boundary) guarantees
every alive WallBuilder's walls are at full HP the instant an autosave can
fire (payday's `rebuild_walls()` already ran that exact round), and each
WallBuilder's own `wall_snapshot` component field already round-trips
generically via SG-3. So the caller (SG-5/SG-6) just calls
`tilemap.rebuild_walls()` once after restoring buildings — zero new
serialization code, and it reconstructs the identical edge set a save would
have captured. `TileMap.save_state()` covers tile-state/condition/spawn-deco
deltas, the stage counters, and `moving_orders` only.

## 4. Risks / open items

- **`mortar_slow_snapshot_ids`' `id()`-vs-uuid translation (D5)** is the
  single easiest thing to get wrong in this whole plan — it is not visible
  from reading `RunState` in isolation, only from reading its docstring
  closely. SG-2 and SG-3 both touch it; keep their tests honest about
  exercising the FULL round-trip (real buildings, real `restore_building`),
  not just a dict-shape check.
- **Schema growth is incremental across SG-1/2/3/4**, all editing
  `data/schemas/savegame.schema.json`. Since this plan is flat (one
  orchestrator, phases run in order), this is not a concurrent-edit risk —
  it is called out only so whoever executes SG-2 onward re-reads the schema
  SG-1 (or the prior phase) actually left, rather than assuming its own
  mental model of the shape.
- **`levelup_pending`/`boss_lives_snapshot`/`boss_love_snapshot` being
  non-default at a round-boundary save** should not happen given the phase
  machine's ordering (level-up/boss-cutscene resolve before payday, which is
  what produces the `BUILDING`-phase edge this plan saves at) — but SG-2's
  round-trip test should include a case where they are non-zero anyway, to
  confirm "save faithfully" degrades gracefully rather than assuming they
  are always zero.
- **Large maps (up to 1024×1024) and `tile_deltas`**: SG-4 stores only
  tiles that differ from the map's legend-derived initial state, which
  should stay small in practice, but there is no hard cap in this plan. If
  a save file grows large on an aggressively-unlocked huge map, that is a
  size/perf question for SG-7's live testing to surface, not something to
  pre-optimize before it is measured.
- **The "Continue" button's disabled/hidden state when no saves exist**
  needs a concrete UI decision at SG-6 implementation time (grey out vs.
  hide entirely) — flagged here rather than assumed, per this project's
  "ask, don't assume" convention; SG-6's own phase execution should confirm
  with the user rather than picking one silently.
