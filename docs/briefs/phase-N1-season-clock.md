# Phase N1 — The season clock

Section S4 (Seasons) of `planning/MasterSheetColumnsPLAN.md` (phase block at
`planning/MasterSheetColumnsPLAN.md:745-780`; section Purpose/Publishes at
`:729-743`). Depends on S1, which has LANDED.

**Goal, in one line:** the run knows which season it is in, and says so exactly
once per round.

N1 ships the *clock* only. Nothing renders differently at the end of N1 —
`RunState.season` simply holds the right integer and the ground cache is dropped
when it turns. N2 (a separate brief, on a branch cut from N1's merged result)
spends the value at the four render-submit sites.

---

## 1. Behavioral spec

### 1.1 The season is `era_of_round`, reused verbatim

`engine/era_math.py:46-52`:

```python
def era_of_round(round_num, rounds_per_era):
    """0-based era index of `round_num` (D1). Round <= 0 is era 0 (D11)."""
    rounds_per_era = max(1, int(rounds_per_era))
    if round_num < 1:
        return 0
    return (int(round_num) - 1) // rounds_per_era
```

That IS the season formula (plan D7, `planning/MasterSheetColumnsPLAN.md:79-82`).

- **Write no new math.** Do not add a `season_of_round`, do not copy the
  expression into `game/`, do not "wrap it for clarity" with a second module.
  `game/core/` already consumes this module for the boss/era clock
  (`game/core/CLAUDE.md:428-430`), so the import direction is established.
- Behaviour that follows for free and must be preserved: **round 0 is season 0**.
  The host seeds `round_num = 0` for the tutorial round
  (`game/main.py:798`, documented at `game/core/CLAUDE.md:124-125`), and the
  function's `round_num < 1` guard already returns 0 there.
- At `rounds_per_season = 10`: rounds 1..10 → season 0, rounds 11..20 → season 1,
  rounds 21..30 → season 2. It clamps nothing and wraps nothing — the per-sheet
  clamp is D7 and already lives in the engine's cut path (S1, LANDED).

### 1.2 The new balancing key

There is currently **no `Seasons` group** in either file — measured, by loading
both JSON documents: `data/balancing/core.json` top-level keys are
`BossBonuses, Camera, Debug, EnemyIntro, General, LightningStrike, PhaseLoop,
TheHole, Tutorial, XP`, and `data/schemas/core.schema.json`'s `required` array
is that same list. N1 adds an eleventh group to both.

- `data/balancing/core.json` → `"Seasons": {"rounds_per_season": 10}`.
- `data/schemas/core.schema.json` → a `Seasons` object property in the same
  shape as its sibling `PhaseLoop` (`additionalProperties: false`, a group
  `description`, a per-key `description`, the key listed in the group's own
  `required`), and `"Seasons"` added to the schema's **top-level `required`**
  array. Sorted-key order puts it between `PhaseLoop` and `TheHole`.
- Bounds: `type: "integer"`, **`minimum: 1`** (mandated). Every numeric leaf in
  this file also carries a `maximum` — `tools/tests/test_balancing_data.py:110`
  (`test_every_numeric_leaf_declares_bounds`) enforces it, and the editor's
  spinbox reads both (ED-30). Match the sibling integer `speed_2x_min_round`,
  which uses `maximum: 1000`.
- The `description` must state the unit, not just restate the name —
  `tools/tests/test_balancing_data.py:98`
  (`test_every_leaf_documents_units_in_description`) enforces that too.

### 1.3 It is read by direct indexing, never `.get()`

`core_balance["Seasons"]["rounds_per_season"]` (plan `:756-759`). D-2: a
schema-**required** key must fail loud, so a missing group is a `KeyError` at the
first round edge, not a silent default that ships wrong art for a whole run.
This matches the existing read one line below the round increment
(`game/core/payday.py:281`, `core_balance["PhaseLoop"]["income_phase_duration"]`).

**No `.get("Seasons", …)`, no `or 10`, no module-level constant.**

### 1.4 `RunState.season`

`RunState` is the single owner of the round loop's authoritative values
(`game/core/game_state.py:1-13`), and `round_num: int = 1` is at
`game/core/game_state.py:23`. `season: int = 0` joins it: a fresh run is round 1,
which is season 0, so the default and the derived value already agree and
`from_balance` (`game/core/game_state.py:190`) needs no change.

### 1.5 It recomputes once, on the round edge

`state.round_num += 1` happens in exactly ONE place —
`game/core/payday.py:277` (step 11 of `run_payday`), four lines before the phase
flips to `INCOME` at `:280`.

**The recompute site for N1 is `game/main.py`'s phase-edge watcher chain**, not
`payday.py`. Two reasons, both hard:

1. `game/core/payday.py` is **not in Phase N1's declared file scope**
   (`planning/MasterSheetColumnsPLAN.md:750-752`). Widening a phase past the
   file list the plan declared is not this brief's call.
2. The other half of the behaviour — `ground_cache.invalidate()` — can only
   happen in `game/main.py`. `ground_cache` is a local of the host
   (`game/main.py:718`) and is not, and must not be, visible to `game/core/`
   logic. Putting the recompute in the same module as the handle it triggers
   keeps the whole edge in one reviewable block instead of two halves that can
   drift by a frame.

The INCOME phase edge IS the round edge: `run_payday` increments the round and
flips to `INCOME` in the same call, and the host already fires an
"payday just ran" block on that edge (`game/main.py:1710-1715`).

Required properties of the recompute:

- **Once per round edge, never per frame.** It lives inside the
  `phase == INCOME and prev_phase != INCOME` guard, which by construction runs
  on one frame per round.
- **`ground_cache.invalidate()` fires only when the season value actually
  CHANGES** — i.e. once every `rounds_per_season` rounds, not on every round
  edge, and never mid-round. Repainting the whole cached ground layer on every
  round would be a silent perf regression that no test would notice.
- A fresh run needs no special case: `build_gameplay()` already calls
  `ground_cache.invalidate()` unconditionally (`game/main.py:775`) and rebuilds
  a fresh `RunState` (season back to 0).

### 1.6 What N1 does NOT do

- No render path reads `state.season` yet. The four submit sites
  (`game/main.py:1877-1892`, `game/map/spawn_deco.py`, `game/map/conditions.py`,
  `engine/tilemap.py`) belong to **N2** and are out of scope here — see §3.
- No engine change. S1 already published the column plumbing.
- No editor change. `editor/panels/balancing.py` recurses the schema and renders
  the new spinbox for free (`/add-balancing-value` step 3).

---

## 2. Architecture plan

### 2.1 Open with `/add-balancing-value` for the data half

**Mandatory.** The JSON + schema half of this phase is exactly the task
`.claude/commands/add-balancing-value.md` owns; run it as
`/add-balancing-value core: rounds per season`. Do not hand-roll the pair. It
carries the `required`-array step, the description/bounds discipline, the
"no editor code needed" fact, and the deterministic-write rule (sorted keys,
2-space indent) that the canonical-form test at
`tools/tests/test_balancing_data.py:87` checks.

### 2.2 `RunState` gains one field and one three-line mutator

```python
# game/core/game_state.py
from engine.era_math import era_of_round
```

Layering: `game/` consuming `engine/` is the sanctioned direction, and
`engine/era_math.py` is stdlib-only with no pygame and no game/editor imports
(`engine/era_math.py:3-6`).

Field, beside `round_num`:

```python
    season: int = 0
```

Mutator, at the end of the dataclass body:

```python
    def update_season(self, rounds_per_season):
        """Recompute `season` from `round_num`; True iff it CHANGED.

        The bool is the caller's invalidate trigger: the host repaints its
        cached ground layer only when the season actually turns, not on every
        round edge. No new math — `era_of_round` IS the season formula (D7).
        """
        new = era_of_round(self.round_num, rounds_per_season)
        if new == self.season:
            return False
        self.season = new
        return True
```

**Why a method rather than four inline lines in `main.py`:** the plan requires a
test that `RunState.season` advances exactly once per N rounds and never
mid-round (`planning/MasterSheetColumnsPLAN.md:773-777`), and the host's watcher
chain has no headless harness — `tools/tests/test_phase_loop.py` drives
`RunState`/`run_payday` directly and cannot reach inside `main()`'s loop. The
method puts the assertable behaviour in a module the suite already imports and
leaves the host with a two-line call. It is **not** a `season_of_round` twin: it
contains no arithmetic, it delegates.

### 2.3 The host calls it on the INCOME edge

Inside the existing "payday just ran" block, after the floater spawns:

```python
                    if session.state.update_season(
                            core_balance["Seasons"]["rounds_per_season"]):
                        ground_cache.invalidate()
```

`core_balance` (`game/main.py:550`), `ground_cache` (`game/main.py:718`) and
`session` are all locals of the same enclosing host function as the watcher
chain — **verified**: the only `def`s between `:550` and `:1710` are nested
closures (`frame_camera` `:572`, `build_gameplay` `:765`, `flush_frame` `:1329`,
…), so no new argument threading, no `nonlocal`, no globals are needed.

Comment the block the way the neighbouring edges are commented: say that payday
already ran (`game/core/payday.py:277` is the round++), that this is the round
edge and not a frame, and that the invalidate is conditional on purpose.

### 2.4 Doc update

`game/core/CLAUDE.md` — extend the `game_state.py` bullet
(`game/core/CLAUDE.md:17-18`, the one that already documents `round_num`) with
`season` + `update_season`, naming: `era_of_round` as the shared formula, the
host's INCOME-edge call site, and the invalidate-on-change rule. Keep it to a
few lines; this is a router-level doc, not a design essay. Do **not** touch the
root `CLAUDE.md`, `PLAN.md`, or another package's doc.

---

## 3. File scope + shared-file contract

### 3.1 Exactly these files. Nothing else.

| File | Change |
|---|---|
| `data/balancing/core.json` | new `Seasons` group, `rounds_per_season: 10` |
| `data/schemas/core.schema.json` | mirror + top-level `required` entry |
| `game/core/game_state.py` | `season` field, `update_season`, `era_of_round` import |
| `game/main.py` | ONE block on the INCOME phase edge — see §3.2 |
| `game/core/CLAUDE.md` | the `game_state.py` bullet |
| `tools/tests/test_era_math.py` | one pin (§4.2) |
| `tools/tests/test_phase_loop.py` | two pins (§4.2) |
| `tools/tests/test_balancing_data.py` | one pin (§4.2) |

**Not in scope, do not touch:** `game/core/payday.py` (§1.5 reason 1),
`engine/**`, `editor/**`, `conftest.py`, `tools/test_domains.py`,
`tools/ci_shards.py`, root `CLAUDE.md`, `PLAN.md`, `planning/**`.

### 3.2 `game/main.py` is shared with Phase N2 — the fence

`game/main.py` is edited by **both** N1 (you) and N2 (next, on a branch cut from
your merged result). The fence:

- **N1 edits ONE region of `game/main.py`: the phase-edge watcher chain.** The
  insertion point is *inside* the existing INCOME-edge block that currently
  reads (`game/main.py:1710-1715`):

  ```python
                  # payday fills state.income_events + flips to INCOME; spawn once
                  if (session.state.phase == GamePhase.INCOME
                          and gp["prev_phase"] != GamePhase.INCOME):
                      gp["floaters"].spawn_income_events(session.state)
                      gp["floaters"].spawn_painter_events(session.state)
                      gp["floaters"].spawn_boost_events(session.state)
  ```

  Append the §2.3 call as the **last statements inside that same `if`**, i.e.
  immediately after `spawn_boost_events(...)` and before the next `# -- 10J`
  comment at `:1716`. Do not restructure the block, do not reorder the floater
  spawns, do not add a second `if` on the same condition, and do not move
  `gp["prev_phase"] = session.state.phase` (`:1750`).

- **N1 does NOT touch the render-submit sites at `game/main.py:1877-1892`.**
  That is N2's exclusive region: `ground_cache.ensure(...)` with its
  `band_render_items` callback (`:1877-1883`), `ground_cache.blit(...)`
  (`:1886`), and the `visible_render_items` deco loop (`:1889-1892`). They gain
  a `column=` argument in N2 and must be byte-identical when N1 lands. If you
  find yourself editing anything below `:1800`, you have left your phase.

- The only `ground_cache` line N1 may add is the conditional
  `ground_cache.invalidate()` inside the edge block. The existing hook wiring at
  `game/main.py:774-775` (`tile_map.on_zone_change = ground_cache.invalidate`,
  plus the fresh-run invalidate) is **read-only context** — do not rewire it, do
  not route the season through `on_zone_change`.

### 3.3 The plan names two test files that do not exist — resolved

Measured (`ls tools/tests/`): `tools/tests/test_game_state.py` and
`tools/tests/test_balance_data.py`, both named in the phase block's Files and
Exit gate (`planning/MasterSheetColumnsPLAN.md:752`, `:779-780`), **do not exist
in this repo**. The real modules are `tools/tests/test_balancing_data.py`
(balanc**ing**), `tools/tests/test_phase_loop.py`, `tools/tests/test_era_math.py`
and `tools/tests/test_ground_cache.py`.

**Decision (made by this brief, confirmed with the section orchestrator): the
new tests go into the EXISTING modules; no new test file is created.** One
sentence why: a new module would have to be registered in `conftest.py`'s
`TIERS` and in `tools/test_domains.py`'s `DOMAINS` — both **outside** this
phase's declared file scope, and both enforced by tests (`test_tiers.py`,
`test_test_domains.py`) that are *not* in this phase's exit gate, so a forgotten
registration would pass N1's gate and fail the section gate instead.

