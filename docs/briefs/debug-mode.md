# Debug Mode — structured run telemetry for balancing + LLM debugging

Designer request: *"I would like to be able to play the game in debug mode where
it outputs a log of all the game actions that are taking place as well as log
certain balancing outcomes, such as the players income and current love per
round, the amount of total damage dealt to enemies and taken per round. I need a
data output that can help the balancing and also be read by an LLM to debug if
something is working."*

Branch `feat/debug-mode-telemetry` off `debugmode`; PR into `Development`.
Cross-package inside `game/` only (`core` + `ui` + `enemies` + a new `debug`
domain) plus `tools/`. **No `engine/` change, no `editor/` change, no `data/`
change.**

**Read**: `game/CLAUDE.md`, `game/core/CLAUDE.md`, `game/ui/CLAUDE.md`,
`game/enemies/CLAUDE.md`.

**Testing bar: bare minimum.** Write only the tests named in this brief — they
are the load-bearing ones. Do not add breadth-for-its-own-sake coverage, and do
not let a review pass demand more.

**Guardrail — the hard one for this task.** Everything here is OBSERVATION.
Gameplay must not move by a single frame or a single point of love. With debug
off, every code path must be byte-identical to today. See §3.

---

## 1. Why this is needed (all **verified**)

Every tunable lives in `data/balancing/*.json`, but there is no way to observe
what those numbers actually produce during a run: no record of income per round,
no damage totals, no wave composition, no trace of what the player spent love on
or where a wave broke through.

The only runtime observability that exists is the 4-second fading `GameLog`
(`game/ui/game_log.py`) and an fps print (`game/main.py:1140-1152`) — both
ephemeral, neither machine-readable.

So a balance change can only be evaluated by feel, and a question like "is the
Storm Priest actually firing?" or "why did round 11 suddenly spike?" has no
evidence to answer it with.

### Deliverables

1. **JSONL event stream** — one JSON object per line; the causal trace an LLM (or
   a human) reads to answer "did X happen, and in what order".
2. **Per-round CSV** — the balance curve, straight into a spreadsheet.
3. **End-of-run markdown summary**.
4. **Self-contained HTML report with inline-SVG charts** — no external assets, no
   CDN, and **no new pip dependency** (`requirements.txt` gains nothing).
5. **`tools/simrun.py`** — a headless sim runner, so a balance change can be
   diffed without playing the game by hand.

---

## 2. What already exists — REUSE, do not rebuild (all **verified**)

| Need | Already there |
|---|---|
| Per-building damage dealt/taken per round | `RoundStats` — `game/buildings/components.py:69-72`; rolled this→last and zeroed at `payday.py:144-151` |
| Per-tile income/upkeep ledger | `RunState.income_events` — `(col, row, amount, kind)`, rebuilt every payday (`payday.py:139,167,199,211`) |
| Aggregate run state | `RunState` — `game/core/game_state.py:19` (love, round_num, base_lives, enemies_killed, player_xp, village_level, boss_stacks) |
| Wave composition | `Spawner.pending()` → `[(tile, etype)]`, `Spawner.enemy_tier` — `game/enemies/spawner.py:81-87`, filled by `begin_round` |
| Cross-package handoff without imports | the optional-callback pattern on `resolve_combat(on_base_hit=…, on_enemy_death=…, on_kidnap=…, on_splash_impact=…, on_defender_fire=…, on_projectile_hit=…)` — `game/enemies/combat.py:427` |
| Optional host-set collaborator on `Session` | `Session.tutorial_gate` / `tutorial_director` — `game/core/session.py:63,69`, `None` by default so logic tests are untouched |
| Headless world construction | `build_board` + `host_frame` — `tools/tests/test_phase_loop.py:50,58` |
| Menu button end-to-end | `_ITEMS` / `_ACTION_IDS` / `hit()` — `game/ui/main_menu.py:33-104`, dispatched `game/ui/shell.py:123-135` |
| Toggle-row screen | `game/ui/settings.py:29-95` (3 existing toggles) |
| Cheat action dispatch | `game/ui/cheat_menu.py:51-63` → `game/main.py:443-470 _execute_cheat()` |

