<!-- active-plan: BossReworkPLAN.md | set: 2026-08-05 -->
> **Active plan:** BossReworkPLAN.md (mirror). Source of truth:
> `planning/BossReworkPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: COMPLETE — 2026-08-05 (BR-1..BR-5 landed) -->

# BossReworkPLAN.md — per-boss balancing, second phase, endgame scaling

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`EnemyReworkPLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/BossReworkPLAN.md BR-1-BR-5` or phase-by-phase.

**PREREQUISITE: `planning/EnemyScalingReworkPLAN.md` (ES-1–ES-5) lands first.**
That rework replaces scale tiers with a global era clock
(`EnemyScaling.rounds_per_era` / `boss_round_in_era`, resolved via
`engine.era_math`), deletes `Boss.round_interval` and gives every type per-era
`eras[]` stat/count rows. The decisions below were amended (ES-5) to sit on
that foundation; the `§3` line numbers predate it and shift with ES-2.

Package: **game** (`game/enemies`, `game/core`, `game/ui`, `game/main.py`) +
**data** (`data/balancing/enemies.json`, `data/schemas/enemies.schema.json`,
`data/slots.json`, `data/sprites/asset_manifest.json`). No engine or editor
changes. Subsystem doc: `game/enemies/CLAUDE.md`.

## 1. Context

Source: the user's *Boss Rework Planning Notes*, scoped through four rounds of
clarifying questions (§2 records every answer).

Bosses today are half-generic and half-special-cased. Five eras live in
`data/balancing/enemies.json` → `EnemyTypes.Boss`, but only `stats[]`,
`death_spawn.spawns[]` and `round_counts[]` are per-era — **`footprint`,
`sprite_scale`, `shake` and the death-spawn thresholds are single global values
shared by all five bosses**, so a designer cannot make the era-4 boss bigger,
shakier or tougher-to-break than the era-0 one. Past era 4 the last boss repeats
verbatim forever, so the endgame flattens.

Separately, the boss's swarm is just an instance of the generic ER-3
`death_spawn`: the boss dies, and its children appear in one frame. The notes
want a visible **second phase** instead — freeze, become untouchable, trickle the
reinforcements out on a timer, then play a final death animation and die.

Outcome: every boss variable becomes per-boss; the endgame gets a declared
scaling curve; the boss death becomes a staged second phase; and a new
**Commander** enemy type exists as the era-0 boss's single second-phase spawn.

## 2. Decisions (settled with the user — do not re-litigate)

- **D1 — Endgame scaling is a compounding multiplier.** A new
  `EnemyTypes.Boss.endgame_boss_scaling` block holds one factor per boss variable
  (`hp`, `dmg`, `move_speed`, `attack_speed`, `attack_range_tiles`, `footprint`,
  `sprite_scale`, `shake.strength`/`shake.interval`, and every `round_counts` /
  `second_phase` count key). The Nth boss past the last defined era is
  `last_era_value × factor^N`; counts round to int. `N = max(0, era − (len(stats) − 1))`,
  where `era` is `engine.era_math.era_of_round(round, rounds_per_era)` — the
  global era clock from EnemyScalingRework (ES-5 amendment: the old
  `round // Boss.round_interval − 1` formula and the `round_interval` key no
  longer exist). BR-4 implements this by REUSING
  `era_math.resolve_era_row(rows, era, factors)`, not a bespoke helper.
- **D2 — A boss in second phase is fully invulnerable and its HP bar is hidden.**
  Defenders drop it as a target; projectiles already in flight do nothing.
- **D3 — `commander` joins the SHARED `$defs/spawn_counts`.** Every
  `death_spawn` row of every enemy type and every `round_counts` row gains
  `commander: 0`. Era 0's second phase is
  `{regular: 0, raiders: 0, siege: 0, commander: 1}` — the era-0 boss spawns
  *only* the Commander, and every other era spawns none. **This deliberately
  overrides the standing argument in `game/enemies/CLAUDE.md`** against widening
  that `$def` (the Formation precedent). BR-5 must amend that doc so the data and
  the doc agree — do not leave the contradiction in place.
