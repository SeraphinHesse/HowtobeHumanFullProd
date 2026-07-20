<!-- status: NOT STARTED — authored 2026-07-20 -->

# EnemyScalingReworkPLAN.md — global era clock, per-era manual stats, batch spawning

Phased, agent-executable plan (same family as `BossReworkPLAN.md` /
`EnemyReworkPLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/EnemyScalingReworkPLAN.md ES-1-ES-5` or
phase-by-phase.

Packages: **engine** (`engine/era_math.py`, new) + **game** (`game/enemies`,
`game/core`) + **data** (`data/balancing/enemies.json`,
`data/schemas/enemies.schema.json`) + **editor** (`editor/panels/balancing.py`,
ES-5 only). The cross-package spread is user-approved (this plan). Subsystem
docs: `game/enemies/CLAUDE.md`, `editor/panels/CLAUDE.md`, `data/CLAUDE.md`.

**Ordering constraint: `BossReworkPLAN.md` (NOT STARTED) builds ON TOP of this
plan and must not start before ES-5 lands.** ES-5 amends that plan so the two
agree (§2 D8).

## 1. Context

Source: the user's *Enemy Scaling Rework notes*, scoped through two rounds of
clarifying questions (§2 records every answer).

Enemy difficulty today is three unrelated systems that don't even share a
period: additive `scale_tiers` stepping every **9** rounds
(`scale_every_n_levels: 9`), boss eras stepping every **10** rounds
(`Boss.round_interval: 10`), and per-type count formulas hardcoded in
`game/enemies/spawner.py` (`base + (round−1)·(epr+tier)` for standards;
raider/siege/formation each different). A designer cannot say "in era 2,
standards have exactly 190 HP and grow +12 HP per round" — stats are only
reachable as base + cumulative tier sums, counts only through code formulas.

Outcome: **one global era clock** (era length and boss round configurable in
the `EnemyScaling` general block); every enemy type gets **fresh, fully manual
stats per era** plus per-round in-era scaling, per-era counts, and a per-era
simultaneous-spawn **batch size**; era arrays are variable-length with an
**endgame scaling** section past the last defined era; and the editor shows a
greyed-out "last round of the previous era" reference beside each era's fields.

## 2. Decisions (settled with the user — do not re-litigate)

- **D1 — The era clock is global and lives in `EnemyScaling`.**
  `rounds_per_era: 10` and `boss_round_in_era: 10` (1..rounds_per_era, default
  = last). `era = (round − 1) // rounds_per_era`;
  `round_in_era = (round − 1) % rounds_per_era + 1`; a round is a boss round
  iff `round_in_era == boss_round_in_era`. Era 0's boss is round 10; era 1
  enemies start at round 11. At the shipped values this is bit-equal to the old
  `round % 10 == 0` / `round // 10 − 1` boss math. `scale_every_n_levels` (9)
  and `Boss.round_interval` are **deleted** — the tier/era mismatch goes with
  them.
- **D2 — Per-era stats are fresh manual values, not scaled bases.** Each era
  row carries the full stat block; in-era growth is a **flat additive
  per-round delta** (`stats + (round_in_era − 1) × per_round`). Deltas cover
  `hp` / `dmg` / `move_speed` only — `attack_speed` and `attack_range_tiles`
  change **between** eras, not within one (deliberate scope; the old tiers
  never scaled them either).
- **D3 — Counts are per-era, types keep their global `start_round`.**
  `n(round) = floor(count_start + (round − r0) × count_per_round)` where
  `r0 = max(era's first round, start_round)`. `count_per_round` is a **number,
  possibly fractional** — `1/3` reproduces the Formation accretion
  (`//rounds_per_formation`), `1.0` the siege one, integers the raider/standard
  slopes. Raiders at round 6 and siege at 14 keep working mid-era.
  `base_count` / `per_round` / `rounds_per_cannon` / `rounds_per_formation` are
  subsumed and deleted.
- **D4 — Batch spawn = batch size per spawn event.** Per-era
  `batch_size` (seeded `era + 1`: singles in era 0, pairs in era 1, triples in
  era 2, …): one timer expiry pops up to `batch_size` queue entries at once.
  Round **totals are unchanged** by this knob; boss-round escorts batch too.
- **D5 — Era arrays are variable-length; past the end, clamp × endgame
  factors.** `minItems: 1`, **no `maxItems`** — which by itself lights up the
  editor's existing ER-5 `+ Row`/`− Row` buttons (`balancing.py:352-398`), no
  editor code needed. Arrays are independent per type (no cross-array length
  cross-check — the Boss-style clamp covers a short array). For
  `era ≥ len(eras)`: `N = era − (len(eras) − 1)` and every variable in the
  virtual row is `last_row_value × factor^N` (counts floored to int) — the
  same compounding shape as BossReworkPLAN D1. Per-type
  `endgame_scaling: {hp, dmg, move_speed, count}` and a general
  `EnemyScaling.endgame_scaling: {batch_size, spawn_interval}`, **all shipped
  1.0** (behaviour-neutral until tuned).
- **D6 — Seed every era value from today's formulas** so day-one gameplay is
  ~identical. Exact parity is impossible at tier boundaries (the step moves
  from every 9 rounds to every 10) — accepted. Raider seeds identical stat
  rows + zero deltas (it deliberately never scaled — preserved as data, not
  code).
- **D7 — Era math lives in `engine/era_math.py`** (pure, stdlib-only) so the
  game and the editor's greyed preview share ONE formula — `editor/` and
  `game/` never import each other; both consume `engine/` (pillar 2). The
  alternative (duplicating the formula in `editor/`) invites drift. This is
  the one place engine hosts balancing math; the module stays free of any
  pygame/Qt/game import (drop it into the purity guards).
- **D8 — Bosses stay in `BossReworkPLAN.md`; this plan only moves the clock.**
  Boss stat/count/second-phase design is untouched here. This plan re-derives
  the boss round trigger and the boss's era from D1's general block (the
  `Boss.round_interval` key dies) and ES-5 amends BossReworkPLAN: its D1 era
  formula and BR-4 reuse `engine.era_math`; its D8 Commander no longer "takes
  the scale-tier bonuses" (tiers are gone) but carries its own `eras[]` block
  resolved by the base per-era resolver, with era counts at 0.
- **D9 — The greyed previous-era reference is computed, read-only, editor
  only.** Beside each era-row field the balancing panel shows, in pale
  disabled text, what that value resolves to on the **last round of the
  previous era** (`stats + (rounds_per_era − 1) × per_round`; counts at the
  era's last active round; flat fields just show the previous era's value).
  Era 0 shows nothing. Recomputed from the STAGED doc, so editing era 1
  updates era 2's reference before saving.

## 3. Where the code is

All **verified** by direct read (2026-07-20).

| Concern | Location |
|---|---|
| Tier resolve + per-era spawn interval | `game/enemies/spawner.py:107-113` |
| `_compose` — boss trigger + standard count formula | `game/enemies/spawner.py:166-171` |
| `_boss_round` — era derive + past-table fallback formulas | `game/enemies/spawner.py:184-222` |
| Raider / siege / formation count formulas | `game/enemies/spawner.py:224-268` |
| `_build_queue` (ramp/jitter delays) | `game/enemies/spawner.py:270-290` |
| `update` — pops ONE enemy per timer expiry | `game/enemies/spawner.py:294-316` |
| `spawn_death_swarm` — children take `self._tier` | `game/enemies/spawner.py:320-339` |
| `enemy_tier` property (read by tests) | `game/enemies/spawner.py:81`, `tools/tests/test_death_spawn.py:157` |
| `tier_scaled_stats` (the ONE tier formula) | `game/enemies/enemy.py:68-82` |
| Per-type `_resolve_stats` overrides | `game/enemies/enemy.py:144-146, 218-222, 232-236, 258-264, 294-298` |
| `_resolve_era` (base row-0; Boss clamp) | `game/enemies/enemy.py:148-151, 289-292` |
| `variant_slot` — `tier` picks the ART era | `game/enemies/enemy.py:44-65` |
| Session boss-round checks (announce + cutscene `boss_num`) | `game/core/session.py:247-251, 464-470` |
| `EnemyScaling` block + per-type formulas' data | `data/balancing/enemies.json:2-41, 153-247` |
| `$defs/scale_tier` | `data/schemas/enemies.schema.json:90-126` |
| Editor: recursive form + ER-5 `+ Row`/`− Row` | `editor/panels/balancing.py:295-407` |
| Editor: leaf row + pending-change dot (pattern for D9) | `editor/panels/balancing.py:409-424` |
| Count-formula test pins | `tools/tests/test_enemies.py:246-330`, `tools/tests/test_boss.py:110-145` |
| Tier-stat test pins | `tools/tests/test_enemies.py:97, 138, 632`, `tools/tests/test_boss.py:247-248`, `tools/tests/test_death_spawn.py:157-158` |
| Resizable-arrays editor pin (names `scale_tiers`) | `tools/tests/test_editor_panels.py:571-585` |

**Reuse, do not reinvent:** the ER-5 row buttons already give add/remove-era UI
for free once the schema says `minItems: 1`; the Boss's era clamp
(`enemy.py:289-292`) is the clamp-to-last precedent D5 generalises; the
pending-dot second-QLabel slot in `_add_leaf_row` is exactly where D9's grey
label goes; `write_validated` is the only writer; `TempDataCase` pins fixtures.

## 4. New data model (`data/balancing/enemies.json`)

`EnemyScaling` becomes:

```
rounds_per_era: 10            boss_round_in_era: 10
spawn_ramp_enabled / spawn_ramp_range        (unchanged, global)
eras: [ { batch_size, spawn_interval } ]     (minItems 1, no maxItems)
endgame_scaling: { batch_size, spawn_interval }          (factors, ship 1.0)
```

DELETED: `base_enemy_count`, `enemies_per_round`, `scale_every_n_levels`,
`scale_tiers`, global `spawn_interval`.

Each of `Standard` / `Raider` / `SiegeCannon` / `Formation` gains:

```
eras: [ {                                    (minItems 1, no maxItems)
  stats:     { hp, dmg, move_speed, attack_speed, attack_range_tiles },
  per_round: { hp, dmg, move_speed },
  count_start: int,
  count_per_round: number,
} ]
endgame_scaling: { hp, dmg, move_speed, count }          (factors, ship 1.0)
```

The flat top-level `hp/dmg/move_speed/attack_speed/attack_range_tiles` leave
the type root (they move into era rows). Kept at type root: `start_round`
(Standard gains one, at 1), `footprint`, `sprite_scale`, `death_spawn`, and the
siege ordering keys `mix_ratio` / `queue_lead_count`. Deleted from type roots:
`base_count`, `per_round`, `rounds_per_cannon`, `rounds_per_formation` (all
subsumed by D3). `Boss` loses only `round_interval`; everything else about it
waits for BossReworkPLAN.

**Seeding (D6) — the executor computes these, writing via the validating
writer.** Five era rows everywhere (matching today's 5 tiers / 5 boss eras).
For era `e` with first round `f(e) = e·10 + 1`:

- stats row = type base + `Σ scale_tiers[0..e)` (today's `tier_scaled_stats`);
  `per_round` all 0 (today stats step per tier, never per round). Raider: five
  identical rows, zero deltas.
- Standard: `count_start = 4 + (f(e)−1)·(2+e)`, `count_per_round = 2+e` —
  today's formula with the tier pinned to the era, exact within the era.
  Raider: slope 2 anchored at start_round 6. Siege: slope 1.0 anchored at 14.
  Formation: slope 1/3 anchored at 16. (`count_start` for a type whose
  `start_round` falls inside era `e` is its count at `r0 = start_round`.)
- `eras[e].spawn_interval = max(0.1, 0.7 − Σ shaves[0..e))`;
  `batch_size = e + 1`.

## 5. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| ES-1 | `engine/era_math.py` — pure era/stat/count resolvers + tests | not started |
| ES-2 | Data + schema restructure, seeded; all game readers swap over | not started |
| ES-3 | Batch spawning + per-era spawn pacing | not started |
| ES-4 | Endgame scaling past the last defined era | not started |
| ES-5 | Editor greyed previous-era reference; docs; BossReworkPLAN amendments | not started |

---

### ES-1 — Era math helper (pure, no behaviour change)

**Goal.** One shared module both the game and the editor call; nothing else
changes this phase.

**Files — new.** `engine/era_math.py`, stdlib-only:
- `era_of_round(round_num, rounds_per_era)` / `round_in_era(...)` /
  `is_boss_round(round_num, rounds_per_era, boss_round_in_era)` (D1 formulas).
- `resolve_era_row(eras, era, endgame_factors)` — clamp to the last row; for
  `era ≥ len(eras)` return a **new dict** with every numeric leaf scaled by
  `factor^N` (D5; counts floored). Never mutates the input rows.
- `stats_at_round(row, round_in_era)` — `stats + (round_in_era − 1) ×
  per_round` per D2 key.
- `count_at_round(row, round_num, era_first_round, start_round)` — D3's
  floored linear formula, 0 below `start_round`.
- `prev_era_reference(rows, era, rounds_per_era, ...)` — the D9 numbers
  (last-round stats / final count of era − 1), for the editor.

**Files — modified.** Add the module to the engine test tree +
`test_editor_viewport.TestPurity`'s import list (it will be imported by the
editor in ES-5; the guard is cheap to extend now).

**Tests.** New `tools/tests/test_era_math.py` (core tier): boundary rounds
(1, 10, 11, 20), non-default `rounds_per_era`/`boss_round_in_era`, clamp +
endgame `f^N`, fractional `count_per_round` reproducing today's siege and
formation sequences, all-1.0 factors = plain clamp.

**Exit gate.** `py tools/smoke.py` + `py tools/testgate.py check --affected`
→ GATE PASS. No behaviour anywhere else changed.

---

### ES-2 — Data restructure + game readers (the big one)

**Goal.** The new data model (§4), seeded, with every reader swapped to
`engine.era_math`. Gameplay ≈ today: counts exact within every era, stats
exact except that steps land at rounds 11/21/31/41 instead of 10/19/28/37
(D6's accepted 9→10 drift — state the delta in the phase report).

**Files — modified.**
- `data/schemas/enemies.schema.json` — new `$defs` (`era_row`,
  `type_era_row`, `endgame_factors`); delete `$defs/scale_tier`; every numeric
  property carries `description` + bounds (D-12; house bounds policy). **No
  `oneOf` unions** (a type-less node crashes the balancing panel — standing
  rule in `data/CLAUDE.md`).
- `data/balancing/enemies.json` — restructured + seeded per §4, through
  `write_validated`.
- `game/enemies/spawner.py` — `begin_round` resolves the era + its
  `EnemyScaling.eras` row (stash `self._era`; keep `enemy_tier` as a property
  alias returning the era — one external test reads it); the boss trigger at
  :166-168 → `era_math.is_boss_round`; the standard/raider/siege/formation
  count sites (:170-171, :224-268) and `_boss_round`'s past-table fallback
  (:202-213) → `era_math.count_at_round` over each type's resolved era row;
  `_boss_round`'s era derive (:193-194) → `era_math.era_of_round`;
  `spawn_death_swarm` (:335) passes the era.
- `game/enemies/enemy.py` — `tier_scaled_stats` → an era-row resolver
  (`resolve_era_row` + `stats_at_round`; it needs the round's position in the
  era, so thread `round_in_era` alongside — the spawner already threads `tier`
  into `create_enemy`, and that argument **becomes the era**; add the
  in-era round the same way). The four `_resolve_stats` overrides collapse:
  Standard/Raider/Siege/Formation all read their own `STAT_SUBTREE` block's
  `eras` — the base implementation can finally be `STAT_SUBTREE`-driven,
  retiring the "reads `Standard` literally" trap (keep the Formation
  regression test, now proving the generic path). `Boss._resolve_stats` /
  `_resolve_era` unchanged except the era argument is now the global era.
  `variant_slot` is untouched (its `tier` argument is already an era-clamped
  art index; art eras now advance every 10 rounds, not 9 — accepted).
- `game/core/session.py` — :247-251 and :464-470 → `era_math.is_boss_round` /
  `boss_num = era_of_round(round) + 1` reading `EnemyScaling`.
- Tests — the count/stat formula pins in `test_enemies.py`, `test_boss.py`,
  `test_death_spawn.py` re-anchor on the new data model (compute expectations
  from era rows, not tier formulas); `test_editor_panels.py:571-585` re-pins
  resizability on the new arrays (`EnemyScaling/eras` **is** resizable,
  `Boss/round_counts` still is not). Pinned fixtures (`TempDataCase`), never
  live `data/`.

**Traps.**
- The spawner's `tier` thread is also the **art** index (`variant_slot`) and
  the **death-spawn row** index (`_resolve_era`) — pass the global era
  everywhere, do not invent a second channel.
- `data/CLAUDE.md`'s ER-1/ER-3 sections and `game/enemies/CLAUDE.md` describe
  the tier system in several places — doc updates land in ES-5, but leave a
  `<!-- ES-2: tiers replaced by eras, docs updated in ES-5 -->` marker only if
  the phase must hand off early; otherwise just do ES-5.

**Exit gate.** GATE PASS (full `--affected`). Live: round 9→10→11 boundary —
boss on 10, visibly fresher enemies from 11; a mid-era round's counts match a
hand-computed era-row value.

---

### ES-3 — Batch spawning + per-era pacing

**Goal.** D4: one timer expiry releases up to `batch_size` enemies at once;
spawn pacing is the era row's own `spawn_interval`.

**Files — modified.**
- `game/enemies/spawner.py` — `begin_round` takes `_interval` and
  `_batch_size` from the resolved `EnemyScaling.eras` row (the tier-shave
  arithmetic at :107-113 is already gone since ES-2); `update` (:294-316) pops
  up to `_batch_size` entries per expiry (each popped entry spawns exactly as
  today — one `create_enemy` + `scene.spawn` per entry, rng order preserved
  within the batch); the next timer comes from the new queue head (ramp) or
  one re-rolled jitter per **batch** (ramp-off). Boss rounds batch the same
  way (the boss simply leads its batch).

**Tests.** `test_enemies.py`: with `batch_size` 2/3 a wave's spawn events
halve/third but the round total is unchanged; `batch_size` 1 is
byte-identical to ES-2 (same rng draw sequence — the fence for the
deterministic fixtures); a seeded run crossing an era boundary changes batch
size on the boundary round.

**Exit gate.** GATE PASS. Live: era 1 visibly spawns pairs, era 2 triples.

---

### ES-4 — Endgame scaling

**Goal.** D5 past-the-end behaviour, shipped behaviour-neutral.

**Files — modified.**
- `data/schemas/enemies.schema.json` + `data/balancing/enemies.json` —
  `endgame_scaling` blocks (per type + `EnemyScaling`), all factors 1.0.
- `game/enemies/spawner.py` / `game/enemies/enemy.py` — every era-row lookup
  goes through `era_math.resolve_era_row(eras, era, endgame_factors)` (most
  already do from ES-2; this phase threads the factors and deletes any
  remaining raw clamp).

**Tests.** `test_era_math.py` already proves `f^N`; add an integration pin:
with a non-1.0 fixture, era 5/6/7 waves resolve `last × f¹/f²/f³` (stats and
counts, counts as ints); with the shipped 1.0 file, a round-60 wave is
byte-identical to ES-3.

**Exit gate.** GATE PASS + a headless assertion of a round-60 standard's
resolved stats and count.

---

### ES-5 — Editor previous-era reference, docs, plan alignment

**Goal.** D9's greyed reference; all docs true again; BossReworkPLAN aligned.

**Files — modified.**
- `editor/panels/balancing.py` — in `_add_leaf_row` (:409-424), when the
  field's path sits inside an `eras/<i>` subtree with `i > 0`, add a second
  read-only `QLabel` after the dot showing `era_math.prev_era_reference(...)`
  formatted compactly (e.g. `prev ⌐ 185`), `setEnabled(False)` + palette-grey
  (keep it legible on both themes — panel-local colors are deliberately
  theme-independent). Values come from the **staged** `self._doc` (D9) and
  refresh wherever `_refresh_dirty` runs; rebuilds (row add/remove) regenerate
  them for free. `rounds_per_era` is read off the staged doc's `EnemyScaling`.
  The editor imports `engine.era_math` — allowed (editor consumes engine);
  module already in `TestPurity` since ES-1.
- Docs (step-3 rule: the package docs, never the root router):
  - `game/enemies/CLAUDE.md` — the scale-tier sections describe the era
    system: D1 clock, per-era rows, D3 counts, D4 batching, D5 endgame; the
    "Raider deliberately does not scale" note becomes "Raider ships flat era
    rows"; the `_resolve_stats`-override trap section records that the base
    resolver is now `STAT_SUBTREE`-driven.
  - `game/core/CLAUDE.md` — the two boss-round checks read `EnemyScaling` via
    `era_math` (one-line touch in the 10G sections).
  - `data/CLAUDE.md` — the enemies balancing shape (§Balancing files): era
    rows, endgame blocks, deleted keys.
  - `editor/panels/CLAUDE.md` — the greyed-reference labels next to the ER-5
    row buttons.
  - `engine/CLAUDE.md` — one line: `era_math` exists, is pure, and is the one
    shared balancing-math module (D7's argument recorded).
- `planning/BossReworkPLAN.md` — the D8 amendments: PREREQUISITE line at the
  top; D1's `round // interval − 1` → `era_math.era_of_round` and
  `Boss.round_interval` → the `EnemyScaling` clock; BR-4 reuses
  `resolve_era_row` instead of a bespoke `_endgame_scaled`; BR-2's D8
  Commander gets `eras[]`-based schedule keys (counts 0) instead of
  `start_round/base_count/per_round`, and its "takes the scale-tier bonuses"
  becomes "resolved by the base per-era resolver".

**Tests.** `test_editor_panels.py` (editor tier): an era-1 stat field carries
a populated, disabled reference label matching a hand-computed
`prev_era_reference`; era 0 carries none; editing era 0's `per_round.hp`
updates era 1's reference before saving.

**Exit gate.** `py tools/smoke.py` + the **full** `py tools/testgate.py
check` → GATE PASS.

## 6. Verification

```bash
py tools/smoke.py                      # data validation + 5-frame headless boot
py tools/testgate.py check --affected  # while iterating
py tools/testgate.py check             # ONCE, before handoff — the gate is ZERO
```

Live `py game/main.py` — the Quick Test for the PR:
1. Rounds 9 → 10 → 11: boss on round 10; from round 11 enemies carry era-1
   stats (visibly tankier) and spawn **in pairs**; round 21 begins triples.
2. A mid-era round's standard count matches the era row's
   `count_start + Δ·count_per_round` by hand.
3. Editor → enemies domain: era arrays show `+ Row`/`− Row`; adding an era
   copies the last row and saves schema-valid; era ≥ 1 stat fields show the
   greyed previous-era last-round reference, and it updates live when the
   previous era is edited.
4. Cheat to round 60 (past the 5 seeded eras) with a test factor > 1.0 in a
   scratch copy: stats/counts grow per `f^N`; with the shipped 1.0 file the
   wave repeats era 4's last-round values.

## 7. Risks / open items

- **The `tier` argument is three things** (stats row, art era, death-spawn
  row) threaded through `create_enemy`. ES-2 renames its meaning to the global
  era in ONE change; a partial swap would mismatch art and stats silently.
  The deterministic wave fixtures are the fence.
- **Deterministic fixtures churn once, in ES-2.** Count values shift at old
  tier boundaries (9→10). Re-pin from the new model's hand-computed values —
  never by copying observed output.
- **Fractional `count_per_round` + floor** must reproduce the old `//`
  sequences exactly at the seeded values (`test_era_math.py` pins siege +
  formation). Beware float drift on long eras — compute as
  `floor(count_start + k · count_per_round)` with `k` an int, not by repeated
  addition; if 1/3 proves drift-prone, `round(..., 9)` before the floor.
- **Per-era `spawn_interval` beyond era 4** no longer shaves further (old
  tier 5 reached 0.215s at round 46+; the seeded era-4 row holds 0.365s until
  the designer tunes `endgame_scaling.spawn_interval`). Deliberate — the
  endgame block is the tuning point (D5/D6).
- **`enemy_tier` survives as an alias** (test_death_spawn reads it); rename
  properly only if that test moves off it in the same change.
- **BossReworkPLAN must not start mid-flight.** Its BR-1/BR-4 edit the same
  files (`enemy.py`, `spawner.py`, the schema). The prerequisite line lands in
  ES-5, but the constraint binds from ES-2 onward — flagged here for the user
  running the plans.
- **The greyed reference is per-field UI in a generic recursive form** — keep
  the era detection purely path-shape-based (`…/eras/<int>/…`) so any future
  type with era rows (the Commander) inherits it with zero edits.
