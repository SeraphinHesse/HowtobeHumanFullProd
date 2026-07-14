# CLAUDE.md — GAME package (router)

Self-contained guide for `game/` — How To Be Human itself, built on `engine/`. You
reached here from the root router. Requirements: SPEC.md §6 (`G-*`). Behavior
source: the prototype repo (`../HowToBeHuman/ClaudePrototype/HowToBeHuman`) — what
the prototype does is the required behavior unless SPEC.md says otherwise.

This doc is a **router**: it holds the host (`main.py`) conventions, the
cross-cutting rules, and the large-map perf INVARIANTS, then points to one
**subsystem doc per domain folder** (auto-loaded when you edit inside it). **When
you change a domain's architecture, update THAT domain's doc**; change the host or
a cross-cutting rule → update this file.

## File scope you may edit
`game/**` and `data/balancing/*` (lock rules apply — check `_lock` first). Never
import or edit `editor/**`. Engine changes are a cross-package task — tell the
user.

## Layout & domains
- `main.py` — the ONLY entry point (`py game/main.py`): pygame window, engine loop,
  input routing. Documented in this router.
- `map/` · `buildings/` · `enemies/` · `core/` · `ui/` — mirror the prototype's
  five balancing domains, which still scope branches and locks (`/start-domain
  buildings` etc.). Each has its own doc:

| Domain | Doc | Owns |
|---|---|---|
| `map/` | `game/map/CLAUDE.md` | runtime TileMap over the map doc; pathfinder; picking; occupancy |
| `buildings/` | `game/buildings/CLAUDE.md` | Building hierarchy; components; registry/placement; research gates |
| `enemies/` | `game/enemies/CLAUDE.md` | Enemy walker; spawner wave queue; type-agnostic combat sweep |
| `core/` | `game/core/CLAUDE.md` | phase machine; payday ordering; XP / village level-up; balance loader |
| `ui/` | `game/ui/CLAUDE.md` | HUD; building panel; floaters; level-up modal; shell + menus |

Perf deep-dive → `game/PERF.md`.

## Host conventions (`main.py`, Phase 2 → 10A)
- `main(max_frames=None)` is importable so `tools/smoke.py` can drive the same code
  headlessly (G-8); `py game/main.py` runs it windowed. `main(autostart=True)`
  skips the shell straight into GAMEPLAY (the headless seam).
- Frame order is fixed per E-14: input → `Scene.update(dt)` → render submit (grid
  tiles + `scene.render_items()`) → `flush` → `flip`.
- **Camera input mapping (E-5) lives here**, on pure engine camera state: **both
  left- and right-click-drag pan** (`cs.pan` + `cs.clamp` to map bounds). Left-drag
  pans only when the press began over the world (not a panel/HUD button) and is
  gated by the same 4px drag threshold that separates a click from a drag, so a
  short left click still selects/places a tile while a left-drag moves the camera
  (`pan_from` tracks this). Scroll wheel steps through the data-driven
  `geometry.json` zoom levels, keeping the viewport-centre world point fixed via
  `screen_to_world`/`world_to_screen` only (no iso math in the host); Esc opens
  pause. A right *click* (a right-press that stayed inside the same 4px drag
  threshold) is a **universal dismiss**, never a world action:
  `handle_world_right_click` closes the cheat menu, else peels one stage off the
  panel via `BuildingUI.dismiss()` and clears the multi-select — from anywhere on
  screen, panel and HUD included. LEVELUP / the boss cutscene are choice-only and
  swallow it. Right-DRAG still pans, so the threshold is what keeps them apart.
- Window size / fps / caption come from `data/display.json` (schema-validated,
  G-7) — never hardcode them.
