<!-- status: NOT STARTED — authored 2026-07-20, reworked against current state 2026-08-05 -->

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

> ## Reworked 2026-08-05 — what changed and why
>
> The plan was authored 2026-07-20 and re-verified against `Development`
> (`048f321`) on 2026-08-05. **No decision was overturned; D1–D9 all stand.**
> Four things moved underneath it:
>
> 1. **The 9-vs-10 clock mismatch is already gone.** `scale_every_n_levels` is
>    now **10**, matching `Boss.round_interval` 10. The era and the tier are
>    therefore the *same integer* today. D6's "exact parity is impossible,
>    drift accepted" is **void** — seeding is now exact, and the ES-2 risk of
>    churning every deterministic wave fixture largely evaporates.
> 2. **Prey hunting + tile-weight overwrite landed** (commit `1107439`,
>    2026-08-05). Every enemy type root now carries **`hunts`** and
>    **`condition_path_weights`**. §4's "kept at type root" list did not name
>    them; as originally written the restructure would have deleted a live
>    subsystem. Fixed, and they stay flat per type (user decision, D10).
> 3. **Exact parity forced a correction to D3.** `count_start: int` cannot
>    reproduce the Formation's accretion across an era boundary — see **D3′**.
>    `count_start` becomes a **number**.
> 4. **Round 0 is the tutorial round** (TU-9) and is special-cased in the
>    spawner. `era_of_round(0)` is `−1` under naive floor division. **D11**
>    pins the contract.
>
> Every line reference in §3 was re-verified on 2026-08-05 and updated.

## 1. Context

Source: the user's *Enemy Scaling Rework notes*, scoped through two rounds of
clarifying questions (§2 records every answer).

Enemy difficulty today is **two** systems bolted together, plus hardcoded
counts. The tier clock and the boss clock now agree — both step every **10**
rounds (`EnemyScaling.scale_every_n_levels: 10`,
`EnemyTypes.Boss.round_interval: 10`) — so the *period* problem the original
draft opened with is fixed. What remains is the shape of the data:

- **Stats are only reachable as `base + cumulative tier sums`**
  (`game/enemies/enemy.py:68-82`). A designer cannot say "in era 2, standards
  have exactly 190 HP" — only "base 55, plus whatever the first two tier rows
  happen to add". Nor can they say "and grow +12 HP per round *within* the
  era": there is no in-era growth at all, stats step once per 10 rounds and sit
  flat between steps.
- **Counts are code, not data.** `game/enemies/spawner.py` hardcodes a
  different formula per type: `base + (r−1)·(epr+tier)` for standards
  (:186-188), `base + (r−r0)·per_round` for raiders (:247), `base + (r−r0)//n`
  accretion for siege (:257-258) and formations (:282-283).
- **The clock itself is not configurable.** The 10 is two independent literals
  in `data/`, and `boss_round_in_era` does not exist — the boss is always the
  *last* round of its era because `round % 10 == 0` says so.
- **Everything past the 5th tier is a cliff.** `min(tier, len(tiers))` clamps;
  from round 51 onward stats never grow again while counts grow forever.

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
  enemies start at round 11. At the shipped values this is bit-equal to the
  current `round % 10 == 0` / `round // 10 − 1` boss math **and** to the
  current tier math `(round − 1) // 10`. `scale_every_n_levels` and
  `Boss.round_interval` are **deleted** — one clock replaces two literals that
  happen to agree today and could silently diverge again tomorrow.
- **D2 — Per-era stats are fresh manual values, not scaled bases.** Each era
  row carries the full stat block; in-era growth is a **flat additive
  per-round delta** (`stats + (round_in_era − 1) × per_round`). Deltas cover
  `hp` / `dmg` / `move_speed` only — `attack_speed` and `attack_range_tiles`
  change **between** eras, not within one (deliberate scope; the tiers never
  scaled them either).
