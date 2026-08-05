"""Event kinds for the debug telemetry stream — THE CONTRACT AN LLM READS.

Every line of ``<run_id>-events.jsonl`` is one JSON object. Five fields are
stamped on EVERY event by ``DebugRecorder.emit``; the rest are per-kind and
listed below.

Stamped on every event
----------------------
``t``        the event kind (one of the constants in this module).
``round``    ``RunState.round_num`` at emit time. Payday increments it at step
             11, so a ``round_summary`` for round N is emitted while
             ``round == N``; the next ``wave_start`` is ``round == N+1``.
             ``0`` is the tutorial round (TU-9), not a bug.
``phase``    ``RunState.phase.name`` — BUILDING / ENEMY / ROUND_END / LEVELUP /
             BOSS_CUTSCENE / INCOME. ``""`` if no state is bound yet.
``frame``    the host's frame counter, as last set by ``set_frame``. ``0`` in
             headless/logic contexts that never stamp it.
``wall_ms``  milliseconds since the recorder was constructed (monotonic).

Levels
------
Level 0 = off (a recorder is never constructed). Level 1 = the causal trace.
Level 2 adds the per-tick combat detail. ``KIND_LEVEL`` maps each kind to its
minimum level; ``emit`` silently drops a kind above the recorder's level, and
raises ``ValueError`` on an unknown kind (typo guard).

Level-1 kinds and their fields
------------------------------
``run_start``     ``level``, ``run_id``, ``map_id``, ``seed`` (may be null),
                  ``love``, ``lives``.
``wave_start``    emitted from ``end_turn`` as the wave is queued.
                  ``wave_size`` (queued enemy count), ``enemy_tier``,
                  ``composition`` ({etype: count}), ``love``, ``lives``.
                  **The recorder reads ``wave_size`` / ``enemy_tier`` off this
                  event** into the round row — they have no other source.
``place``         a building was placed. ``building_type``, ``col``, ``row``,
                  ``cost``, ``tier``.
``unlock``        a building TYPE was unlocked (level-up card).
                  ``building_type``, ``cost``.
``research``      a tier was researched / advanced. ``building_type``,
                  ``tier``, ``cost``.
``enemy_death``   an enemy died in the field. ``etype``, ``xp``, ``wx``, ``wy``.
``base_hit``      an enemy reached the hole. ``etype``, ``waived`` (true = the
                  tutorial's scripted free loss, which costs NO life),
                  ``lives_after``. **A base hit applies no HP damage** — see
                  "damage taken" below.
``kidnap``        a kidnap-capable enemy carried a building off. ``etype``,
                  ``building_type``, ``col``, ``row``.
``lightning``     a Lightning Strike fired. ``level``, ``damage`` (the FLAT
                  damage applied to each enemy hit), ``hits`` (enemies inside
                  the radius), ``total_damage`` (``damage`` x ``hits`` — this is
                  what ``note_lightning`` accumulates into
                  ``dmg_dealt_lightning``), ``wx``, ``wy``. Damage here earns NO
                  ``RoundStats`` credit — lightning has no shooter.
``payday``        the income phase resolved. ``income_actual``,
                  ``income_potential``, ``upkeep_actual``, ``upkeep_potential``,
                  ``story_income``, ``painter_income``, ``love_end``,
                  ``income_by_type`` / ``upkeep_by_type`` ({building_type: love}).
``round_summary`` the full per-round row — every key in
                  ``metrics.ROUND_FIELDS``, flat. This is the same record that
                  becomes one line of ``-rounds.csv``.
``levelup``       a village level resolved. ``village_level``, ``option``,
                  ``player_xp``.
``boss_choice``   ``boss_num``, ``option`` ("A"/"B"), ``outcome``.
``cheat``         a cheat fired. ``action``, plus whatever the cheat carried
                  (``amount`` / ``round``). **Any cheat sets ``cheated`` = 1 on
                  every round row for the REST of the run** — a cheated run must
                  be visibly tagged or it silently pollutes the balance data.
                  The cheat menu's own **debug-log arm/disarm toggle** reports
                  here too (``action`` ``debug_log_on`` / ``debug_log_off``,
                  with the ``round`` it happened on). That is deliberate on
                  both counts: the ``debug_log_on`` marker is where capture
                  STARTS, so every round before it is missing rather than
                  empty, and latching ``cheated`` says out loud that a
                  part-way-captured run is not clean balance data either.
``game_over``     ``round``, ``kills``, ``buildings_placed``.
``run_end``       ``outcome`` ("game_over" / "quit" / whatever the host passes),
                  ``rounds`` (rows written).

Level-2 kinds
-------------
``enemy_spawn``   **RESERVED — declared, never emitted.** The intended fields
                  are ``etype``, ``col``, ``row``, ``hp``, but nothing calls it:
                  the only place one enemy enters the world is
                  ``Spawner.update``'s pop (``game/enemies/spawner.py``), which
                  has no host seam to reach it and no ``resolve_combat``
                  callback covers it. The per-round count IS recorded — the
                  whole wave is counted at ``wave_start`` via ``note_spawn``, so
                  ``enemies_spawned`` and ``composition`` are complete; only the
                  per-enemy line is missing. Do not "look for" this kind in a
                  stream: its absence is the documented state, not a bug in the
                  run you are reading.
``damage``        one damage application, from ``resolve_combat(on_damage=…)``.
                  ``attacker`` (``BUILDING_TYPE`` / ``ETYPE``, **null when no
                  attacker is credited** — e.g. a homing projectile whose
                  shooter is gone), ``target``, ``dmg``, ``target_hp_after``.
                  The level-1/level-2 cross-check sums only events with a
                  non-null BUILDING attacker: that is exactly the set
                  ``RoundStats.dmg_dealt_this_round`` credits.
``wall_damage``   an enemy spent a hit on a perimeter edge WALL (10E).
                  ``attacker`` (the enemy's ``ETYPE``), ``col``/``row`` +
                  ``col2``/``row2`` — the two tiles the damaged edge sits
                  BETWEEN (a wall spans an edge; it has no single tile) —
                  ``dmg``, ``hp_after`` (``0`` once it broke), ``broke``.
                  A wall is a map-owned ``WallEdge`` with no ``Health`` and no
                  ``RoundStats``, so this damage is credited to NOTHING and
                  appears in no round-row column: it is stream-only, and it is
                  deliberately absent from ``dmg_dealt``'s enemy-side mirror.
``defender_fire`` a defender launched a projectile. ``wx``, ``wy`` — the
                  muzzle-anchored spawn point, which is ALL
                  ``resolve_combat``'s ``on_defender_fire`` callback carries.
                  The shooter and its target are not in that signature and
                  telemetry does not get to widen a gameplay one to reach
                  them. **Beam defenders (Sun Scorcher) never emit this** —
                  they are instant hitscan and fire no projectile; their
                  output shows up as ``damage`` events only.

What the numbers do and do not include
--------------------------------------
**"Damage taken" is two separate things and they are NEVER fused.**
``dmg_taken_buildings`` is HP damage dealt to built occupants (the base
included), read off ``RoundStats``. ``lives_lost`` is base breaches that cost a
life: ``resolve_combat`` returns early once ``on_base_hit`` is supplied
(``combat.py``), so a breach applies **no HP damage at all**. A round can lose
a life with ``dmg_taken_buildings == 0``. ``leaks`` counts every breach,
including tutorial-waived ones; ``lives_lost`` counts only the ones that were
charged.

**Lightning is reported as its own damage source.** It has no shooter, so it
earns no ``RoundStats`` credit and is invisible to ``dmg_dealt``.
``dmg_dealt_lightning`` / ``lightning_hits`` are accumulated separately via
``note_lightning``. ``dmg_dealt + dmg_dealt_lightning`` is the run's true
output; ``dmg_dealt`` alone is the building-credited half.

**Actual vs potential income.** ``run_payday``'s income sweep AND its upkeep
sweep both ``continue`` on ``not alive``, so a building destroyed during the
wave contributes no income and pays no upkeep. Both halves are reported:
- ``income_actual`` — what was really paid, summed from
  ``RunState.income_events``: village-scaled base income + every ALIVE
  building's yield + painter lump-sum payouts.
- ``income_potential`` — village-scaled base income + EVERY built occupant's
  ``yield_amount()`` with the same Boss2A/2B per-recipient deltas the real
  sweep folds in, ignoring ``alive``, PLUS the realised painter payout as a
  pass-through term. A painter's lump sum is banked over many rounds rather
  than produced by this round's yield sweep, and a pure pre-payday read cannot
  know a painter was about to complete — so it is added to BOTH sides at the
  same value. That keeps ``income_lost_to_damage`` a clean measure of yield
  lost to dead buildings on a painter round instead of clamping it to 0 and
  reading as "nothing was lost". Story payouts are in NEITHER side.
- ``income_lost_to_damage`` = ``max(0, income_potential - income_actual)`` —
  the love the player would have had if nothing had died.
- ``upkeep_unpaid_from_deaths`` = ``max(0, upkeep_potential - upkeep_actual)``
  — the bills a dead building did not pay. It partly offsets the lost income.

The potential sweep uses the PURE ``yield_amount()``, never ``collect_income()``:
``collect_income`` resets/advances the Meditator streak, so calling it from
telemetry would move gameplay. For a Meditator, ``income_potential`` therefore
reports its current-streak yield undisturbed.

**``story_income``** (Boss1B/3B) is paid silently and never appears in
``income_events``, so it is measured as the love delta across payday step 3 and
reported on its own. It is NOT part of ``income_actual``.

**Bankruptcy.** ``RunState.add_love``/``spend_love`` clamp at ``>= 0``, so on a
round where upkeep exceeds love, ``upkeep_actual`` is what was BILLED, not
necessarily what was deducted. ``love_end`` is the truth.
"""

