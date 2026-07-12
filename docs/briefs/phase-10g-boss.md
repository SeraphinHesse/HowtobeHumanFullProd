# Phase 10G Brief — Boss

> Coordination artifact for the 10G–10I subagent batch. Planner fills §1–§4;
> orchestrator reconciles §3 across the three briefs; coder treats §3 as a hard
> boundary; reviewer verifies the diff against §1/§2/§4.

**Phase goal (MIGRATION_PLAN.md 10G):** era stats/sizes, boss-round queue
composition, announcement, screen shake, death-swarm, boss HP bar, boss
cutscene A/B + boss_bonuses port (payday hooks into reserved slots), boss
history panel.

## Known repo state (verified at umbrella base — do not re-derive)

- Balancing data DONE: `data/balancing/enemies.json` → `EnemyTypes.Boss`
  (`stats[5]`, `era_sizes`, `round_counts`, `death_spawns`, `round_interval:10`,
  `shake:{interval,strength}`); schema complete. No schema work expected.
- Pre-existing hooks: payday reserved slot 3 comment (`game/core/payday.py:149`,
  "Boss-bonus payouts (Boss1B / Boss3B)"); `GamePhase.BOSS_CUTSCENE` declared
  (`game/core/phases.py:20`); `BossState(era, death_spawned)`
  (`game/enemies/components.py:163`); spawner `_boss_round` stub +
  `ENABLE_BOSS = False` (`game/enemies/spawner.py:22,109`); `Boss` thin class
  reads `EnemyTypes.Boss.stats[era]` (`game/enemies/enemy.py:~170`).
- Templates: LEVELUP insertion at ROUND_END-expiry in `session.pre_sim`
  (`game/core/session.py:99,126-135`) is the template for entering
  BOSS_CUTSCENE (add to `Session.frozen`, defer payday to resolve);
  `game/ui/levelup.py` + `game/ui/game_over.py` = modal template
  (open/layout/update/hit/submit, top of click ladder, swallows keys);
  `RunState` drained-event ledgers (`game/core/game_state.py:40-60`) pattern
  the boss history; `effects.submit_hp_bars` (`game/ui/effects.py:156`)
  patterns the boss HP bar; screen shake = host-side transient camera-pan
  jitter in `game/main.py` (no engine change).
- `game/enemies` imports NO `game/core` — cross-boundary via callbacks
  (`on_base_hit`, `on_enemy_death`). Death-swarm hooks off `on_enemy_death` +
  `BossState.death_spawned` one-shot guard.
- main.py click ladder `game/main.py:271-285`, keys near `:363`.

## 1. Behavioral spec (planner)

All prototype citations are into `../HowToBeHuman/ClaudePrototype/HowToBeHuman`
(READ-ONLY). Live `Balancing_Enemies.json` beats `balancing_enemies.py` defaults;
**all HP/DMG below are ×10 scale**. The repo's `data/balancing/enemies.json`
`EnemyTypes.Boss` already carries every number verbatim — cite it in code, the
prototype numbers below are the verification reference.

### 1.1 Per-era boss stats (`balancing_enemies.py:85-91` `BOSS_ERAS`, py-only — no JSON override; repo `Boss.stats[era]`)

| era | name | hp | dmg | move (tiles/s) | atk interval (s) | range (tiles) | sprite_w×h | era_sizes w×h |
|---|---|---|---|---|---|---|---|---|
| 0 | Bandit Chieftain | 2000 | 200 | 0.30 | 1.50 | 2 | 72×56 | 36×28 |
| 1 | Cannon Fortress | 3800 | 320 | 0.33 | 1.40 | 2 | 108×84 | 54×42 |
| 2 | Wrecking Ball | 6500 | 480 | 0.36 | 1.30 | 2 | 108×84 | 108×84 |
| 3 | Iron Drill | 10000 | 700 | 0.40 | 1.15 | 3 | 116×88 | 116×88 |
| 4 | Siege Tank | 15000 | 1000 | 0.45 | 1.00 | 3 | 124×96 | 124×96 |

- **Sizes**: two tables exist. `BOSS_ERA_SIZES` (live JSON,
  `Balancing_Enemies.json:75-96`) is what the boss actually renders at — the
  procedural sprite is scaled to it at startup (`sprite_gen.py:1511-1526`);
  `BOSS_ERAS[i].sprite_w/h` only drive the render offset + overhead-bar width
  (`boss.py:33-39,137-140`). In this repo boss art is the `boss_era_0..4` slots
  (`data/slots.json:397-421`) with editor-owned frame sizes, so **both size
  tables are parity data only — do NOT wire them at runtime**.
- **NO tier scaling**: `Boss.__init__` calls `super().__init__(tier=tier)` then
  **overwrites** hp/dmg/speed/range/attack from the era table (`boss.py:17-39`)
  — cumulative `ENEMY_SCALE_TIERS` bonuses never apply. Repo `Boss._resolve_stats`
  (`game/enemies/enemy.py:184-189`) already does this.