- **D3 — Counts are per-era, types keep their global `start_round`.**
  `n(round) = floor(count_start + (round − r0) × count_per_round)` where
  `r0 = max(era's first round, start_round)`. `count_per_round` is a **number,
  possibly fractional** — `1/3` reproduces the Formation accretion
  (`//rounds_per_formation`), `1.0` the siege one, integers the raider/standard
  slopes. Raiders at round 5 and siege at 14 keep working mid-era.
  `base_count` / `per_round` / `rounds_per_cannon` / `rounds_per_formation` are
  subsumed and deleted.
- **D3′ (2026-08-05 correction) — `count_start` is a NUMBER, not an int.**
  Exact parity (D6) is impossible with an integer. The old accretion formulas
  floor from a **type-global** anchor; D3 re-anchors at each **era's** first
  round, and the fractional remainder is lost at the boundary. Worked example —
  Formation, `start_round 16`, `rounds_per_formation 3`, old formula
  `1 + (r−16)//3`:

  | round | old | D3 with `count_start` int 2 @ r0=21 | D3 with `count_start` 2.667 |
  |---|---|---|---|
  | 21 | 2 | 2 ✓ | 2 ✓ |
  | 22 | 3 | **2 ✗** | 3 ✓ |
  | 23 | 3 | 3 | 3 ✓ |

  Seeding therefore writes the **exact rational count at `r0`** (era 2's
  Formation row is `count_start: 2.667`), and the resolver floors. A designer
  authoring a fresh era types a whole number and gets the obvious behaviour;
  fractions appear only in seeded accretion rows. Compute as
  `floor(round(count_start + k × count_per_round, 9))` with `k` an int — never
  by repeated addition (float drift lands exactly on the integers that matter).
- **D4 — Batch spawn = batch size per spawn event.** Per-era
  `batch_size` (seeded `era + 1`: singles in era 0, pairs in era 1, triples in
  era 2, …): one timer expiry pops up to `batch_size` queue entries at once.
  Round **totals are unchanged** by this knob; boss-round escorts batch too.
- **D5 — Era arrays are variable-length; past the end, clamp × endgame
  factors.** `minItems: 1`, **no `maxItems`** — which by itself lights up the
  editor's existing ER-5 `+ Row`/`− Row` buttons (`balancing.py:396-451`), no
  editor code needed. Arrays are independent per type (no cross-array length
  cross-check — the Boss-style clamp covers a short array). For
  `era ≥ len(eras)`: `N = era − (len(eras) − 1)` and every variable in the
  virtual row is `last_row_value × factor^N` (counts floored to int) — the
  same compounding shape as BossReworkPLAN D1. Per-type
  `endgame_scaling: {hp, dmg, move_speed, count}` and a general
  `EnemyScaling.endgame_scaling: {batch_size, spawn_interval}`, **all shipped
  1.0** (behaviour-neutral until tuned). This also removes today's cliff: past
  tier 5 stats currently freeze forever while counts keep climbing.
- **D6 — Seeding is EXACT (2026-08-05: strengthened).** The original draft
  accepted parity drift because tiers stepped every 9 rounds and eras every 10.
  **`scale_every_n_levels` is now 10**, so `era == tier` for every round and
  every seeded value reproduces today's number exactly — stats, counts, spawn
  interval. The one deliberate behaviour change in the whole plan is D4's
  batching (and it preserves round totals). Any post-ES-2 gameplay difference
  at `batch_size: 1` is a **bug**, not accepted drift — that is the fence for
  the deterministic wave fixtures. Raider seeds identical stat rows + zero
  deltas (it deliberately never scaled — preserved as data, not code).
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
- **D10 (2026-08-05, new) — Behavioural per-type keys stay FLAT at the type
  root; only stats and counts go per-era.** `hunts`,
  `condition_path_weights`, `kidnapping`, `footprint`, `sprite_scale`,
  `death_spawn`, `registry_group`, `start_round`, `mix_ratio`,
  `queue_lead_count` are unchanged by this plan. A Raider hunts economic
  buildings in every era. *Why:* the restructure is about **numbers that scale
  with round**, and these do not; promoting them into era rows multiplies the
  seeding surface and the schema for no requested capability. Promoting
  `hunts` / `condition_path_weights` into era rows later is additive and does
  not invalidate anything here (Risks).
