# Section S4 handoff

**Landed** — `section-S4`, code head @ `63b451f` (+ this handoff commit); both phases green, **zero fix rounds**, three clean reviews
(N1, N2, whole-section). N1 `phase-N1-season-clock` @ `3fe4062` · N2 `phase-N2-render-paths` @ `abc9bed`.

**Interface deltas**
- **`Seasons.rounds_per_season`**, `data/balancing/core.json`, default **10**; schema `integer`/`min 1`/
  `max 1000`, `"Seasons"` added to the top-level `required`. Read by direct indexing, never `.get()` (D-2).
- **`RunState.season: int = 0`** + **`update_season(rounds_per_season) -> bool`**
  (`game/core/game_state.py:225`) — pure delegation to `engine.era_math.era_of_round`; **no new season
  math, no `season_of_round` twin**. That bool is the SOLE trigger for `ground_cache.invalidate()`.
  Called at the round edge, `game/main.py:1716-1729`, inside the existing INCOME phase-edge guard —
  once per round, never per frame. `game/core/payday.py` untouched (I scope-rejected that widening).
- **`engine/tilemap.py:322`/`:369` (`visible_render_items`, `band_render_items`),
  `game/map/spawn_deco.py:57`, `game/map/conditions.py:25` all gain `column=None`**, threaded onto EVERY
  emitted `RenderItem`. D12 holds — opaque like `tint_for_code`; no `era_math`, no balancing read.
- **Four submit sites, `game/main.py:1891-1929`**, pass `column=session.state.season`; the ground-cache
  lambda reads it **in its body**, not as a bound default. Backgrounds, enemies, buildings, HUD untouched (D8).
- **`column=None`, never `column=0`** — `0` is a real season; only `None` falls back to the stored column.
  Pinned in `tools/tests/test_asset_store.py::TestColumnBlock` (append-only).
- **D6/D3 ruled for seasons (S3 handed this over): S4 computes NO capability predicate.** D3 is already
  enforced once at `engine/assets/store.py:225`; D6 is irrelevant — seasons address columns by **index**,
  never by D4's `columns` names, and ship no UI. Rationale in the plan's Section S4 block.

**Open findings**
1. **Live Quick Test NOT run — blocked on art, not code.** No shipped master sheet is multi-column (one
   entry, `column_width: 15`, no `columns`), so "cheat to round 11/21 and watch tiles step" is unrunnable
   until a designer authors one. *User / top orch.* **verified**
2. Ground tiles step only via N1's conditional `invalidate()`; drop it and they lag until a zoom/resize.
   *Top orchestrator.* **inferred**
3. Plan-doc fixes inside my own S4 blocks — three named test modules don't exist (`test_game_state`,
   `test_balance_data`, `test_map_conditions`), N2's `column=0` was superseded by S1's fixes, and
   `game/map/CLAUDE.md`'s spawn_deco `column` clause I fixed forward in `63b451f`. Keep these on merge.
   *Top orch.* **measured**

**Gate** (measured, merged `section-S4`) — `py tools/smoke.py` **PASS** (62 data files valid, 5 headless
frames, shell boot OK). `py -m pytest` over the 7 touched test files `-q -n 4` → **198 passed, 1351
subtests, 0 failed, 0 skipped**. No `test_guard` deny in this section; `63b451f` is docs-only on top of
that measured tree.