---

## 3. Design decisions (settled — do not relitigate)

1. **One sink, explicit emit sites — no event bus.** This repo deliberately has
   none (`game/core/CLAUDE.md`: point-to-point callbacks). A `DebugRecorder` hangs
   off `Session.debug`, `None` by default — the `tutorial_director` precedent. Every
   emit site is `if self.debug: self.debug.emit(...)`, so debug-off costs one
   attribute check and a bare `Session` built by a logic test is untouched.

2. **Level-1 damage comes from `RoundStats`, not the hot path.** Summing
   `dmg_dealt_this_round` / `dmg_taken_this_round` across built tiles at payday —
   immediately **before** `payday.py`'s step-2 snapshot zeroes them — gives exact
   per-round totals with **zero instrumentation in the combat sweep**. Only level 2
   threads a per-tick callback, and it is `None` at level ≤1, so levels 0 and 1 are
   byte-identical inside `game/enemies/`.

3. **Two known gaps in `RoundStats`, both handled explicitly — do not paper over
   them:**
   - **Lightning has no shooter**, so its damage is never credited to `RoundStats`
     (`game/core/lightning.py`). The recorder counts it separately, from
     `Session.lightning_strike`, and reports it as its own damage source.
   - **A base breach applies no HP damage.** `resolve_combat` returns early once
     `on_base_hit` is supplied (`combat.py:738-748`), so "damage taken by the
     player" is **lives lost**, not HP. Report `lives_lost` and
     `building_dmg_taken` as separate columns; never fuse them into one
     misleading "damage taken".

4. **New package `game/debug/`**, pure — no pygame, with its own `TestPurity`. It
   may import `game/core` + `game/buildings/components`, mirroring what
   `payday.py` already does.

5. **Output to `logs/`** at repo root, gitignored. Tests write to a tempdir.
   Nothing here reads or writes `data/` — the `data/` tripwire is unaffected.

---

## 4. Phases

### Phase 1 — Recorder core (`game/debug/`)

- **`game/debug/__init__.py`** — exports `DebugRecorder`, `LEVELS`.
- **`game/debug/recorder.py`** — `DebugRecorder(out_dir, level, run_id)`:
  - `emit(kind, **fields)` — level-gated; stamps `t` (kind), `round`, `phase`,
    `frame`, `wall_ms`, appends one JSON line. Buffered; flushed on round
    boundary and on `close()`.
  - `note_lightning(dmg, hits)` — the no-shooter accumulator (§3.3).
  - `begin_round(...)` / `end_round(summary)` — accumulator lifecycle.
  - `close()` — flush, then hand the collected round rows to `report.py`.
  - Level 0 is never constructed; call sites guard on `is None`.
- **`game/debug/metrics.py`** (pure, no I/O) — `round_summary(state, tilemap,
  spawner, accum)` returns the round record. Iterates `tilemap.built_tiles()` for
  `RoundStats`, splits `state.income_events` into income vs upkeep and by
  building type, reads love / lives / xp / village level / kills off `RunState`.
- **`game/debug/events.py`** — event-kind constants plus a one-screen docstring
  documenting every kind and its fields. **That docstring is the contract an LLM
  reads — keep it complete and accurate.**

Level-1 kinds: `run_start`, `wave_start`, `place`, `unlock`, `research`,
`enemy_death`, `base_hit`, `kidnap`, `lightning`, `payday`, `round_summary`,
`levelup`, `boss_choice`, `cheat`, `game_over`, `run_end`.
Level 2 adds: `enemy_spawn`, `damage`, `wall_damage`, `defender_fire`.

**Tests** — `tools/tests/test_debug_log.py`: JSONL is one valid object per line;
level gating drops level-2 kinds at level 1; `round_summary` arithmetic against a
hand-built `RunState` + synth tilemap (copy `build_board`,
`tools/tests/test_phase_loop.py:50`); a `TestPurity` asserting `game.debug`
imports no pygame.

