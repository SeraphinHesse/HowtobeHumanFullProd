# CLAUDE.md — game/core (Phases 9F + 10A + 10F + 10G + 10H)

The round machine + economy + progression, porting the prototype's
`Game._update_gameplay` / `_begin_enemy_phase` / `_begin_round_end` /
`_begin_income_phase` / `_award_xp` / `_roll_levelup_options` / `_resolve_levelup`.
You reached here from `game/CLAUDE.md`. All pure logic (no pygame — a `TestPurity`
guards it). When you change core conventions, update THIS doc.

`balance.py` is the single validated balancing loader for all five domains
(`load_balance(data_dir, domain)`).

## Round loop (Phase 9F)
Four files beside `balance.py`:
- **`phases.py`** — `GamePhase` (BUILDING/ENEMY/ROUND_END/LEVELUP/INCOME —
  LEVELUP since 10A, BOSS_CUTSCENE since 10G) and `GameState`
  (GAMEPLAY/GAME_OVER; menu states 9H).
- **`game_state.py`** — `RunState` dataclass: the single owner of `phase`, `state`,
  `round_num` (starts 1, `++`'d in payday — prototype numbering), `love`,
  `base_lives`, `phase_timer`, run stats. `from_balance(core, buildings)` seeds
  it — `buildings` decides which types start unlocked (`starts_unlocked_for`,
  data-driven; see `game/buildings/CLAUDE.md`); `add_love`/`spend_love` clamp
  at ≥0 (prototype clamps every currency write).
- **`payday.py`** — `run_payday(state, tilemap, core, occupancy=None, scene=None)`
  mirrors `_begin_income_phase` **step for step; the ordering is SACROSANCT**. 9F
  drives: snapshot RoundStats (this→last) → base income + duck-typed `yield_amount`
  sweep → duck-typed `upkeep` sweep (clamp 0) → **[slot 6: Painter payout]** →
  revive sweep (`rebuild()` on non-base, base excluded) → round++ → phase=INCOME.
  **Do not reorder without the user.**
  - **10G filled slot 3** (the last reserved no-op), and the boss-upgrade
    rework re-pointed it: ONE `boss_bonuses.love_bonus_income(state, tilemap,
    core_balance)` call — the Boss2A/2B story love — still AFTER the RoundStats
    snapshot, still BEFORE base income, still paid silently (NO floater). **The
    slot's ORDINAL POSITION is unchanged.** Step 4's income sweep carries NO
    boss fold-in any more: the old per-recipient Boss2A/2B deltas (and
    `defence_count`/`aoe_count`) are DELETED — both income bonuses are
    whole-board sums now, so nothing folds into per-recipient yields.
  - **10E filled slots 8 + 10**: `_process_wall_teardown` (slot 8, BEFORE revive)
    tears down every DEAD `wall_builder`'s perimeter (`tilemap.remove_walls_for_builder`)
    — seen as `alive == False` at this point, same as painters/boosts; `tilemap.rebuild_walls()`
    (slot 10, AFTER revive) restores every ALIVE builder's frozen snapshot to full HP
    (walls regenerate each payday; a revived builder's torn-down walls come back, and
    only a builder that STAYS dead — revive off — loses its walls for good).
  - **Building Movement appended slot 10b, the new LAST step** — one
    `game.buildings.movement.process_moves(tilemap, occupancy, scene)` call
    directly after `tilemap.rebuild_walls()`. A **pure APPEND: nothing above
    it moved**, so the sacrosanct ordering is untouched. It ticks every
    in-transit building's `rounds_left` down one and lands the ones that
    arrive. AFTER revive on purpose: an in-transit building holds no tile, so
    it was never a candidate for slots 7-9 this payday, and it starts its
    first round on the new tile in the same fully-healed state as everything
    else at this point. `occupancy`/`scene` thread through unchanged —
    `run_payday`'s signature did NOT grow (the module-level
    `from game.buildings.movement import process_moves` is as safe as the
    `game.buildings.components` import already beside it; verified no cycle).
  - **10D filled slot 7**: `_process_boosts` sweeps every `"boost"`-tagged building
    on a built tile BEFORE revive. Alive boosters (ramp mode) accumulate their
    per-turn `boost_value` onto cardinal-adjacent combat neighbours' `BoostReceiver`
    (one `boost_events` floater each); a booster dead THIS round explodes its debuff
    onto neighbours once (guarded by `BoostEmitter.exploded`, reset in `rebuild()`)
    and, in flat mode, reverses its 10× contribution. Runs before revive for the
    same reason painters do — it must see the dead booster as `alive == False`.
  - **debug-mode-telemetry threads three hooks BETWEEN existing steps,
    never reordering them**: `debug.on_payday_start(state, tilemap,
    core_balance, built)` runs BEFORE step 2's snapshot (so it still sees
    this round's true `dmg_*_this_round`, and the potential ledger can see
    which occupants died during the wave); `debug.on_payday_story(state)`
    runs immediately AFTER step 3 (story_income is measured as the exact
    love delta across that one step, since the slot-3 payout leaves no
    `income_events` trace — this stays correct for free across the
    boss-upgrade rework); `debug.on_payday_end(state, tilemap)` runs
    immediately AFTER step 6 (painters) — BEFORE steps 7-11 — so
    `income_events` holds base + yields + upkeep + painter payouts while
    `round_num` is still pre-increment. `debug=None` (every pre-existing
    caller) is a no-op at all three sites; `payday.py` never imports
    `game.debug` — it duck-types the three method calls on whatever object
    `Session` hands it, exactly like `occupancy`/`scene`.
  - **10C filled slot 6**: `_process_painters` advances alive painters and, on a
    completed one, pays the lump sum + frees the tile (occupant/content_key
    cleared, BUILDABLE, occupancy cleared, building despawned) + bars it via
    `RunState.used_painter_tiles`. The revive step removes a dead gone-for-good
    painter (freeing the tile, NOT barring it) with a `painter_events` "painting
    lost!" message. Freeing a tile needs `occupancy` + `scene`, so both are
    threaded from the `Session` (optional-defaulted → logic tests keep the 3-arg
    call). The income sweep calls a meditator's `collect_income(disturbed)`
    instead of `yield_amount()` — the ONE non-duck-typed branch, for the streak
    compounding (see `game/buildings/CLAUDE.md`).