- **D4 — Boss `endphase` + `death` manifest rows ship as placeholders** reusing
  the existing idle frames; a missing row must fall back gracefully (the phase
  still runs on its timer). Real art lands later via `/replace-visual`.
- **D5 — Thresholds change for era 0 only.** Era 0 gets `at_hp_fraction: 0.5` and
  `spawn_hp_fraction: 0.5`. Eras 1–4 keep `0.0` / `1.0` — their swarm still fires
  at actual death, just trickled instead of burst.
- **D6 — Second-phase children spawn at the boss's tile**, exactly as
  `spawn_death_swarm` does today, one every `spawn_delay` seconds. `spawn_delay`
  is a **per-child interval**, not a total phase duration.
- **D7 — Per-era keys nest into the `stats[]` rows.** Each of the five rows gains
  `footprint`, `sprite_scale` and a `shake: {interval, strength}` object; the
  global keys are deleted. `round_counts[]` and `second_phase.spawns[]` stay as
  their own index-aligned arrays — they are count tables, not stats.
- **D8 — The Commander.** Hunts buildings like the boss (`goal_is_base=False` +
  `repath_on_kill=True`, reusing the existing `PathAgent` flags); its stats are
  **resolved by the base per-era resolver** like Standard/Siege (so it inherits
  the base `_resolve_stats` — no override; ES-5 amendment: scale tiers no
  longer exist, the base resolver reads the type's own `eras[]` rows), so it
  carries its own `eras[]` block; siege-sized **24×2** HP bar; **no** camera
  shake and **no** `"boss"` scene tag. Era-0 stats: `footprint 1` (walker),
  `move_speed 2.7` (raider), `hp 2000` (era-0 boss), `dmg 100` (half the era-0
  boss). Its schedule keys are the era model's: `start_round 0` and every era
  row's `count_start` / `count_per_round` at **0** so it never enters a normal
  wave yet — but every schedule key exists so it can be switched on later with
  a data edit alone.

## 3. Where the code is

All **verified** by scouting.

| Concern | Location |
|---|---|
| `Boss` subclass (era resolve, building-hunting `on_spawn`) | `game/enemies/enemy.py:267-322` |
| `Enemy.__init__` reads `footprint` / `sprite_scale` / `death_spawn` | `game/enemies/enemy.py:106-124` |
| `Enemy.alive` = `hp > max_hp * at_hp_fraction` — the ONE threshold site | `game/enemies/enemy.py:172-180` |
| Duck-typed contract (`death_spawn_plan`, `death_spawned`, `mark_death_spawned()`) | `game/enemies/enemy.py:189-209` |
| `DeathSpawn` component | `game/enemies/components.py:401-424` |
| Boss round trigger + `_boss_round` composition + the past-table fallback | `game/enemies/spawner.py:166-222` |
| Boss era at pop time (`_boss_era`) | `game/enemies/spawner.py:305` |
| `spawn_death_swarm` burst | `game/enemies/spawner.py:320-339` |
| Session stash + `post_sim` flush | `game/core/session.py:298-301, 427-439` |
| Camera shake driver (reads `Boss.shake`, `by_tag("boss")`) | `game/main.py:717-733` |
| Corpse / death-anim lifetime from manifest `total_ms` | `game/enemies/corpse.py:23, 45-77` |
| Boss balancing block | `data/balancing/enemies.json` → `EnemyTypes.Boss` |
| `$defs/boss_stat` · `$defs/death_spawn` · `$defs/spawn_counts` | `data/schemas/enemies.schema.json:3-52, 53-89, 127-156` |
| Boss slots `boss_era_0..4` (idle row only) | `data/slots.json`, `data/sprites/asset_manifest.json` |

**Reuse, do not reinvent:** `PathAgent.goal_is_base` / `repath_on_kill` /
`adopt_goal` already exist for the boss and are exactly what the Commander needs;
`variant_slot()` handles per-era slot rolls; `Spawner._pick_spawn_tile` is the one
clearance-filtered tile chooser; `AssetStore.animation_total_ms` already returns
`None` for a missing row, which *is* the graceful fallback D4 asks for.

## 4. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| BR-1 | Per-boss balancing restructure — data + schema + readers, zero behaviour change | done |
| BR-2 | Commander enemy type (`/add-enemy`), dormant in the wave system | done |
| BR-3 | `death_spawn` → `second_phase` for the Boss + the delayed second-phase state machine | done |
| BR-4 | Endgame boss scaling applied past the last era | done |
| BR-5 | Era-0 tuning (per-era `second_phase.staging`), round-60 revert, commander wiring, `sprite_fit` fix, docs | done |

---

### BR-1 — Per-boss balancing restructure

**Goal.** Every boss variable becomes per-era. A pure refactor: with the five rows
carrying today's global values, gameplay is byte-identical.

**Files — modified.**
- `data/schemas/enemies.schema.json` — move `footprint`, `sprite_scale`, `shake`
  into `$defs/boss_stat`; drop them from `properties.EnemyTypes.Boss`; add
  `commander` to `$defs/spawn_counts` (required, `minimum: 0`).
- `data/balancing/enemies.json` — copy `footprint: 2`, `sprite_scale: 1.0`,
  `shake: {interval: 0.12, strength: 0.6}` into all five `stats[]` rows; add
  `commander: 0` to every `spawn_counts`-shaped row in the file (every type's
  `death_spawn.spawns`, plus Boss `round_counts`).
- `game/enemies/enemy.py` — the Boss resolves `footprint` and `sprite_scale` from
  its era row. **Trap:** the base `Enemy.__init__` reads `block["footprint"]` off
  the `STAT_SUBTREE` block directly (`enemy.py:106-124`). The Boss needs an
  era-aware override *seam* in the base class, not a copy-pasted `__init__`.
- `game/main.py:717-733` — the shake reads the **live** boss's era row. Take the
  era off the tagged boss object; do not re-derive it from the round number.
- `game/enemies/spawner.py` — `_footprint_of` resolves the boss's era row.

**Tests.** Extend `tools/tests/test_boss.py`: per-era footprint / sprite_scale /
shake resolve correctly, and changing era 2 does not move era 0. Assert against a
**pinned fixture** — never live `data/` (`TempDataCase`).

**Exit gate.** `py tools/smoke.py` + `py tools/testgate.py check --affected` →
GATE PASS. Live: a round-10 and a round-30 boss look and shake exactly as before.

---

### BR-2 — Commander enemy type

**Goal.** A full enemy type on par with the other five — balancing, schema, slots,
spawner branch — but with every schedule key at 0 so it never appears in a normal
wave.

**Invoke `/add-enemy`.** Do not hand-roll it. Values and behaviour per D8.

**Files — new / modified.**
- `game/enemies/enemy.py` — `class Commander(Enemy)`: `ETYPE = "commander"`,
  `REGISTRY_GROUP = "Commander"`, `DEFAULT_SLOT`, `STAT_SUBTREE = ("Commander",)`,
  `HP_BAR_W, HP_BAR_H = 24, 2`. `on_spawn` mirrors the Boss's
  `find_path_to_nearest_non_base_building` → `adopt_goal` and sets
  `repath_on_kill=True`. **Deliberately no `_resolve_stats` override** — D8 says
  the base per-era resolver (`STAT_SUBTREE`-driven since ES-2) applies its
  `eras[]` rows. Leave a one-line comment saying so, because
  `game/enemies/CLAUDE.md` documented Formation's pre-ES-2 override as
  mandatory and the next reader may still expect one.
- `game/enemies/spawner.py` — `ENABLE_COMMANDER = True` + a `_commander_group`
  that returns 0 at the shipped values. Call it **LAST** among the composition
  groups so every earlier group's rng draw sequence stays byte-identical (the
  deterministic-wave fixtures depend on this — same rule Formation follows).