# -- level 1: the causal trace ---------------------------------------------
RUN_START = "run_start"
WAVE_START = "wave_start"
PLACE = "place"
UNLOCK = "unlock"
RESEARCH = "research"
ENEMY_DEATH = "enemy_death"
BASE_HIT = "base_hit"
KIDNAP = "kidnap"
LIGHTNING = "lightning"
PAYDAY = "payday"
ROUND_SUMMARY = "round_summary"
LEVELUP = "levelup"
BOSS_CHOICE = "boss_choice"
CHEAT = "cheat"
GAME_OVER = "game_over"
RUN_END = "run_end"

# -- level 2: per-tick combat detail ---------------------------------------
ENEMY_SPAWN = "enemy_spawn"
DAMAGE = "damage"
WALL_DAMAGE = "wall_damage"
DEFENDER_FIRE = "defender_fire"

LEVEL_OFF, LEVEL_BASIC, LEVEL_VERBOSE = 0, 1, 2
LEVELS = (LEVEL_OFF, LEVEL_BASIC, LEVEL_VERBOSE)

#: Every kind -> the minimum recorder level that records it.
KIND_LEVEL = {
    RUN_START: LEVEL_BASIC,
    WAVE_START: LEVEL_BASIC,
    PLACE: LEVEL_BASIC,
    UNLOCK: LEVEL_BASIC,
    RESEARCH: LEVEL_BASIC,
    ENEMY_DEATH: LEVEL_BASIC,
    BASE_HIT: LEVEL_BASIC,
    KIDNAP: LEVEL_BASIC,
    LIGHTNING: LEVEL_BASIC,
    PAYDAY: LEVEL_BASIC,
    ROUND_SUMMARY: LEVEL_BASIC,
    LEVELUP: LEVEL_BASIC,
    BOSS_CHOICE: LEVEL_BASIC,
    CHEAT: LEVEL_BASIC,
    GAME_OVER: LEVEL_BASIC,
    RUN_END: LEVEL_BASIC,
    ENEMY_SPAWN: LEVEL_VERBOSE,
    DAMAGE: LEVEL_VERBOSE,
    WALL_DAMAGE: LEVEL_VERBOSE,
    DEFENDER_FIRE: LEVEL_VERBOSE,
}

#: ``note_love_spent`` reasons. The round row's ``buildings_placed`` counts
#: ``SPEND_PLACE`` calls; ``love_spent_buildings`` sums ALL of them.
SPEND_PLACE = "place"
SPEND_UNLOCK = "unlock"
SPEND_RESEARCH = "research"
SPEND_REASONS = (SPEND_PLACE, SPEND_UNLOCK, SPEND_RESEARCH)