- **`session.py`** — `Session` orchestrates per frame: `end_turn()` (BUILDING→ENEMY,
  `spawner.begin_round(round_num, …)`); `pre_sim(dt, scene)` (spawner during ENEMY;
  ROUND_END/INCOME timers from `core.PhaseLoop`; payday at ROUND_END end);
  `post_sim(scene)` (wave-clear = `spawner.done` + no live enemy + no kidnapper
  walking home (Art/enemies, below) → ROUND_END; or a `_wipe_pending`
  lives-breach wipe); `on_base_hit(enemy)` (`base_lives--` + round wipe, game
  over at 0 lives). Everything freezes on GAME_OVER (no phase advances) —
  prototype `_update` has no GAME_OVER branch.

Love → interactive placement + real HUD/End-Turn button are 9G; `Session` owns the
love store, ready to feed `place_building`.

- **`Session.tutorial_gate` (TU-6)**: an optional host-set callable
  (`() -> bool`, the `BuildingUI.on_build_vfx` host-callback precedent), `None`
  by default (a bare `Session` a logic test builds never gates). `end_turn()`
  checks it right after its existing `state != GAMEPLAY or phase != BUILDING`
  guard and returns early if it says no — this is the ONE place the round-1
  guided tutorial (`game/tutorial/director.py`, `game/CLAUDE.md`) actually
  gates End Turn; `game/main.py` wires it to
  `gp["tutorial"].allows_end_turn`. TU-5's `pending_cutscene` insertion sits
  textually below this one (both inside `end_turn()`, non-overlapping).
- **`Session.tutorial_director` (TU-7)**: an optional `TutorialDirector`
  reference (not just a bare callable like `tutorial_gate` — `on_base_hit`
  and `_begin_round_end` need to call more than one method on it), `None` by
  default, set alongside `tutorial_gate` in `build_gameplay()`
  (`gp["world"].session.tutorial_director = gp["tutorial"]`). Two call sites,
  both no-ops when `None` or when the director is finished/inactive:
  `on_base_hit` consults `director.charges_life_on_base_hit(round_num)`
  immediately before decrementing `base_lives` (the scripted free-loss
  waiver — a pure read, never mutates the director; the tutorial's scripted
  round is round 0 since TU-9, not round 1 — see below); `_begin_round_end`
  unconditionally calls `director.on_round_end(round_num)` right after
  setting `phase = ROUND_END`, on every road there (wipe / wave-clear /
  quick-skip / cheat-skip alike) — harmless outside the one scripted step
  that's actually waiting on that event id. Detail (script shape, the
  stone-thrower chain) → `game/CLAUDE.md`'s TU-7 subsection.
