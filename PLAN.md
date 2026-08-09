<!-- active-plan: TimelinePLAN.md | set: 2026-08-09 -->
> **Active plan:** TimelinePLAN.md (mirror). Source of truth:
> `planning/TimelinePLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: IN PROGRESS — phase T1 next -->

# TimelinePLAN.md — authored building unlock scheduling

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. This work happens on
`feature/timeline-unlock-scheduling` (already branched off `origin/Development`)
to avoid conflicting with unrelated in-flight branches.

## 1. Vision

Today, "when a building becomes available to research" lives as a scattered
per-tier `unlock_min_round` field across 12 building-type groups in
`data/balancing/buildings.json` (36 tier objects total). To find or change
when any given building unlocks, a developer opens the editor's balancing
form and scrolls through a deep per-building schema tree — there is no
single place that shows the whole unlock schedule at a glance, and no way to
see how one edit reshapes the overall pacing.

Separately, the level-up mechanic that surfaces these unlocks to the player
(`game/core/levelup.py::roll_levelup_options`) is a live stochastic roll: it
walks every building type, collects whatever currently passes its
round/village-level gate, shuffles, and shows exactly 3 cards (padding with
"+Love" filler if fewer qualify). There's no way to *see*, as a designer,
what that pool looks like at a given point in the game, or to deliberately
curate "this level-up should be able to offer these three specific things."

**Timeline** fixes both: one visual, horizontal editor panel (round 0 →
round 50, scrollable/zoomable beyond that) where every building's
unlock/tier-upgrade card is drag-and-drop placed into an "offer slot"
attached to a specific player level-up (identified by `village_level`, the
existing 1/2/3/… counter). Placing a card there is what makes it *eligible*
to be rolled at that level-up onward — replacing `unlock_min_round` as the
single source of truth for unlock timing, while leaving the random
roll-of-3 mechanic untouched. A computed graph overlay shows, for each
level-up, the best-case (upper-bound) round at which it would occur,
computed live from the game's real enemy-count formulas and XP values — not
a hand-placed guess.

### Confirmed design decisions (do not re-litigate)

1. **Architecture split**: `editor/` owns the new drag-and-drop authoring UI
   and writes new schema-validated `data/` JSON; `game/`/`engine/` read it
   at runtime.
2. **Tiers are real and placeable**: both a building type's initial *unlock*
   card and each subsequent *tier-upgrade* card (e.g. Stone Thrower →
   Slinger) are placeable — matching the existing two-offer-kind model in
   `game/buildings/research.py`/`game/core/levelup.py`.
3. **Level-ups stay XP/kill-triggered.** `game/core/xp.py`'s trigger is
   untouched. The timeline's round-axis position for a level-up is a
   *computed reference*, never a hard schedule.
4. **The graph is a deterministic best-case formula**: assume every enemy
   spawned in a round is killed (enemy counts per round are already a
   closed-form, non-random formula in `engine/era_math.py`). Must be clearly
   labeled as a best-case/upper-bound curve in the UI.
5. **The random roll-of-3 stays exactly as-is** — Timeline slots only
   curate the *eligible pool*; no change to `OPTION_COUNT`, the shuffle, or
   the "+Love" fallback padding.
6. **Timeline data replaces `unlock_min_round`** as the sole source of
   unlock timing — deleted from schema and content once the runtime read
   path is repointed, after a reviewed migration seeds the new data.
7. **Slots are indexed by `village_level`** (`RunState.village_level`) — not
   by round.
8. **Terminology**: `data/slots.json` is the unrelated sprite/asset slot
   registry. This feature's "slot" uses different vocabulary ("offer slot")
   and does not touch `data/slots.json`.
9. Slot cardinality per level-up is dynamic/editable directly in the
   Timeline UI, not fixed.

All of the above, plus every file/line reference below, was verified against
the current repository state — `game/core/levelup.py`,
`game/buildings/research.py`, `engine/era_math.py`, `game/core/xp.py`,
`data/schemas/{core,buildings}.schema.json`, `editor/domains.py`,
`game/core/balance.py`, `tools/smoke.py`, and `game/buildings/defender.py`
were all directly read to confirm exact current shapes before this plan was
written.

## 2. Architecture / decisions (with rationale)

- **D1 — New standalone balancing domain, `progression`.**
  `data/balancing/progression.json` + `data/schemas/progression.schema.json`,
  added to `game/core/balance.py::DOMAINS` (currently `("buildings",
  "enemies","map","ui","core","vfx")`) for runtime loading. **Deliberately
  NOT added as a `data/slots.json` category** — `editor/domains.py::
  domains()` derives its auto-rendered selector/balancing-panel list as
  *slots.json categories ∩ balancing files*; Timeline needs a bespoke
  drag-and-drop widget, never a generic recursive form, so it must not also
  auto-render as one. `tools/smoke.py`'s generic stem-pairing walk
  (`data/foo.json` ↔ `schemas/foo.schema.json`, `tools/smoke.py:25-61`)
  picks the new pair up for free — `progression` is not one of its four
  named stem-pairing exceptions (map / balancing_history / agent_forms /
  screen overrides).
- **D2 — The Timeline panel is a selector-tree leaf under "buildings"**
  (corrected mid-T5, user-confirmed — originally planned as a toolbar
  button; see the note under the build-order table). Edit model mirrors
  `editor/panels/balancing.py`'s staged-dict + dirty-dot + explicit Save
  pattern (no `QUndoStack`).
- **D3 — `buildings.json` gains two new required fields per building-type
  group**: `building_type` (the `RESEARCH`/`tiers_unlocked` key, e.g.
  `"defence"`) and `card_slots` (array of exactly 3 asset-slot keys, one per
  tier). These exist ONLY in Python today (`BUILDING_TYPE`/`TIER_SPRITES`
  class attributes, confirmed in `game/buildings/defender.py:11,13` and all
  12 leaf classes) with no JSON equivalent — the editor may never import
  `game/`, so it cannot enumerate building types or resolve card art
  without this addition. Mirrors the existing `registry_group` precedent.
  Seeding is mechanical transcription from the 12 leaf files.
- **D4 — `unlock_min_round` is deleted from schema + content**, not merely
  ignored — confirmed required in all 10 tier `$defs` in
  `data/schemas/buildings.schema.json` and present on all 36 tier objects in
  `data/balancing/buildings.json`.
- **D5 — `upgrade_gate`'s second consumer is re-keyed to a village_level,
  not a round.** `game/core/levelup.py::upgrade_gate`'s `tier_hidden` mode
  is read by `game/ui/building_ui.py`'s `_upgrade_state` to format
  `"Unlocks at round {cost}"` in the live in-game upgrade panel. Instead:
  `game/buildings/research.py` gains `timeline_level_for(btype, idx,
  progression_balance) -> int | None`; `upgrade_gate`'s `tier_hidden` branch
  returns that village_level directly; the one `building_ui.py` f-string
  becomes `"Unlocks at level {cost}"` (or "Not yet offered" when `None`).
  Only `game/ui` text change this plan requires.
- **D6 — The `gate_kind="min_village_level"` stacked gate** (Maw Mortar,
  Cave Painter's `unlock_min_village_level`) is untouched — a different,
  orthogonal gate from the round gate this plan replaces.
- **D7 — The best-case curve calculator is vocabulary-free in `engine/`**,
  with a small duplicated vocabulary adapter in `game/core/` and `editor/` —
  mirroring `engine/era_math.py`'s own discipline and the two
  already-precedented duplication cases in this repo (`editor/vfx_params.py`
  ↔ `game/ui/effects.py`; `editor/panels/_screen_primitives.py` ↔ `game/ui`'s
  widget look). A cross-package drift test pins the two vocabulary tables
  together (the `TestRegistryGroupDrift` pattern).
- **D8 — Boost-trio grouping is untouched** — only the lead type's Timeline
  placement is consulted for the shared "unlock all three" card; the UI
  should visually pin the two non-lead members when the lead is placed
  (should-have UX affordance, not a new mechanism).

### Data model

`data/balancing/progression.json` / `data/schemas/progression.schema.json`.
Top-level `Timeline.levels`: a sparse array of per-`village_level` records,
house schema style (`additionalProperties:false`, full `required`, bounded
numerics, no `oneOf`):

```json
{
  "Timeline": {
    "levels": [
      {
        "village_level": 1,
        "offer_slots": [
          {"assignment": {"kind": "unlock", "building_type": "storm_priest", "tier_index": 0}},
          {"assignment": {"kind": "unlock", "building_type": "wall_builder", "tier_index": 0}},
          {"assignment": {"kind": "unlock", "building_type": "blocker", "tier_index": 0}}
        ]
      },
      {
        "village_level": 4,
        "offer_slots": [
          {"assignment": {"kind": "tier", "building_type": "defence", "tier_index": 1}},
          {"assignment": null}
        ]
      }
    ]
  }
}
```

- `village_level`: integer [1,1000] (repo's existing bounds policy; 50 is
  only the UI's initial view range, never a data cap).
- `offer_slots`: `minItems:0`, no `maxItems` (dynamic cardinality) — an
  empty, persisted slot (`assignment: null`) is a legitimate saved state.
- `assignment` (nullable object): `{kind: enum["unlock","tier"],
  building_type: string, tier_index: integer[0,2]}` — all three keys always
  present even when unused. No `oneOf`.
- `village_level` uniqueness across `levels`, and `(building_type,
  tier_index)` uniqueness across the whole Timeline, are beyond JSON Schema
  — enforced by the editor's pure ops helper before every write, and by a
  runtime loader cross-check that fails loud on violation.

### Runtime read path

- `game/buildings/research.py`: delete `tier_unlock_min_round`; add
  `timeline_level_for(btype, idx, progression_balance) -> int | None`.
- `game/core/levelup.py`: `tier_offerable`, `roll_levelup_options`,
  `upgrade_gate` all gain/thread a `progression_balance` parameter; the
  shuffle/take-3/fallback-pad logic in `roll_levelup_options` stays
  byte-identical — only pool membership changes.
- Call-site ripple: `game/core/session.py` (`Session.__init__`/
  `resolve_levelup` thread `progression_balance`, loaded in `game/main.py`'s
  boot sequence via `game.core.balance.load_all`); `game/ui/building_ui.py`'s
  `upgrade_gate(...)` call + its one f-string; `tools/tests/test_levelup.py`,
  `tools/tests/test_boost.py` fixtures.

### Best-case XP-curve calculator

- `engine/xp_curve.py` (new, pure, stdlib-only, built on `engine.era_math`):
  `enemy_counts_for_round`, `boss_round_counts` (mirrors
  `game/enemies/spawner.py::_boss_round`'s fallback-past-era-4 behavior),
  `cumulative_best_case_xp(round_range,...) -> dict[round,cum_xp]`,
  `threshold_crossing_rounds(...) -> dict[village_level, round|None]`. Type
  keys are opaque.
- `game/core/xp_curve.py` (new, vocabulary adapter): `threshold_sequence`
  reproduces `xp.py::advance_village_level`'s threshold walk read-only
  (ships the documented 50/65/85/110/140… curve); `best_case_curve` builds
  the vocabulary from `enemies_balance["EnemyTypes"]` + `core_balance["XP"]`
  (promote `xp.py`'s private `_XP_KEY` to `XP_KEY_FOR_ETYPE`) and calls into
  `engine.xp_curve`.
- `editor/timeline_curve.py` (new, pure, Qt-free, the deliberately
  duplicated adapter — reads `data/balancing/{core,enemies}.json` directly,
  never imports `game/`). Registered in `TestPurity`. A cross-package test
  asserts byte-identical output vs. `game/core/xp_curve.py` on the same
  fixture.

### The editor panel

`editor/panels/timeline.py` (`TimelinePanel`, new):
- **Graph strip**: round axis with tick marks at each `village_level`'s
  computed best-case round, labeled `"Lv N ~round R"`, an always-visible
  "best-case / upper bound" legend, the raw cumulative-XP curve line.
- **Offer-slot rows**: one per `village_level` record, square drop-target
  buttons per `offer_slots[i]` plus `+`/`−` to append/remove a trailing
  empty square, an "Add level" affordance. Filled squares render via the
  SAME injected icon-provider pattern `editor/panels/palette.py` uses
  (`viewport.slot_qimage(slot_key)`), resolving `card_slots[idx]`.
- **Browse list**: one row per `building_type` (enumerated live, never
  hardcoded), expandable to its up to 3 cards, draggable via the same
  `slot_qimage` provider, greyed once placed.
- **Drag-and-drop — genuinely new ground** (zero existing `QDrag`/
  `QMimeData` usage anywhere in `editor/`). Custom-MIME payload
  `(kind, building_type, tier_index)`; dropping onto an occupied slot
  replaces it unconditionally (no confirm dialog). All gesture-recognition
  code stays Qt-boundary-only; every mutation goes through:
- **`editor/timeline_ops.py`** (new, pure, `engine.data_io`-only, in
  `TestPurity`): `load_progression`, `assign_slot`, `clear_slot`,
  `add_slot`, `remove_slot`, `add_level`, `remove_level`,
  `save_progression` (the one `write_validated` call, cross-checking both
  uniqueness invariants before writing).
- Wiring: `editor/main.py` — a selector-tree leaf (D2, corrected from a
  toolbar button); `self.timeline.set_icon_provider(self.viewport.slot_qimage)`.

### Migration

`tools/migrate_timeline_from_unlock_min_round.py` (kept, not throwaway,
reviewable and re-runnable):
1. For every `(building_type, tier_index)`, read current `unlock_min_round`.
2. Run `game/core/xp_curve.best_case_curve` over the full round range
   against current, unmigrated data to get `round → cumulative_xp` and
   `village_level → round`.
3. Bucket each tier/unlock into the smallest `village_level` whose computed
   round is `>= R`.
4. Write through `editor.timeline_ops.save_progression`.
5. Print a diff table (`old unlock_min_round → computed village_level →
   curve round`) as a **required human review gate** before the phase that
   deletes `unlock_min_round` runs.

## 3. Build order

| Phase | Goal | Status |
|-------|------|--------|
| T1 | `buildings.json` art/type exposure (`building_type`/`card_slots`) | done |
| T2 | `progression` balancing domain (schema + empty seed) | done |
| T3 | Best-case XP-curve calculator (`engine`/`game.core`/`editor`) | done |
| T5 | Editor Timeline panel + `timeline_ops` (drag-and-drop) | done |
| T6 | Migration from `unlock_min_round` → Timeline data | not started |
| T4 | Runtime read path switch; delete `unlock_min_round` | not started |
| T7 | Docs | not started |

**D2 correction (made during T5, user-confirmed):** the Timeline panel is a
**selector-tree leaf under "buildings"** (the Theme/Cutscenes/Tutorial/
Strings single-document-panel pattern), not a toolbar button as originally
planned — see `editor/panels/CLAUDE.md`'s Timeline panel section for the
full reasoning.

Execution order is **T1 → T2 → T3 → T5 → T6 → T4 → T7** (kept as T1–T7 to
match the design doc's numbering; T4 intentionally runs after T6 so the
destructive schema change has a reviewed replacement dataset first).

### T1 — `buildings.json` art/type exposure
**Goal.** Add `building_type` + `card_slots` to all 12 groups; no behavior
change anywhere yet.
**Files.** `data/schemas/buildings.schema.json` (12 group blocks);
`data/balancing/buildings.json` (12 groups, transcribed from
`game/buildings/*.py` leaf classes), through `write_validated`.
**Tests.** `tools/tests/test_balancing_data.py` (D-12 bounds/description walk
picks the fields up automatically); a new pinning test asserting every
`card_slots[idx]` resolves to a real `data/slots.json` slot key.
**Exit gate.** `py tools/smoke.py` + `py tools/testgate.py check --affected`.

### T2 — `progression` domain
**Goal.** Schema + empty-but-valid seed file exist; nothing reads/writes it.
**Files — new.** `data/schemas/progression.schema.json`,
`data/balancing/progression.json` (`{"Timeline": {"levels": []}}`).
**Files — modified.** `game/core/balance.py::DOMAINS` (append
`"progression"`).
**Deviation from original file list (user-confirmed during execution):**
`tools/tests/test_balancing_data.py::DOMAINS` is **NOT** updated in T2.
That test's `test_out_of_range_numeric_rejected` requires every listed
domain to have at least one populated numeric leaf to violate; the T2 seed
is genuinely empty (`levels: []`), so it would fail for a reason unrelated
to a real bug. Add `"progression"` to that `DOMAINS` tuple in **T6**
instead, once the migration gives the file real content to test against.
**Tests.** `py tools/smoke.py` validates the new pair automatically (schema
validity / canonical formatting / description+bounds checks all still apply
via smoke's generic stem-pairing walk, independent of the DOMAINS tuple
above).
**Exit gate.** GATE PASS.

### T3 — Calculator
**Goal.** `engine/xp_curve.py`, `game/core/xp_curve.py`,
`editor/timeline_curve.py` — pure, headlessly testable, no readers changed.
**Files — new.** The three modules above.
**Files — modified.** `game/core/xp.py` (promote `_XP_KEY` →
`XP_KEY_FOR_ETYPE`); `tools/tests/test_editor_viewport.py::TestPurity` (add
`editor.timeline_curve`).
**Tests.** `tools/tests/test_xp_curve.py`: boundary rounds, boss-round
replacement, endgame-scaling pass-through, `threshold_sequence` reproduces
50/65/85/110/140; cross-package drift test (`editor.timeline_curve` vs.
`game.core.xp_curve`).
**Exit gate.** `py tools/testgate.py check --affected`.

### T5 — Editor panel
**Goal.** `editor/panels/timeline.py` + `editor/timeline_ops.py`, a
selector-tree leaf (D2, corrected from toolbar during execution), graph +
drag-and-drop authoring, writes validated `progression.json`.
**Files.** `editor/panels/timeline.py` (new), `editor/timeline_ops.py`
(new), `editor/panels/selector.py` (new `_TIMELINE_ROLE` leaf under
"buildings"), `editor/main.py` (panel construction, `right_stack` wiring,
`set_icon_provider`), `test_editor_viewport.py::TestPurity` (both new
modules) + one pre-existing pinned `right_stack.count()` test updated for
the new 8th page.
**Tests.** `tools/tests/test_timeline_ops.py` (pure, 16 tests): assign/
clear/add/remove round-trips; uniqueness cross-checks raise before writing
invalid data. `tools/tests/test_timeline_panel.py` (Qt tier, 10 tests):
add/remove level/slot, assign/replace/clear via panel methods, ONE synthetic
`QDropEvent` exercising the real drop path, Save round-trip, graph
tick-round values vs. `editor.timeline_curve` directly.
**Exit gate.** `py tools/smoke.py` green; targeted pytest files green;
headless `MainWindow` construction + Timeline-leaf-selection smoke check
(no real display available this session — real mouse-driven GUI interaction
not exercised). Full editor regression suite (`test_editor_panels.py`) and
the full/`--affected` testgate **deferred to final handoff** per user
request during this session (testgate's `--affected` falls back to the full
suite whenever `conftest.py` is touched, which every phase's new test file
does).

### T6 — Migration
**Goal.** Reviewable, re-runnable migration producing the initial
`progression.json` from today's `unlock_min_round` content.
**Files.** `tools/migrate_timeline_from_unlock_min_round.py` (new), run once,
its output committed as the seed `data/balancing/progression.json`; also add
`"progression"` to `tools/tests/test_balancing_data.py::DOMAINS` now that the
file has real numeric content (see T2's deferral note above).
**Tests.** `tools/tests/test_migration_timeline.py`: bucketing preserves the
relative order of `unlock_min_round` values.
**Exit gate.** Human review of the printed diff table; `py tools/smoke.py`
on the committed output.

### T4 — Runtime read path
**Goal.** `game/core/levelup.py`/`game/buildings/research.py` read Timeline
data; `unlock_min_round` is gone. Runs after T6 is committed and reviewed.
**Files.** `game/buildings/research.py`, `game/core/levelup.py`,
`game/core/session.py`, `game/ui/building_ui.py`, `game/main.py`;
`data/schemas/buildings.schema.json` + `data/balancing/buildings.json`
(delete `unlock_min_round`); `tools/tests/test_levelup.py`,
`tools/tests/test_boost.py`; `game/buildings/CLAUDE.md`.
**Tests.** Extend `test_levelup.py`: unplaced tier never offered; placed tier
offered starting exactly at `village_level >= N`; roll-of-3 regression pin;
`upgrade_gate`'s `tier_hidden` returns a village_level.
**Exit gate.** Full `py tools/testgate.py check` (spans `game/core` +
`game/buildings` + `game/ui`); live `py game/main.py` through a level-up.

### T7 — Docs
**Goal.** Durable-doc updates land where the code changed.
**Files.** `game/buildings/CLAUDE.md`, `game/core/CLAUDE.md` (XP section),
`editor/CLAUDE.md`/`editor/panels/CLAUDE.md` (new Timeline section),
`data/CLAUDE.md` (new `progression` domain + the two new `buildings.json`
fields).
**Exit gate.** Full `py tools/testgate.py check`.

## 4. Test coverage summary

- **Pure logic**: `engine/xp_curve.py`, `game/core/xp_curve.py`, the
  editor/game curve drift pin, `research.py::timeline_level_for`,
  `levelup.py`'s eligibility + roll-of-3/shuffle/fallback regression pin,
  `editor/timeline_ops.py` round-trips + uniqueness cross-checks, migration
  order-preservation.
- **Editor Qt tier**: drag-assign, drag-replace, add/remove slot, graph
  rendering vs. a pinned fixture, icon-provider grey-X fallback,
  `TestPurity` membership.
- **Integration**: write a `progression.json` fixture via
  `editor.timeline_ops`, boot a `Session` with matching balance data, drive
  `roll_levelup_options` across increasing `village_level`, assert the
  offered pool matches exactly what was placed; a live `py game/main.py` run
  exercising a real level-up end to end.

## 5. Risks / open items

- The best-case curve is explicitly an upper bound — real playthroughs will
  cross thresholds later. This is intentional (confirmed with the user) but
  worth re-confirming with a designer once the panel is live, in case the
  gap between best-case and real pacing feels misleading in practice.
- T4's deletion of `unlock_min_round` is destructive; it must not run until
  T6's migration diff has been human-reviewed (see T6's exit gate — not a
  machine gate).
- `game/ui`'s `_upgrade_state` wording changes ("round" → "level") is a
  small but visible in-game text change; worth a screenshot in the T4 PR
  description.
- Boost-trio visual pinning in the Timeline UI (D8) is a should-have, not
  required for T5's exit gate — flag if descoped.
- **Full-suite verification is deferred to final handoff** (user request
  during this session): T2/T3/T5 each ran only targeted pytest files +
  `py tools/smoke.py`, not the full/`--affected` testgate. One full
  `py tools/testgate.py check` is still owed before this branch is
  considered done — do not skip it at handoff.

## Critical files

- `data/schemas/buildings.schema.json`, `data/balancing/buildings.json`
- `data/schemas/progression.schema.json` (new), `data/balancing/progression.json` (new)
- `game/core/levelup.py`, `game/buildings/research.py`, `game/core/xp.py`,
  `game/core/session.py`, `game/ui/building_ui.py`
- `engine/era_math.py`, `engine/xp_curve.py` (new)
- `game/core/xp_curve.py` (new), `editor/timeline_curve.py` (new)
- `editor/panels/timeline.py` (new), `editor/timeline_ops.py` (new)
- `editor/panels/palette.py`, `editor/panels/viewport.py` (icon-provider pattern)
- `editor/domains.py`, `game/core/balance.py`
- `tools/tests/test_editor_viewport.py` (`TestPurity`)
- `tools/migrate_timeline_from_unlock_min_round.py` (new)
