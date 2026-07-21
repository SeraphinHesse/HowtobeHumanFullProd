# Phase TU-7 — Scripted loss, lives intro, stone-thrower chain, tutorial end

> Source plan: `planning/TutorialPLAN.md` §3 "Phase TU-7" (lines 263-286) and
> §2 D1-D8 (lines 51-111). **Depends on TU-5 and TU-6, neither of which has a
> brief on disk yet** (`docs/briefs/phase-tu-5-cutscene-playback.md` and
> `docs/briefs/phase-tu-6-sequencer-director-flute-chain.md` do not exist in
> this worktree — confirmed by directory listing at brief-authoring time).
> Every API this brief assumes from TU-5/TU-6 (director shape, `Session`
> wiring, event-feed convention) is therefore **inferred** from the plan's D1-D8
> + TU-5/TU-6 build-order rows, not read from their actual code. Each such
> assumption is called out explicitly below and MUST be checked against the
> real TU-5/TU-6 briefs (or their landed code) before/while this phase
> executes. This is the single biggest open risk in this brief.

## 1. Behavioral spec

**Goal, verbatim from the plan** (`planning/TutorialPLAN.md:263-269`): the
round-1 loss plays out (no defences -> enemies reach the hole), costing a life
iff `first_loss_costs_life`; message box #2 (lives text) shows at ROUND_END;
round 2 opens the guided stone-thrower chain against `tutorial_stone`; after
that placement the tutorial ends and all input is released.

**Message text #2** (verbatim, from the plan's Vision section,
`planning/TutorialPLAN.md:47-49` — the plan states this string already lives
byte-identical in `data/tutorial/tutorial.json` once TU-1 lands):

> "Once the humans reach our hole the round is lost. You have only 3 lives. If
> economy buildings get destroyed during the human attack they don't yield
> resources. To defend your base you need to build defense buildings"

**measured**: `data/tutorial/tutorial.json` does **not exist in this worktree
today** (`Glob data/tutorial/**` → no results, checked at brief-authoring
time) — TU-1 is "not started" per the build-order table
(`planning/TutorialPLAN.md:117`). TU-7's implementer must pull the live string
out of whatever TU-1 actually wrote (byte-for-byte, no re-typing) rather than
this brief — this brief only pins the *content*, not the *file:line*, because
the file doesn't exist yet.

### Existing mechanics TU-7 rides on top of (all **verified** by reading the current pre-TU-5/6 `game/core/session.py`)

- **A base breach already costs exactly one life per round and wipes the
  round**, independent of any tutorial: `Session.on_base_hit`
  (`game/core/session.py:403-423`) decrements `st.base_lives` (line 419) and
  sets `self._wipe_pending = True` (line 423) unless lives hit 0 (line
  420-421, → `GAME_OVER`). `post_sim` (`game/core/session.py:290-320`, wipe
  branch at 304-306) then calls `_wipe_round(scene)` + `_begin_round_end()`
  the next frame, clearing every other live/queued enemy — **only one
  `on_base_hit` call ever fires per round** (already covered by the existing
  test `TestGameOverLives.test_life_lost_and_round_wiped_on_breach`,
  `tools/tests/test_phase_loop.py:223-244`, which spawns two inbound enemies
  and asserts exactly one life is lost). This means TU-7 needs **no new
  "force a loss" mechanic** — round 1 of a real tutorial run naturally has no
  defence building yet (only the TU-6 flute chain has fired), so the first
  enemy that reaches the hole IS the scripted loss, for free, from existing
  code. TU-7's only job is to (a) optionally waive the life cost, and (b) hook
  the message box + round-2 chain to that same event.
- **`_begin_round_end()`** (`game/core/session.py:458-473`) sets
  `st.phase = GamePhase.ROUND_END` (line 472) unconditionally, and is the ONE
  place every road to ROUND_END passes through (`post_sim` wipe path line 306,
  `post_sim` normal wave-clear path line 315, `quick_skip_combat` line 143,
  `cheat_skip_round` line 177) — the natural, single insertion point for a
  "did we just enter ROUND_END" event feed.
- **`end_turn()`** (`game/core/session.py:228-254`) is a no-op unless
  `state == GAMEPLAY and phase == BUILDING` (line 235-236) — TU-7 does not
  touch it; TU-5 (pending-cutscene) and TU-6 (allow/skip gating) both already
  touch this method, so TU-7 deliberately edits *other* methods on the same
  class to keep merge conflicts localized (see §3).
- **`GamePhase`/`GameState`** enums live in `game/core/phases.py`, imported at
  `game/core/session.py:35`.