- **The tutorial round is round 0 (TU-9)**: an active tutorial run's
  `Session` is seeded to `round_num = 0` host-side (`main.py`'s
  `build_gameplay`), never as a `Session`/`RunState` default — a bare
  `Session` a logic test builds, or an inactive/auto-skipped director, always
  starts at round 1 unchanged. `Session.end_turn`'s boss announce-marker
  check and `_begin_round_end`'s boss-cutscene-queue check both gained a
  `round_num != 0` guard (round 0 is never a boss round — `0 % n == 0` was true
  for every interval under the pre-ES-1 expression; since ES-2 both sites go
  through `era_math.is_boss_round`, which is False at round 0 by contract for
  every configuration (D11), so the explicit guard is now belt-and-braces
  rather than load-bearing); the `first_end_turn` cutscene request re-keyed off a new
  one-shot `RunState.first_end_turn_cutscene_requested` latch instead of
  `round_num == 1`, so it still fires exactly once on the run's first
  `end_turn()` whether that round is 0 (tutorial) or 1 (a skipped run). Full
  detail → `game/CLAUDE.md`'s "The tutorial is round 0 (Phase TU-9)" section.

- **`Session.debug` (debug-mode-telemetry)**: an optional `game.debug.
  DebugRecorder` reference, `None` by default — the SAME shape as
  `tutorial_director` above (host-set, `build_gameplay()` assigns it, a bare
  `Session` a logic test builds is untouched). Every emit site across this
  module is `if self.debug is not None: self.debug.<call>(...)`: `end_turn`
  (`wave_start`, reading composition off `spawner.pending()` since that is
  the only source for `wave_size`/`enemy_tier`), `on_base_hit` (`note_base_
  hit` + `base_hit`, plus `game_over` on the fatal hit — a base breach
  applies NO HP damage, so this is `lives_lost`/`leaks` bookkeeping only,
  never fused with `RoundStats`), `on_enemy_death` (`note_kill` + `enemy_
  death`), `on_kidnap` (`note_kidnap` + `kidnap`), `resolve_levelup` (`unlock`/
  `research` for the level-up reward + `note_love_spent`, then `levelup`),
  `resolve_boss_cutscene` (`boss_choice`), `lightning_strike` (an optional
  `on_hit` collector threaded into `lightning.strike`, summed into `note_
  lightning` — see below), and every `cheat_*` method (`cheat` — a cheated
  run is latched `cheated=1` for the rest of the run by the recorder itself,
  never unset here). `run_payday` takes `debug` as its sixth positional
  argument at all three call sites (`pre_sim`'s ROUND_END branch,
  `resolve_levelup`, `resolve_boss_cutscene`) — see `payday.py`'s doc section
  below for the three-hook ordering.
  - **`lightning.strike` gained an optional `on_hit(dmg)` callback** (additive
    — `None` keeps every other caller, including every test in this module,
    byte-identical): lightning earns no `RoundStats` credit (no shooter), so
    this is the only way to learn a strike's total damage/hit count.
    `Session.lightning_strike` collects every `on_hit` call from every firing
    caster in the click into one list and reports the SUM as `note_lightning`'s
    `dmg` argument (total damage, not per-enemy) — only when `fired` is True,
    so a click that hit nothing because every caster was still cooling logs
    nothing (a caster that DID fire but hit zero enemies still logs, per
    `note_lightning`'s own "a whiff still pays the cooldown" contract).
  - **`RESEARCH`/`UNLOCK` have TWO distinct sources**, both legitimate per
    `events.py`'s "researched / advanced" wording: `resolve_levelup` emits
    them for a TYPE-WIDE reward (a level-up card unlocking a building type, or
    researching its next tier — `RunState.unlocked_buildings`/
    `tiers_unlocked`); `game/ui/building_ui.py`'s upgrade-panel tier-advance
    branch emits `RESEARCH` for one INSTANCE advancing into an
    already-researched tier (`building.advance_tier()`). Neither building_ui
    site has a natural `UNLOCK` action to pair with `PLACE`/`RESEARCH` — a
    tile unlock (`_unlock_click`, COMBAT → BUILDABLE) is a different concept
    with different fields (col/row, not building_type) and is NOT wired to any
    debug event.

> Cross-package note (9F): `engine/render/fonts.py` `get_font` now probes a cached
> SysFont with `get_height()` and rebuilds it if its pygame session was torn down
> (a prior `pygame.quit()` — surfaced by drawing HUD text across the repeated
> in-process `game.main` boots the tests/smoke do). Pure engine robustness fix, no
> API change. (Detail now in `engine/render/CLAUDE.md`.)

## XP / village level-up / research (Phase 10A)
Enemies and buildings drop XP, XP fills a village level, and each level opens a
modal LEVELUP window whose reward researches the next building tier (or pays love).
- **`game/core/xp.py`** (pure) — `xp_for_etype` (keyed on `Enemy.ETYPE`),
  `award_xp` (arms `levelup_pending`; queues an `xp_events` floater),
  `advance_village_level` (the 50→65→85→110→140 threshold walk; surplus carries
  forward, one level per resolve), and **`scaled_base_income`** — the ONE source
  for payday, the HUD income line and the base-info panel, so they can't drift.
- **`game/core/levelup.py`** (pure) — the option roll + `apply_levelup_option` +
  **`upgrade_gate`**, the FIVE-mode upgrade classifier the panel renders (`in_tier`
  / `tier_upgrade` / `tier_locked` / `tier_hidden` / `max_tier`). A tier can no
  longer be advanced into for free: it must be **researched on a level-up** first,
  and stays unnamed until its `unlock_min_round`. A locked TYPE's own unlock
  card is gated the same way, by its `tiers[0].unlock_min_round` — the single
  round gate per type (no separate era key); unlocking a type makes tier 1
  immediately placeable. The gate table + stacking rules live in
  `game/buildings/research.py` (see that doc).
- **Phase machine**: at ROUND_END's expiry a pending level-up enters
  `GamePhase.LEVELUP` **instead of** running payday; `Session.resolve_levelup`
  applies the reward, advances the level, then runs payday (the prototype's
  `run_income=True` path — the cheat `return_phase` path is 10H). `Session.frozen`
  is the host's single "skip the whole sim" flag: no `scene.update`, no combat, no
  animation behind the modal. Payday's base income is now village-scaled.
- **XP award sites**: field kills via `resolve_combat(on_enemy_death=…)` (same
  layering trick as `on_base_hit`); a kidnap transition via
  `resolve_combat(on_kidnap=…)` → `Session.on_kidnap` (Art/enemies, below —
  same layering trick, one more callback); base-damage kills gated by
  `XP.xp_on_base_damage_kill`; queued-but-never-spawned enemies paid on a lives
  wipe (`Spawner.pending()`), while live enemies cleared from the field pay nothing
  (prototype-exact); building deaths gated by `XP.xp_from_buildings`, **once per
  building `id()` for the whole run** — a faithful prototype quirk: revive, die
  again, no second payout. `on_enemy_death` also fixes a real bug — `enemies_killed`
  used to count only base breaches, so the game-over screen under-reported kills.
  - **`_award_building_deaths` runs from `pre_sim`'s ENEMY arm AND from both of
    `post_sim`'s round-ending branches.** The second site is not redundant: a
    building that dies on the very frame the round ends — a base breach
    (`_wipe_pending`) or the last enemy of the wave — never sees another
    ENEMY-phase `pre_sim`, and payday's slot-9 revive then makes it `alive`
    again, so its XP was silently lost forever. The id-keyed
    `_xp_awarded_buildings` guard makes the extra sweep a provable no-op
    otherwise. This bites hardest on a kidnap, which is *always* a building
    death, but it was never kidnap-specific.
- **Grouped unlock (10D boost trio)**: `roll_levelup_options` offers an unlock card
  only for the LEAD member of a spec's `unlock_group` (`btype == unlock_group[0]`),
  skipping the other locked members — so the three boosters surface as ONE "Unlock
  Boost Buildings" card whose `apply_levelup_option` unlocks all three, gated by
  the lead's own `tiers[0].unlock_min_round` (10 — each boost line carries its
  own copy of that value, no shared `gate_kind`/globals key needed). All three
  still carry a `RESEARCH` row so each researches its own tiers after unlocking.
