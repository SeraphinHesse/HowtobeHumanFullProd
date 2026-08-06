# Code Quality Review — full repo scan (2026-08-06)

Scope: every package on `Development` (reviewed at merge commit `d104be4`) —
`engine/` (36 files), `game/` logic + `game/ui/` (57 files), `editor/` (20
files), `data/`, `tools/` + the full test suite (908 tests, actually run
headless). Five parallel reviewers read every source file; mechanical layering
checks were run repo-wide; the three headline bugs below were re-verified by
hand against the code.

## TL;DR

The architecture the docs claim is the architecture the code has. Layering
(engine ← game, engine ← editor, never game ↔ editor), schema-validated data
writes, pygame containment, and data-as-single-source-of-truth all hold under
inspection — this is **not** a spaghetti codebase. The real debt is
concentrated and mechanical:

1. **3 verified bugs** (one latent crash, one confirm-less destructive delete,
   one wrong cost preview).
2. **10 editor tests fail on a clean checkout** because they assert on live
   `data/` content that has since changed (and they surfaced 2 more probable
   editor bugs).
3. **Two god files** in `game/ui/` and gameplay logic accreting into closures
   in `game/main.py`.
4. A `game.core ↔ game.buildings` **import cycle** papered over with three
   lazy imports.
5. Assorted dead scaffolding, duplication, and doc drift (full list below).

Test suite result (headless, after installing `libegl1` — a container gap, not
a repo problem): **11 failed, 890 passed, 7 skipped, 857 subtests passed**.
`tools/smoke.py` passes: 20 data files schema-valid, 5 headless gameplay
frames, shell boot OK.

---

## Verified bugs (fix first)

### B1 — Latent crash on the first gameplay frame of a hole-less map — HIGH
`game/enemies/combat.py:434` — `_resolve_base_arrivals` calls
`tilemap.get(tilemap.base_col, tilemap.base_row)` unguarded. Hole-less maps
are explicitly supported (`game/map/tile_map.py:82-87` sets
`base_col = None`; the pathfinder guards it at `pathfinder.py:131`), but
`TileMap.get(None, None)` hits `0 <= None` → `TypeError`
(`tile_map.py:210`). `resolve_combat` runs every frame, so any map without a
hole crashes on frame one of gameplay.
**Fix:** early-return when `tilemap.base_col is None`.

### B2 — Editor "Clear" deletes assets with no confirmation — HIGH
`editor/panels/details.py:165` —
`self._clear_btn.clicked.connect(self.clear_entry)` passes Qt's
`clicked(checked=False)` into `clear_entry(confirm=True)`, silently turning
`confirm` off: Clear deletes the imported PNG + manifest entry with **no
dialog**. This is exactly the trap `editor/panels/CLAUDE.md` warns about
(`map_details.py:134` does it correctly with a lambda).
**Fix:** `self._clear_btn.clicked.connect(lambda: self.clear_entry())`.

### B3 — Batch-build hover shows per-building cost, spends total — MED
`game/ui/building_ui.py:562` — hovering CONFIRM on the construct preview sets
`self._hover_cost = self.preview.cost` (one building), but the actual spend is
`total_cost` (cost × count); the construct-card hover path multiplies
correctly (`:573`). Shift multi-select batches under-report the love-pill
"remaining" preview.
**Fix:** use `self.preview.total_cost`.

### Probable bugs surfaced by the failing tests (need triage)
- `import_sheet()` rejection path leaves a partial PNG copy on disk
  (`test_details_panel.py::test_too_small_sheet_rejected` — the reject returns
  `None` but the copied file exists).
- With all layer eyes off, the editor viewport still submits 1 sprite — some
  render item (base / start-area / deco?) is not wired to any eye
  (`test_editor_map_mode.py::TestRenderPath::test_layer_eyes_filter_submitted_items`).
- `test_run_controls.py::test_build_finished_reemits_build_state` is
  order-dependent (fails in the full run, passes alone) — shared Qt state not
  reset between tests.

---

## Test suite health — HIGH priority as a group

10 of the 11 failures are one root cause: editor tests copy the **live**
`data/` tree (`TempDataCase`, `test_editor_panels.py:65`) and hardcode
assumptions about its mutable content —

- `painter_t1_lvl1` assumed to have no manifest entry ("unassigned → grey X"),
  but `asset_manifest.json` now carries it;
- the active map assumed to be `first_light`, but the committed pointer is now
  `summertest2` (`data/maps/active_map.json`) — which `data/CLAUDE.md:146-147`
  says shouldn't be committed that way in the first place.

**Fixes:** (a) repoint `data/maps/active_map.json` to `first_light` (via the
validating writer) per the documented policy, and decide what to do with the
committed scratch maps (`test`, `test2`, `summertest1`, `summertest2`);
(b) make `TempDataCase` synthesize the manifest/active-pointer state each test
needs instead of asserting on live content, so a designer importing an asset
can never turn CI red again.