**Housekeeping, fold in here:** `.gitignore` gains `logs/`; `conftest.py`'s
`TIERS` registers `test_debug_log` and `test_simrun` as `core` (a module missing
from `TIERS` is a hard error — `tools/tests/test_tiers.py`).

### Phase 2 — Level-1 emit sites

No behavior change when `debug is None`.

- **`game/core/session.py`** — `self.debug = None` beside `tutorial_director`
  (`session.py:69`). Emit from `end_turn` (`wave_start`: composition from
  `spawner.pending()` + `spawner.enemy_tier`, plus love/lives at wave start),
  `on_base_hit`, `on_enemy_death`, `on_kidnap`, `_begin_round_end`,
  `resolve_levelup`, `resolve_boss_cutscene`, `lightning_strike` (via
  `note_lightning`), and **every `cheat_*` method** — a cheated run must be
  visibly tagged or it silently pollutes the balance data.
- **`game/core/payday.py`** — `run_payday(..., debug=None)`; `Session` passes
  `self.debug` at all three call sites (`session.py:317,400,426`). Emit
  `round_summary` **before** the step-2 snapshot zeroes `RoundStats`, and `payday`
  (income/upkeep breakdown) after step 5. **The payday step ordering is
  SACROSANCT — do not reorder it.** The emits sit between existing steps.
- **`game/ui/building_ui.py`** — emit `place` / `unlock` / `research` from
  `_do_place` and the tier-advance branch, the same seam
  `lightning.unlock_from_placement` already hooks. Reads `session.debug`; no new
  plumbing.
- **`game/main.py`** — construct the recorder in `main()`, assign `session.debug`
  in `build_gameplay()`, call `recorder.close()` before `pygame.quit()` and on
  the game-over path.

### Phase 3 — Level-2 combat detail

One new optional callback on `resolve_combat` — exactly the ESV-5/ESV-6
precedent, where `None` keeps every existing caller byte-identical.

- **`game/enemies/combat.py:427`** — add `on_damage=None`, invoked at the damage
  sites (`combat.py:136,228,638`) and the enemy→building site
  (`game/enemies/components.py:432`) with `(attacker_kind, target_kind, dmg,
  target_hp_after)`, guarded by `if on_damage is not None`.
- **`game/main.py`** — pass `on_damage=` **only when level ≥ 2**.

### Phase 4 — Reports

**`game/debug/report.py`** (pure, stdlib only), all written from
`recorder.close()`:
- `write_rounds_csv(rows, path)` — one row per round.
- `write_summary(rows, events, path)` — markdown digest: totals, income curve,
  damage share by building type, love-spend breakdown, leak rounds, outcome.
- `write_html(rows, path)` — one self-contained HTML file, inline SVG charts:
  love over rounds, income vs upkeep, damage dealt vs taken, kills vs leaks, wave
  size vs damage output.

Tests: the CSV header matches the metrics keys (so they cannot drift); the HTML
references no external URL.

### Phase 5 — Activation surfaces

1. **CLI** — parse `--debug[=N]` in `game/main.py`'s `if __name__ == "__main__"`
   block; add `debug_log=None` to `main()` (`main.py:171`) so headless callers and
   tests drive it directly. Keep it out of `max_frames`/`autostart` semantics.
