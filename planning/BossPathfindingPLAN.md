# BossPathfindingPLAN.md — make the boss destroy every building in succession

Phased, agent-executable plan (same family as `EnemyReworkPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`.
Runnable via `/execute-plan-phases planning/BossPathfindingPLAN.md BP-1-BP-4`
or phase-by-phase.

Package scope: **game** only (`game/enemies`, `game/map`) + `data/balancing`.
No engine or editor changes. Read `game/enemies/CLAUDE.md` and
`game/map/CLAUDE.md` — this plan does not restate their architecture.

## Context

The boss is meant to grind through the player's buildings one after another and
turn on the hole last. It does not. A diagnosis run on 2026-07-14 found four
independent defects, all reproduced headlessly:

1. **It freezes solid.** `PathAgent._condition_speed()` returns
   `max(0.0, real − enemy_speed_penalty)`. Forest/mountain penalty is a flat
   **0.4 t/s**; boss `move_speed` is **0.3–0.45**. Eras 0–3 compute exactly
   **0.0** — and it is a *latch*, not a slowdown: speed 0 → `Movement` cannot
   advance → `mv.index` frozen → the condition is only re-read on an index
   change (`components.py:111`) → speed stays 0 forever. The boss is the only
   unit in the game slower than its own terrain penalty.
2. **It quits early.** `find_path_to_nearest_building` uses the goal predicate
   `lambda b: True` — the base is in the goal set — and
   `content_weights.base_building` is **0**, cheaper than any real building
   (1–2). Measured: on an 8-building board the boss killed **2**, walked to the
   hole, and ended its own round with **6 still standing**.
3. **It wanders.** Target choice is a weighted Dijkstra (cost, not distance),
   re-derived from scratch after every kill with no memory. Terrain, defence
   coverage (+1/tile) and the round-11 top-3 damage discount (×0.5) all bend the
   cost field, so the "nearest" building can be across the map.
4. **It rewinds.** `_repath()` snaps to `round(wx)` and resets `mv.index = 0`,
   so the boss walks *backward* onto its own tile centre after every kill.

There is no "current target" state anywhere: `PathAgent._target` is only the
thing the boss is *presently punching*. The 10G re-path machinery exists — it is
aimed wrong.

Full diagnosis with flowcharts and the measured repros:
<https://claude.ai/code/artifact/d911a123-49e9-48af-9940-d5a3ddca339d>

## User decisions (binding)

- **D1 — Terrain speed: subtractive with a floor.** Keep
  `real − enemy_speed_penalty`, but floor it at a fraction of the unit's *own*
  speed: `max(real × min_speed_fraction, real − penalty)`. Chosen over a
  multiplicative penalty **because only the boss's numbers move** — walker
  1.2→0.8, raider 2.7→2.3, siege 1.0→0.6, formation 0.9→0.5 stay byte-identical,
  so `test_balancing_parity` and the deterministic 10I fixtures do not move.
- **D2 — The boss attacks the hole only when the board is clear.** No timeout,
  no escape hatch. The base leaves the boss's goal set until no non-base
  building is alive.
- **D3 — Choose the target by distance, route to it by cost.** Target *choice*
  is plain geometric distance (what the player sees); the *route* stays a
  weighted Dijkstra (so it still walks around ponds). One weighted search
  currently does both jobs and the two requirements fight.
- **D4 — The boss's `attack_range_tiles` (2–3) stays dead data for now.** Wiring
  it up changes the block-and-attack model for every enemy; out of scope, noted
  in Risks.

## 1. Architecture decisions

- **The floor is a balancing key, not a constant** (G-7 — every tunable comes
  from `data/balancing/`). Add `TileConditions.min_speed_fraction` to
  `data/balancing/map.json` + its schema via `/add-balancing-value`. It reads
  from the same `_condition_mods` seam `PathAgent` already uses, so headless
  stubs without `balance` stay neutral.
- **Break the latch independently of the floor.** Even with D1 the refresh gate
  is wrong: refresh `_current_condition` from the tile *underfoot* each frame,
  not only on a waypoint-index change. Then no future penalty can ever weld a
  unit to the floor. Cheap and defensive — do it even though D1 already makes
  the speed non-zero.
- **A new pathfinder goal variant, not a flag on the old one.**
  `find_path_to_nearest_non_base_building` sits beside the existing four
  `find_path_to_nearest_*` variants and reuses `_goal_tiles` /
  `_find_path_to_goals` unchanged. Goal-set variants are already fresh Dijkstras
  (~one per wave), so **the `game/PERF.md` flow-field invariant is untouched** —
  this plan adds no per-enemy search.
- **The target lives in declared `PathAgent` fields** (E-11: all state in
  components — the editor inspector and save/load depend on it). Never a stashed
  `self._target_col`.
- **Nothing changes for Standard / Raider / Siege / Formation.** Every new
  `PathAgent` field is default-off, exactly as 10G's `goal_is_base` /
  `repath_on_kill` were. That is the regression fence.

## 2. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| BP-1 | Unfreeze: speed floor + break the condition-refresh latch | not started |
| BP-2 | Base last: the boss hunts buildings until the board is clear | not started |
| BP-3 | Committed target: remember it, watch it die, choose by distance | not started |
| BP-4 | No rewind on re-path + docs | not started |

---

### Phase BP-1 — Unfreeze

**Goal.** A boss can cross a forest or mountain tile. No enemy's speed can ever
reach 0 from a terrain penalty, and no unit can latch on a stale condition.

**Files.**
- modified: `data/balancing/map.json` + `data/schemas/*` — new
  `TileConditions.min_speed_fraction` (use `/add-balancing-value`).
- modified: `game/enemies/components.py` — `PathAgent._condition_speed()` applies
  the floor (D1); `PathAgent.update()` refreshes `_current_condition` from the
  tile underfoot every frame instead of only on an index change
  (`components.py:107–118`).
- modified: `game/enemies/CLAUDE.md` — the 10I modifier bullet now states the
  floor.

**Tests.** `tools/tests/test_boss.py` (new): an era-0 boss (0.3 t/s) placed on a
forest tile still moves, and reaches the base within a bounded sim. Assert every
non-boss type's conditioned speed is **unchanged** (0.8 / 2.3 / 0.6 / 0.5) — the
parity fence for D1.

**Exit gate.** `py -m unittest discover -s tools/tests -t .` green against the
baseline failure set; `tools/smoke.py` passes; schema validation passes (data
changed). Boss crosses forest in a headless run.

---

### Phase BP-2 — Base last

**Goal.** The boss never targets the hole while any other building stands. This
is the phase that delivers the plan's title.

**Files.**
- modified: `game/map/pathfinder.py` — add
  `find_path_to_nearest_non_base_building` (excludes the base tile from
  `_goal_tiles`; falls back to `find_path` — the base — when no non-base building
  is alive).
- modified: `game/enemies/enemy.py` — `Boss.on_spawn` calls the new variant.
- modified: `game/enemies/components.py` — `PathAgent._repath` calls it too;
  `goal_is_base` is then naturally `False` for the whole rampage and flips `True`
  exactly once, when the last building dies.
- modified: `game/enemies/CLAUDE.md` + `game/map/CLAUDE.md`.

**Tests.** `tools/tests/test_boss.py`: with N buildings alive the boss's goal is
never the base tile, even when the base is strictly nearer (the repro from the
diagnosis — boss equidistant from base and a defence tower picks the building);
with zero buildings alive it paths to the base and `goal_is_base` is `True`.
Regression: the existing `test_base_only_goal_still_breaches` and
`test_dead_goal_repaths_instead_of_phantom_breach` stay green.

**Exit gate.** Suite green; smoke passes. Scripted 8-building run: the boss
destroys **all eight** before reaching the base (the diagnosis run destroyed 2 of
8 — this is the number that must move).

---

### Phase BP-3 — Committed target

**Goal.** The boss picks a victim, remembers it, and stops re-litigating the
whole board after every kill.

**Files.**
- modified: `game/enemies/components.py` — new declared `PathAgent` fields
  `target_col: int = -1` / `target_row: int = -1` (default-off sentinel, so the
  other four enemy types are byte-identical). `update()` re-paths **when the
  target dies**, checked each frame — not only on the blocked→unblocked edge.
- modified: `game/map/pathfinder.py` — target *selection* by geometric distance
  over the alive non-base building set (D3); the *route* to the chosen tile stays
  the existing weighted `_dijkstra`.
- modified: `game/enemies/CLAUDE.md` — the 10G flag bullet gains the target
  fields; correct the `Boss` docstring at `enemy.py:271`, which already *claims*
  "re-paths every time its target dies" and does not.

**Tests.** `tools/tests/test_boss.py`: a target killed by **another enemy** while
the boss is en route makes the boss re-path immediately (today it marches to the
corpse and only re-paths on arrival); with a pond fronting a near building the
boss targets the **near** one (distance) while its path still routes **around**
the pond (cost).

**Exit gate.** Suite green; smoke passes. Total tiles walked on the scripted
8-building board is within ~1.3× of a sensible tour (the diagnosis measured
greedy churn; this is the number that must come down).

---

### Phase BP-4 — No rewind + docs

**Goal.** Kill the visible half-tile reverse after every kill, and land the docs.

**Files.**
- modified: `game/enemies/components.py` — `_repath()` drops `path[0]` when the
  boss is already closer to `path[1]` (or starts at `index = 1` when it has
  overshot the tile centre); resets `_last_index = 0` and re-reads
  `_current_condition` from the tile underfoot, fixing the stale-condition tail.
- modified: `game/enemies/CLAUDE.md`.

**Tests.** `tools/tests/test_boss.py`: after a re-path the boss's position is
**monotonic along the new path** — it never moves away from `path[1]`. (Diagnosis
measured col 11.000 → 10.705 in the second after a kill.)

**Exit gate.** Suite green; smoke passes; live `py game/main.py` boss round — the
boss visibly walks building to building without reversing, and turns on the hole
only once the board is clear.

## Verification (every phase)

Per root `CLAUDE.md` step 2: run `tools/smoke.py` (headless SDL dummy) and
`py -m unittest discover -s tools/tests -t .` against the recorded baseline
failure set; if `data/` changed, confirm schema validation passes; report each
claim tagged **measured** / **verified** / **inferred** (`/report`). PRs state a
concrete in-game Quick Test: *round 10, place four buildings around the hole,
watch the boss clear all four before it touches the base.*

## Risks / open items

- **The balancing-parity fixture is the real fence for BP-1.** D1 was chosen
  precisely so no non-boss number moves. If `test_balancing_parity` goes red, the
  floor has leaked into other types — that is a bug, not an expected update.
- **BP-3 changes what "nearest" means** and will alter which building the boss
  eats first on existing saves/maps. Intended, but it is a felt gameplay change,
  not a silent fix.
- **A boss the defenders cannot reach still stalls the round** — the wave never
  clears while it lives. BP-1 removes the *freeze* cause; it does not add a
  general stall guard. D2 deliberately declined a timeout. Revisit only if it
  bites in playtest.
- **`attack_range_tiles` (2–3) remains dead data** (D4). `Enemy.__init__` builds a
  `RangeSensor` with it (`enemy.py:114`) but nothing enemy-side reads it — the
  boss must be *adjacent* to attack. A "Wrecking Ball" with 3-tile reach still
  waddles up and touches its victim. Wiring it up is its own phase.
- **Boss rounds are crowded** (`[boss] + all siege + standards + raiders`), so
  BP-3's "target died to someone else" path is common, not an edge case. Test it
  with a populated wave, not a lone boss.
