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
  - **10G filled slot 3** (the last reserved no-op): the Boss1B/3B story
    payouts via `boss_bonuses.boss1b_income`/`boss3b_income` — AFTER the
    RoundStats snapshot (Boss3B reads the `dmg_dealt_last_round` it just
    rolled), BEFORE base income, paid silently (NO floater). The Boss2A/2B
    per-recipient deltas fold into each `amount` INSIDE the existing step-4
    income sweep (`defence_count`/`aoe_count` computed once, NO alive filter on
    the counts), so floaters, totals and the HUD readout stay in lockstep.
  - **10E filled slots 8 + 10**: `_process_wall_teardown` (slot 8, BEFORE revive)
    tears down every DEAD `wall_builder`'s perimeter (`tilemap.remove_walls_for_builder`)
    — seen as `alive == False` at this point, same as painters/boosts; `tilemap.rebuild_walls()`
    (slot 10, AFTER revive) restores every ALIVE builder's frozen snapshot to full HP
    (walls regenerate each payday; a revived builder's torn-down walls come back, and
    only a builder that STAYS dead — revive off — loses its walls for good).
  - **10D filled slot 7**: `_process_boosts` sweeps every `"boost"`-tagged building
    on a built tile BEFORE revive. Alive boosters (ramp mode) accumulate their
    per-turn `boost_value` onto cardinal-adjacent combat neighbours' `BoostReceiver`
    (one `boost_events` floater each); a booster dead THIS round explodes its debuff
    onto neighbours once (guarded by `BoostEmitter.exploded`, reset in `rebuild()`)
    and, in flat mode, reverses its 10× contribution. Runs before revive for the
    same reason painters do — it must see the dead booster as `alive == False`.
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
  `post_sim(scene)` (wave-clear = `spawner.done` + no live enemy → ROUND_END; or a
  `_wipe_pending` lives-breach wipe); `on_base_hit(enemy)` (`base_lives--` + round
  wipe, game over at 0 lives). Everything freezes on GAME_OVER (no phase advances)
  — prototype `_update` has no GAME_OVER branch.

Love → interactive placement + real HUD/End-Turn button are 9G; `Session` owns the
love store, ready to feed `place_building`.

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
  and stays unnamed until its `unlock_min_round`. The gate table + stacking rules
  live in `game/buildings/research.py` (see that doc).
- **Phase machine**: at ROUND_END's expiry a pending level-up enters
  `GamePhase.LEVELUP` **instead of** running payday; `Session.resolve_levelup`
  applies the reward, advances the level, then runs payday (the prototype's
  `run_income=True` path — the cheat `return_phase` path is 10H). `Session.frozen`
  is the host's single "skip the whole sim" flag: no `scene.update`, no combat, no
  animation behind the modal. Payday's base income is now village-scaled.
- **XP award sites**: field kills via `resolve_combat(on_enemy_death=…)` (same
  layering trick as `on_base_hit`); base-damage kills gated by
  `XP.xp_on_base_damage_kill`; queued-but-never-spawned enemies paid on a lives
  wipe (`Spawner.pending()`), while live enemies cleared from the field pay nothing
  (prototype-exact); building deaths gated by `XP.xp_from_buildings`, **once per
  building `id()` for the whole run** — a faithful prototype quirk: revive, die
  again, no second payout. `on_enemy_death` also fixes a real bug — `enemies_killed`
  used to count only base breaches, so the game-over screen under-reported kills.
- **Grouped unlock (10D boost trio)**: `roll_levelup_options` offers an unlock card
  only for the LEAD member of a spec's `unlock_group` (`btype == unlock_group[0]`),
  skipping the other locked members — so the three boosters surface as ONE "Unlock
  Boost Buildings" card whose `apply_levelup_option` unlocks all three. All three
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

## Boss cutscene + bonuses (Phase 10G)
- **`boss_bonuses.py`** (pure) — the prototype's `boss_bonuses.py` WITHOUT its
  global singleton: the six stack counters live in `RunState.boss_stacks`
  (fresh run = fresh RunState = the reset). `BOSS_CHOICES`/`choice_desc` carry
  the exact A/B UI copy; `apply_choice(state, (boss_num-1)%3, option)` stacks;
  `story_damage_bonus` (Boss1A per-BUILDABLE-tile + Boss3A per-10-love of the
  End-Turn snapshot) is the flat int the HOST threads into
  `resolve_combat(dmg_bonus=…)` each frame; `boss1b_income`/`boss3b_income`
  are payday slot 3; `defence_count`/`aoe_count` the Boss2A/2B counts. **Bonus
  magnitudes are code constants** (the `COMBAT_SPEEDS` precedent), everything
  else reads balancing.
- **Phase flow**: `end_turn` snapshots love EVERY round (Boss3A) and, on a boss
  round (`round_num % Boss.round_interval == 0`), lives + one `boss_events`
  announce marker. `_begin_round_end` queues
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

## Lightning strike + cheat menu (Phase 10H)
`game/core/lightning.py` (pure; imports `engine.core` only) owns the ability:
- **State on `RunState`**: `lightning_level` (**seeded 1** — the prototype boots
  with lightning unlocked at L1 and never resets it; the L0 20♥ unlock branch
  stays implemented but is unreachable from a normal boot) and
  `lightning_cooldown`. Tunables ONLY from `core.json LightningStrike`
  (cooldown [5,3,2] / damage [10,15,32] / radius [1,2,3] / unlock 20 /
  upgrades [35,80] — the LIVE prototype JSON, not the stale `.py` defaults).
- **`strike(state, core, scene, cs, wx, wy)`** — flat damage to every alive
  `"enemy"` in a **Euclidean circle in the PROJECTED pixel plane** (prototype
  `game.py:505-508`): both points go through `cs.world_to_screen` and the
  threshold is `radius_tiles * tile_w/2 * zoom` (pan cancels in the delta, zoom
  scales linearly — no iso math outside `engine.coords`). NOT Chebyshev, NOT
  tile-space Euclidean. The cooldown is spent UNCONDITIONALLY (a whiff still
  pays + shows VFX); no RoundStats credit (no shooter); kills flow through the
  next `resolve_combat` → `on_enemy_death` (normal XP/kill path). Spawns a
  `LightningFX` (`Crater` pattern: overlay object, ages in `scene.update` on the
  ENEMY-scaled sim dt, self-despawns; `BOLT_LIFE`/`MARKER_LIFE` are code
  constants like `CRATER_LIFE`).
- **Cooldown ticks ONLY in `pre_sim`'s ENEMY branch** on the host's sim dt
  (speed-scaled, pause-frozen); never reset by round end or `upgrade`.
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