- `data/balancing/enemies.json` + `data/schemas/enemies.schema.json` —
  `EnemyTypes.Commander` in the post-ES-2 era shape: an `eras[]` block whose
  rows carry `stats` (`hp 2000`, `dmg 100`, `move_speed 2.7`, `attack_speed`
  and `attack_range_tiles` at walker defaults), zero `per_round` deltas and
  `count_start` / `count_per_round` **0**; `endgame_scaling` all 1.0;
  `footprint 1`, `sprite_scale 1.0`, `start_round 0`, and a `death_spawn`
  block with `enabled: false`.
- `data/slots.json` — a `Commander` group under `enemies` with 4 era subchildren;
  grey-X placeholders until art imports.
- `data/sprites/asset_manifest.json` — placeholder rows per slot (`idle` first per
  the schema, plus `walk`; `death` optional).

**Tests.** `tools/tests/test_enemies.py`: Commander stats come from its own
`eras[]` block (not `Standard`'s); its per-era/per-round resolution runs
through the same base resolver as Standard; it contributes 0 to every wave at
the shipped values; and the deterministic composition fixtures for rounds
1 / 6 / 14 / 10 are byte-identical to BR-1.

**Exit gate.** GATE PASS. Live: force one in via the cheat menu — it walks to a
non-base building, attacks it, re-paths when that building dies, and shows the
24×2 bar with no screen shake.

---

### BR-3 — `second_phase` + the delayed state machine

**Goal.** For the **Boss only**, `death_spawn` is renamed `second_phase` and gains
`delayed_spawns` (bool, default `true`) + `spawn_delay` (seconds per child). Every
other enemy type keeps `death_spawn` untouched.

**`delayed_spawns: false`** — byte-identical to today's one-frame burst.

**`delayed_spawns: true`** — on crossing `at_hp_fraction`:
1. The boss does **not** die; it plays `endphase` if the manifest has that row.
2. `Movement.speed = 0`; `EnemyCombat` disabled; untargetable and immune; HP bar
   hidden (D2).
3. Children spawn one per `spawn_delay` at the boss's tile (D6), reusing
   `spawn_death_swarm`'s per-child construction path.
4. When the last child has spawned, the boss plays `death` and dies through the
   **normal** path — so XP, kill count, splatter and the `Corpse` all fire exactly
   as they do now.

**Files — modified.**
- `game/enemies/components.py` — extend `DeathSpawn` (or add a `SecondPhase`
  sibling) with `delayed`, `spawn_delay`, the phase clock and the remaining-child
  queue. All state in components (E-11).
- `game/enemies/enemy.py` — **the highest-risk edit in this plan.** `Enemy.alive`
  must not flip for a boss in a delayed phase; add an explicit duck-typed
  `targetable` (or `invulnerable`) property rather than special-casing at each
  reader. `alive` is the single evaluation site that `resolve_combat`,
  `_resolve_base_arrivals` and the wave-clear check all read.
- `game/enemies/combat.py` — skip acquisition of, and damage to, an untargetable
  enemy; drop in-flight projectiles whose target became untargetable.
- `game/enemies/spawner.py` — tick the phase clock, pop one child per expiry.
- `game/ui/effects.py` — `submit_enemy_hp_bars` skips a boss in second phase.
- `game/core/session.py` — the wave-clear check must not end the round while a
  boss is mid-phase. **Note:** this is the natural place to also fix the known
  limitation in `game/enemies/CLAUDE.md` (a death on the wave's last frame ends
  the round before its children appear) — a boss frozen for several seconds makes
  that bug far more visible. Raise it with the user at this phase rather than
  silently expanding scope.

**Tests.** `tools/tests/test_boss.py`: `delayed_spawns: false` is byte-identical to
today; a delayed boss survives past its threshold, takes **zero** damage while
frozen, emits exactly `sum(counts)` children at the right cadence, then dies
exactly once; the round does not end mid-phase.

**Exit gate.** GATE PASS. Live: the round-10 and round-20 bosses both stage
correctly at 1× and at 2× combat speed (the phase clock must take the speed-scaled
`sim_dt`, like the `Corpse` fade clock does).

---

### BR-4 — Endgame boss scaling

**Goal.** Bosses past the last defined era grow per D1 instead of repeating.

**Files — modified.**
- `data/schemas/enemies.schema.json` + `data/balancing/enemies.json` —
  `EnemyTypes.Boss.endgame_boss_scaling`, one factor per variable, **all shipped
  at 1.0** so the phase is behaviour-neutral until tuned.
- `game/enemies/enemy.py` — `Boss._resolve_stats` resolves its row through
  `engine.era_math.resolve_era_row(stats, era, endgame_boss_scaling)` (the
  shared ES-4 helper — no bespoke `_endgame_scaled`);
  `N = max(0, era − (len(stats) − 1))` is that helper's own formula.
- `game/enemies/spawner.py` — the same helper applied to `round_counts` and the
  `second_phase` counts on the past-the-table path (ES-2 already replaced the
  old fall-back-to-the-standard-formula behaviour with era-row counts; this
  phase swaps that fallback to endgame-scaled `round_counts` instead).

**Tests.** Era 4 unchanged; eras 5 / 6 / 7 scale as `last × f¹ / f² / f³`; counts
come out as ints; an all-1.0 block is byte-identical to BR-3.

**Exit gate.** GATE PASS + a headless assertion of the round-60 boss's resolved
stats and counts.

---

### BR-5 — Era-0 tuning, anims, docs

**Goal.** Ship the designed values and the placeholder animation rows.

**Files — modified.**
- `data/balancing/enemies.json` — era 0 `second_phase`: `at_hp_fraction 0.5`,
  `spawn_hp_fraction 0.5`, `delayed_spawns true`, a chosen `spawn_delay`, spawns
  `{regular: 0, raiders: 0, siege: 0, commander: 1}`. Eras 1–4 keep `0.0` / `1.0`
  (D5).
- `data/sprites/asset_manifest.json` — `endphase` + `death` rows on
  `boss_era_0..4`, reusing the idle frames (D4).
- `game/enemies/CLAUDE.md` — update the **Boss** and **`death_spawn`** sections:
  the second-phase machine, per-era keys, endgame scaling, and an amended note
  recording *why* `commander` now lives in the shared `$defs/spawn_counts` (D3
  overrides the existing standing argument — record the override, don't leave the
  doc contradicting the data). Per root `CLAUDE.md` step 3, the package doc is the
  one that gets updated — not the root router.

**Tests.** The era-0 boss enters second phase at exactly 50% HP and emits one
Commander at 50% of the **Commander's own** max HP.

**Exit gate.** `py tools/smoke.py` + the **full** `py tools/testgate.py check` →
GATE PASS.

**AS EXECUTED (2026-08-05).** The user expanded and overrode this phase at
dispatch time; what actually shipped:
1. **The four threshold keys became PER-ERA** — a new 5-row
   `second_phase.staging[]` array (`$defs/second_phase_row`), index-aligned
   with `stats[]`/`round_counts[]`/`spawns[]`; `spawns[]` stayed put (D7 bars
   boss-only keys from the shared `$defs/spawn_counts`). Resolved through the
   new `Enemy.resolve_phase_row` seam, and **deliberately NOT through
   `endgame_boss_scaling`** — it clamps past era 4, because a compounded
   `at_hp_fraction` climbs past 1.0. Then D5's tuning on top: era 0 `0.5`/`0.5`,
   eras 1–4 unchanged.
2. **BR-4's round-60 companion change was REVERTED** (user decision).
   `_boss_round` falls back to the per-type `_count_of` counts past the table
   again, so round 60 is 295/46/37, not 700/215/61. Everything else BR-4
   shipped stayed: the boss's own stats/fit/shake/`second_phase.spawns` still
   grow through `endgame_boss_scaling`, and `Boss._resolve_era` still returns
   the global era. Measured byte-identical to BR-3 over rounds 0–60.
3. **`round_counts[era]["commander"]` is wired**, composed LAST so the shipped
   all-zero counts draw no rng.
4. **`editor/sprite_fit.py` fixed** — it read the Boss's `footprint`/
   `sprite_scale` flat (gone since BR-1), raised `KeyError`, and a bare
   `except Exception` swallowed it into a `(0.0, 1.0)` preview. Now per-era,
   with the tolerance net narrowed to the two data loads.

**NOT shipped, deliberately — open for the user:**
- **Era 0's `commander: 1` spawn count.** The dispatch scoped BR-5's ONE
  gameplay change to the thresholds, so era 0's `spawns` row is still all
  zeros. Consequence, measured: the era-0 boss now freezes at 50% HP with **no
  children** and dies — effectively 700 HP instead of 1400. One data edit
  turns the Commander on.
- **The `endphase`/`death` placeholder manifest rows.** Measured: a manifest
  row's index IS its sheet row, and every `boss_era_*` sheet is exactly as
  tall as it declares, so an appended row resolves outside the sheet and
  renders the **grey-X placeholder** for the whole phase. Leaving them absent
  IS D4's graceful fallback (idle frames for `endphase`, no corpse for a
  missing `death`). They land with real art, via `/replace-visual`.