Each pin also lands where its harness already lives: `test_phase_loop.py` is
headless and already imports `RunState`/`run_payday`
(`tools/tests/test_phase_loop.py:1-30`, `class TestRunState` at `:85`);
`test_balancing_data.py` already walks the core schema/JSON pair;
`test_era_math.py` already covers `era_of_round`.

---

## 4. Exit gate + Quick Test

### 4.1 The gate — this and nothing wider

```bash
py tools/smoke.py
py -m pytest tools/tests/test_era_math.py tools/tests/test_phase_loop.py tools/tests/test_balancing_data.py -q -n 4
```

`-n 4` is **mandatory**, not decoration: `pytest.ini:8` sets `-n auto`, which
spawns 32 xdist workers on this box.

You are a subagent. **No full suite, no `py tools/testgate.py check`, no
`--affected`, no tier sweep (`-m core` / `-m editor` / `-m meta`).**
`.claude/hooks/test_guard.py` denies all four from a subagent; the single full
`check` is the main session's step at handoff, not yours. The authority is
§"Test Suite Policy" in the root `CLAUDE.md`.

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

The gate is ZERO: `GATE PASS` / all green, or you are not done.

### 4.2 The tests — write these four, and no more

Bare minimum. Do not add coverage beyond this list; a reviewer asking for more
is out of scope for this phase.

