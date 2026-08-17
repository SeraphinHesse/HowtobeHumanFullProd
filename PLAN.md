<!-- active-plan: BossUpgradeTimelinePLAN.md | set: 2026-08-17 -->
> **Active plan:** BossUpgradeTimelinePLAN.md (mirror). Source of truth:
> `planning/BossUpgradeTimelinePLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: IN PROGRESS -->
<!-- plan-scale: large -->

# BossUpgradeTimelinePLAN.md — boss-fight upgrade choice, timeline-authored

Phased, agent-executable plan (same family as `TimelinePLAN.md` /
`BossReworkPLAN.md`). Base branch: `Development`. This work happens on
`feature/boss-upgrade-timeline` (already branched off `origin/Development`).

## 1. Vision

Today, after a boss fight (every 10 rounds), the player sees a win/lose
narrative "A/B story bonus" cutscene (`game/ui/boss_cutscene.py`) backed by
`game/core/boss_bonuses.py`'s six hidden income/damage effects, and on a loss
automatically receives a per-era "consolation love" reward already wired
end-to-end (`RunState.add_love` via `Session._boss_loss_reward`, amount from
`enemies.json`'s `EnemyTypes.Boss.stats[era].loss_love_reward`).

This plan replaces it with a **Boss Upgrade Timeline**: a designer-authored,
editor-configurable system mirroring the existing building-upgrade Timeline
(`TimelinePLAN.md` — `data/balancing/progression.json` +
`game/core/levelup.py` + `editor/panels/timeline.py`) but for boss upgrades —
direct-slotted (no random pool), 4 authored milestones that cycle every 4th
bossfight, always 3 options per milestone, each of 12 upgrades editable
(name/description/numeric params) and each usable in only one milestone slot.
The existing per-boss retaliation-love reward moves into this same timeline
as a 4-cycle table, replacing the `enemies.json` field. This is a large
feature — a new data domain, a new "boss upgrade applies a lasting run
effect" engine touching ~10 files across `game/buildings/`, `game/enemies/`,
`game/core/`, `game/map/`, `game/ui/`, plus a new bespoke editor panel.

### Confirmed design decisions (settled with the user — do not re-litigate)

- **D1 — Cycle.** Exactly 4 authored milestones. `milestone_index =
  (boss_num - 1) % 4` — boss 5 repeats milestone 1 verbatim, forever.
  Decoupled from the existing 5-era `enemies.json` enemy-stat scaling
  (untouched).
- **D2 — Slots.** Always exactly 3 shown per milestone. No randomization —
  direct designer assignment via drag-and-drop, mirroring the building
  Timeline's `assign_slot`.
- **D3 — Uniqueness.** Each of the 12 catalog upgrades may be placed into at
  most one milestone slot across the whole timeline (authoring-time
  constraint, `validate_uniqueness`) — this is what "seen once" means, NOT
  "consumed after picked". The same milestone always re-offers the identical
  3 options on every repeat.
- **D4 — Free re-pick, additive stacking.** The player freely picks 1 of 3 at
  every bossfight, independent of prior picks. Persistent %-based effects
  picked more than once (via repeats) **stack additively**. One-time effects
  simply re-trigger (idempotent).
- **D5 — Cutscene fully replaced.** `boss_cutscene.py`'s old A/B narrative
  pick is deleted; the 3 upgrade cards ARE the new cutscene content, on both
  win and loss.
- **D6 — Old boss-bonus system fully retired.** `game/core/boss_bonuses.py`'s
  six effects (dmg-per-unbuilt-tile, dmg-per-building, love-per-level,
  love-per-low-level-building, dmg-per-love-chunk, dmg-per-lightning-building),
  `RunState.boss_stacks`, the payday slot-3 `love_bonus_income` call (slot
  ORDINAL position stays, becomes a documented no-op — payday order is
  sacrosanct), and HUD's "Story" income row are all removed.
- **D7 — Retaliation bonus.** Moves into the new timeline as **4 cyclic
  values** (one per milestone, same `(boss_num-1)%4` cycle), edited from the
  new panel, becoming the sole source of truth. `enemies.json`'s
  `loss_love_reward` field/mechanism is retired; `Session._boss_loss_reward`
  is rewired. Still paid only on a loss, still via `RunState.add_love` (the
  existing, reused API). Seed data: placeholder progression (e.g.
  30/60/100/150 love) — the user tunes exact numbers in the new panel
  afterward.
- **D8 — Storage.** ONE new file `data/balancing/boss_upgrades.json` +
  `data/schemas/boss_upgrades.schema.json`. Catalog = 12 **fixed named keys**
  (not an open array — each requires bespoke code anyway), each with editable
  `name`, `description`, `params`. Timeline = 4 milestones × 3 slots
  (nullable upgrade-id references) + `retaliation_bonus_love` per milestone.
  Registered as a new balancing domain exactly like `progression`
  (`game/core/balance.py::DOMAINS`, `Session`, `game/main.py`,
  `tools/simrun.py`).
- **D9 — Card art.** Text-only. No icon/art pipeline for boss upgrade cards,
  editor or in-run.
- **D10 — Editor overwrite.** Drag-drop onto an occupied slot silently
  overwrites (matches the building Timeline's `assign_slot`, no
  confirmation).
- **D11 — Editor panel placement.** New top-level **"Bosses"** category
  (sibling to "buildings", not nested under it) in the selector tree.
- **D12 — Musician auto-level scope** (upgrade #5). Musician tier line only
  (Flute Player → Harp Player → Trio), not all buildings.
- **D13 — Thorns scope** (upgrade #8). Triggers on both building hits AND
  wall hits.
- **D14 — Move-cost cap** (upgrade #4). Caps the **time** cost dial (the one
  actually enabled today; love cost stays off).
- **D15 — Tile-condition dmg bonus scope** (upgrade #11). Any non-Grass
  condition (Mountain/Pond/Forest) — Grass never counts.
- **D16 — Mortar-slow scope** (upgrade #3). Snapshot semantics — only
  mortars alive at pick-time get slow-on-hit; mortars built afterward do
  not. Duration defaults to 2.5s (matching Stormpriest's).
- **D17 — Stone-thrower sync** (upgrade #9). One-time only, no ongoing
  re-sync rule.
- **D18 — Boost double-trigger** (upgrade #10). Permanent global rule —
  applies to boost buildings placed before AND after the pick.
- **D19 — Shared slow-debuff infrastructure** (needed for #3 and #7).
  **Extend the existing `BuffState`** (`game/enemies/components.py` — today
  the Drummer's ally-buff aura) to also accept building-sourced entries,
  rather than building a parallel mechanism. Read its full implementation
  before touching it.
- **D20 — Red debuff arrow (new requirement).** Mirroring the existing gold
  "buff arrow" indicator (`game/ui/effects.py::submit_buff_arrows`,
  `BUFF_ARROW_SLOT = "vfx_buff_arrow"`, a small procedural gold triangle
  drawn above any alive enemy with `BuffState.sources` non-empty, swappable
  via imported art), add a parallel **red debuff arrow** for any enemy
  carrying an active negative (slowing) `BuffState` contribution. New
  `DEBUFF_ARROW_SLOT = "vfx_debuff_arrow"` + `_DEBUFF_ARROW_RED` color
  constant beside `_BUFF_ARROW_GOLD`; new `submit_debuff_arrows` method
  mirroring `submit_buff_arrows`'s structure exactly (same anchor-point
  logic, same art-vs-procedural-triangle fallback) but keyed on a
  **negative** aggregate `move_speed` contribution. `submit_buff_arrows`
  itself narrows to a **positive** contribution so the two read as
  mutually distinct (gold = real buff, red = slow), stacking vertically if
  an enemy is somehow both. Wired in `game/main.py` beside the existing
  call. New slot registered in `data/slots.json`'s vfx category + the vfx
  schema, same site as `vfx_buff_arrow`.
- **D21 — Branch.** `feature/boss-upgrade-timeline`, off `Development`
  (done).

All of the above was verified against the current repository state before
this plan was written — `data/schemas/progression.schema.json`,
`data/balancing/progression.json`, `game/core/levelup.py`,
`editor/panels/timeline.py`, `editor/timeline_ops.py`, `engine/era_math.py`,
`game/core/session.py`, `game/core/game_state.py`, `game/ui/boss_cutscene.py`,
`game/ui/effects.py`, `game/buildings/building.py`,
`game/buildings/movement.py`, `game/buildings/registry.py`,
`game/buildings/musician.py`, `game/buildings/defender.py`,
`game/buildings/aoe_defence.py`, `game/enemies/combat.py`,
`game/enemies/components.py`, `game/core/lightning.py`,
`game/core/payday.py`, `game/map/tile_map.py`, and `game/ui/building_ui.py`
were all directly read or scouted to confirm exact current shapes.

## 2. The 12 boss upgrades (id — effect type — params — hook)

1. **`restock_lives`** — ONE-TIME. Sets `RunState.base_lives` back to
   `core.json`'s `TheHole.base_lives`. No params.
2. **`wall_cost_discount`** — PERSISTENT, stacks, floor-clamped to a minimum
   of 1. Param `cost_reduction_pct` (default 50). Hooks
   `Building.build_cost()`/`upgrade_cost()`, scoped to `Blocker`/
   `WallBuilder` only.
3. **`mortar_slow`** — PERSISTENT, snapshot-scoped to mortars alive at
   pick-time. Params `slow_pct` (20), `duration_seconds` (2.5). Hook:
   `combat.py`'s `_fire_splash`, via the extended `BuffState`.
4. **`move_time_cap`** — PERSISTENT, global. Param `move_time_cap` (1). Hook:
   `move_time()`'s `_stepped()` helper — caps the TIME dial.
5. **`musician_auto_level`** — PERSISTENT, global, Musician line only. Param
   `bonus_levels` (1). Hook: `registry.place_building()`, driven through the
   normal "advance one level" path.
6. **`tile_discount`** — PERSISTENT, stacks. Param `discount_pct` (20). Hook:
   `TileMap.unlock_cost()`.
7. **`stormpriest_slow`** — PERSISTENT, global, live (no snapshot). Params
   `slow_pct` (20), `duration_seconds` (2.5). Hook: `lightning.py`'s
   `strike()`, right after damage applies, same extended `BuffState`.
8. **`thorns`** — PERSISTENT, stacks, buildings AND walls. Param
   `reflect_pct` (10). Hooks: `EnemyCombat.update()`, both branches.
9. **`stone_thrower_sync`** — ONE-TIME. No params. Sweeps all placed
   `Defender` instances, levels every non-max one up to match the highest.
10. **`boost_double_trigger`** — PERSISTENT, global. Param `extra_triggers`
    (1). Hook: `_process_boosts` calls `apply_per_turn()` an extra time
    within the same slot-7 step; doubles the `boost_events` push.
11. **`condition_dmg_bonus`** — PERSISTENT, stacks. Param `dmg_bonus_pct`
    (20). New wiring reading the TARGET enemy's own tile condition.
12. **`tile_refund`** — ONE-TIME. No params. Pays back
    `RunState.love_spent_on_tiles` (new accumulator) via `state.add_love`.

## 3. Build order

| Phase | Scope | Status |
|---|---|---|
| BU-0 | Branch | done |
| BU-1 | Data layer — schema, content, domain registration | pending |
| BU-2 | RunState + effect-engine skeleton | done |
| BU-3 | Effect-engine hook wiring (12 upgrades + debuff arrow) | pending |
| BU-4 | Boss cutscene UI + Session rewire; retire boss_bonuses | pending |
| BU-5 | Editor panel | pending |
| BU-6 | Tests | pending |
| BU-7 | Docs | pending |

---

### BU-1 — Data layer

**Goal.** Stand up the new balancing domain: schema, seed content, domain
registration, `Session` wiring.

**Files.**
- `data/schemas/boss_upgrades.schema.json` (new) — `Catalog`: 12 fixed named
  keys (`additionalProperties: false`), each `{name, description, params:
  {...}}`. `Timeline.milestones`: fixed-length-4 array, each `{slots: [id|
  null, id|null, id|null], retaliation_bonus_love: int}`.
- `data/balancing/boss_upgrades.json` (new) — all 12 upgrades seeded with §2's
  defaults; 4 milestones each assigning 3 distinct upgrade ids (no repeats
  across the whole timeline) + placeholder retaliation values (e.g.
  30/60/100/150).
- `game/core/balance.py` — add `"boss_upgrades"` to `DOMAINS`.
- `game/core/session.py` — `Session.__init__`/`Session.create` grow an
  optional trailing `boss_upgrades_balance=None` param, stored as
  `self.boss_upgrades_balance` (the `progression_balance` shape).
- `game/main.py`, `tools/simrun.py` — load + thread it in, beside the
  existing `progression_balance` load.

**Verify.** `py tools/smoke.py`.

### BU-2 — RunState + effect-engine skeleton

**Goal.** Minimal new `RunState` ledgers, and `game/core/boss_upgrades.py`
(pure, no `game.buildings`/`game.enemies` imports — mirrors
`boss_bonuses.py`'s discipline) as the one place that knows "which upgrade
ids exist" and "how many times has each been picked".

**Files.**
- `game/core/game_state.py` — `RunState` grows: `boss_upgrade_stacks: dict`
  (`{upgrade_id: pick_count}`), `love_spent_on_tiles: int = 0`,
  `mortar_slow_snapshot_ids: set`, `boss_upgrade_choices: list`
  (`(boss_num, upgrade_id, outcome)`, replaces `boss_choices`).
- `game/core/boss_upgrades.py` (new) — `milestone_index(boss_num)`,
  `milestone_slots(balance, boss_num)`, `retaliation_love(balance,
  boss_num)`, `stack_count(state, upgrade_id)`, and `apply_pick(state,
  upgrade_id, boss_upgrades_balance, core_balance, tilemap=None,
  scene=None)` — increments the stack dict; performs the immediate side
  effect in-line for the three ONE-TIME upgrades (#1, #9, #12).

**Verify.** `py tools/smoke.py`; grep-confirm `boss_upgrades.py` imports
nothing from `game.buildings`/`game.enemies`.

### BU-3 — Effect-engine hook wiring

**Goal.** Wire each catalog upgrade's real effect at its hook point(s),
magnitudes always read via `stack_count`, never hardcoded.

**Sub-tasks.**
- 3.1 One-time (#1, #9, #12 — mostly inside `apply_pick`; #12's accumulator
  hook sits in `building_ui.py`'s `_unlock_click`, incrementing
  `state.love_spent_on_tiles` alongside `st.spend_love(chunk_cost)`).
- 3.2 Simple persistent passives (#2, #4, #5, #6) — optional trailing
  `run_state=None` param on `Building.build_cost()`/`upgrade_cost()`,
  `move_time()`'s `_stepped()`, `registry.place_building()`; thread through
  their real call sites (`building_ui.py` price displays/click handlers,
  `payday.py` move processing).
- 3.3 Shared slow-debuff infra, then #3 and #7 — first read `BuffState`'s
  full implementation and confirm widening its per-source model is safe.
  #3 snapshots mortar ids at pick-time; #7 applies live, unconditionally.
  **Also D20** (red debuff arrow) here: `game/ui/effects.py`'s
  `submit_debuff_arrows` + constants, `submit_buff_arrows` narrowed to
  positive-only, both wired in `game/main.py`; new `vfx_debuff_arrow` slot
  in `data/slots.json` + vfx schema.
- 3.4 Thorns (#8) — both branches of `EnemyCombat.update()`.
- 3.5 Tile-condition target damage bonus (#11) — read `combat.py`'s full
  damage-finalization call graph first so the multiply applies exactly once
  per hit.
- 3.6 Boost double-trigger (#10) — `_process_boosts`, extra
  `apply_per_turn()` call(s) inside the existing slot-7 step.

**Files.** `game/buildings/building.py`, `game/buildings/movement.py`,
`game/buildings/registry.py`, `game/map/tile_map.py`,
`game/enemies/components.py`, `game/enemies/combat.py`,
`game/core/lightning.py`, `game/core/payday.py`, `game/ui/building_ui.py`,
`game/ui/effects.py`, `game/main.py`, `data/slots.json`, the vfx schema.

**Verify.** `py tools/smoke.py`. Practical verification of most sub-tasks
waits for BU-4 (no UI to pick an upgrade before then) — treat BU-3+BU-4 as
one dev/verify cycle.

### BU-4 — Boss cutscene UI + Session rewire; retire boss_bonuses

**Goal.** Replace the A/B narrative picker with the 3-card upgrade picker,
re-point retaliation-love at the new table, retire the old bonus system.

**Files.**
- `game/ui/boss_cutscene.py` — 3 boxes instead of 2, sourced from
  `boss_upgrades_balance["BossUpgrades"]["Catalog"][id]["name"/
  "description"]` (live-formatted with `params`) for `milestone_slots`.
  `hit()` returns the picked `upgrade_id`. Constructor gains
  `boss_upgrades_balance`.
- `game/core/session.py` — `_boss_loss_reward` → `boss_upgrades.
  retaliation_love(self.boss_upgrades_balance, era + 1)`.
  `resolve_boss_cutscene` calls `boss_upgrades.apply_pick(...)`;
  `boss_choices` → `boss_upgrade_choices`.
- **Retire (D6)**: `game/core/boss_bonuses.py`, `RunState.boss_stacks`, the
  payday slot-3 `love_bonus_income` call (leave the ordinal slot as a
  documented no-op), `hud.py`'s "Story" income row.
- `game/ui/building_ui.py`'s `_submit_boss_popup` — reword rows to
  `f"Boss {n}: {outcome} — {catalog[option]['name']}"`.
- `tools/simrun.py`'s headless boss-cutscene auto-resolution — pick one of
  the 3 offered ids deterministically.

**Verify.** Live `py game/main.py` through one full boss win (3-card pick,
effect visibly applied) and one loss (retaliation banner + payout, still a
card is picked); `py tools/smoke.py`.

### BU-5 — Editor panel

**Goal.** New "Bosses" top-level category with a Boss Upgrade Timeline panel:
catalog browse list with inline editable name/description/params,
drag-and-drop into a 4×3 milestone grid, silent overwrite, per-milestone
retaliation field.

**Files.**
- `editor/boss_upgrades_ops.py` (new, pure, in `TestPurity`) —
  `load_boss_upgrades`/`save_boss_upgrades` (through `write_validated`),
  `assign_slot`, `clear_slot`, `set_retaliation_love`, `set_catalog_field`
  (name/description/params — new capability), `placements`,
  `validate_uniqueness`.
- `editor/panels/boss_upgrades.py` (new, `BossUpgradesPanel`) — browse list
  of 12 catalog cards, inline edit form, drag-drop onto 4×3 grid, text-only
  cards.
- `editor/panels/selector.py` — new top-level "Bosses" category, one leaf,
  `boss_upgrades_selected` signal.
- `editor/main.py` — wire panel into `right_stack`, connect signal,
  `_on_boss_upgrades_selected`.

**Verify.** `py -m pytest tools/tests/test_editor_viewport.py::TestPurity -q`
(both new modules added to the purity list); live `py editor/main.py` —
select Bosses ▸ Boss Upgrade Timeline, edit, drag, save, reload, `py
tools/smoke.py`.

### BU-6 — Tests

**Goal.** Cover the new domain, engine, hooks, UI, editor ops; replace the
test pinning the retired `enemies.json` loss-reward mechanism.

**Files.** `tools/tests/test_boss.py` (rework
`test_loss_pays_this_eras_consolation_love`), new
`tools/tests/test_boss_upgrades.py`, extend hook-site test files (building
cost, movement, registry, tile_map, combat/components incl. debuff arrow,
payday, building_ui), rework whatever covers `boss_cutscene.py`'s old A/B
behavior, new `tools/tests/test_editor_boss_upgrades.py` + `TestPurity`
append, remove/retarget the old `boss_bonuses.py` test coverage.

**Verify (role-scoped).** Targeted `py -m pytest tools/tests/test_boss*.py
tools/tests/test_editor_boss_upgrades.py -q` + `py tools/smoke.py`. The
single full `py tools/testgate.py check` is the MAIN SESSION's job at
`/commitpushpr` handoff — never mid-task.

### BU-7 — Docs

**Goal.** Update every package doc this feature touches.

**Files.** `data/CLAUDE.md`, `game/core/CLAUDE.md`, `game/buildings/CLAUDE.md`,
`game/enemies/CLAUDE.md`, `game/ui/CLAUDE.md`, `editor/CLAUDE.md`,
`editor/panels/CLAUDE.md`.

**Verify.** Re-read each touched section against the final implementation.

---

## 4. Critical files

`data/schemas/boss_upgrades.schema.json`, `data/balancing/boss_upgrades.json`
(new); `game/core/boss_upgrades.py` (new), `game/core/game_state.py`,
`game/core/session.py`, `game/core/balance.py`; `game/ui/boss_cutscene.py`,
`game/ui/effects.py`, `game/ui/building_ui.py`, `game/main.py`;
`game/buildings/building.py`, `game/buildings/movement.py`,
`game/buildings/registry.py`, `game/buildings/defender.py`;
`game/enemies/components.py`, `game/enemies/combat.py`,
`game/core/lightning.py`, `game/core/payday.py`; `game/map/tile_map.py`;
`editor/boss_upgrades_ops.py`, `editor/panels/boss_upgrades.py` (new),
`editor/panels/selector.py`, `editor/main.py`.

## 5. Verification (whole feature)

- `py tools/smoke.py` after every phase.
- Targeted `py -m pytest tools/tests/test_boss*.py
  tools/tests/test_editor_boss_upgrades.py -q` once BU-6 exists.
- Live `py game/main.py`: reach a boss fight, confirm 3 text-only cards
  show, pick one, confirm its effect is visibly active; reach a repeat
  (boss 5) and confirm the same 3 options reappear; lose a boss fight and
  confirm the retaliation-love banner + payout.
- Live `py editor/main.py`: Bosses ▸ Boss Upgrade Timeline — edit, drag,
  save, reload.
- Full `py tools/testgate.py check` — main session only, once, at
  `/commitpushpr` handoff.