- **Empty pool is expected before round 10**: only `defence` + `economic` exist,
  both start unlocked at tier 1, their tier-2s are round-gated to 10, and the hole
  is lives-based so the prototype's `+1 Base HP` fallback doesn't apply — so early
  level-ups show three identical `+25 Love` cards (the prototype's pad-to-3). The
  pool fills as 10B–10E land their families.

The UI half of level-up (`game/ui/levelup.py`, XP bar, gated construct list) lives
in `game/ui/CLAUDE.md`.

## Combat speed + quick-skip (Phase 10F)
`Session` owns the combat-speed selector; the HOST decides where it applies.
- **`COMBAT_SPEEDS = (1.0, 1.5, 2.0, 0.0)`** (module constant in `session.py`,
  prototype `game.py:45-47`) indexed by `Session.combat_speed_idx`. Index 3 is the
  in-combat **pause — a 0.0 multiplier, NOT a phase change**, so the round machine
  is completely untouched while it holds. A code constant, not balancing (like
  `AOE_TRAVEL_TIME`); the two round-gate thresholds ARE data
  (`core.PhaseLoop.speed_1_5x_min_round` / `speed_2x_min_round`).
- **The round-gate lives in `Session.speed_unlocked`, not the UI.** The prototype
  gated only its HUD buttons, so its keyboard shortcuts could bypass the gate;
  gating in the setter instead means the keys and the (10L) buttons cannot drift
  apart. `set_combat_speed` no-ops on a locked or out-of-range index and remembers
  the last non-pause index so `toggle_pause` restores it.
- **Speed scales the ENEMY phase ONLY** — the host computes
  `sim_dt = dt * session.combat_speed` while `phase == ENEMY` and feeds that ONE
  value to `pre_sim` + `scene.update` + `resolve_combat` (spawner, movement and
  the combat sweep must advance together, prototype `game.py:1211-13`).
  ROUND_END/INCOME timers always tick on real `dt` — a 2× wave still gets its full
  payday beat. Because the scaling only applies while ENEMY, passing the single
  `sim_dt` everywhere is safe: in every other phase it IS `dt`.
- **`quick_skip_combat(scene)`** (the bare `P` key) abandons the wave → ROUND_END:
  despawn live enemies + `spawner.clear()`. It pays **NO XP** — neither the
  cleared enemies nor the queued ones. That is prototype-exact and deliberately
  UNLIKE `_wipe_round` (a lives breach), which still pays the queued enemies so a
  life loss can't rob the player.
- Speed **persists across rounds**; a new run builds a new `Session`, which is the
  prototype's "reset to 1× on new game". The 1×/1.5×/2×/pause **buttons + the
  lives-faces indicator are 10L** (the UI-editor phase) — 10F ships the mechanic
  and the `1`/`2`/`3` + `P` keys only, so `toggle_pause` currently has no key bound
  to it.

## Boss cutscene + bonuses (Phase 10G; reworked)
- **`boss_bonuses.py`** (pure) — no global singleton: the six stack counters
  live in `RunState.boss_stacks` (fresh run = fresh RunState = the reset).
  `apply_choice(state, (boss_num-1)%3, option)` stacks; picking the same option
  twice doubles it. The **positional ids `boss1a`…`boss3b` + `BONUS_IDS` are
  permanent** — they encode set+option, which the cutscene's `WinA`/`WinB`
  labels, the `(boss_num-1)%3` set cycle and the boss-history popup all key off
  — so re-designing the EFFECTS never touches `RunState`/`game_state.py`.
- **The six effects (boss-upgrade rework)**: 1A +dmg per unbuilt (BUILDABLE)
  tile · 1B +dmg per building placed · 2A +love per building level past
  `level_past_threshold` · 2B +love per building at `low_level_target` · 3A
  +dmg per `love_chunk_size` of love held (the End-Turn snapshot) · 3B +dmg
  per lightning building built.
- **Magnitudes are BALANCING now, not code constants** (they were in 10G):
  `data/balancing/core.json`'s `BossBonuses` block, threaded in as
  `core_balance`. That domain was chosen because `core_balance` already reaches
  every call site — no function gained a new parameter CHAIN and
  `run_payday`'s signature is untouched. `choice_desc(effective_idx, option,
  core_balance)` `.format()`s the live numbers into the two-line UI copy, so
  the cutscene can never advertise a magnitude the math no longer uses.
- **Two payout sites**: `story_damage_bonus(state, tilemap, core_balance)` sums
  1A + 1B + 3A + 3B into the ONE flat int the HOST threads into
  `resolve_combat(dmg_bonus=…)` each frame; `love_bonus_income(state, tilemap,
  core_balance)` sums 2A + 2B in one walk and is payday slot 3.
- **"Buildings" = ALIVE, non-base occupants of built tiles**, in every count —
  a destroyed building stops counting until payday's revive. This is a
  deliberate change: 10G's `defence_count`/`aoe_count` had NO alive filter, and
  both are DELETED (with `boss1b_income`/`boss3b_income`). Levels read
  `TierState.current_level_in_tier` (a building freshly advanced into a new
  tier is level 1 again); lightning buildings are duck-typed off the
  `"lightning_source"` TAG (the `payday._process_boosts` `"boost"` precedent) —
  this module must NEVER import `game.buildings.registry`, which risks closing
  an import cycle (`game.core.session` imports `game.debug` at module scope).
- **Phase flow**: `end_turn` snapshots love EVERY round (Boss3A) and, on a boss
  round, lives + one `boss_events` announce marker. **Both boss-round checks in
  this file (`end_turn`'s announce marker and `_begin_round_end`'s cutscene
  queue) read the era clock through `engine.era_math`** (ES-2/D1):
  `era_math.is_boss_round(round_num, EnemyScaling.rounds_per_era,
  EnemyScaling.boss_round_in_era)`, and the cutscene's `boss_num` is
  `era_math.era_of_round(round_num, rounds_per_era) + 1`. `Boss.round_interval`
  is DELETED — there is one clock, in `EnemyScaling`, and no round arithmetic is
  written out here. `_begin_round_end` queues
  `pending_boss_cutscene = {boss_num, outcome}` (outcome = lives vs snapshot).
  At ROUND_END expiry the pending cutscene **beats** `levelup_pending`;
  `Session.frozen` covers `BOSS_CUTSCENE` exactly like LEVELUP.
  `resolve_boss_cutscene(option, scene)` applies the stack, appends
  `(boss_num, option, outcome)` to `boss_choices` (the per-run history the
  base-info popup reads; no disk persistence), then chains → LEVELUP (if
  pending) → payday, exactly once.
- **Death spawn handshake (layering) — GENERALISED in ER-3**: `game/core` still
  imports NO `game/enemies`. The gate is **no longer `ETYPE == "boss"`** (that
  was a G-3 violation): `on_enemy_death` duck-types `death_spawn_plan` off ANY
  enemy — `None` unless that type carries an ENABLED `death_spawn` — plus
  `death_spawned` / `mark_death_spawned()` (a METHOD, because the E-11 setattr
  guard blocks public property setters). The stash is a **LIST**
  (`_death_spawns_pending`), not 10G's single slot: several units can die in one
  frame (ER-4's Formations will) and a single slot would silently drop all but
  the last. The stashed `plan` is an **OPAQUE payload** — core never inspects or
  indexes into it, it just hands it back to
  `spawner.spawn_death_swarm(scene, col, row, plan)`. `post_sim` drains the list
  (rebinding it to `[]` **before** iterating, so a re-entrant death can't lose or
  double-run a burst) BEFORE the wave-clear check, so the burst is submitted to
  the Spawner while the round is still live. Quick-skip / lives-wipe / cheat
  despawns never reach the callback → they spawn nothing.
  - **The wave-clear check consults the SPAWN QUEUE too (ER-5).** Flushing the
    burst before the check was not enough on its own: `Scene.spawn()` only QUEUES
    and `by_tag()` reads the live list, so children burst on THIS frame were
    invisible to the check eight lines below — killing the last enemy of a drained
    wave ended the round and the children materialised into it. The condition is
    now `spawner.done and no live enemy and not scene.queued_by_tag("enemy")`
    (`engine/core/CLAUDE.md`). This closes the general queue-then-check race, not
    just the death-burst instance. It was a real bug for the 10G boss from the
    start and would have been a common one for ER-4's Formations.

## Lightning strike + cheat menu (Phase 10H; Storm Priest rework; feature-storm-acolyte-multi-build)
`game/core/lightning.py` (pure; imports `engine.core` only) owns the ability:
- **State on `RunState`**: `lightning_level` (**seeded 0** — every run boots
  with lightning LOCKED; placing a Storm Priest, the `"lightning_source"`-
  tagged building, is the ONLY way to raise it to L1, via
  `unlock_from_placement(state, building)` — a pure, tag-gated, latching
  helper (never re-locks) called from `game/ui/building_ui.py._do_place`
  after every successful placement). **There is no love-priced level-up any
  more** (`next_cost`/`upgrade` are DELETED — the Storm Priest rework
  replaced them): leveling past L1 is driven entirely by each placed Storm
  Priest's own tier, via `sync_level_from_tier(state, building)` (same
  tag-gated/latching shape, called from `game/ui/building_ui.py`'s
  tier-advance branch — tier 1/2/3 -> lightning level 1/2/3). Tunables ONLY
  from `core.json LightningStrike` (cooldown [5,3,2] / damage [12,18,38] /
  radius [1,2,3] — `unlock_cost`/`upgrade_costs` were removed from the schema
  + content along with the love-priced path).
  - **feature-storm-acolyte-multi-build re-scoped `lightning_level`'s
    MEANING (its FIELD/latch semantics are unchanged)**: the run-singleton
    ban on Storm Priest is lifted (`game/buildings/CLAUDE.md`'s Storm Priest
    section) — several may be placed, each levelled independently. So
    `lightning_level` is now a pure **UI/gating signal** ("is lightning
    unlocked at all" / "the best tier ever placed"), never a damage/radius/
    cooldown source; every fired bolt reads those off the FIRING building's
    own `tier_number()` instead (see `strike()` below). `lightning_cooldown`
    is **DELETED from `RunState`** — the cooldown moved onto each acolyte's
    own `LightningCaster` component (below), since a run can now have
    several, each on its own clock.
- **`LightningCaster` (`game/core/lightning.py`, attached per Storm Priest by
  `_extra_components`) carries a declared `cooldown: float = 0.0` field** —
  the per-caster ability clock feature-storm-acolyte-multi-build moved off
  `RunState`. **Drained ONLY by `tick(state, dt, scene)`, never by
  `LightningCaster.update(dt)`** (that runs from `scene.update` in EVERY
  phase and would silently break the "cooldown frozen outside ENEMY" rule —
  `update(dt)` still owns only the "attack" -> "idle" flash-pose timer,
  unchanged).
- **`can_strike(state, scene)`** — `state.lightning_level > 0` (unlocked) AND
  at least one alive `lightning_source` is off cooldown; a click with every
  acolyte still charging is a silent no-op, same shape as the old
  single-caster gate.
- **`strike(state, core, vfx, scene, cs, wx, wy)`** — **fires EVERY alive,
  ready caster** at the clicked point in one click (the old "stop after the
  first `lightning_source`" `break` is GONE): each contributes flat damage to
  every alive `"enemy"` in ITS OWN tier's **Euclidean circle in the PROJECTED
  pixel plane** (prototype `game.py:505-508`, `LightningStrike` indexed by
  that building's own `tier_number() - 1`, not `state.lightning_level`) —
  both points go through `cs.world_to_screen` and the threshold is
  `radius_tiles * tile_w/2 * zoom` (pan cancels in the delta, zoom scales
  linearly — no iso math outside `engine.coords`). NOT Chebyshev, NOT
  tile-space Euclidean. Several nested `LightningFX` rings landing at once
  read as several bolts and are honest about which tiers actually
  contributed — damage stacks (an enemy at the centre takes every firing
  acolyte's damage). Each firing caster's cooldown is spent UNCONDITIONALLY
  (a whiff still pays + shows VFX, per-caster); a caster still cooling sits
  the whole click out, untouched. No RoundStats credit (no shooter); kills
  flow through the next `resolve_combat` → `on_enemy_death` (normal XP/kill
  path). Each firing caster spawns its OWN `LightningFX` (`Crater` pattern:
  overlay object, ages in `scene.update` on the ENEMY-scaled sim dt,
  self-despawns; `BOLT_LIFE`/`MARKER_LIFE` are code constants like
  `CRATER_LIFE`) and its OWN `LightningCaster.trigger()` — since Storm Priest
  dropped the `"combat"` tag and no longer earns its "attack" pose through
  combat, `strike()` is what flashes each firer: `SpriteAnimator` to "attack"
  for `CASTER_FLASH_DURATION` (0.4s, a code constant like `BOLT_LIFE`) before
  it reverts to "idle" in its own `update(dt)`. Both a hit and a whiff
  trigger the flash (same "a whiff still pays + shows VFX" rule as the
  cooldown spend).
- **Cooldown ticks ONLY in `pre_sim`'s ENEMY branch** (`tick(state, dt,
  scene)`, walking every alive `lightning_source`'s own caster) on the host's
  sim dt (speed-scaled, pause-frozen); never reset by round end or a tier
  sync.
- **`Session` cheat delegates** (all no-op outside GAMEPLAY; the Ctrl+L menu UI
  is `game/ui/cheat_menu.py`, the host maps its action strings here):
  `cheat_add_love`, `cheat_skip_round` (quick-skip's body WITHOUT the ENEMY
  guard — no XP, then the NORMAL ROUND_END→payday flow), `cheat_goto_round`
  (round_num + BUILDING, **no payday invoked** — ordering untouched),
  `cheat_trigger_levelup`, `cheat_unlock_all` (sweeps the whole `RESEARCH`
  table — deliberately FIXES the prototype's meditator/blocker omission).
- **The `return_phase` path is now live**: `_begin_levelup(run_income=True,
  return_phase=None)`; the cheat LEVEL UP outside ENEMY/LEVELUP passes
  `run_income=False, return_phase=<current phase>` so `resolve_levelup`
  restores that phase and runs **NO payday** (village-level math identical on
  both paths). The natural ROUND_END call site keeps the defaults — zero
  behavior change there. Mid-ENEMY the cheat only arms `levelup_pending`; the
  window then fires at ROUND_END on the normal payday path.

## Kidnapping (Art/enemies)
`resolve_combat(on_kidnap=…)` — the fourth layering-trick callback beside
`on_base_hit`/`on_enemy_death`/the ER-3 death-spawn handshake, fired from
`game/enemies`'s kidnap pass the frame a kidnap-capable enemy's killing blow
transitions it into a carrier (see `game/enemies/CLAUDE.md`).
- **`Session.on_kidnap(enemy, building)`** mirrors `on_enemy_death`:
  `enemies_killed += 1` + `_award_enemy_xp(enemy)`, but deliberately **skips**
  the `enemy_death_events` splatter append (no VFX) and the ER-3
  `death_spawn_plan` stash (a kidnapped unit never bursts). **It does nothing
  at all to the building** (user decision): the victim is left standing on its
  tile as a plain dead building, so every payday slot treats it exactly like
  one killed by a non-kidnapping enemy — slot 7 explodes a kidnapped booster,
  slot 8 tears down a kidnapped `wall_builder`'s perimeter and slot 10 restores
  it, and the **slot-9 revive rebuilds it, so a kidnapped building reappears
  next phase**. `BuildingSprite` hides it meanwhile. It used to call
  `payday._free_tile(...)` here and be gone for good; that, the explicit
  `remove_walls_for_builder` call it needed, and the `scene` parameter are all
  deleted.
- **Wave-clear now also waits on kidnappers** (confirmed user decision — "a
  kidnapper walking home HOLDS the round open"): `post_sim`'s condition gained
  `and not scene.by_tag("kidnapper") and not scene.queued_by_tag("kidnapper")`
  (the ER-5 queued-tag reasoning applies here too — a fresh kidnapper is a
  retag, not a spawn, but the check must not race a same-frame despawn either).
- **Every "clear the field" path must also clear kidnappers**, or the round
  can never end once one exists: `quick_skip_combat`, `_wipe_round`,
  `cheat_skip_round` and `cheat_goto_round` each now despawn `by_tag("enemy")
  + by_tag("kidnapper")`. Kidnappers pay nothing extra on those paths — they
  already paid their XP on the kidnap itself.

## 10J ledgers
`RunState` grew two more drained-by-UI ledgers (the `income_events` contract):
`log_events` (plain strings for the fading game log — `GameLog.drain`) and
`enemy_death_events` (`(wx, wy)` splatter positions, appended by BOTH
`Session.on_enemy_death` and `on_base_hit`; the gore gates live in the FX
layer, core stays ui-free). No phase/payday ordering change.

## Names write (9H)
`game/core/names.py append_random_name` persists the add-name menu's typed name to
`buildings.json` `BuildingsGlobal.random_names` via `write_validated` — the one
runtime data write (disk I/O stays out of pygame-pure `game/ui`).

## Verify
Phase-machine unit tests; headless 3-round currency ledger matches
prototype-computed values: `py -m unittest discover -s tools/tests -t .`. Live
`py game/main.py` for phase/combat behavior.