- **Camera shake on a frozen boss** (BR-3's finding) — untouched; may be
  intended drama.

## 5. Verification

```bash
py tools/smoke.py                      # data validation + 5-frame headless boot
py tools/testgate.py check --affected  # while iterating
py tools/testgate.py check             # ONCE, before handoff — the gate is ZERO
```

Live `py game/main.py` — the Quick Test for the PR:
1. Cheat to round 10. The era-0 boss spawns, hunts buildings, and ignores the hole
   while anything else stands.
2. Damage it to 50%. It freezes, its HP bar disappears, defenders stop shooting
   it, and one Commander appears at its feet after `spawn_delay`.
3. The boss then plays its death row and dies; XP, kill count and splatter fire.
4. The Commander walks off, attacks the nearest non-base building, and re-paths
   when that building dies.
5. Cheat to round 60 and confirm the boss's HP/damage exceed the era-4 values by
   the configured factors.

## 6. Risks / open items

- **`Enemy.alive` is load-bearing.** It is the single site that combat, base
  arrivals and wave-clear all read. "Alive but untargetable" is the one change
  here that can break unrelated systems — BR-3 must add an explicit property, not
  special-case each reader.
- **Widening `$defs/spawn_counts`** touches every `death_spawn` row in the file
  and contradicts a standing note in `game/enemies/CLAUDE.md`. Chosen
  deliberately (D3); BR-5 must amend the doc so the reasoning is recorded.
- **The last-frame death limitation** becomes much more visible with a
  multi-second second phase. BR-3 flags it; whether to fix it there or split it
  into its own phase is a call for the user at that point.
- **`spawn_delay` and the endgame factors ship untuned.** BR-4 ships 1.0
  everywhere for safety; real values are a balancing pass after a playtest.
- **The even-footprint sprite offset** (the known 16px cosmetic gap documented in
  `game/enemies/CLAUDE.md`) is inherited, not addressed here. Per-era footprints
  make it more noticeable, but the fix is engine-side and wants its own phase.
- **Second-phase timing under combat speed.** The phase clock must take the
  speed-scaled `sim_dt` so the phase does not desync at 1.5×/2× — the `Corpse`
  fade clock is the pattern to copy.