1. **`tools/tests/test_era_math.py`** — pin the season semantics on the
   *existing* function: `era_of_round(r, 10) == 0` for `r` in 1..10 and `== 1`
   for `r` in 11..20. This is a pin on shared behaviour N1 now depends on, not a
   new function.
2. **`tools/tests/test_phase_loop.py`** — `RunState().season == 0`, and walking
   `round_num` 1..25 calling `update_season(10)` each time advances `season`
   exactly at 11 and 21 and nowhere else (once per N rounds, never mid-round).
3. **`tools/tests/test_phase_loop.py`** — `update_season` returns `True` exactly
   on those change rounds and `False` on every other round. **That boolean is
   the ground-cache trigger**: it is what gates `ground_cache.invalidate()` in
   `game/main.py`, so this pins "invalidated on a season change and not
   otherwise" at the only layer that has a headless harness. Do **not** add a
   test to `tools/tests/test_ground_cache.py` — that module builds a
   `GroundCache` directly and already pins the rebuild-trigger logic
   (`tools/tests/test_ground_cache.py:1-7`); the one-line host wire itself is
   covered by the Quick Test below, not by a unit test.
4. **`tools/tests/test_balancing_data.py`** — `data/balancing/core.json` carries
   `Seasons.rounds_per_season`, it validates against
   `data/schemas/core.schema.json`, and the schema declares `minimum: 1`. Read
   it the way the game does — `doc["Seasons"]["rounds_per_season"]`, indexing,
   never `.get()`.