Structural test debt: no `conftest.py` — 17 files repeat the SDL-dummy
preamble, 7 repeat the QApplication-singleton block, 8 hand-roll their own
`copytree(data/)`, and `TempDataCase` lives inside a test module imported by 7
siblings. One `conftest.py` + a non-test helper module collapses all of it.

Otherwise the suite is genuinely good: expectations are derived from
`load_balance` instead of duplicating balance literals, only 2 conditional
skips, docstrings map to SPEC IDs.

---

## Structural findings (the "spaghetti watch" list)

### S1 — `game/ui/building_ui.py` (1,139 lines) is the one true god file
Eight responsibilities in one class (ConstructPreview modal, 4-mode panel
state machine, unlock chunk math, construct list, upgrade + rename + tier
preview, base-info incl. lightning + boss popup, terrain tooltip, love-spend
transactions), with the 4-way mode dispatch **triplicated** as parallel
if/elif chains in `hover` (567-595), `handle_click` (613-635) and `submit`
(812-819). Suggested split: `game/ui/panel/` package — `construct_preview.py`,
thin `panel.py` dispatcher, one module per mode with `hover/click/submit`.

### S2 — `game/ui/effects.py`: `FloaterManager` is a misnamed grab-bag
Floaters + particles + splatters + boss announce + gold highlights + slashes +
watchers, plus seven `submit_*` methods that read only `scene`/`cs` and touch
no instance state (`:439,477,500,516,571,590,675`). Moving the stateless
scene-readers into a `scene_fx.py` module leaves a real FloaterManager and two
~350-line files.

### S3 — Gameplay logic hiding in `game/main.py` closures
`main.py` (782 lines) is mostly a defensible shell, but the click-consume
priority ladder (`handle_world_click`, :335-398), the shift multi-select state
machine (:404-431), the cheat dispatcher (:304-333) and the untyped 13-key
`gp` dict (:237-239) are real game logic that is not headlessly testable.
Suggested: extract a pygame-free `GameplayController` (takes a shift flag as
an argument); main.py stays as the window/event/render pump.

### S4 — `game.core ↔ game.buildings ↔ game.map` import cycle
Three documented lazy imports paper over one structural cycle
(`game_state.py:110`, `session.py:213`, `building.py:100`): `RunState` can't
be seeded without the buildings `RESEARCH` table. `game/core/balance.py` has
no core dependency — moving it (or the research seed) below the packages
dissolves the cycle and all three lazy imports.

### S5 — Armed-brush state quintuplicated in the editor
`viewport.py:242-281` + `palette.py:64-77,459-536`: five parallel
`_armed_*` fields, five mutually-clearing setters, five signals — ~40 lockstep
lines per new brush kind. One `(kind, value)` tuple + one `brush_armed`
signal.

### S6 — Text-entry widget implemented 4×
Key handling + the "stone box / focus border / placeholder / `_` cursor"
render block copy-pasted in `building_ui.py` (×2), `add_name.py`,
`cheat_menu.py`. One `TextField` in `widgets.py`.

### Explicitly checked and NOT a problem
`engine/tilemap.py` vs `game/map/tile_map.py` is a legitimate layer split
(file-format model + render emitters vs runtime zone/unlock wrapper), not
duplication — though the identical basename invites confusion. Same for
`engine/render/hud.py` vs `game/ui/hud.py` (primitives vs emitter).

---

## Rule-adherence audit (the project's own pillars)

| Rule | Verdict |
|---|---|
| game ↔ editor never import each other | ✅ holds, enforced by a test (`test_editor_viewport.py:190-210`) |
| game logic pygame-free | ✅ pygame only in `game/main.py`; editor only in `viewport.py` with dummy drivers |
| engine never imports game/editor | ✅ zero occurrences; pygame confined to the 7 documented render/media modules |
| data/ writes via validating writer | ✅ editor + game clean; sole raw `json.dump` is the gitignored `.editor_prefs.json` |
| data/ formatting deterministic | ✅ all 20 files byte-exact canonical; schema pairing complete both ways |
| data/ is the ONLY value store | ⚠️ mostly — exceptions listed below |
| small single-purpose files | ⚠️ building_ui.py, effects.py, main.py closures (S1-S3) |

**Data-as-truth exceptions found in code:**
- `game/buildings/boost.py:122,128,142` — flat-mode `boost_value() * 10`;
  `defence.py:42,93` — explosion HP penalty `max_hp // 2`, per-debuff
  `dmg // 2` and `speed *= 1.5`. These are designer-tunable magnitudes living
  in py.
- `engine/tilemap.py:31-35` — `DEFAULT_BACKGROUNDS` hardcodes content slot
  names in engine.
- `engine/video.py:22` — `CUTSCENE_LENGTH = 44.2`, unused, and contradicts
  `video_playback.py`'s own "engine stays game-agnostic" docstring.
- `game_state.py:75-76` duplicates the six boss-bonus keys that
  `boss_bonuses.py` already owns (`default_stacks()`).

---

## Dead code / scaffolding to delete