2. **Main menu `PLAY DEBUG` + gear** — `game/ui/main_menu.py:33,41`: add
   `("PLAY DEBUG", "play_debug")` to `_ITEMS`, `"play_debug": "btn_play_debug"` to
   `_ACTION_IDS`, plus a small gear `Button` with id `btn_play_debug_settings`.
   Route both in `game/ui/shell.py:123-135`. The gear opens
   **`game/ui/debug_settings.py`**, a modal copied from `game/ui/settings.py:29-95`
   (toggle rows + BACK): level 1/2, and which outputs to write. Code-only — no
   `data/ui/screens/*.json` entry is needed (an absent override means "code
   defaults", pinned by `test_ui_skinning.py`).
3. **Cheat-menu toggle** — one row in `game/ui/cheat_menu.py:51`, dispatched in
   `game/main.py:443-470 _execute_cheat()`, arming/disarming the recorder mid-run.
   It records a `cheat` event marking the arm point, so a partially-captured run
   is obvious rather than misleading.

### Phase 6 — `tools/simrun.py`

Headless balance-sweep runner. Builds a real world without pygame, following
`test_phase_loop.py`'s `build_board`/`host_frame` pattern but over the **live
active map** (`engine.tilemap.load_active_map` + real `load_balance`), then loops
frames with a build policy.

```
py tools/simrun.py --rounds 20 --strategy greedy_defence --seed 7
py tools/simrun.py --rounds 20 --strategy none --seed 7     # do-nothing baseline
```

- **Strategies** in `game/debug/policies.py` (pure): `none`, `greedy_defence`
  (cheapest defence nearest the base), `balanced` (alternate economy/defence). A
  policy is `(state, tilemap, buildings_balance) -> [(tile, building_type)]`,
  called once per BUILDING phase; it places through the real `place_building`
  (`game/buildings/registry.py:44`) so costs, gates and occupancy are real.
- Seeded RNG threaded into `Spawner` — `game/CLAUDE.md`: seed the RNG in anything
  whose outcome depends on it.
- Writes the same four artifacts to `logs/sim-<strategy>-<seed>-*`.

---

## 5. Files

**New:** `game/debug/{__init__,recorder,metrics,events,report,policies}.py`,
`game/ui/debug_settings.py`, `tools/simrun.py`,
`tools/tests/{test_debug_log,test_simrun}.py`

**Modified:** `game/core/{session,payday}.py`, `game/main.py`,
`game/ui/{main_menu,shell,cheat_menu,building_ui}.py`,
`game/enemies/{combat.py,components.py}` (Phase 3 only), `conftest.py`,
`.gitignore`, `game/CLAUDE.md` (a `debug/` row + short section),
`game/core/CLAUDE.md` (document `Session.debug` beside `tutorial_director`).

---

## 6. Verify

```bash
py tools/smoke.py                          # data validation + 5-frame headless boot
py tools/testgate.py check --affected      # while iterating
py tools/testgate.py check                 # ONCE, before handback — GATE PASS or you are not done
```

Then, all headless (SDL dummy drivers — no display required):

1. `py tools/simrun.py --rounds 12 --strategy greedy_defence --seed 7` →
   `logs/sim-greedy_defence-7-rounds.csv` has plausible non-zero love, income,
   upkeep, damage dealt/taken, kills and leaks. Assert `report.html` contains no
   `http://`, `https://` or `//cdn` reference.
2. **The level-1 / level-2 cross-check — the proof that the `RoundStats`
   aggregation is correct.** Same seed at level 2; assert per round that
   `sum(damage events) == round_summary.dmg_dealt`, excluding lightning (reported
   separately). Pin this in `test_simrun.py` so it stays true.
3. **Off-path regression**: a headless boot with no debug flag
   (`main(max_frames=120, autostart=True)`) writes **nothing** to `logs/`.
4. **Determinism**: the same `--seed` twice produces byte-identical `rounds.csv`.

### Do NOT attempt these — leave them as a PR checklist

There is no display and no human at the keyboard for the automated run.

- [ ] `py game/main.py --debug=1`, play 3 rounds, place a building, let one enemy
      through; confirm `wave_start` / `place` / `enemy_death` / `base_hit` /
      `payday` / `round_summary` appear in causal order, and that
      `round_summary.love_end` matches the HUD love at each round end.
- [ ] Gear → level 2 → `PLAY DEBUG` produces a level-2 log.
- [ ] `Ctrl+L` debug toggle lands a `cheat` marker in the stream.
- [ ] `report.html` opens offline and the charts read correctly.