- **D11 (2026-08-05, new) — Round 0 is era 0 by definition.** Round 0 is the
  tutorial's forced-composition round (TU-9, `spawner.py:174-182`): it composes
  exactly `EnemyScaling.tutorial_round_enemy_count` Standards and skips every
  scaling formula. Naive floor division gives `(0−1)//10 == −1`, which would
  index the era array from the end. `era_math.era_of_round` **clamps at 0** and
  `is_boss_round(0, …)` is **False** for every configuration — pinned by test
  in ES-1, so no caller has to remember the guard. The spawner's existing
  round-0 early return stays where it is (it is a *composition* rule, not a
  clock rule).

## 3. Where the code is

All **re-verified by direct read on 2026-08-05** against `Development`
(`048f321`). Line numbers moved ~+17 in `spawner.py`, ~+4 in `enemy.py` and
~+45 in `balancing.py` since the 2026-07-20 authoring; **no formula was
rewritten** — every structure the plan targets is intact.

| Concern | Location |
|---|---|
| Tier resolve + spawn-interval shave | `game/enemies/spawner.py:107-118` |
| Round-0 tutorial composition (D11) | `game/enemies/spawner.py:174-182` |
| `_compose` — boss trigger + standard count formula | `game/enemies/spawner.py:183-188` |
| `_boss_round` — era derive + past-table fallback formulas | `game/enemies/spawner.py:201-239` |
| Raider count formula | `game/enemies/spawner.py:241-249` |
| Siege count formula (+ lead/mix split) | `game/enemies/spawner.py:251-262` |
| Formation count formula | `game/enemies/spawner.py:264-285` |
| `_build_queue` (ramp/jitter delays) | `game/enemies/spawner.py:287-307` |
| `update` — pops ONE enemy per timer expiry | `game/enemies/spawner.py:311-333` |
| `spawn_death_swarm` — children take `self._tier` | `game/enemies/spawner.py:337-356` (tier at :352) |
| `enemy_tier` property (read by tests) | `game/enemies/spawner.py:81-82` |
| `_boss_era` stash | `game/enemies/spawner.py:64`, set at `:210` |
| `ENABLE_RAIDERS/SIEGE/BOSS/FORMATION` flags | `game/enemies/spawner.py:31-34` |
| `tier_scaled_stats` (the ONE tier formula) | `game/enemies/enemy.py:68-82` |
| `_cond_weights` copy (prey/tile-weight, D10) | `game/enemies/enemy.py:~149` |
| Base `_resolve_stats` (reads `Standard` LITERALLY) | `game/enemies/enemy.py:148-150` |
| `_resolve_era` (base row-0) | `game/enemies/enemy.py:152-155` |
| Raider override (does NOT scale) | `game/enemies/enemy.py:222-226` |
| SiegeCannon override (scales like Standard) | `game/enemies/enemy.py:236-240` |
| Formation override (scales like Standard) | `game/enemies/enemy.py:262-268` |
| Boss `_resolve_era` clamp / `_resolve_stats` | `game/enemies/enemy.py:293-296, 298-302` |
| `variant_slot` — `tier` picks the ART era | `game/enemies/enemy.py:45-65` |
| `ENEMY_CLASSES` (still exactly 5 types) | `game/enemies/enemy.py:330-336` |
| Session boss-round checks (announce + cutscene `boss_num`) | `game/core/session.py:247-251, 464-470` |
| `EnemyScaling` block + per-type data | `data/balancing/enemies.json:2-41, 156-263` |
| `$defs/scale_tier` | `data/schemas/enemies.schema.json:90-126` |
| Editor: recursive form + array build | `editor/panels/balancing.py:340-394` |
| Editor: ER-5 `+ Row`/`− Row` | `editor/panels/balancing.py:396-451` |
| Editor: leaf row + pending-change dot (pattern for D9) | `editor/panels/balancing.py:453+` |
| Count-formula test pins | `tools/tests/test_enemies.py`, `tools/tests/test_boss.py` |
| Tier-stat test pins | `tools/tests/test_enemies.py`, `test_boss.py`, `test_death_spawn.py:157-158` |
| Resizable-arrays editor pin (names `scale_tiers`) | `tools/tests/test_editor_panels.py:571-585` |
| **Must stay green (new since authoring)** | `tools/tests/test_prey_hunting.py`, `test_tile_runtime.py`, `test_pathfinder.py` |