- **Active map (Phase 6, D-20/D-21)**: boot loads
  `engine.tilemap.load_active_map(data_dir)` (follows `data/maps/active_map.json`)
  and builds coords with THE MAP's dims (`load_coordinate_system(data_dir,
  map_cols=…, map_rows=…)`). The static map is submitted **windowed** each frame:
  `cs.visible_tile_window(view_w, view_h, margin=4)` →
  `engine.tilemap.visible_render_items(map_doc, …)` generates ONLY the tiles that
  can touch the viewport — what makes very large maps (up to 1024×1024) render at
  full fps. Invalid map data fails LOUD (D-2); the E-37 log-and-placeholder
  tolerance covers ART only.
- **Session wiring (9F → 10A)**: the host builds a `TileMap` +
  `engine.physics.TileOccupancy`, attaches the `BaseBuilding`, and builds a
  `game.core.Session`. Each frame: `session.pre_sim(sim_dt, scene)` →
  `scene.update(sim_dt)` → `game.enemies.resolve_combat(..., on_base_hit=…,
  on_enemy_death=…)` → `session.post_sim(scene)`. `session.frozen` skips the whole
  sim behind a modal.
- **Combat speed is a HOST concern (10F)**: `Session` owns the selector, `main.py`
  owns where it lands. `sim_dt = dt * session.combat_speed` while
  `phase == ENEMY`, else plain `dt` — and that ONE value feeds all three sim calls
  above, so spawner, movement and combat never desync. Never scale the
  ROUND_END/INCOME timers. Keys (gameplay, ENEMY phase only): `1`/`2`/`3` =
  1×/1.5×/2× (round-gated inside `Session`), bare `P` = quick-skip the wave. The
  matching HUD buttons + the lives-faces readout are **10L**.
- **10J host wiring**: the BUILDING click branch runs the shift multi-select
  (`update_selection` + `gp["sel"]`/`gp["sel_cat"]`); `panel.name_editing`
  routes keys to the upgrade-panel rename row before the shortcut keys;
  the game log + FX watchers run in the world update block and splatters clear
  on the ENEMY-phase edge. Detail → `game/ui/CLAUDE.md`.
  - **No world background art**: 10J's `background_master` ground-cache underlay
    was CUT before merge — it suppressed every `BACKGROUND`-zone tile so the art
    could show through. The world background is built from background tiles +
    deco props; `BACKGROUND` tiles always render. `ui.FX.bg_art` survives only as
    a balancing-parity key (nothing reads it at render time).

## Large-map performance — INVARIANTS (why/detail → `game/PERF.md`)
These are load-bearing; a regression drops a 1024² map to ~2 fps. Rules only here:
- **Every tile-state write goes through `TileMap.set_tile_state`** (keeps the
  `_by_state` index consistent; HUD tile queries are O(result), not full scans).
- **Placement occupancy is incremental** — `occupancy.set` per placed tile; the
  full-map `sync_occupancy` is a rebuild-only variant, never on the placement path.
- **No full-map scans on routine actions** — `_find_2x2` (spawn-recede) uses an
  expanding-window search, byte-identical to the old full scan.
- **Ground terrain draws through the scrolling `GroundCache`**, fed the
  `band_render_items` diagonal-strip emitter (NOT `visible_render_items`),
  with `TileMap.terrain_overrides` as `code_overrides` so unlock/recede zone
  changes show; `tile_map.on_zone_change = ground_cache.invalidate` (wired in
  `build_gameplay`) repaints the cache once per zone change, never per frame.
- **GC is frozen after `build_gameplay`** (`freeze_static`), gated to windowed runs
  (`tune_gc`) — headless boots must not have GC state mutated.
- **Base pathfinding is a shared flow field** — `find_path` /
  `find_path_ignoring_walls` walk ONE cached reverse-Dijkstra field from the
  base instead of a Dijkstra per enemy spawn. INVARIANT: every weight or
  blocking mutation must bump `TileMap._path_version` (zone/content writes go
  through `set_tile_state`/`set_tile_content`; wall add/remove/death and the
  pre-query weight producers bump internally) — a missed bump serves stale
  paths. See `game/PERF.md`.

## Conventions (whole package)
- Game classes subclass `GameObject` but keep ALL state in components (engine rule)
  — the editor's inspector and save/load depend on it.
- No pygame calls in gameplay logic; visuals are submitted as RenderItems via
  `SpriteAnimator`. HUD/menus may use the direct HUD layer (G-6), pygame-free.
- Every tunable comes from `data/balancing/` at startup (G-7). New constant → add
  it to the domain's JSON + schema, never hardcode. ×10 combat HP/DMG scale
  applies; `BASE_HP` stays 10. (Use `/add-balancing-value`.)
- Combat-capable buildings advertise capability via components/tags (the
  prototype's `IS_COMBAT` contract) — core sweeps must stay type-agnostic.
- **Phase machine + income ordering** (snapshot → income → upkeep → painters →
  revive → cleanup) is prototype-exact (G-5); **do not reorder without the user.**

## Porting protocol (PLAN phase 9+)
Port one domain at a time, prototype as spec: acceptance checklist → runnable test
→ implement → iterate until green → live playtest. State what you verified (smoke
test vs live round vs static read).

## Verify before finishing
Headless smoke test (`tools/smoke.py`) after every change; live `py game/main.py`
round for phase/combat/UI behavior. If balance changed: schema validation passes,
lock respected.
