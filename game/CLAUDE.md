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
| `debug/` | `game/CLAUDE.md` (this section) | `DebugRecorder` — structured run telemetry (JSONL/CSV/MD/HTML) for balancing + LLM debugging |
| `tutorial/` | `game/CLAUDE.md` (this section) | `TutorialDirector` — binds the engine sequencer to real tiles/cards/buttons |

Perf deep-dive → `game/PERF.md`.

## Debug mode — structured run telemetry (debug-mode-telemetry)
`game/debug/` is a pure package (no pygame, no `data/` I/O — its own
`TestPurity`) hanging a `DebugRecorder` off `Session.debug`, `None` by default
— the `tutorial_director` precedent (`game/core/CLAUDE.md`). Every emit site
across the game is `if session.debug is not None: session.debug.<call>(...)`,
so debug-off costs one attribute check per site and a bare `Session` a logic
test builds is byte-identical. See `game/debug/events.py`'s module docstring
for the full event-kind contract (what an LLM or a human reads) and
`game/debug/recorder.py`'s docstring for the `DebugRecorder` API.
- **Level 1 (`LEVEL_BASIC`)** — the causal trace: waves, placements, unlocks,
  research, deaths, base hits, kidnaps, lightning, payday, the per-round
  summary row, level-ups, boss choices, cheats, game over. Emit sites:
  `game/core/session.py` (`end_turn`/`on_base_hit`/`on_enemy_death`/
  `on_kidnap`/`resolve_levelup`/`resolve_boss_cutscene`/`lightning_strike`/
  every `cheat_*`), `game/core/payday.py` (`run_payday`'s three hooks, see
  that doc's payday section), `game/ui/building_ui.py` (`_do_place`, the
  upgrade panel's tier-advance branch).
- **Level 2 (`LEVEL_VERBOSE`)** adds per-tick combat detail via
  `resolve_combat(..., on_damage=None)` (`game/enemies/combat.py`) — the
  ESV-5/ESV-6 optional-callback precedent, `None` keeping every existing
  caller byte-identical. **One damage site cannot be reached through that
  parameter**: an enemy attacking a blocking building/wall
  (`game/enemies/components.py EnemyCombat.update`) runs inside
  `Scene.update`, which the host calls BEFORE `resolve_combat` each frame —
  so `components.py` exposes its own module-level seam,
  `set_damage_hook(fn)` (the `game/ui/widgets.py set_skin_hit_test`
  precedent: unset by default, installed by `game/main.py` only when the
  recorder's level is >= 2, bracketing the `scene.update()` call). Its
  sibling `set_wall_damage_hook(fn)` covers the edge-WALL branch of that
  same method: a wall carries no `Health` and no `RoundStats` and spans an
  EDGE rather than sitting on a tile, so it needs its own shape and its own
  seam — detail in `game/enemies/CLAUDE.md`.
- **Two documented gaps in the event contract, both deliberate.**
  `defender_fire` reports only the muzzle POINT (`resolve_combat`'s
  `on_defender_fire` callback carries nothing else, and telemetry does not
  widen a gameplay signature to find out more), and a beam defender never
  emits it at all — it is hitscan and fires no projectile. `enemy_spawn` is
  **declared but never emitted**: the only per-enemy entry point is
  `Spawner.update`'s pop, which has no host seam; the per-round count is
  complete via `note_spawn` at `wave_start`. Both are spelled out in
  `game/debug/events.py`'s docstring so the contract does not lie.
- **`game/main.py`** wires the whole thing: `main(debug_log=None)` accepts
  `None` (off), an `int` level (builds a fresh `DebugRecorder` writing to
  `REPO / "logs"`), or an already-constructed `DebugRecorder` (the seam
  headless callers/tests drive directly — see that function's docstring).
  The recorder is bound to the fresh run's `RunState` and assigned to
  `session.debug` inside `build_gameplay()`; `set_frame()` is stamped once
  per simulated frame; `close()` is called at the GAME_OVER transition, in
  `teardown_gameplay()` (quit-to-menu / the game-over screen's MAIN MENU
  button), AND again (idempotent — a no-op every time after the first) just
  before `pygame.quit()`, so the four artifacts
  (`-events.jsonl`/`-rounds.csv`/`-summary.md`/`-report.html`) are always
  written.
- **Three activation surfaces, all built on that one seam.** `recorder` is a
  plain `main()` local (never nested in an `if`) precisely so each of them can
  reassign it with `nonlocal`:
  1. **CLI** — `--debug` / `--debug=N`, parsed by `debug_level_from_argv` in
     the `if __name__ == "__main__"` block. Hand-rolled, not argparse, so
     `max_frames`/`autostart` (a headless TEST seam) stay off the command
     line; a bad level exits loud rather than booting un-instrumented.
  2. **Main menu `PLAY DEBUG` + its gear** (`game/ui/CLAUDE.md`) — the shell
     returns a new `"new_game_debug"` intent, and `execute()` builds the
     recorder from `shell.debug_settings` BEFORE `build_gameplay()`.
  3. **Cheat menu `Debug Log`** — arms/disarms mid-run (`session.debug` is a
     plain public attribute). Both directions emit a `cheat` event: the
     `debug_log_on` marker is where capture STARTS, and it latches the round
     row's `cheated` flag, because a part-way-captured run is not clean
     balance data either.
- **A FOURTH gate sits in front of all three: `data/balancing/core.json`'s
  `Debug` group** (player-identity). `main.py` passes it into the `Shell`
  as `debug_balance=core_balance["Debug"]` — indexed DIRECTLY, never `.get`,
  because the schema requires the key and missing data must fail loud (D-2);
  `Shell`/`MainMenu` still default it to `{}` so every bare construction (the
  exporter, the golden pin, every test) reads each flag as its permissive
  default. Three flags: `regular_mode_available` / `debug_mode_available`
  hide either launcher row, and `ask_player_identity` decides whether PLAY
  DEBUG puts the identity prompt up first (off ⇒ it starts an unstamped debug
  run immediately). **The availability matrix's fail-safe**: both modes off
  reverts to regular-only with ONE latched warning — never ship a menu with no
  way to start a game. Debug-only keeps the START NEW GAME slot (and its
  `btn_new_game` id) but emits `"play_debug"` from it; the id/action
  decoupling that makes this possible is `game/ui/CLAUDE.md`.
- **The run id is player-stamped.** `DebugRecorder(..., player_name=,
  player_skill=)` folds `slug_player(name, skill)` into an auto-generated run
  id, so **all four artifact filenames** carry the player, and the MD/HTML
  reports grow a `Player:` header. `_new_recorder()` reads the pair off
  `shell.player_identity` (the level/outputs still come from
  `shell.debug_settings`, which the `Shell` itself seeds from the same `Debug`
  balancing defaults — ONE source, no drift). **Both `RUN_START` emit sites**
  (`build_gameplay()` and the cheat menu's `toggle_debug` arm) read
  `recorder.player_name`/`.player_skill` off the RECORDER, never off the
  shell, so the event can never disagree with the run id the artifacts are
  named after. An unnamed/regular run produces exactly the run id it always
  did.
- **One high-score row is recorded at the GAME_OVER transition, INDEPENDENTLY
  of the recorder.** Beside the existing `session.debug.close(outcome=
  "game_over")` call, `main.py` appends a `game.core.highscores.make_entry(...)`
  row to `scores/highscores.json` (the gitignored per-machine play history at
  the repo root — NOT `data/`; it still goes through `write_validated` against
  `data/schemas/highscores.schema.json`, so the single write path holds). A
  regular run has no recorder and still records a row — `make_entry`
  normalises the `(None, None)` identity to `Anonymous` / `unknown`, and
  `run_id`/`debug` are `None`/`False`. A `main()`-scoped `score_recorded`
  latch (reset in `build_gameplay()`) makes it fire at most once per run, and
  is set BEFORE the append so a raising write cannot retry every frame; the
  append is wrapped in `try/except Exception` with ONE logged warning, because
  a read-only disk must never crash a finished run on the game-over screen.
  The host also loads that document at boot (seeding the high-score table and
  pre-filling the identity prompt via `Shell.set_highscores`/
  `prefill_identity`) and RE-READS it on the shell's `"open_highscores"`
  intent, so a run that just finished shows up.
- **`tools/simrun.py`** is the headless balance-sweep host — real active map,
  real balancing, real `Session`/`resolve_combat`/`place_building`, no
  window, one seeded RNG, writing the same four artifacts to
  `logs/sim-<strategy>-<seed>-*`. It answers for the player: what to build
  (`game/debug/policies.py`, the pure `(state, tilemap, buildings_balance) ->
  [(tile, building_type)]` contract), when to unlock territory and end the
  turn, and the two modal phases (LEVELUP/BOSS_CUTSCENE freeze the world and
  would otherwise deadlock). `policies.py` is deliberately NOT re-exported
  from `game/debug/__init__.py` — it imports `game.buildings.registry`, and
  `game.core.session` imports `game.debug` at module scope, so exporting it
  would close an import cycle.

## VFX variant selection (`vfx_variants.py`, `vfx_misc.py`, VfxAuthoringPLAN VA-2)
Two small top-level modules owning the GAME half of "which of this effect's
interchangeable sprites plays this time". The pure registry half (which slots
are a family, clamped indexing) is `engine/vfx/variants.py`, which is kept free
of this vocabulary exactly as `engine/vfx/params.py` is kept free of spark
preset names (D5).
- **`vfx_variants.py`** — `RANDOM`/`LEVEL`/`MISC` (the `variant_select.mode`
  enum), `source_level(obj)` and `resolve(registry, slot_key, mode, misc_key,
  *, rng=None, source=None)`. **`resolve` short-circuits before any mode logic
  when a slot has fewer than two variants, and that is load-bearing, not an
  optimisation**: every vfx slot ships with exactly one variant, so drawing an
  RNG number on the common path would consume from the shared global stream
  and desync every downstream roll from what the game did before this feature.
  VA-2 is a visual no-op only because that branch exists;
  `tools/tests/test_vfx_variants.py` pins it with a draw-counting Random.
  `source_level` reads a building's `TierState.current_tier` or an enemy's
  `_enemy_era` transient — reaching into that underscore is deliberate (it is
  set on EVERY enemy at construction, including the boss, whose public `era`
  is a different number off `DeathSpawn`), and the alternative is widening
  `RunState.*_events` and the `resolve_combat` callbacks to thread a level
  through for a cosmetic lever, which D4 declines. No source in hand ⇒ variant
  0 — the answer at the five events that carry only a world point.
- **`vfx_misc.py`** — the "misc value" provider registry: `register(key, fn)` /
  `resolve(key) -> int` / `unregister` / `clear` / `registered`. **Nothing
  registers a provider today, and that is the point**: a designer can author a
  `misc_key` in the editor before the code that feeds it exists. EVERY failure
  mode resolves to 0 and none of them raise (unregistered key, empty key, a
  provider that throws, a non-integer return) — this is a cosmetic lever, so a
  bad provider must pick the first variant, not take down the frame that
  consulted it. An empty key cannot be registered: `""` is what every trigger
  row ships with, and binding it would turn every un-configured misc row live
  at once.
- **`editor/` mirrors the mode→index mapping rather than importing it** (that
  package may never import `game/`) — the sanctioned duplication
  `editor/vfx_params.py` and `editor/timeline_curve.py` already are.

## Host conventions (`main.py`, Phase 2 → 10A)
- `main(max_frames=None)` is importable so `tools/smoke.py` can drive the same code
  headlessly (G-8); `py game/main.py` runs it windowed. `main(autostart=True)`
  skips the shell straight into GAMEPLAY (the headless seam).
- Frame order is fixed per E-14: input → `Scene.update(dt)` → render submit (grid
  tiles + `scene.render_items()`) → `flush` → `flip`.
- **Camera input mapping (E-5) lives here**, on pure engine camera state: **both
  left- and right-click-drag pan** (`cs.pan` + `cs.clamp`, which bounds the view
  to **map bounds ∩ the camera leash**). The leash is `core` balancing's
  `Camera.max_offset_tiles_x`/`max_offset_tiles_y` — how many TILES the viewport
  centre may stray from the map's **`camera_limit_center`** marker, `0` =
  unlimited. That marker is a separate paintable map object from
  `camera_start` precisely so the opening view and the play-area centre are
  independently placeable; a map that paints none falls back to `camera_start`,
  then to the map centre. `main()` builds the
  `engine.coords.CameraLimit` once at boot, right after `load_coordinate_system`
  and BEFORE the first `frame_camera()`, and installs it on `cs` via
  `set_camera_limit` — so drag-pan, `step_zoom` and `center_on` all honour it
  without a single extra call site, and `build_gameplay()`'s re-frame inherits it.
  Measuring in tiles (not pixels) is what makes the stop point land the same
  distance out at every zoom level. The editor never installs one — its viewport
  stays free-roam on purpose, so a designer can still see the whole map. Left-drag
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
  **Both halves of that mapping become CONDITIONAL when the DRAG SEL toggle is
  on** — left-DRAG box-selects instead of panning, and a right-click on an
  already-selected tile deselects it instead of dismissing. See the
  drag-selection section below; with the toggle off (the default, and its state
  every frame until the player clicks the button) everything above holds
  verbatim.
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
  matching HUD buttons + the lives-faces readout are **10L**. Both are
  REBINDABLE (below) — numpad `1`/`2`/`3` stay a fixed always-on alias
  alongside the rebindable primary key, since rebinding only ever changes
  which primary key fires the action.
- **Rebindable hotkeys (feature: rebindable hotkeys)**: every gameplay hotkey
  dispatches through `key_bindings[action]` (a live dict built at boot from
  `ui.json`'s `Keybindings` group + any player rebind in
  `scores/keybindings.json`, `engine.input.load_keybindings`) compared
  against `_binding_key_name(event)` — the pygame-keycode-to-neutral-string
  translator beside `_key_name`. 18 actions: `end_turn` (Space), combat speed
  ×3 (`1`/`2`/`3`), `quick_skip_combat` (`P`), `toggle_cheat_menu` (Ctrl+L),
  `toggle_heatmap`/`toggle_range`/`toggle_tier_overview` (H/R/T, the same
  flip `MapOverlays.hit()` does for their pills), `toggle_drag_select` (Q,
  the same flip the DRAG SEL HUD button does), `confirm_purchase` (Enter —
  only while a construct/move preview is open, routed through the SAME
  public `panel.handle_click` a mouse click on CONFIRM uses, aimed at that
  button's own centre, so keyboard and mouse can never disagree),
  `zoom_level_1`/`_2`/`_3` (`4`/`5`/`6` — an ABSOLUTE jump to the data-driven
  `core.json Camera.zoom_levels[i]`, sorted ascending, via the new
  `set_zoom_level(cs, index, view_w, view_h)`, `step_zoom`'s sibling sharing
  its `_recenter_zoom` recentring body; a no-op if that index doesn't exist,
  the combat-speed round-gate precedent), and `move_up`/`_down`/`_left`/
  `_right` (WASD — camera panning). Esc, F12 and text-editing keys
  (Backspace/arrows/Enter-while-typing-a-name) stay fixed system conventions,
  never rebindable. The in-game Settings → Controls screen
  (`game/ui/keybinds_screen.py`, `game/ui/CLAUDE.md`) surfaces 16 of the 18
  `Keybindings` actions for player rebinding; `toggle_cheat_menu` (a hidden
  dev feature) and `quick_skip_combat` (a testing convenience) are
  deliberately excluded from that screen but keep dispatching normally.
  Rebind capture (Esc cancels, a collision flashes, otherwise the key is
  written + persisted) is host-only logic (`main.py`'s `_handle_capture_key`)
  since `game/ui` must stay pygame-free.
- **WASD/arrow-key camera panning (feature: rebindable hotkeys)** is the ONE
  action group that is POLLED every frame (`pygame.key.get_pressed()`, right
  after the event loop, the `skip_held` cutscene precedent) rather than
  KEYDOWN-dispatched — panning must happen continuously while held, not once
  per press. `_binding_pygame_key(binding)` is the REVERSE of
  `_binding_key_name`: a binding string -> the pygame keycode to poll (a
  single alnum char resolves via `ord()`, a named key via the same lookup
  table `_binding_key_name` uses); `_binding_held(binding, keys_pressed)`
  wraps it with the `ctrl+`-modifier check. The 4 arrow keys ALWAYS pan too —
  a fixed always-on alias outside the rebindable set, exactly like numpad
  1/2/3 beside the rebindable combat-speed keys — so rebinding `move_up` only
  ever changes W. Speed is `core.json Camera.keyboard_pan_speed` (SCREEN
  pixels/second, zoom-independent — matching mouse-drag panning's own raw
  1:1-pixel behaviour, `cs.pan(-event.rel[0], -event.rel[1])`; a drag never
  scales by zoom either). **Gated exactly like mouse drag-panning**: only
  while `shell.state in _WORLD_STATES` (GAMEPLAY/GAME_OVER), never while
  `session.frozen` (LEVELUP/BOSS_CUTSCENE/ENEMY_INTRO), the cheat menu is
  open, a construct/move preview modal has focus (which also captures typed
  characters — WASD must not leak into a name field), or the upgrade panel's
  rename row is capturing keys.
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

## Drag-selection toggle (host wiring)
A HUD toggle (`btn_drag_select`, `game/ui/CLAUDE.md`) that turns ONE
left-press-drag-release into a rectangle selection reaching the same end state
10J's Shift+Click multi-select builds one click at a time. **With the toggle
off nothing here runs and click / Shift+Click / camera-pan behave exactly as
they always did** — every branch below is guarded on
`gp["drag_select_enabled"]`.
- **State**: `gp["drag_select_enabled"]` (bool, default `False`), seeded in the
  `gp` literal and reset beside `gp["sel"], gp["sel_cat"] = [], None` in BOTH
  `build_gameplay()` and `teardown_gameplay()`. It lives in `gp` rather than on
  the `Hud` because the event loop reads it directly; `Hud.submit` receives it
  per frame (`drag_select_enabled=`) only to draw the active rim, and
  `Hud.hit()` never mutates it (see that doc — `Hud.hit()` runs twice per
  click).
- **The toggle flip is ONE branch**, in `handle_world_click` right after the
  `("speed", idx)` branch: `hud_action == "drag_select"` inverts the flag and
  returns.
- **Arming (MOUSEBUTTONDOWN-left)**: `pan_from` is computed exactly as before,
  and only then re-routed — `pan_from is not None` IS the existing "this press
  began over the world, not a UI element" signal, so the new button, the panel
  and every other HUD element keep drag-select from arming over them **for
  free** (`over_ui` already calls `gp["hud"].hit(px, py)`, which now covers the
  new button). Armed only in the BUILDING phase; arming sets
  `drag_select_from`/`drag_select_current` (two event-loop locals holding
  **`Tile` objects, not screen coords**, so the preview survives a camera
  nudge) and clears `pan_from` — the gesture is never both.
- **Live preview**: a MOUSEMOTION `elif` sibling of the camera-pan arm
  (mutually exclusive: `pan_from` is `None` whenever `drag_select_from` is
  armed) updates `drag_select_current`; the world overlay pass draws the
  rectangle at the same point the tutorial tile highlight draws (before
  `gp["panel"].submit`) with `widgets.submit_tile_diamond_fill`, running the
  SAME `_SEL_CATEGORY` filter `finish_drag_select` does — so a tile shown can
  never fail to be selected on release.
- **Release (MOUSEBUTTONUP-left)**: the `<= _DRAG_THRESHOLD_SQ` short-press
  path is UNTOUCHED (a plain click, toggle on or off, still selects the one
  tile through `handle_world_click` → `update_selection`); a real drag past the
  threshold calls `finish_drag_select` instead.
- **`finish_drag_select(start_tile, end_tile)`** sits beside `update_selection`
  and reuses its `_SEL_CATEGORY` table and its "primary tile first" convention:
  the start tile's category is the batch's category, every tile in the
  normalized rectangle that shares it joins, and **locked/unowned tiles are
  silently skipped** (they carry no category — mirroring today's "a click can't
  hit them" rule). It runs the same `tutorial.allows(("tile", col, row))` D6
  gate every other tile click goes through, on the start tile AND on each
  candidate — zero-overhead outside the tutorial, and during it a drag
  collapses to at most the one highlighted tile instead of bypassing the
  whitelist. It then feeds `tutorial.on_tile_clicked` and
  `panel.open_for_tile(..., selected_tiles=picked)` — the existing batch UI,
  unmodified.
- **Right-click single-tile deselect** sits in `handle_world_right_click` after
  the game-over / cheat-menu / frozen-or-boss-cutscene guards and BEFORE the
  dismiss ladder, gated on `panel.preview is None` (a right-click over an open
  construct preview still peels the preview — Shift+Click never reaches the
  world there either). A right-click on a tile NOT in `gp["sel"]`, or with the
  toggle off, falls through to the universal dismiss unchanged.

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

## Scripted loss + stone-thrower chain + tutorial end (Phase TU-7)
TU-7 appends the round-2 half of the script to the SAME
`data/tutorial/tutorial.json` step list TU-6 built — round 1's chain flows
straight into it with no seam: after `highlight_end_turn_button` advances on
`end_turn`, the very next step is round-2's "wait for the scripted loss".
`TutorialDirector` binds `map_doc.tutorial_stone` exactly like TU-6 bound
`tutorial_flute` (same nullable-marker shape, same `"tile_click:tutorial_
stone"` / `"tile_clicked:tutorial_stone"` / `"tile:tutorial_stone"` naming
per the `_action_id`/event-feed/highlight-id conventions TU-6 established).
- **The scripted loss needs no new "force a loss" mechanic.** The tutorial's
  scripted round (round 0 since TU-9 — see below; this section predates that
  rework and originally read "round 1") has no defence building yet (only the
  flute chain fired), so the first enemy that reaches the hole IS the scripted
  loss — `Session.on_base_hit` already runs unconditionally. TU-7's only
  addition there is a **free-loss waiver**, gated on a NEW `TutorialDirector.
  charges_life_on_base_hit(round_num)` query (pure read, never mutates the
  sequencer): `True` (normal rules) unless the tutorial is active, `round_num
  == 0` (TU-9), the sequencer's CURRENT step carries `flags: {"is_scripted_loss":
  true}`, and the script's `first_loss_costs_life` is `False`. `on_base_hit`
  consults it immediately before `st.base_lives -= 1`; a waived loss leaves
  lives untouched and can never trigger `GAME_OVER`.
- **`Session.tutorial_director`** (new attribute, `None` by default, set
  alongside `tutorial_gate` in `build_gameplay()`) is how `on_base_hit` and
  `_begin_round_end` reach the director — `tutorial_gate` stayed a bare
  callable (End-Turn only), so the free-loss query and the round-end
  notification needed the real object.
- **`_begin_round_end` notifies the director unconditionally**
  (`director.on_round_end(round_num)`, a new event-feed method mirroring
  `on_end_turn`'s shape) on EVERY road to ROUND_END — wipe, normal
  wave-clear, quick-skip, cheat-skip alike. Harmless outside the exact step
  that's waiting on the `"round_end"` id (D6): `TutorialSequencer.advance`
  only ever moves past the CURRENT step, so a repeat or an off-step call is a
  no-op.
- **Message box #2** (`lives_intro`, already present in TU-1's schema/content
  — TU-7 added no new message key) has no Skip button, matching D7 ("only
  box #1 carries Skip"); its step's `allow` list omits `skip_tutorial`.
- **The stone-thrower (Defender, `BUILDING_TYPE = "defence"`) chain reuses
  every TU-6 primitive unchanged**: `allows(("card", "defence"))` /
  `_tutorial_allows_panel_click` / `ui_highlight_rects` needed zero new code,
  since TU-6 already read `building_type` generically off the clicked card
  rather than hardcoding `"economic"`. `on_building_placed` gained ONE
  generalization: economy placements still count toward `Tutorial.
  economy_buildings_required` before advancing; any OTHER building type
  (i.e. `"defence"`) advances the sequencer on a single placement — additive,
  the economy-counting path is untouched.
- **No separate "terminal step" object exists.** The round-2 chain's last
  step (`highlight_confirm_button_defence`, advancing on
  `building_placed:defence`) is simply the LAST entry in the step list — once
  `advance()` moves past it, `TutorialSequencer.finished` becomes `True` via
  its existing "past the last step" semantics, with no new engine code. (A
  literal step object with `advance_on: null` would instead get the sequencer
  PERMANENTLY stuck there, since `advance()` no-ops whenever the current
  step's `advance_on` is `None` — deliberately avoided.)
- **`engine/tutorial.py` needed no changes.** `charges_life_on_base_hit`
  reads the current step's flags via the sequencer's existing public
  `current` property (`Step.flags` is a plain dict field) — no new accessor
  was needed.

## Un-stick on panel close + close-panel hint (Phase TU-8)
Two fixes riding the SAME script/sequencer TU-6/TU-7 built.
- **Fix 1 — closing the panel mid-chain reverts, not dead-ends.** The card
  and Confirm steps of BOTH chains (`highlight_musician_card`/
  `highlight_confirm_button`, `highlight_defender_card`/
  `highlight_confirm_button_defence`) carry `revert_on: "panel_closed"` +
  `revert_to: <their own tile step id>` in the script — `engine.tutorial
  .TutorialSequencer.revert` is the new GENERIC backward move this needed
  (`engine/CLAUDE.md`). `TutorialDirector.on_panel_closed()` feeds the
  opaque `"panel_closed"` event; `main.py` calls it from EVERY panel-close
  path that did NOT just land a placement — the preview modal's own
  X/CANCEL (`_preview_click`'s `"close"`/`"cancel"` outcomes), the bare
  panel's own X (`handle_click`'s pre-mode `close_btn` branch), Esc in both
  states, and the right-click universal dismiss (`panel.dismiss()`) — each
  call site captures `panel.preview`/`panel.visible` BEFORE the panel call
  and compares after, so a click that only renamed/typed/rerolled the dice
  (preview stays open) or that a SUCCESSFUL placement cleared (guarded by
  the same `panel.last_placed_type` signal `on_building_placed` already
  used) never fires the event. `TutorialDirector` adds no new game-vocabulary
  concept here — `on_panel_closed` just calls `sequencer.revert("panel_closed")`.
- **Fix 2 — a close-panel hint step, flute chain only.** One new step,
  `highlight_close_panel_hint`, sits between `highlight_confirm_button` and
  `highlight_end_turn_button` in the SAME script (never mirrored after the
  round-2 defence placement — the tutorial ends there and input is
  released): `highlight: ["button:close"]` (resolved by
  `ui_highlight_rects` via a new additive `BuildingUI.close_rect()`,
  the `card_rect`/`confirm_rect` pattern) and `flags: {"banner":
  "close_panel_hint"}`, resolved by a new `TutorialDirector.banner_text()`
  against the script's `messages` map — **never the modal `message` field**,
  which would show the click-swallowing `TutorialMessageScreen` and block
  the very right-click it is meant to teach. Its `advance_on` is the SAME
  `"panel_closed"` event Fix 1 reverts on elsewhere; `on_panel_closed()`
  simply tries `sequencer.advance("panel_closed")` first, then
  `sequencer.revert("panel_closed")` — only one of the two can ever match
  the CURRENT step, so trying both is exactly as cheap as knowing which one
  in advance. End Turn stays un-highlighted AND unclickable for free: the
  step's `allow` list omits `button:end_turn`, the exact whitelist mechanism
  every other step already uses (no new gate).
- **The banner is NOT `TutorialMessageScreen`.** A new `widgets
  .submit_tutorial_banner(renderer, text, view_w, view_h)` (the
  `submit_ui_box_highlight` sibling, same `C_TUTORIAL_HIGHLIGHT` white) draws
  a big centred filled box + text with **no hit-test, no input
  consumption** — submitted in `main.py`'s overlay pass off
  `tutorial.banner_text()`, independent of (and drawn alongside)
  `ui_highlight_rects`'s Close-button ring. Never gates or gets gated.

## The tutorial is round 0 (Phase TU-9)
The tutorial's scripted round is **round 0**, not round 1 — real enemy
spawning/scaling now begins at round 1 exactly where it always numerically
started, whether the run went through the tutorial or was skipped. This
re-keys several call sites that previously read `round_num == 1` as "the
tutorial round"; TU-6/TU-7/TU-8's prose above predates this and still says
"round 1"/"round 2" in places describing the flute/stone chains conceptually
(script vocabulary, unaffected) rather than the literal round number (which
did change — see the fixed callouts above).
- **Seeding**: `build_gameplay()` (`main.py`) sets
  `gp["world"].session.state.round_num = 0` right after constructing
  `gp["tutorial"]`, but ONLY when `gp["tutorial"].active` is `True` — an
  inactive/auto-skipped director (old/unpainted map) and every bare `Session`
  a logic test builds are untouched, still defaulting to round 1
  (`RunState.from_balance`). This is the ONE seed site — deliberately host-side
  rather than a `Session`/`RunState` default, so those two stay unchanged.
- **`EnemyScaling.tutorial_round_enemy_count`** (`data/balancing/enemies.json`,
  default 1, minimum 0) is the ONLY thing round 0 ever spawns — exactly that
  many `"standard"` walkers, from a NEW early branch in
  `Spawner._compose` checked BEFORE the boss check and before `begin_round`'s
  tier formula: `0 % round_interval == 0` is true for every interval, so an
  unguarded boss check would wrongly treat round 0 as a boss round, and
  `(0 - 1) // n` goes negative — both are guarded explicitly rather than
  incidentally. `Session.end_turn`'s boss announce-marker check and
  `_begin_round_end`'s boss-cutscene-queue check gained the same `round_num
  != 0` guard for the identical reason (three sites total, `game/enemies/
  spawner.py` + `game/core/session.py` ×2).
- **Skip jumps straight to round 1.** `main.py`'s `handle_world_click` message
  branch, right after `tutorial.skip()`: `if session.state.round_num == 0:
  session.state.round_num = 1`. No round 0, no forced walker, normal wave
  scaling from there — a host-side concern (the director holds no `Session`
  reference).
- **The cutscene no longer keys on `round_num == 1`.** `RunState` grew a
  one-shot latch, `first_end_turn_cutscene_requested` (bool, never
  serialized, sitting beside `pending_cutscene`); `Session.end_turn()` requests
  the `first_end_turn` cutscene the first time this is `False`, regardless of
  round number, then sets it `True` — fires once whether the run's first End
  Turn is round 0's (an active tutorial) or round 1's (a skipped run), and
  never again after that.
- **HUD**: `game/ui/hud.py`'s round label shows the literal word `"Tutorial"`
  at `round_num == 0`, `f"ROUND {n}"` otherwise (`game/ui/CLAUDE.md`'s HUD
  readout-ids section — the round label is still code-owned text, override
  surface unchanged). `game_over.py`'s "Round Reached" readout was
  deliberately left alone.
- **`TutorialDirector.charges_life_on_base_hit`** re-keyed from `round_num !=
  1` to `round_num != 0` (see the TU-7 section above) — no other
  `TutorialDirector`/`TutorialSequencer` change; the script's step ids/event
  feed are unaffected, only which literal round they fire on shifted down by
  one.

## Wall + tile-highlight render order — host wiring (fix/depth-sorted-world-fills)
Every tile-diamond highlight (click/drag-select, condition tint, RANGE,
HEATMAP, TIER OVERVIEW, the tutorial highlight) and every wall segment now
draws through `Renderer.submit_world_fill`/a `RenderItem` on the `entities`
layer — the SAME depth-sorted queue buildings use (`engine/render/CLAUDE.md`'s
"Depth-sorted world fills"; the wall side of it is `game/map/CLAUDE.md`'s
"Edge walls are LIVE" section). Position-based depth against a building on a
DIFFERENT tile is automatic (the ordinary iso sort). `main.py` owns the ONE
thing position can't resolve — a same-tile TIE, broken by submission order:
- **Highlights submit BEFORE `world.scene.render_items()`** (`gp["overlays"]
  .submit(...)`, the tutorial highlight, the drag-select live rectangle,
  `gp["panel"].submit(...)`) — so a same-tile building draws ON TOP of its
  own highlight.
- **Wall edges split around it**: the two far sides (`edge_nw`/`edge_ne`)
  submit BEFORE (same-tile building draws over its own back wall); the two
  near sides (`edge_se`/`edge_sw`, `game.map.wall_render.FRONT_SIDES`) submit
  AFTER (a same-tile building draws BEHIND its own near wall — a fence in
  front of a house). `wall_render_items()` still returns one unfiltered list;
  `main.py` partitions it by `item.animation in FRONT_SIDES` at the call site.

**A prior version of this fix (fix/highlight-render-order) tried to solve
the highlight half by reordering these same submission calls, without
changing the underlying primitive — a real no-op bug**: `widgets
.submit_tile_diamond`/`_fill` used to go through `Renderer
.submit_overlay_lines`/`submit_overlay_polys`, a SEPARATE pass `flush()`
always draws dead last, after every world sprite, regardless of submission
order. Reordering the calls changed nothing about the rendered frame. Fixed
by routing those two helpers through `submit_world_fill` instead — see
`engine/render/CLAUDE.md` for why `submit_overlay_lines`/`submit_overlay_polys`
remain correct AS-IS for their other consumers (editor grid lines, anchor
handles, splatters/craters, which are deliberately drawn over sprites) and
are not what a new "draw this behind a building" consumer should reach for.

## Building Movement — host wiring
The feature's rules are `game/buildings/movement.py`
(`game/buildings/CLAUDE.md`), its panel/modal `game/ui/building_ui.py`
(`game/ui/CLAUDE.md`). `main.py` owns exactly two pieces:
- **The destination click.** `handle_world_click`'s BUILDING branch gained one
  check immediately after `tile = tile_at_screen(...)`: while
  `panel.mode == "move_select"`, the click is the destination pick and never a
  selection change — `_pick_move_destination(tile, session)` then `return`
  (the phase/mode-conditional shape the ENEMY-phase lightning branch below it
  already has, not a new subsystem). A click on anything but a legal tile
  (unbuilt BUILDABLE and not already `tilemap.is_moving`) is a **silent
  no-op** so the player keeps picking; the panel is the cancel affordance.
  The helper only OPENS a `MovePreview` — `start_move` (via
  `BuildingUI._do_move`) stays the single legal seam that moves anything.
- **The in-transit signpost.** A loop over `world.tile_map.moving_orders` in
  the world-overlay pass (beside the tutorial tile highlight, before
  `panel.submit`) draws the `moving_sign` slot as a `HudSprite` at BOTH
  endpoints plus a `submit_text` round countdown. `moving_sign_art` is a
  boot-time `manifest.entry(MOVING_SIGN_SLOT) is not None` bool, derived once
  exactly like `condition_art`/`tree_slots`/`wall_art` — E-37: an unimported
  slot draws only the countdown, never a grey X. `moving_orders` is empty on
  effectively every frame, so this costs one list check.

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
py tools/smoke.py                             # headless data validation + 5-frame boot
py -m pytest tools/tests/test_<area>.py -q    # the files your change touches
```
**Which tests you may run is ROLE-scoped — the role table in §"Test Suite
Policy" (root `CLAUDE.md`) is the only authority, and a `PreToolUse` hook
enforces it.** A subagent stops at the two commands above. The single full
`py tools/testgate.py check` belongs to the MAIN SESSION at handoff and is not
yours to run from here. The gate is ZERO failures — `GATE PASS` or you're not
done.
Then a live `py game/main.py` round for phase/combat/UI behavior. If balance
changed: confirm schema validation passes — and that is all. **The prototype
parity gate is deleted** (the migration is complete), so a balance value that
diverges from the prototype needs no mapping entry, no `OVERRIDDEN` tag and no
justification to a test. Retune freely; the schemas are the only guard rail.

**Seed the RNG in any test whose outcome depends on it.** The spawner takes an
injectable `rng` precisely so tests are deterministic; a test that used the bare
`random` module failed roughly one run in ten for reasons unconnected to what it
was measuring.