**Reuse, do not reinvent:** the ER-5 row buttons already give add/remove-era UI
for free once the schema says `minItems: 1`; the Boss's era clamp
(`enemy.py:293-296`) is the clamp-to-last precedent D5 generalises; the
pending-dot second-QLabel slot in `_add_leaf_row` is exactly where D9's grey
label goes; `write_validated` is the only writer; `TempDataCase` pins fixtures.

## 4. New data model (`data/balancing/enemies.json`)

`EnemyScaling` becomes:

```
rounds_per_era: 10            boss_round_in_era: 10
spawn_ramp_enabled / spawn_ramp_range        (unchanged, global)
tutorial_round_enemy_count                   (unchanged, global — D11)
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
  count_start: number,                       (D3′ — NOT int)
  count_per_round: number,
} ]
endgame_scaling: { hp, dmg, move_speed, count }          (factors, ship 1.0)
```

The flat top-level `hp/dmg/move_speed/attack_speed/attack_range_tiles` leave
the type root (they move into era rows).

**Kept at type root, untouched (D10 — this list is exhaustive; anything not
named here and not listed as deleted is a bug in the restructure):**
`start_round` (Standard gains one, at 1), `footprint`, `sprite_scale`,
`death_spawn`, `registry_group`, `kidnapping`, **`hunts`**,
**`condition_path_weights`**, and the siege ordering keys `mix_ratio` /
`queue_lead_count`.

Deleted from type roots: `base_count`, `per_round`, `rounds_per_cannon`,
`rounds_per_formation` (all subsumed by D3). `Boss` loses only
`round_interval`; everything else about it waits for BossReworkPLAN.