- **Era selection** (`game.py:1264`): `boss_era = max(0, round_num //
  BOSS_ROUND_INTERVAL - 1)`, clamped to the last table entry (`boss.py:23`).
  Interval **10** (live JSON `Balancing_Enemies.json:102` — the py default 15 and
  MIGRATION_AGENT_READ_FIRST §7's "every 15" are STALE). So round 10→era 0,
  20→era 1, … 50→era 4, 60+→era 4 (clamped).

### 1.2 Boss-round queue composition (`game.py:831-874`)

- Detection: `is_boss_round = round_num % BOSS_ROUND_INTERVAL == 0` (`game.py:832`).
- Companion counts come from `BOSS_ROUND_COUNTS[boss_idx]` where
  `boss_idx = round_num // BOSS_ROUND_INTERVAL - 1` (`game.py:851-854`). Live
  JSON (`Balancing_Enemies.json:108-134`, beats the py table — repo
  `Boss.round_counts` matches):

  | boss_idx (round) | regular | raiders | siege |
  |---|---|---|---|
  | 0 (r10) | 12 | 22 | 0 |
  | 1 (r20) | 40 | 75 | 6 |
  | 2 (r30) | 280 | 125 | 31 |
  | 3 (r40) | 400 | 170 | 46 |
  | 4 (r50) | 700 | 215 | 61 |

- **Beyond the table** (boss_idx ≥ 5, i.e. round 60+): fall back to the normal
  per-type formulas incl. start-round guards (`game.py:855-864`) — regular
  `base_enemy_count + (round-1)*(enemies_per_round + tier)`, raiders
  `base_count + (round-start)*per_round`, siege
  `base_count + (round-start)//rounds_per_cannon`.
- **Order** (`game.py:866-874`): `[boss] + [ALL siege] + shuffle(regular + raiders)`
  — exactly ONE boss leads, then every siege cannon (NO lead/mix split on boss
  rounds), then the shuffled rest. Spawn tiles: each entry gets
  `random.choice(spawn_tiles)`. The ramp+jitter delay build is the existing
  shared code (`game.py:901-924` == repo `Spawner._build_queue`).
- The boss spawns from the queue like any enemy (`game.py:1262-1267`); the live
  boss is remembered (`_active_boss`) for HP bar + shake.

### 1.3 Death swarm (`game.py:1314-1334`)

On the boss's death (any cause), **once** (`death_spawned` one-shot,
`boss.py:44`): spawn at the boss's current tile `(e.col, e.row)`, immediately
(directly into the live enemy list, NOT the spawn queue), reading
`BOSS_ERAS[era].death_regular/raiders/siege` (py-only; repo
`Boss.death_spawns[era]`):

| era | regular | raiders | siege |
|---|---|---|---|
| 0 | 10 | 5 | 1 |
| 1 | 14 | 7 | 2 |
| 2 | 20 | 10 | 3 |
| 3 | 26 | 13 | 4 |
| 4 | 34 | 16 | 5 |

Swarm enemies are constructed with the CURRENT enemy tier (`tier=self._enemy_tier`,
`game.py:1329-1333`) — so standard+siege swarm members DO take scale-tier bonuses
(raiders never do). They path from the boss's position on spawn. The flat JSON
`BOSS_DEATH_REGULAR/RAIDERS/SIEGE` keys (8/4/0) are **dead** — the game reads the
per-era values. A boss cleared by quick-skip `P` or a lives-wipe is despawned
without dying on the field — no swarm (prototype clears the list wholesale).

### 1.4 Boss pathing (`boss.py:49-97`)

The boss paths via `find_path_to_nearest_building` (any alive building, base
included; already ported at `game/map/pathfinder.py:159-164`). It attacks any
non-base building within `attack_range_tiles` on its route at its
`attack_speed`, and **re-paths to the new nearest building every time its attack
target dies** (`boss.py:108-114` `_do_attack` → `_repath`). Reaching the base
tile sets `reached_base` (one life, standard breach).

### 1.5 Screen shake (`game.py:1879-1890, 1947-1949`)

Active while `phase == ENEMY` AND a live boss is on the field. Render-time
camera offset, restored after the frame (pure visual, never touches sim state):
`t = ticks_ms; ox = int(sin(t/period_ms * 6.28) * strength);
oy = int(cos(t/period_ms * 9.42) * strength)` with `period_ms =
BOSS_SHAKE_INTERVAL*1000` = **0.12 s** and strength = **0.6 px** (live JSON
`Balancing_Enemies.json:103-104`; the py default 2.5 is stale). Repo keys:
`Boss.shake.{interval,strength}`. Stops the moment the boss dies / the round ends.

### 1.6 Boss HP bars

Two bars, both only while the boss lives:
- **HUD bar** (`src/ui/hud.py:356-368`): bottom-center, 200×12 px at
  `y = view_h - 55`, red under-bar + green fill + 1px border, `"BOSS"` label
  (red) left of it, `hp/max_hp` text right of it. Shown only during
  `phase == ENEMY` and while the boss is alive (`game.py:2037-2038` passes
  `boss_hp=None` once dead).
