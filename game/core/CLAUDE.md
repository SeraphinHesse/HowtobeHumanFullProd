# CLAUDE.md — game/core (Phases 9F + 10A)

The round machine + economy + progression, porting the prototype's
`Game._update_gameplay` / `_begin_enemy_phase` / `_begin_round_end` /
`_begin_income_phase` / `_award_xp` / `_roll_levelup_options` / `_resolve_levelup`.
You reached here from `game/CLAUDE.md`. All pure logic (no pygame — a `TestPurity`
guards it). When you change core conventions, update THIS doc.

`balance.py` is the single validated balancing loader for all five domains
(`load_balance(data_dir, domain)`).

## Round loop (Phase 9F)
Four files beside `balance.py`:
- **`phases.py`** — `GamePhase` (BUILDING/ENEMY/ROUND_END/LEVELUP/INCOME driven now
  — LEVELUP since 10A; BOSS_CUTSCENE declared at its prototype ordinal but never
  entered — 10G) and `GameState` (GAMEPLAY/GAME_OVER; menu states 9H).
- **`game_state.py`** — `RunState` dataclass: the single owner of `phase`, `state`,
  `round_num` (starts 1, `++`'d in payday — prototype numbering), `love`,
  `base_lives`, `phase_timer`, run stats. `from_balance(core)` seeds it;
  `add_love`/`spend_love` clamp at ≥0 (prototype clamps every currency write).
- **`payday.py`** — `run_payday(state, tilemap, core, occupancy=None, scene=None)`
  mirrors `_begin_income_phase` **step for step; the ordering is SACROSANCT**. 9F
  drives: snapshot RoundStats (this→last) → base income + duck-typed `yield_amount`
  sweep → duck-typed `upkeep` sweep (clamp 0) → **[slot 6: Painter payout]** →
  revive sweep (`rebuild()` on non-base, base excluded) → round++ → phase=INCOME.
  The remaining reserved no-op slot (boss-bonus, slot 3) stays in place for 10G.
  **Do not reorder without the user.**
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

## Names write (9H)
`game/core/names.py append_random_name` persists the add-name menu's typed name to
`buildings.json` `BuildingsGlobal.random_names` via `write_validated` — the one
runtime data write (disk I/O stays out of pygame-pure `game/ui`).

## Verify
Phase-machine unit tests; headless 3-round currency ledger matches
prototype-computed values: `py -m unittest discover -s tools/tests -t .`. Live
`py game/main.py` for phase/combat behavior.