`MortarTargeting` is out of scope and untouched. (Noted in passing: nothing in
`engine/`, `game/`, `editor/` or `tools/` reads it — it is orphaned data. Not
this plan's problem; do not delete it here.)

### Seeding (D6) — exact, computed by the executor via `write_validated`

Five era rows everywhere (matching today's 5 tiers / 5 boss eras). Because
`scale_every_n_levels == rounds_per_era == 10`, **era `e` IS tier `e`** and
era `e`'s first round is `f(e) = 10e + 1`. Let `C(e, key) = Σ scale_tiers[i][key]
for i in range(min(e, 5))`.

**Stats.** `per_round` is all-zero for every type and every era (today's stats
step per era and are flat within it). Row `e`:

- **Standard / SiegeCannon / Formation** — `tier_scaled_stats(block, balance, e)`:
  `hp = block.hp + C(e,"hp")`, `dmg = block.dmg + C(e,"dmg")`,
  `move_speed = block.move_speed + C(e,"speed")`; `attack_speed` and
  `attack_range_tiles` copied flat from the type block.
  (Current bases: Standard 55/10/1.2, Siege 280/100/1.0, Formation 440/30/0.9.)
- **Raider** — five identical rows straight from its block (42/20/2.7), zero
  deltas. It never scaled; that is now data, not a code exception.

**Counts.** `r0(e) = max(f(e), start_round)`; `count_start` is the type's
current formula evaluated at `r0(e)` **without flooring** (D3′).

| Type | current formula | `start_round` | `count_per_round` | `count_start` at `r0` |
|---|---|---|---|---|
| Standard | `1 + (r−1)·(2+tier)` | 1 (new) | `2 + e` | `1 + (r0−1)·(2+e)` |
| Raider | `1 + (r−5)·1` | 5 | `1` | `1 + (r0−5)` |
| SiegeCannon | `1 + (r−14)//1` | 14 | `1` | `1 + (r0−14)` |
| Formation | `1 + (r−16)//3` | 16 | `1/3` | `1 + (r0−16)/3` |

Only the Formation produces a fractional `count_start` — eras 0–4 seed to
`1` / `1` / `2.667` / `6` / `9.333`. Every other row is a whole number.

**This table is verified, not asserted.** Evaluating each `(count_start,
count_per_round, r0)` triple against the current formula for every round from
each type's `start_round` to round 60 gives **zero mismatches** for all four
types. Re-running the same sweep with `count_start` floored to an int (the
pre-D3′ shape) gives **15 mismatched rounds**, all Formation, beginning at
round 22 (`3` → `2`). ES-1's test is that sweep.

**Pacing.** `eras[e].spawn_interval = max(0.1, 0.8 − Σ scale_tiers[i]["spawn_interval"]
for i in range(min(e,5)))` → `0.8 / 0.73 / 0.64 / 0.54 / 0.41`.
`eras[e].batch_size = e + 1`.

**Boss** keeps its 5-row `stats[]` and `round_counts[]` exactly as they are;
only `round_interval` is removed and its trigger re-derived from the clock.
`_boss_round`'s past-the-table fallback (`spawner.py:216-230`) re-expresses the
same three formulas through `era_math.count_at_round` over each type's resolved
era row — same numbers, one code path.

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
  `is_boss_round(round_num, rounds_per_era, boss_round_in_era)` (D1 formulas),
  **clamped at round 0 per D11** — `era_of_round(0, …) == 0`,
  `is_boss_round(0, …) is False` for every configuration.
- `resolve_era_row(eras, era, endgame_factors)` — clamp to the last row; for
  `era ≥ len(eras)` return a **new dict** with every numeric leaf scaled by
  `factor^N` (D5; counts floored). Never mutates the input rows.
- `stats_at_round(row, round_in_era)` — `stats + (round_in_era − 1) ×
  per_round` per D2 key.
- `count_at_round(row, round_num, era_first_round, start_round)` — D3's
  floored linear formula with **D3′'s `round(..., 9)` before the floor**;
  returns 0 below `start_round`.
- `prev_era_reference(rows, era, rounds_per_era, ...)` — the D9 numbers
  (last-round stats / final count of era − 1), for the editor.

**Files — modified.** Add the module to the engine test tree +
`test_editor_viewport.TestPurity`'s import list (it will be imported by the
editor in ES-5; the guard is cheap to extend now).

**Tests.** New `tools/tests/test_era_math.py` (core tier): boundary rounds
(**0**, 1, 10, 11, 20, 21), non-default `rounds_per_era`/`boss_round_in_era`,
clamp + endgame `f^N`, all-1.0 factors = plain clamp, and — the D3′ fence —
**fractional `count_per_round` reproducing today's siege and formation
sequences round-by-round from `start_round` to round 40**, asserted against the
old `//` expressions computed inline in the test.

**Exit gate.** `py tools/smoke.py` + `py tools/testgate.py check --affected`
→ GATE PASS. No behaviour anywhere else changed.

---

### ES-2 — Data restructure + game readers (the big one)

**Goal.** The new data model (§4), seeded, with every reader swapped to
`engine.era_math`. **Gameplay is EXACTLY today's** (D6) — stats, counts and
spawn interval all reproduce, because era == tier at the shipped values. Any
observable difference is a bug to fix in-phase, not drift to report.

**Files — modified.**
- `data/schemas/enemies.schema.json` — new `$defs` (`era_row`,
  `type_era_row`, `endgame_factors`); delete `$defs/scale_tier`; every numeric
  property carries `description` + bounds (D-12; house bounds policy).
  `count_start` is `"type": "number"` (D3′). **No `oneOf` unions** (a type-less
  node crashes the balancing panel — standing rule in `data/CLAUDE.md`; the
  enemies schema has none today, keep it that way).
- `data/balancing/enemies.json` — restructured + seeded per §4, through
  `write_validated`. **`hunts` and `condition_path_weights` survive untouched
  on all five types** (D10) — diff-check this explicitly before commit.
- `game/enemies/spawner.py` — `begin_round` (:107-118) resolves the era + its
  `EnemyScaling.eras` row (stash `self._era`; keep `enemy_tier` as a property
  alias returning the era — one external test reads it); the boss trigger
  (:183-184) → `era_math.is_boss_round`; the standard/raider/siege/formation
  count sites (:186-188, :241-285) and `_boss_round`'s past-table fallback
  (:216-230) → `era_math.count_at_round` over each type's resolved era row;
  `_boss_round`'s era derive (:210) → `era_math.era_of_round`;
  `spawn_death_swarm` (:352) passes the era. The round-0 early return (:176-182)
  **stays** (D11).
- `game/enemies/enemy.py` — `tier_scaled_stats` (:68-82) → an era-row resolver
  (`resolve_era_row` + `stats_at_round`; it needs the round's position in the
  era, so thread `round_in_era` alongside — the spawner already threads `tier`
  into `create_enemy`, and that argument **becomes the era**; add the
  in-era round the same way). The four `_resolve_stats` overrides collapse:
  Standard/Raider/Siege/Formation all read their own `STAT_SUBTREE` block's
  `eras` — the base implementation (:148-150) can finally be `STAT_SUBTREE`-driven,
  retiring the "reads `Standard` literally" trap (keep the Formation
  regression test, now proving the generic path). `Boss._resolve_stats` /
  `_resolve_era` unchanged except the era argument is now the global era.
  `variant_slot` is untouched (its `tier` argument is already an era-clamped
  art index, and art eras already advance every 10 rounds — **no art change**,
  which the original draft wrongly listed as accepted drift).
  The `_cond_weights` copy (:~149) is untouched (D10).
- `game/core/session.py` — :247-251 and :464-470 → `era_math.is_boss_round` /
  `boss_num = era_of_round(round) + 1` reading `EnemyScaling`.
- Tests — the count/stat formula pins in `test_enemies.py`, `test_boss.py`,
  `test_death_spawn.py` re-anchor on the new data model (compute expectations
  from era rows, not tier formulas); `test_editor_panels.py:571-585` re-pins
  resizability on the new arrays (`EnemyScaling/eras` **is** resizable,
  `Boss/round_counts` still is not). `test_prey_hunting.py`,
  `test_tile_runtime.py` and `test_pathfinder.py` must stay green **unmodified**
  — if they need edits, D10 was violated. Pinned fixtures (`TempDataCase`),
  never live `data/`; the fixture copy under
  `tools/tests/fixtures/data/balancing/enemies.json` is restructured in the
  same change.

**Traps.**
- The spawner's `tier` thread is also the **art** index (`variant_slot`) and
  the **death-spawn row** index (`_resolve_era`) — pass the global era
  everywhere, do not invent a second channel.
- **The deterministic wave fixtures should NOT churn.** Under D6 the counts are
  identical round-for-round. A fixture that needs re-pinning is a signal the
  seeding is wrong — investigate before re-pinning, and never re-pin by copying
  observed output.
- `data/CLAUDE.md`'s ER-1/ER-3 sections and `game/enemies/CLAUDE.md` describe
  the tier system in several places — doc updates land in ES-5, but leave a
  `<!-- ES-2: tiers replaced by eras, docs updated in ES-5 -->` marker only if
  the phase must hand off early; otherwise just do ES-5.

**Exit gate.** GATE PASS (`--affected`). Live: round 9→10→11 boundary — boss on
10, era-1 stats from 11; a mid-era round's counts match a hand-computed era-row
value; **a round-22 wave contains exactly the Formation count it did before**
(the D3′ fence, visible in-game).

---

### ES-3 — Batch spawning + per-era pacing

**Goal.** D4: one timer expiry releases up to `batch_size` enemies at once;
spawn pacing is the era row's own `spawn_interval`.

**Files — modified.**
- `game/enemies/spawner.py` — `begin_round` takes `_interval` and
  `_batch_size` from the resolved `EnemyScaling.eras` row (the tier-shave
  arithmetic at :107-118 is already gone since ES-2); `update` (:311-333) pops
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
- `editor/panels/balancing.py` — in `_add_leaf_row` (:453+), when the
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
    system: D1 clock, per-era rows, D3/D3′ counts, D4 batching, D5 endgame; the
    "Raider deliberately does not scale" note becomes "Raider ships flat era
    rows"; the `_resolve_stats`-override trap section records that the base
    resolver is now `STAT_SUBTREE`-driven. **State explicitly that `hunts` and
    `condition_path_weights` are per-type, not per-era** (D10) — that doc's
    prey-hunting section was written days before this plan and must not read as
    contradicted.
  - `game/core/CLAUDE.md` — the two boss-round checks read `EnemyScaling` via
    `era_math` (one-line touch in the 10G sections).
  - `data/CLAUDE.md` — the enemies balancing shape (§Balancing files): era
    rows, endgame blocks, deleted keys, `count_start` being a number and why.
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
5. Raiders still make for economy buildings and siege still makes for defences
   (D10 regression — `hunts` survived the restructure).

## 7. Risks / open items

- **`count_start` fractions are the whole parity story** (D3′). If ES-1's
  round-by-round siege/formation fence is skipped, ES-2 ships a wave that is
  one Formation short from round 22 and nothing catches it — the deterministic
  fixtures re-pin silently if an executor "fixes" them by copying output.
  Compute `floor(round(count_start + k × count_per_round, 9))`, `k` an int,
  never repeated addition.
- **The `tier` argument is three things** (stats row, art era, death-spawn
  row) threaded through `create_enemy`. ES-2 renames its meaning to the global
  era in ONE change; a partial swap would mismatch art and stats silently.
  The deterministic wave fixtures are the fence.
- **D10 is a scope line that will be pushed on.** Promoting `hunts` /
  `condition_path_weights` into era rows ("the era-4 Standard hunts defences")
  is a plausible next ask. It is additive — a per-era override read *before*
  the type-root value — and does not invalidate anything here. Do not
  pre-build it.
- **Per-era `spawn_interval` beyond era 4** no longer shaves further (today the
  clamp at `min(tier, 5)` already freezes it at 0.41s from round 51; the seeded
  era-4 row holds the same 0.41s until the designer tunes
  `endgame_scaling.spawn_interval`). This is parity, not a regression — the
  endgame block is the tuning point (D5).
- **`enemy_tier` survives as an alias** (`test_death_spawn.py:157` reads it);
  rename properly only if that test moves off it in the same change.
- **BossReworkPLAN must not start mid-flight.** Its BR-1/BR-4 edit the same
  files (`enemy.py`, `spawner.py`, the schema). The prerequisite line lands in
  ES-5, but the constraint binds from ES-2 onward — flagged here for the user
  running the plans.
- **The greyed reference is per-field UI in a generic recursive form** — keep
  the era detection purely path-shape-based (`…/eras/<int>/…`) so any future
  type with era rows (the Commander) inherits it with zero edits.
- **This branch (`EnemyRework`) is behind `Development`.** The rework above was
  verified against `Development@048f321`. Rebase before ES-1, or the prey-hunting
  keys D10 protects will not be in the working tree.