- `engine/video.py:25-62,98-116` — `_FallbackClock` + tolerant plumbing for a
  sibling module that can no longer be missing (~55 lines).
- `engine/render/backend.py:20-27` — pre-merge `ImportError` fallback for
  `hud.py`, unreachable since it landed.
- `game/enemies/spawner.py:24-26` — `ENABLE_RAIDERS/SIEGE/BOSS` flags,
  permanently True, toggled from nowhere.
- `editor/map_session.py` `push_*_move` trio + `tilemap_ops.py:132-160`
  (`remove_top_deco`/`move_base`/`move_camera`) — zero non-test callers.
- `game/ui/widgets.py:59 pretty()`, `effects.py:394 active`,
  `editor/theme.py:56 toggled()` — zero callers.
- Two silently-inert settings toggles (`game/ui/settings.py:23-27`):
  `income_floaters` is toggled but never read; `bg_art` toggles a cut feature.
  Wire the first, delete the second.
- `engine/core/.gitkeep`.

## Smaller correctness/robustness items

- `engine/core/component.py:56` — component registry silently overwrites on a
  class-name collision; serialization keys on bare class name → raise on
  duplicate.
- `game/core/session.py:62-64,384-386` — `_xp_awarded_buildings` keeps raw
  `id()`s forever; CPython id reuse can deny a later building its death XP.
  Use a `weakref.WeakSet`.
- `game/core/payday.py:231-243` — revive sweep iterates a stale snapshot and
  can `rebuild()` a despawned painter (harmless today, a trap tomorrow).
- `engine/data_io.py:39` — `write_validated` isn't atomic; a mid-write crash
  truncates the single source of truth. Temp file + `os.replace`.
- `editor/main.py:329,478` — `_refresh_levels`/`_apply_slot` unpack
  `self._node` with no None guard (crash if a level signal beats the first
  selection).
- `editor/panels/details.py:370-378` / `asset_import.py:41-46` — manifest
  read failure substitutes an empty doc; the next Save then validly writes it,
  wiping every slot's entries. Only substitute when the file doesn't exist.
- `editor/balancing_history.py:53-71` — lock wait busy-polls up to 10 s on
  the GUI thread (Save button path).
- `engine/assets/store.py:41,75-92` — sheet cache keyed by slot, not path: N
  slots sharing one PNG hold N surface copies.
- `game/enemies/spawner.py:142-153` — boss-round fallback re-implements the
  raider/siege count formulas verbatim (3 copies can drift).
- Cross-module writes to underscore privates as seams:
  `registry.py:90-92` (`building._tile_condition`), `coverage.py:77-84`
  (`tilemap._defence_coverage_fn`), plus UI reads of `_boost_label` /
  `_target`. Promote to tiny public accessors.
- `game/ui/hud.py:57-107` — `income_sources` hand-mirrors the core payday
  sweep in the UI layer; move it beside `run_payday` in core.
- `requirements.txt` — zero version pins; designer machines get whatever pip
  resolves today. Add bounded pins.
- Palette drift: two different `_XP_PURPLE` values under the same name
  (`hud.py:49` vs `effects.py:33`); tooltip chrome duplicated between
  `hud.py` and `building_ui.py`.
- Doc drift: `phases.py:24-26` says `BOSS_CUTSCENE` is "never entered" (live
  since 10G); root + data CLAUDE.md still say smoke.py exists "once it
  exists"; `data/balancing_history/ui.json` missing vs its doc.

---

## What is genuinely good (keep doing this)

- **Layering is enforced, not aspirational** — by tests (editor purity test
  asserts `game/` never enters `sys.modules`), by grep-verifiable containment,
  and by callback/duck-typed seams (core↔enemies, map↔buildings).
- **Data discipline is real** — 100% schema pairing, byte-exact canonical
  formatting, fail-loud loaders, every write through `write_validated`, tests
  reading tuning from data instead of duplicating literals.
- **Deliberate engineering where it counts** — the shared flow-field
  pathfinder with a single documented invalidation seam; `ground_cache.py`'s
  scroll-and-fill design with its failure-history docstring; capability-marker
  dispatch instead of isinstance chains (11 building leaves, zero roll-code
  branches); bounded-memory FX watchers.
- **Traceability** — prototype file:line citations and SPEC IDs throughout
  make behaviour-vs-bug review cheap.

## Suggested fix order

1. **Bugs:** B1, B2, B3 + triage the 2 test-surfaced editor bugs.
2. **Test health:** repoint `active_map.json`, decouple `TempDataCase` from
   live data, add `conftest.py` → suite green on clean checkout.
3. **Dead code + inert toggles sweep** (pure deletions, zero risk).
4. **Structural:** split `building_ui.py` (S1), extract `GameplayController`
   from main.py (S3), dissolve the core↔buildings cycle (S4), then S2/S5/S6.
5. **Data-as-truth stragglers:** move the boost/defence magnitudes into
   `buildings.json`; drop `CUTSCENE_LENGTH`/`DEFAULT_BACKGROUNDS` from engine.