The file's existing generic walks (`test_every_leaf_documents_units_in_description`
`:98`, `test_every_numeric_leaf_declares_bounds` `:110`, the canonical-form check
`:87`) cover the description/bounds/formatting requirements automatically — do
not duplicate them.

### 4.3 Quick Test (in-game; the orchestrator or the user runs this, not you)

1. `py game/main.py`, start a run.
2. Open the cheat/debug menu and skip rounds to **round 11** (or set
   `Seasons.rounds_per_season` to 2 in the editor's Balancing panel → `core` →
   `Seasons` first, and skip to round 3 — faster, and it also confirms the new
   spinbox renders with its bounds).
3. **Expected:** the run crosses the boundary with no visible change to tile art
   (N2 has not landed yet) and **no stutter, no flicker, and no error**. The
   ground layer is repainted exactly once at the crossing.
4. Play three more rounds past the boundary. **Expected:** nothing repaints
   again — if the terrain visibly re-blits every round, the invalidate is firing
   unconditionally instead of on change.
5. Start a fresh run from the game-over/menu screen. **Expected:** it boots
   clean at round 0/1 with no stale ground.

---

## OPEN — orchestrator must decide

Nothing blocking. Two things the orchestrator should be aware of, both already
ruled on above and recorded here so the decision is visible rather than buried:

- **`game/core/payday.py` stays untouched.** The plan's design note offered the
  payday site as one of two candidates (`planning/MasterSheetColumnsPLAN.md:765-768`)
  but did not list the file in the phase's Files (`:750-752`). This brief picks
  the `game/main.py` watcher (§1.5). If the orchestrator would rather the season
  be recomputed in `run_payday` — which would make it correct for any future
  headless consumer of `RunState.season` without a host loop — that is a scope
  widening of one file and needs its ruling before the coder starts, plus a
  separate `prev_season` comparison in `main.py` for the invalidate.
- **The plan's Exit gate names two nonexistent test modules** (§3.3). This brief
  substitutes the three real modules. The plan doc itself still says
  `test_game_state.py` / `test_balance_data.py`; someone should correct
  `planning/MasterSheetColumnsPLAN.md:752` and `:779-780` — the planner does not
  edit a plan mid-flight without being asked, and the coder must not.