- **Building type keys** (needed to bind the round-2 card gate): `Musician`
  (Flute Player) is `BUILDING_TYPE = "economic"`
  (`game/buildings/musician.py:11`); `Defender` (Stone Thrower → Slinger →
  Pistoleer) is `BUILDING_TYPE = "defence"` (`game/buildings/defender.py:11`).
  Both start unlocked from round 1 (`game/buildings/CLAUDE.md`, "Research /
  gating seam" section: "Only `defence` (Stone Thrower) and `economic` (Flute
  Player) start unlocked"), so round 2 does not need to unlock anything new —
  it only needs to **restrict which already-unlocked card is clickable**.
- **Card click dispatch**: `BuildingUI.cards` is a list of `(btype, btn)`
  pairs (`game/ui/building_ui.py:503`, appended once per unlocked type),
  consumed by `BuildingUI.handle_click` (`game/ui/building_ui.py:658`, card
  loop at line 701, placement commit `_do_place` at line 795). The host feeds
  this through `panel.handle_click(mx, my, session, buildings_balance,
  world.scene, world.occupancy)` at `game/main.py:424` (also called at line
  410 inside the `panel.preview is not None` modal branch). **TU-7 does not
  modify `building_ui.py` or this dispatch** — see §2's "why no
  `building_ui.py` edit" note; this citation exists so the orchestrator can
  verify TU-6 actually built a data-driven per-card gate here, since TU-7's
  round-2 restriction depends entirely on that gate already existing and
  being reusable.

## 2. Architecture plan

TU-7 adds exactly two behavioral pieces to the director/script, and one
narrow, load-bearing hook into `Session`. It deliberately adds **no new
files** (per the task's file-scope constraint) and touches **no
UI-rendering code** — everything round-2-specific rides the SAME generic
step-sequencer + generic message-box + generic per-card gate that TU-6 must
already have built for the round-1 flute chain. If TU-6 did NOT build a
data-driven "restrict clickable cards to a target building_type" gate (as
opposed to a one-off "restrict to Musician" special case), that gate has to
be generalized in THIS phase, and `game/tutorial/director.py`'s file-scope
budget already covers it — flag this as a decision point for the orchestrator
to confirm once TU-6 lands.

**Assumed director API surface** (all **inferred** — cross-check against the
real TU-6 brief/code):

- `director.allows(action: str) -> bool` — already specified by D6
  (`planning/TutorialPLAN.md:95-101`): true when the tutorial is inactive,
  skipped, or finished (zero-overhead path). TU-7 reuses it unchanged for
  `allows("select_card:defence")`/`allows("place_building")` style checks —
  it does NOT reuse it for the free-loss life check (see next point; that is
  a game-rule consult, not an input gate, and conflating the two under one
  method risks an accidental double meaning of "allowed").
- **NEW for TU-7**: `director.charges_life_on_base_hit(round_num: int) ->
  bool`. Default `True` (matches current `on_base_hit` behavior exactly when
  the tutorial is inactive/skipped/finished — D6's zero-overhead principle).
  Returns `False` **only** when: the tutorial is active, `round_num == 1`,
  the sequencer's current/just-completed step is the scripted first-loss step,
  AND the script's `first_loss_costs_life` flag is `False`. This is a pure
  read — it does not mutate director/sequencer state (the mutation, if any,
  happens via the normal event-feed path below).
- **NEW for TU-7**: the director must be **notified** when round 1 actually
  reaches ROUND_END, so its sequencer can advance past the "wait for the
  scripted loss" step into message box #2. Proposed event id:
  `director.notify("round_end", round_num=st.round_num)` — reusing whatever
  generic `notify`/event-feed method name TU-6 actually settled on (the task
  brief for TU-6 calls this "an event feed" without naming it; **the
  orchestrator must reconcile the exact method name** — this brief calls it
  `notify` by analogy with the `tile_clicked:flute` /
  `building_selected:musician` event-id examples in D2,
  `planning/TutorialPLAN.md:68-69`). The event id itself,
  `round_end`/`round_end:<n>`, is new for TU-7 and must be added to
  `engine/tutorial.py`'s vocabulary of `advance_on` ids used by
  `data/tutorial/tutorial.json` — but `engine/tutorial.py` needs **no code
  change**, since D2 already specifies event ids as opaque strings the engine
  never interprets (`planning/TutorialPLAN.md:64-69`); only the JSON script
  and the director's event-feed call site are new.
- Director must also expose (or the sequencer step's `flags` must carry)
  enough for `director.py` to answer "is round 1's loss step still pending /
  just resolved" without `Session` needing to know anything about tutorial
  internals — `Session` only ever calls the two methods above, passing
  `round_num`, never reading director state directly.

**Why no `building_ui.py` edit**: D6 states the input gate sits at "the two
existing choke points" — `panel.handle_click()` in `game/main.py` and the
phase-advance calls in `game/core/session.py` — not inside
`building_ui.py`'s card loop itself. TU-6 must therefore already have wired
its round-1 "only the Musician card is clickable" restriction generically
(via a per-card `director.allows(f"select_card:{btype}")` check reached from
one of the two choke points, or via a hook `building_ui.py` calls into that
TU-6 added in its own file-scope budget). TU-7's round-2 restriction to
`"defence"` only requires the **script** to say which `building_type` the
active step targets — zero new code in the click path. **If this
generalization turns out not to exist after TU-6 lands** (e.g. TU-6
hard-coded `"economic"` instead of reading it from the step), that is a
TU-6 defect to fix when TU-6 lands, not new TU-7 scope creep — flag it to the
orchestrator rather than quietly patching `building_ui.py` from this phase.

**Script additions** (`data/tutorial/tutorial.json`, schema already covers
this per TU-1's plan description — `planning/TutorialPLAN.md:70-76`): append
the round-2 step list after TU-6's round-1 steps:

1. a "wait for scripted loss" step: `advance_on: "round_end"`, no highlight,
   `flags: {is_scripted_loss: true}` (or equivalent — whatever flag key
   `charges_life_on_base_hit` reads).
2. message box #2 step: `message: "<message-2 id>"`, no Skip button (D7 only
   puts Skip on box #1), `advance_on` = the message box's dismiss/continue
   event.
3. tile-highlight step: `highlight: "tutorial_stone"`, `advance_on:
   "tile_clicked:stone"`.
4. card-highlight step: `highlight: "card:defence"`, `allow: ["defence"]`,
   `advance_on: "building_selected:defence"`.
5. confirm-highlight step: `highlight: "confirm"`, `advance_on:
   "building_placed:defence"`.
6. terminal step: no highlight, `flags: {tutorial_end: true}` — once reached,
   `director.allows(...)` and `charges_life_on_base_hit(...)` both return
   permissive/default values for the rest of the run (same "finished" state
   TU-6 must already define for after the round-1 chain, generalized to also
   mean "after round-2 chain").

`first_loss_costs_life` itself is **not new** — it is TU-1 data
(`planning/TutorialPLAN.md:74,93-94`); TU-7 only *reads* it, it does not add
the field.

## 3. File scope + shared-file contract

**No new files this phase** (task constraint). Modified only:

- **`game/tutorial/director.py`** — add: the round-2 step wait/loss/chain
  logic riding the same sequencer-driving loop TU-6 built; `
  charges_life_on_base_hit(round_num)`; whatever plumbing is needed so
  `allows()` keeps working through the round-2 chain and goes permissive at
  the terminal step. No public-method renames to TU-6's existing surface —
  only additive methods.
- **`data/tutorial/tutorial.json`** — append the 6 round-2 steps above (or
  however many the actual TU-1 schema decomposes them into) to the existing
  step list. No schema change (TU-1's schema already covers `message` /
  `highlight` / `advance_on` / `allow` / `flags` per D2/D3).
- **`game/core/session.py`** — **exactly two insertion points**, both inside
  existing methods, chosen specifically to avoid the lines TU-5 and TU-6 are
  expected to touch:
  1. **`on_base_hit`, immediately before the life decrement**
     (`game/core/session.py:419`, currently `st.base_lives -= 1`): insert a
     guard —
     ```python
     charge = True
     if self.tutorial_director is not None:
         charge = self.tutorial_director.charges_life_on_base_hit(
             st.round_num)
     if charge:
         st.base_lives -= 1
     ```
     replacing the bare `st.base_lives -= 1` at line 419. The `if st.base_lives
     <= 0` check at line 420 must then key off whatever `st.base_lives` ends
     up being (unchanged if `charge` was False — i.e. a waived first loss
     can never trigger game over, which is correct: the plan's `false` case
     keeps all 3 lives).
  2. **`_begin_round_end`, right after `st.phase = GamePhase.ROUND_END`**
     (`game/core/session.py:472`): insert —
     ```python
     if self.tutorial_director is not None:
         self.tutorial_director.notify("round_end", round_num=st.round_num)
     ```
     This fires on every path into ROUND_END (wipe, normal wave-clear,
     quick-skip, cheat-skip) — harmless/no-op outside the scripted round-1
     wait step, since the director only cares about this event while its
     sequencer is on that exact step (D6 zero-overhead principle applies
     here too).
  - **Explicitly NOT touched by TU-7**: `end_turn()` (`session.py:228-254`,
    owned by TU-5's `pending_cutscene` insert and TU-6's allow/skip gating
    insert) and `post_sim`'s wipe/wave-clear branching logic itself
    (`session.py:290-320`, structurally unchanged — TU-7 only adds a call
    inside `_begin_round_end`, which `post_sim` already calls unmodified).
  - **Cross-phase reconciliation note for the orchestrator**: this brief
    assumes `Session` gains a `self.tutorial_director` attribute (name
    inferred — analogous to how `Session` already threads other optional
    collaborators) set at construction time by TU-6 (most likely via a new
    optional param on `Session.create`/`__init__`, since the existing
    signature is `Session.create(Spawner(), tm, ENEM, CORE, BUILD)` with no
    director param today — verified by reading
    `tools/tests/test_phase_loop.py:166`). **If TU-6 names this attribute
    differently, or wires it via a setter/late-bind instead of the
    constructor, TU-7's two insertion points must use that exact name/shape
    instead** — this is the single most important thing to verify once
    TU-6's actual brief/code exists, before TU-7 starts.
- **Tests**: extend `tools/tests/test_tutorial_director.py` (created by
  TU-6, per the task's file list) with the round-2/loss/end-state cases below.
  If TU-6 also touches `game/core`-level session behavior with its own test
  file, this phase's `on_base_hit`/`_begin_round_end` cases belong in
  whichever file already hosts `TestGameOverLives`
  (`tools/tests/test_phase_loop.py:217-244`) — add a new
  `TestScriptedTutorialLoss` class there rather than duplicating the
  `Session.create`/`build_board`/`frame()` harness. Register any new test
  module in `conftest.py` TIERS if TU-6 didn't already (per its file scope).

## 4. Exit gate + Quick Test

**Tests (headless, extend existing modules per §3):**

- `first_loss_costs_life: true` → a scripted round-1 run (flute placed, no
  defence, one enemy inbound to the base) ends round 1 with `base_lives == 2`
  (down from the seeded 3).
- `first_loss_costs_life: false` → same scenario ends round 1 with
  `base_lives == 3` (unchanged).
- Message box #2 fires exactly once, at round 1's ROUND_END, and never again
  on subsequent rounds' ROUND_ENDs.
- The round-2 chain: only the `"defence"` card is selectable
  (`director.allows("select_card:defence")` true,
  `director.allows("select_card:economic")` false mid-chain); it binds to
  `tutorial_stone`, not `tutorial_flute`.
- After the stone-thrower placement, `director.allows(...)` returns `True`
  for every action tried (card select of any type, tile click anywhere, end
  turn) and `charges_life_on_base_hit` returns `True` (normal rules resume).
- A **skipped** tutorial run never sees message box #1 or #2 (director
  inactive from the start) but still gets the TU-5 `first_end_turn` cutscene
  request on round 1's `end_turn()` (this exercises the "OpenCV
  optionality"/"gate on events, never cutscene-finished" risk item,
  `planning/TutorialPLAN.md:290-292` — assert on the `pending_cutscene`
  request event, not on any video-playback state).
- `BOSS_CUTSCENE` interaction is explicitly out of scope
  (`planning/TutorialPLAN.md:302-303`) — no test needs to exercise round 1
  also being a boss round; if the boss interval could ever make round 1 a
  boss round, that is a pre-existing data/balancing concern, not something
  TU-7 introduces or must guard against.

**Gate**: `py tools/smoke.py` then **full** `py tools/testgate.py check`
(not `--affected`) — the plan explicitly marks TU-7 as the plan's hand-back
phase (`planning/TutorialPLAN.md:284-285`), so the full suite runs once here.
`GATE PASS` or not done.

**Live Quick Test**: `py game/main.py` → New Game (tutorial NOT skipped) →
place the flute per the TU-6 chain → End Turn → watch the `first_end_turn`
cutscene play/skip → let round 1 run with no defence → the enemy reaches the
hole, life count drops (or doesn't, per the `first_loss_costs_life`
balancing/script toggle currently set) → message box #2 appears with the
lives/economy/defence text → the stone-thrower chain highlights
`tutorial_stone`, then the Defender card (other cards visibly un-clickable),
then Confirm → place it → confirm all input is now free (camera pan, any
card, any tile) and no more tutorial boxes appear → let the run continue into
free play. **Second run**: New Game → Skip on message box #1 → confirm no
box #2 ever appears and the round-1 `first_end_turn` cutscene still plays.