- **Overhead bar** (`boss.py:136-143`): a wide bar above the sprite,
  `bar_w = max(48, sprite_w*2//3)`, 4 px tall, red+green, drawn only when
  `hp < max_hp` (same rule as the repo's building bars).

### 1.7 Announcement (`src/effects.py:292-337`, trigger `game.py:841-848`)

On End Turn of a boss round, a screen-space centered two-line banner
`"SOMETHING BIG" / "IS APPROACHING!"`, xl font, color `(220, 40, 40)`. Fade in
**0.5 s** → hold **2.0 s** → fade out **0.8 s** — repo keys
`ui.json FX.boss_announce.{enabled,fade_in,hold,fade_out}` (the canonical wired
flag; the prototype's `FEATURE_BOSS_ANNOUNCEMENT` was never read). Ignores the
camera; drawn over the game surface.

### 1.8 Boss cutscene (A/B choice) — trigger + flow

- **Snapshot at wave start** (`game.py:834-839`): on a boss round End Turn,
  `_boss_round_lives_snapshot = base_lives`. Additionally — EVERY round, boss or
  not — `BONUSES.current_love = currency` (the Boss3A snapshot).
- **Queue at round end** (`game.py:933-938`): in `_begin_round_end`, if
  `round_num % interval == 0` and not GAME_OVER:
  `pending = {boss_num: round_num // interval, outcome: 'win' if base_lives >=
  snapshot else 'loss'}`. (round_num is still pre-increment at ROUND_END.)
- **Enter** (`game.py:1215-1229`): at ROUND_END timer expiry the pending
  cutscene takes priority **over LEVELUP**: build the modal, `phase =
  BOSS_CUTSCENE`. The phase is fully modal + input-driven (no timers); the world
  freezes exactly like LEVELUP.
- **UI** (`src/ui/boss_cutscene.py`): near-black overlay (alpha 210); headline
  `"Cutscene: Round Won :)"` green `(100,220,100)` / `"... Lost :("` red
  `(220,100,100)`; subtitle `"How will we react?"`; two boxes 180×130 px, 20 px
  gap, centered (+20 px down); buttons labeled `WinA`/`WinB` (or
  `LossA`/`LossB`), description text under each. **No cancel — the player must
  pick A or B** (clicks elsewhere swallowed).
- **Resolve** (`game.py:947-963`): `effective_idx = (boss_num - 1) % 3` (choice
  sets cycle every 3 bosses); `apply_choice(effective_idx, option)` increments
  that option's stack by 1 (stacking: picking the same option twice doubles it,
  `boss_bonuses.py:67-74`); append `(boss_num, option, outcome)` to
  `boss_choices`; then `levelup_pending ? _begin_levelup(run_income=True) :
  _begin_income_phase()` — i.e. BOSS_CUTSCENE → (LEVELUP →) payday → INCOME.

### 1.9 Boss bonuses — COMPLETE list (`src/core/boss_bonuses.py`)

Six stack counters, all start 0, reset on new game. **Magnitudes are
prototype-hardcoded in source, NOT balancing** (like `COMBAT_SPEEDS` /
`AOE_TRAVEL_TIME`) — keep them code constants. Set 0 = bosses 1,4,7…; set 1 =
2,5,8…; set 2 = 3,6,9….

| id | set/option | desc (exact UI copy) | exact effect | hook point (prototype) |
|---|---|---|---|---|
| `boss1a` | 0/A | "Per unbuilt tile, buildings do\n+1 extra damage" | `dmg += (# tiles in state BUILDABLE) × stacks`, per shot, live count | defence dmg calc `defence_building.py:136-143`; AOE `aoe_defence_building.py:174-180`; beam inherits (subclass) |
| `boss1b` | 0/B | "Per building level past 2,\ngenerate +1 love per round" | payday: `Σ over alive non-base buildings max(0, current_level_in_tier − 2) × stacks` love (in-tier level 1..3 ⇒ +1 per lvl-3 building per stack). No floater. | `game.py:989-998`, BEFORE base income, AFTER RoundStats snapshot |
| `boss2a` | 1/A | "Per Stone Thrower building,\nFlute Players yield +1 love" | each **musician's** (`building_type == 'economic'`) yield `+= (# occupants with building_type == 'defence') × stacks`. Count has NO alive filter; `aoe_defence` does NOT count. Painter/meditator unaffected. | `economic_building.py:32-39` (inside `yield_amount`, so the income sweep + floaters + HUD all see it) |
| `boss2b` | 1/B | "Per AOE building,\nMeditators yield +1 love" | each **meditator's** income-time payout `+= (# occupants with building_type == 'aoe_defence') × stacks` (added after streak logic; no alive filter on the count) | `meditator_building.py:68-76` (`collect` path) |
| `boss3a` | 2/A | "Per 10 love held, defence\nbuildings deal +1 damage" | `dmg += (love_snapshot // 10) × stacks` per shot; snapshot = love at the CURRENT wave's End Turn (updated every round, `game.py:838-839`) | `defence_building.py:145-146` + AOE `:182-183` |
| `boss3b` | 2/B | "Per 10 dmg by top building\nlast round, +1 love/round" | payday: `(max dmg_dealt_last_round over alive buildings // 10) × stacks` love. Reads the values the snapshot JUST rolled ⇒ the round that just ended. `// 10` acts on ×10-scaled damage. No floater. | `game.py:999-1009` |

The HUD income line counts boss1b+boss3b as `Story` income and folds
boss2a/boss2b into the Musicians/Meditators lines (`game.py:1957-2006`).

### 1.10 Boss history

`game.boss_choices` — a per-RUN list of `(boss_num, option, outcome)` tuples
(`game.py:112,957`), reset on new game. **No disk persistence.** UI: the
base-info panel carries a `"BOSS CHOICES"` button (`building_ui.py:555-558`)
opening a small popup (`_BossHistoryPanel`, `building_ui.py:1488-1569`): title
"Boss Choices", one row per entry (`"Boss {n}: {Outcome} {option}"`), hover
shows the choice's desc as a tooltip, "None yet" when empty, Close button.

### 1.11 XP

Boss kill pays `XP_PER_BOSS = 150` (`Balancing_Core.json:15`; repo
`core.json XP.xp_per_boss`, already wired through `game/core/xp.py:16-21` —
**no code needed**).

### 1.12 Live-JSON vs .py drift flags (JSON wins)

- `BOSS_ROUND_INTERVAL`: **10** (JSON) vs 15 (py). Repo has 10. ✓
- `BOSS_ROUND_COUNTS`: JSON table (§1.2) vs a much larger py table. Repo = JSON. ✓
- `BOSS_SHAKE_STRENGTH`: **0.6** (JSON) vs 2.5 (py). Repo 0.6. ✓
- `BOSS_ERAS` (stats, death_*): py-only, no JSON key — authoritative as-is; the
  flat JSON `BOSS_HP/DMG/...` keys are era-0 constructor fallbacks and
  `BOSS_DEATH_*` flat keys are dead. Repo `stats`/`death_spawns` match. ✓
- `BOSS_ERAS[i].swarm_*`: dead fields (queue counts come from
  `BOSS_ROUND_COUNTS`) — not migrated, correctly.
- Repo `EnemyScaling.scale_every_n_levels = 9` (vs prototype live 10) shifts the
  companion/death-swarm TIER at round 10 to `(10-1)//9 = 1`. Tests must compute
  from repo data (they load real balance), not the prototype.

## 2. Architecture plan (planner)

Layering invariants: `game/enemies` imports NO `game/core` (callbacks only);
`game/ui → game/core` one-way; payday ordering sacrosanct (fill slot 3 ONLY);
all state in components / `RunState`; tunables from `data/balancing` via
`game/core/balance.py` (NO new balancing keys — everything 10G needs already
exists; bonus magnitudes are code constants, the `COMBAT_SPEEDS` precedent).

### 2.1 New files

- **`game/core/boss_bonuses.py`** (pure, no pygame — covered by the existing
  purity test). The prototype module rebuilt WITHOUT the global singleton:
  stacks live in `RunState.boss_stacks` (§2.3). Contents:
  - `BOSS_CHOICES` — the 3×A/B table: `{set_idx: {"A"|"B": {"id": "boss1a"...,
    "desc": <exact §1.9 copy>}}}` + `choice_desc(effective_idx, option)`.
  - `apply_choice(state, effective_idx, option)` — `state.boss_stacks[id] += 1`.
  - `story_damage_bonus(state, tilemap)` → `unbuilt × boss1a + (love_snapshot
    // 10) × boss3a` where `unbuilt = len(tilemap.buildable_tiles())`
    (Boss1A/3A, §1.9). ONE flat int — identical for every defender.
  - `boss1b_income(state, tilemap)` / `boss3b_income(state, tilemap)` — the
    slot-3 payouts (formulas §1.9; read `TierState.current_level_in_tier` /
    `RoundStats.dmg_dealt_last_round` via components).
  - `defence_count(tilemap)` / `aoe_count(tilemap)` — the Boss2A/2B counts
    (occupants by `building_type`, NO alive filter, prototype-exact).
- **`game/ui/boss_cutscene.py`** — `BossCutscene`, the `levelup.py` modal
  template verbatim (construct→`open(boss_num, outcome)`→`layout`→`update`→
  `hit`→`submit`, lays out on `open`): opaque near-black backdrop (HUD pass has
  no alpha — same accepted divergence as `LevelupWindow`), win/loss headline +
  colors, subtitle, two 180×130 boxes labeled `WinA/WinB` or `LossA/LossB` with
  desc lines from `boss_bonuses.BOSS_CHOICES`. `hit` returns `"A"`/`"B"`/None;
  no dismiss. Export from `game/ui/__init__.py`.
- **`tools/tests/test_boss.py`** — §4.

### 2.2 `game/enemies` (exclusive to 10G)

- **`spawner.py`**: flip `ENABLE_BOSS = True` (line 23). Rewrite the
  `_compose` boss branch (lines 110-116): when
  `round % Boss.round_interval == 0` → counts from
  `Boss.round_counts[round // interval - 1]`, falling back to the three normal
  formulas (with start-round guards) beyond the table; return
  `boss_entry + siege_all + shuffle(regular + raiders)` (§1.2 — no lead/mix
  split on boss rounds; the existing `_raider_group`/`_siege_groups` are the
  NON-boss path only). The boss entry's tier argument is the ERA:
  `era = max(0, round // interval - 1)` — pop-time in `update()` passes
  `era` as `tier` for `etype == "boss"` (the `Boss.__init__` docstring already
  reserves this: "tier doubles as the era index"). All other entries keep the
  real `self._tier` (companions + death swarm DO scale).
- **`enemy.py` `Boss`**: keep thin. Add tag `"boss"` (extra tags tuple → scene
  queries by HUD/shake need no `_active_boss` ref); override `on_spawn` to path
  via `find_path_to_nearest_building` (fallback `find_path` →
  `find_path_ignoring_walls` chain as now); set `PathAgent.repath_on_kill =
  True` + `PathAgent.goal_is_base = False` when the path goal is not the base
  (§2.2 PathAgent). `variant_slot` already era-picks via the tier param (slots
  `boss_era_0..4` are the Boss group's eras).
- **`components.py`**:
  - `PathAgent` gains two JSON-safe fields, default-off (Standard/Raider/Siege
    byte-identical): `goal_is_base: bool = True` — `reached_base` is only set
    on `Movement.arrived` when True (kills the phantom-base-hit hazard the 10F
    deferral documented: a path ENDING on a hunted building must not count as a
    breach); `repath_on_kill: bool = False` — on unblocking because the blocker
    died, re-run `find_path_to_nearest_building` from the current tile (import
    from `game.map.pathfinder` — already this package's dependency), reload
    `Movement.waypoints`, set `goal_is_base` from whether the new goal is the
    base. On `arrived` with `goal_is_base == False` (goal building died with no
    blocker contact): re-path the same way instead of flagging `reached_base`.
    This is the prototype boss's `_repath`-after-kill (`boss.py:108-114`)
    mapped onto the block-and-attack model.
  - `BossState` stays as-is (era + `death_spawned` guard, set by the session).
- **`combat.py`**: `resolve_combat(...)` gains optional `dmg_bonus=0`
  (default keeps every existing call/test byte-identical), threaded into the
  three fire paths — `_fire` (projectile dmg), `_fire_splash` (shell dmg),
  `_update_beam` (per-tick dmg) — added to `defender.damage()` at fire time.
  The host computes it per frame from `boss_bonuses.story_damage_bonus` (a
  plain int crosses the boundary; layering intact).

### 2.3 `game/core`

- **`game_state.py` `RunState`** — new fields (all JSON-safe defaults):
  `boss_stacks: dict` (default `{boss1a..boss3b: 0}` via factory);
  `boss_choices: list` (the history ledger, `(boss_num, option, outcome)`);
  `boss_lives_snapshot: int = 0`; `boss_love_snapshot: int = 0` (Boss3A);
  `pending_boss_cutscene: dict = None`-style field (use `object = None`);
  `boss_events: list` (drained-by-UI announcement ledger, same contract as
  `xp_events`). New run = fresh `RunState` = prototype's reset.
- **`session.py`** (SHARED — §3 anchors):
  - `frozen` covers BOSS_CUTSCENE (phase in `(LEVELUP, BOSS_CUTSCENE)`).
  - `end_turn`: EVERY round `st.boss_love_snapshot = st.love` (Boss3A,
    prototype `game.py:838-839`); on a boss round also
    `st.boss_lives_snapshot = st.base_lives` + append one announce marker to
    `st.boss_events` (the enabled gate lives in FloaterManager — session stays
    free of ui balance).
  - `_begin_round_end`: queue `st.pending_boss_cutscene = {"boss_num": ...,
    "outcome": ...}` per §1.8 (GAME_OVER never reaches here — post_sim gates).
  - ROUND_END expiry in `pre_sim`: a pending cutscene beats `levelup_pending`
    → `_begin_boss_cutscene()` (just sets `phase = BOSS_CUTSCENE`; the host
    opens the modal on the phase edge, the LEVELUP pattern).
  - New `resolve_boss_cutscene(option, scene=None)`: `apply_choice(state,
    (boss_num-1) % 3, option)` → append `(boss_num, option, outcome)` to
    `st.boss_choices` → clear pending → `levelup_pending ?
    self._begin_levelup() : run_payday(st, tilemap, core, occupancy, scene)`.
  - Death swarm — layering: `game/core` imports no `game/enemies`, so Session
    only DUCK-TYPES the dead enemy (the same contract `combat.py` uses for
    `alive`/`dmg`). Give `Boss` two guard-safe `@property`s over `BossState`:
    `era` and `death_spawned` (+ setter). `on_enemy_death`: if
    `getattr(enemy, "ETYPE", "") == "boss"` and not `enemy.death_spawned` →
    set it, stash `self._boss_swarm_pending = (round(wx), round(wy), era)`.
    `post_sim` flushes the stash BEFORE the wave-clear check (so the round
    can't end between boss death and swarm) by calling
    `self.spawner.spawn_death_swarm(scene, col, row, era)` — a NEW `Spawner`
    method (it already owns balance/tilemap/tier/registry/rng) that constructs
    `death_spawns[era]` standard/raider/siege at the boss tile with the
    CURRENT tier and `scene.spawn`s them immediately (not queued). All enemy
    construction stays in `game/enemies`.
- **`payday.py`**: fill **slot 3 only** (line 148-149 comment → real code):
  `love += boss1b_income(state, tilemap) + boss3b_income(state, tilemap)`
  (each guarded on stacks > 0; NO income_events — prototype pays silently).
  Inside the EXISTING step-4 income sweep (no reorder): musicians
  (`building_type == "economic"`) add `defence_count(tilemap) ×
  state.boss_stacks["boss2a"]`; the meditator branch adds `aoe_count(tilemap)
  × boss_stacks["boss2b"]` after `collect_income` — both deltas fold into
  `amount` so floaters + totals match the prototype (§1.9). Compute the two
  counts ONCE before the sweep.
- **`phases.py`**: no edit (`BOSS_CUTSCENE` already declared at its ordinal).

### 2.4 `game/ui`

- **`effects.py`**: `FloaterManager` gains
  - `spawn_boss_events(state)` — drains `state.boss_events`; gated by
    `ui.FX.boss_announce.enabled`; creates the announcement (timings from
    `ui.FX.boss_announce`).
  - `submit_announce(renderer, view_w, view_h)` — screen-centered two-line
    banner (§1.7); fade approximated by lerping the `(220,40,40)` text color
    toward the background over fade_in/fade_out (HUD pass has no alpha — same
    documented divergence as craters/levelup; true alpha is 10J).
  - `submit_boss_bars(renderer, cs, scene, phase, view_w, view_h)` — the
    `submit_hp_bars` pattern (`effects.py:156`): find the live boss
    (`scene.by_tag("boss")`, alive); HUD bar bottom-center 200×12 at
    `view_h - 55` with "BOSS" + `hp/max` texts, ENEMY phase only; overhead bar
    over the boss sprite — a fixed 48 px width (the prototype's minimum;
    slot-frame-derived widths are 10J polish), 4 px tall, only when
    `hp < max_hp`.
- **`hud.py`** (SHARED — §3): `_PHASE_LABEL[GamePhase.BOSS_CUTSCENE] =
  "CUTSCENE"` + `_PHASE_COLOR[...] = C_GOLD`; `income_breakdown` adds one
  bounded story block so the HUD net matches the next payday: `income +=
  boss1b_income + boss3b_income + defence_count×boss2a×(#alive musicians) +
  aoe_count×boss2b×(#alive meditators)` via the `boss_bonuses` helpers
  (`game.ui → game.core` import is sanctioned).
- **`building_ui.py`** (10G-exclusive here, but flag to orchestrator — 10H adds
  its lightning section to the same base_info mode): base_info mode gains a
  "BOSS CHOICES" button + a `_BossHistoryPanel`-style popup (rows
  `"Boss {n}: {Outcome} {option}"`, hover desc line, "None yet", Close);
  reads `session.state.boss_choices` + `boss_bonuses.choice_desc`. Popup
  consumes clicks inside the panel (mode already consumes, line 371).

### 2.5 `game/main.py` (SHARED — §3 anchors)

Host-side only: build/teardown the `BossCutscene`; click-ladder branch;
open-on-phase-edge; per-frame drain of `boss_events`; compute
`dmg_bonus = story_damage_bonus(state, tile_map)` once per frame and pass to
`resolve_combat`; screen shake = transient `cs.pan(ox, oy)` before the world
render branch / `cs.pan(-ox, -oy)` right after `renderer.flush` (formula §1.5,
`time.perf_counter()`-based ms; NO `cs.clamp` between pan/unpan so the offset
restores exactly); submit announcement + boss bars + cutscene.

### 2.6 Data / schemas / docs

No `data/` or schema changes (verified complete). Update
`game/enemies/CLAUDE.md` (boss live, PathAgent repath/goal flags, spawner
death-swarm API), `game/core/CLAUDE.md` (BOSS_CUTSCENE flow, slot 3, RunState
boss fields, boss_bonuses module), `game/ui/CLAUDE.md` (cutscene modal,
announcement, boss bars, history popup).

## 3. File scope + shared-file contract (planner → orchestrator reconciles)

### 3.1 Exhaustive touchable-file list

| file | change |
|---|---|
| `game/core/boss_bonuses.py` | **create** (§2.1) |
| `game/ui/boss_cutscene.py` | **create** (§2.1) |
| `tools/tests/test_boss.py` | **create** (§4) |
| `game/enemies/spawner.py` | boss composition + `ENABLE_BOSS=True` + `spawn_death_swarm` |
| `game/enemies/enemy.py` | `Boss`: tag, `era`/`death_spawned` properties, `on_spawn` path, repath flags |
| `game/enemies/components.py` | `PathAgent.goal_is_base` / `repath_on_kill` |
| `game/enemies/combat.py` | optional `dmg_bonus=0` threading |
| `game/core/session.py` | **SHARED** — §3.2 blocks only |
| `game/core/game_state.py` | `RunState` boss fields (§2.3) |
| `game/core/payday.py` | slot 3 + Boss2A/2B deltas inside step 4 (NO reorder) |
| `game/ui/hud.py` | **SHARED** — §3.2 blocks only |
| `game/ui/effects.py` | announcement + `submit_boss_bars` |
| `game/ui/building_ui.py` | base_info "BOSS CHOICES" button + history popup |
| `game/ui/__init__.py` | export `BossCutscene` (one line) |
| `game/main.py` | **SHARED** — §3.2 blocks only |
| `game/enemies/CLAUDE.md`, `game/core/CLAUDE.md`, `game/ui/CLAUDE.md` | doc updates (exit-gate rule 3) |

NOT touchable: `data/**` (balancing + schemas are DONE), `engine/**`,
`editor/**`, `game/core/phases.py` (BOSS_CUTSCENE already declared),
`game/map/**` (pathfinder variants already ported), the prototype repo (ever).

> **Orchestrator:** also read `docs/briefs/phase-10g-i-coordination.md` —
> cross-phase file matrix + rulings; it wins over this brief on conflicts.

Collision watch for the orchestrator (10G lands FIRST; 10H/10I rebase over it):
`game/ui/building_ui.py` base_info mode (10H adds its lightning section there),
`game/ui/effects.py` (10H lightning FX), `game/ui/__init__.py` (any new export),
`game/core/game_state.py` (10H cheat fields). 10G keeps each of those additions
a single bounded block too.

### 3.2 SHARED-file insertion points (exact; one clearly-bounded block each,
marked `# -- 10G boss ... --` where a comment fits)

**`game/core/session.py`** (anchors = current 10F file):
1. `frozen` property (lines 75-79): change the return to
   `self.state.phase in (GamePhase.LEVELUP, GamePhase.BOSS_CUTSCENE)` — the
   ONLY edit inside an existing statement in this file.
2. `end_turn` (lines 133-146): ONE block inserted immediately BEFORE
   `st.phase = GamePhase.ENEMY` (line 145): love/lives snapshots + announce
   event (§2.3).
3. `pre_sim` ROUND_END branch (lines 159-168): inside the
   `if st.phase_timer <= 0:` body, insert `if st.pending_boss_cutscene:` →
   `self._begin_boss_cutscene()` as the FIRST arm, `elif st.levelup_pending:`
   (existing) second, `else: run_payday(...)` (existing) third — mirrors
   prototype `game.py:1215-1226`.
4. `post_sim` (lines 174-184): ONE block at the top of the
   `phase == ENEMY` path, BEFORE the `_wipe_pending` / wave-clear checks:
   flush `self._boss_swarm_pending` via `spawner.spawn_death_swarm`.
5. New methods `_begin_boss_cutscene` + `resolve_boss_cutscene`: insert as one
   block AFTER `resolve_levelup` (after line 207), section-commented
   `# -- BOSS_CUTSCENE (10G) --`.
6. `on_enemy_death` (lines 249-252): ONE block prepended inside the method
   (boss duck-type check + stash) before the existing kill-count/XP lines.
7. `__init__` (lines 44-65): one line `self._boss_swarm_pending = None` beside
   `self._wipe_pending`.

**`game/ui/hud.py`**:
1. `_PHASE_LABEL` dict (lines 25-31): add
   `GamePhase.BOSS_CUTSCENE: "CUTSCENE",` as a new entry (before the closing
   brace); `_PHASE_COLOR` (lines 32-36): add
   `GamePhase.BOSS_CUTSCENE: C_GOLD,`.
2. `income_breakdown` (lines 42-59): ONE block inserted immediately BEFORE the
   `return income, upkeep` line, commented `# -- 10G boss-bonus story income --`
   (§2.4). Nothing else in hud.py changes — the boss HP bar deliberately lives
   in `effects.py`, NOT here, to keep 10G's hud footprint minimal (10H adds the
   lightning cooldown readout, 10I the overlay toggles, to this same file).

**`game/main.py`** (anchors = current 10F file):
1. Import (lines 61-63): add `BossCutscene` to the existing `from game.ui
   import (...)` list — name-only edit.
2. `gp` dict literal (lines 219-220): add key `"boss_cutscene": None`.
3. `build_gameplay` (lines 222-233): one line after the `gp["levelup"] = ...`
   line (229): `gp["boss_cutscene"] = BossCutscene(view_w, view_h)`.
4. `teardown_gameplay` key tuple (line 238): add `"boss_cutscene"`.
5. `handle_world_click` (lines 264-299): ONE block inserted immediately BEFORE
   `if session.frozen:` (line 275): if
   `session.state.phase == GamePhase.BOSS_CUTSCENE`: `choice =
   gp["boss_cutscene"].hit(mx, my)`; on a choice → `close()` +
   `session.resolve_boss_cutscene(choice, world.scene)`; `return` either way
   (fully modal — swallows the click). Key events need NO new code: the
   existing `session.frozen` gate at line 341 already swallows keys.
6. Sim section (lines 403-445): (a) ONE block after the LEVELUP open-on-edge
   block (lines 428-431): open the boss cutscene on the BOSS_CUTSCENE phase
   edge (`gp["panel"].close()` + `gp["boss_cutscene"].open(...)` from
   `session.state.pending_boss_cutscene`); (b) one line beside
   `gp["floaters"].spawn_xp_events(...)` (line 433):
   `gp["floaters"].spawn_boss_events(session.state)`; (c) one line beside the
   `if session.frozen: gp["levelup"].update(...)` pair (lines 442-443): update
   the boss cutscene when its phase holds; (d) inside the sim-gate block
   (lines 414-420) compute `dmg_bonus =
   story_damage_bonus(session.state, world.tile_map)` and pass
   `dmg_bonus=dmg_bonus` to the existing `resolve_combat` call (one new kwarg
   on the existing call + one new import from `game.core.boss_bonuses`).
7. Render world branch (lines 462-496): (a) ONE shake block right after
   `session = world.session` (line 464): compute `(shake_ox, shake_oy)` per
   §1.5 when `phase == ENEMY` and a live `scene.by_tag("boss")` exists, then
   `cs.pan(shake_ox, shake_oy)`; (b) one line near the floaters submits
   (line 486): `gp["floaters"].submit_boss_bars(renderer, cs, world.scene,
   session.state.phase, view_w, view_h)` + `gp["floaters"].submit_announce(
   renderer, view_w, view_h)`; (c) ONE block after the levelup submit (lines
   489-490): submit the boss cutscene when `phase == BOSS_CUTSCENE`; (d) undo
   the shake `cs.pan(-shake_ox, -shake_oy)` immediately after
   `renderer.flush(window)` (line 496) — inside the same branch, before
   `_t_flush_end`.

10H (lightning/cheat) will add key handling near line 355-366 and its own click
branch; 10I adds overlay submits — every 10G main.py block above is positioned
so none of those regions are touched.

## 4. Exit gate + Quick Test (planner)

### 4.1 `tools/tests/test_boss.py`

Follow `tools/tests/test_phase_loop.py` fixture style exactly: module-level
`load_balance(REPO / "data", ...)` for all five domains, the `synth`/
`build_board` TileMap fixture, `host_frame`/`frame` helpers, deterministic
`random.Random(seed)` injected into `Spawner.begin_round` / `Session.create`.
Hand-computed expectations use the REPO's live JSON (not prototype numbers —
§1.12 notes `scale_every_n_levels` differs). Coverage:

1. **Queue composition** — board with ≥1 `s` tile, seeded rng:
   - round 10 (`boss_idx 0`): queue length `1 + 0 + (12 + 22)` = 35; entry 0 is
     `"boss"`; zero `"siege"`; multiset of the rest = 12 standard + 22 raiders.
   - round 20 (`boss_idx 1`): entry 0 `"boss"`, entries 1-6 all `"siege"`
     (all 6 lead — no mix split), then 40 + 75 shuffled; total 122.
   - round 60 (beyond table): boss leads; counts equal the three hand-computed
     fallback formulas at round 60 with the repo's tier value.
   - non-boss round (e.g. 11) composes exactly as before 10G (regression:
     compare against the 10F expectation — no boss entry).
2. **Era stats + no tier scaling**: for era 0..4, the spawned boss's
   `Health.max_hp` / `dmg` / `Movement.speed` / `EnemyCombat.attack_speed`
   equal `Boss.stats[era]` verbatim; constructing with a huge tier-as-era
   clamps to era 4; scale-tier bonuses are absent (hp == table hp exactly).
   Era selection: round 10 → era 0, round 50 → era 4, round 60 → era 4.
3. **Death-swarm one-shot**: spawn a boss, kill it (`Health.damage(hp)`), run
   a frame with `on_enemy_death=session.on_enemy_death` → after `post_sim`,
   scene holds exactly `death_spawns[era]` new standard/raiders/siege at the
   boss tile; standard swarm members carry the CURRENT tier's cumulative hp
   bonus (they scale; raiders don't); calling `on_enemy_death` again with the
   same boss object spawns nothing (`death_spawned` guard); a boss despawned
   via `quick_skip_combat` spawns nothing.
4. **Boss pathing guard**: a boss whose path goal is a non-base building does
   NOT set `reached_base` when the goal building dies and it arrives there
   (re-paths instead); a boss whose only goal is the base still breaches
   normally (regression for the 10F phantom-base-hit hazard).
5. **Bonus payout math** (pure + payday):
   - `story_damage_bonus`: with `boss1a=2` stacks and N BUILDABLE tiles +
     `boss3a=1`, `boss_love_snapshot=57` → `N*2 + 5`.
   - `resolve_combat(dmg_bonus=k)`: a defender's projectile deals
     `damage() + k` (assert via target HP delta).
   - Payday slot 3: place a building, upgrade it to in-tier level 3, set
     `boss1b=1` → payday pays `+1` beyond the 10F-expected ledger; set
     `boss3b=2` and a defender's `dmg_dealt_this_round=37` before payday →
     `+ (37 // 10) * 2` (proves slot 3 runs AFTER the snapshot roll);
     ordering regression: total love after payday matches
     hand-sum(snapshot → slot3 → base income → yield → upkeep).
   - Boss2A: musician + 1 defence building, `boss2a=1` → musician's income
     event amount = `yield_amount() + 1`; a DEAD defence building still counts
     (no alive filter). Boss2B analogous with a meditator + mortar if cheap to
     build, else assert via the pure `aoe_count` helper.
   - Stacking: `apply_choice` twice on the same option → stacks 2; choice sets
     cycle `(boss_num-1) % 3` (boss 4 → set 0).
6. **Cutscene phase flow**: run a boss round on a board WITH a spawn tile (the
   phase-loop tests' no-spawn-tile trick can't detect a boss round's queue —
   end the wave via `quick_skip_combat` or by killing everything) →
   ROUND_END → after `round_end_delay`, phase is BOSS_CUTSCENE (NOT
   LEVELUP/INCOME even with `levelup_pending=True`); `session.frozen` is True;
   `resolve_boss_cutscene("A")` applies the stack, appends
   `(1, "A", "win")` to `boss_choices`, and lands in LEVELUP (pending set) or
   INCOME (pending clear) with payday paid exactly once; outcome is `"loss"`
   when a life was lost during the boss round (snapshot compare); no cutscene
   queues on a NON-boss round (regression).
7. **XP**: killing the boss pays `core.XP.xp_per_boss` (150) through
   `on_enemy_death`.
8. **Purity/regression**: full suite green — the existing 336+ tests must not
   change (default args keep `resolve_combat`/`Spawner` behavior identical
   when 10G features are unused).

### 4.2 Live Quick Test (state in the PR)

`py game/main.py` → START NEW GAME. SPACE (End Turn) + `P` (quick-skip)
through rounds 1-9; build a Stone Thrower + Flute Player near the hole en
route. Round 10 End Turn: the red "SOMETHING BIG / IS APPROACHING!" banner
fades in/holds/fades; the Bandit Chieftain spawns big and slow among 12+22
companions; while it lives the screen judders subtly (0.6 px) and the
bottom-center BOSS bar drains as defenders hit it; on its death a burst of
10 standard + 5 raiders + 1 siege pours from its tile. After the wave (win or
life lost), the ROUND_END beat opens the cutscene — "Round Won :)"/"Lost :(",
two boxes; pick **B** (Boss1B). Payday runs; open the hole's base-info panel →
"BOSS CHOICES" button lists `Boss 1: Win B` with the desc on hover; the HUD
income line rises by +1 per level-3 building once one exists. Quick-skip to
round 20 → Cannon Fortress (era 1) with 6 leading siege; pick **A** on the
set-1 cutscene and verify a musician's payday floater grows by the defence
count. Smoke: `py tools/smoke.py`; suite:
`py -m unittest discover -s tools/tests -t .`.

### 4.3 Reviewer checklist

- [ ] Payday ordering byte-order-identical: ONLY slot 3 filled (between the
      RoundStats snapshot and base income) + the two in-sweep Boss2A/2B deltas;
      steps never reordered; no floater from slot 3.
- [ ] `game/enemies` still imports NO `game/core`; death swarm + dmg bonus
      cross the boundary as callbacks/plain values only; `Spawner` owns all
      enemy construction.
- [ ] Shared files (`main.py` / `hud.py` / `session.py`) touched ONLY at the
      §3.2 anchors, each addition one bounded block (10H/10I merge cleanly).
- [ ] `Session.frozen` covers BOSS_CUTSCENE; no sim/animation behind the
      modal; keys swallowed; cutscene has NO dismiss path except A/B.
- [ ] Cutscene priority: BOSS_CUTSCENE beats LEVELUP at ROUND_END expiry, and
      chains cutscene → levelup → payday when both pend (payday exactly once).
- [ ] `ENABLE_BOSS = True`; boss-round composition `[boss] + all-siege +
      shuffle(rest)`; era/counts formulas match §1.1-1.3 with the CLAMP and
      the beyond-table fallback.
- [ ] No tier scaling on the boss; companions + death swarm DO use the live
      tier; ×10 numbers read from `enemies.json` verbatim (no literals).
- [ ] Shake is render-only (`cs.pan` symmetric apply/undo, no clamp between),
      params from `Boss.shake`, active only ENEMY-phase + boss alive.
- [ ] No `data/` / schema edits; no prototype edits; no new balancing keys
      (bonus magnitudes are code constants per §2 rationale).
- [ ] Package CLAUDE.md docs updated (enemies / core / ui); PR states the §4.2
      Quick Test scenario and what was actually verified (smoke / suite /
      live).
