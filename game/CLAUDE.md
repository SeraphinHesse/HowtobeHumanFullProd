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
`game/**` and `data/balancing/*` (schema-valid writes only). Never
import or edit `editor/**`. Engine changes are a cross-package task — tell the
user.

## Layout & domains
- `main.py` — the ONLY entry point (`py game/main.py`): pygame window, engine loop,
  input routing. Documented in this router.
- `map/` · `buildings/` · `enemies/` · `core/` · `ui/` — mirror the prototype's
  five balancing domains, which still scope file ownership and branch naming.
  Each has its own doc:

| Domain | Doc | Owns |
|---|---|---|
| `map/` | `game/map/CLAUDE.md` | runtime TileMap over the map doc; pathfinder; picking; occupancy |
| `buildings/` | `game/buildings/CLAUDE.md` | Building hierarchy; components; registry/placement; research gates |
| `enemies/` | `game/enemies/CLAUDE.md` | Enemy walker; spawner wave queue; type-agnostic combat sweep |
| `core/` | `game/core/CLAUDE.md` | phase machine; payday ordering; XP / village level-up; balance loader |
| `ui/` | `game/ui/CLAUDE.md` | HUD; building panel; floaters; level-up modal; shell + menus |
| `tutorial/` | `game/CLAUDE.md` (this section) | `TutorialDirector` — binds the engine sequencer to real tiles/cards/buttons |

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

## Tutorial director (Phase TU-6)
`game/tutorial/director.py` (`TutorialDirector`, no doc of its own — the
package is one file) binds `engine.tutorial.TutorialSequencer`'s opaque ids to
real tiles/cards/buttons for the round-1 guided flute-placement chain. This is
where "flute"/"economic"/"confirm" vocabulary lives — never in
`engine/tutorial.py` (D2).
- **Construction** (`build_gameplay()`, alongside `gp["panel"] =
  BuildingUI(...)`): `TutorialDirector(data_dir, map_doc,
  core_balance["Tutorial"])` reads `data/tutorial/tutorial.json` (TU-1) + the
  map doc's `tutorial_flute` marker. Either missing/invalid → ONE logged
  warning, an empty already-`skip()`ped sequencer, `self.active = False` —
  NEVER raises, so an old/unpainted map is always fully playable from frame 1.
  `TutorialMessageScreen` (the Continue/Skip message box, `game/ui/CLAUDE.md`)
  is built right after, sharing `shell.skinning` like every other gameplay
  screen.
- **The gate sits in the UI layer, not the placement seam** (D6):
  `place_building`/`registry.py` are untouched. Three choke points, matching
  the plan's own file-scope note verbatim:
  1. `handle_world_click`'s message branch — while
     `tutorial.message_visible`, the message box consumes EVERY click
     (highest priority bar GAME_OVER), routing Continue/Skip to
     `tutorial.on_message_dismissed()`/`tutorial.skip()`.
  2. `_tutorial_allows_panel_click(mx, my)` wraps both `panel.handle_click()`
     call sites (the preview-modal branch and the normal branch): it checks
     `tutorial.allows(("confirm",))` / `tutorial.allows(("card", btype))`
     ONLY when the click actually lands on the Confirm button / a construct
     card — every other click inside the panel (close, cancel, the name box,
     the dice reroll) passes through UNGATED, a deliberate simpler reading
     over the stricter "reject literally everything" prose (flagged, not
     guessed at silently). The tile-pick branch gates the same way:
     `tutorial.allows(("tile", col, row))` before `update_selection`.
  3. `Session.tutorial_gate` (`game/core/CLAUDE.md`) — set to
     `gp["tutorial"].allows_end_turn` in `build_gameplay()`; `end_turn()`
     checks it right after its existing BUILDING-phase guard. No keyboard-wide
     gate exists or is needed — `K_SPACE`'s dev-convenience `end_turn()` is
     gated by the SAME `Session` check, so it cannot bypass the chain.
- **Event feed**: a successful gated action calls the matching
  `on_*` hook (`on_tile_clicked`/`on_card_selected`/`on_building_placed`/
  `on_message_dismissed`/`on_end_turn`) to advance the sequencer.
  `panel.last_placed_type` (one extra transient `BuildingUI` field, additive)
  is how `main.py` detects "a placement just landed" vs. a cancelled preview,
  since both clear `panel.preview` the same way.
  `on_building_placed` keeps its own running counter so
  `Tutorial.economy_buildings_required` > 1 holds off the End-Turn unlock
  until every required placement lands, even though the shipped default (1)
  can't live-exercise that path.
- **Rendering**: `tutorial.tile_highlight_targets()` (0 or 1 `(col, row)`
  pairs) draws a white `submit_tile_diamond` in the world overlay pass, before
  `panel.submit()`; `tutorial.ui_highlight_rects(panel, hud)` resolves
  `"card:*"`/`"button:confirm"`/`"button:end_turn"` highlight ids into screen
  rects (via `panel.card_rect()`/`panel.confirm_rect()`/`hud.end_turn.rect`,
  `None` skipped — never crashes mid-transition) for
  `widgets.submit_ui_box_highlight`, drawn after the HUD; the message box
  submits last. Detail on the widgets/screen side → `game/ui/CLAUDE.md`.
- **D6 zero-overhead contract**: an inactive/skipped/finished tutorial costs
  exactly one `finished` bool check per gated call site — `TutorialDirector`
  and `TutorialSequencer` both fast-path every query to the "always allowed"
  answer once finished.

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
```bash
py tools/smoke.py              # headless data validation + 5-frame boot
py tools/testgate.py check     # the gate is ZERO failures — GATE PASS or you're not done
```
Then a live `py game/main.py` round for phase/combat/UI behavior. If balance
changed: confirm schema validation passes — and that is all. **The prototype
parity gate is deleted** (the migration is complete), so a balance value that
diverges from the prototype needs no mapping entry, no `OVERRIDDEN` tag and no
justification to a test. Retune freely; the schemas are the only guard rail.

**Seed the RNG in any test whose outcome depends on it.** The spawner takes an
injectable `rng` precisely so tests are deterministic; a test that used the bare
`random` module failed roughly one run in ten for reasons unconnected to what it
was measuring.
