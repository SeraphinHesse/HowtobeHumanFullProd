Status: Complete

# NewEnemyTypesPLAN.md — Sniper, Digger, Drummer enemy types

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION\_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/NewEnemyTypesPLAN.md NE-0-NE-3` or phase-by-phase.

## 1\. Vision

Add three new enemy types that each break the existing "walk until blocked,
then melee" model in a different, deliberate way, so players can't defend
with one building archetype:

* **Sniper** (`start\_round: 26`) — stands off at 2 tiles and snipes
attack-capable buildings; forces longer-range defenses, not just melee
towers.
* **Digger** (`start\_round: 35`) — burrows underground untargetable, erupts
under a claimed blocker/structure for one huge hit, then re-targets; a wall
of blockers alone isn't a complete defense.
* **Drummer** (`start\_round: 25`) — a support unit that buffs nearby enemies'
hp/dmg/speed (and, per its own variable list, their attack speed) while they
stay within 1 tile, adding a "kill the support unit first" layer.

All six existing enemy types (`game/enemies/enemy.py`) share one model:
`PathAgent` walks toward a target and only attacks once physically blocked
adjacent to a building; `attack\_range\_tiles`/`RangeSensor` are **decorative**
today — nothing reads them for an enemy's own attack (confirmed: no enemy
currently fires from range, only when blocked). No buff/aura/status-effect
system exists anywhere in the game. The existing `hunts` system
(`game/enemies/components.py`'s `\_HUNT\_QUERIES`, backed by
`game/map/pathfinder.py`'s shared `\_hunt()`/`\_goal\_tiles()` helper) is a clean,
reusable seam — a hunt is just "a predicate over `building\_type` fed through
the existing distance-choose/cost-route/base-fallback search" — so both
Sniper's and Digger's target sets are new *predicates* through **existing**
machinery, not new pathfinding architecture.

## 2\. Decisions (with rationale)

* **D1 — the `defence` hunt category widens** from `building\_type == "defence"` to "every attack-capable building" (`defence`, `aoe\_defence`,
`storm\_priest`, `sun\_scorcher`), and this is a **shared, intentional**
change: `SiegeCannon` (already `hunts: "defence"`) will also path to
mortars/Storm Priest/Sun Scorcher from NE-0 onward, per explicit user
decision — not scoped to Sniper alone.
* **D2 — a new `"structure"` hunt category** covers "every non-economy,
non-boost, non-base building" (`blocker`, `wall\_builder`, `defence`,
`aoe\_defence`, `storm\_priest`, `sun\_scorcher`) for Digger. `blocker`/
`wall\_builder` are the common case in practice, but the category is not
restricted to just those two.
* **D3 — Sniper's range is a real new combat mode**, not a cosmetic stat:
`PathAgent` grows `stand\_off\_range`/`in\_range` (both default-off, so every
existing type stays byte-identical), and `EnemyCombat.update()`'s one gate
becomes `pa.blocked or pa.in\_range` — no duplicate damage-application path.
* **D4 — Digger's building claim releases** as soon as that digger moves on
(destroys its target and re-targets) or dies. Not permanent for the match.
* **D5 — Digger interrupted mid-dig** (target destroyed by something else
while underground) emerges immediately at the empty tile and re-targets
right away, rather than waiting out its timer.
* **D6 — Drummer's HP buff heals on apply** (current HP rises by the granted
amount, not just headroom) **and un-heals/clamps on decay** (losing a
source's contribution shrinks max HP back down, clamping current HP if it's
now above the new max).
* **D7 — Drummer buffs stack additively** per source — 2 Drummers in range is
2× the bonus of 1, and each source's contribution decays independently 4s
after that enemy leaves that Drummer's radius.
* **D8 — no engine changes are expected.** All three types are buildable
entirely inside `game/enemies/`, `game/map/pathfinder.py`, and `data/` —
confirmed against `engine/core/CLAUDE.md` (`RangeSensor` is already a pure
candidate-query primitive; no new engine Component is needed, only new
`game/`-side components following the `PathAgent`/`EnemyCombat` precedent).

## 3\. Build order

|Phase|Scope|Status|
|-|-|-|
|NE-0|Shared pathfinder foundation (widen `defence`, add `structure` hunt)|not started|
|NE-1|Sniper — new ranged stand-off combat mechanic|not started|
|NE-2|Digger — burrow / claim / emerge state machine|not started|
|NE-3|Drummer — new buff/aura component|not started|

### Phase NE-0 — Shared pathfinder foundation

**Goal**: both new hunt predicates exist and are exercised by an existing
type (SiegeCannon) before any new enemy class depends on them, so a mistake
here shows up against a type with existing test coverage first.

**Files** — modified: `game/map/pathfinder.py` (widen
`find\_path\_to\_nearest\_defence`'s predicate to `\_ATTACK\_BUILDING\_TYPES = {"defence", "aoe\_defence", "storm\_priest", "sun\_scorcher"}`, mirroring the
existing `\_ECONOMY\_BUILDING\_TYPES` pattern; add `find\_path\_to\_nearest\_ structure` with `\_STRUCTURE\_BUILDING\_TYPES = {"blocker", "wall\_builder", "defence", "aoe\_defence", "storm\_priest", "sun\_scorcher"}`, same shape as
`find\_path\_to\_nearest\_defence`), `game/enemies/components.py` (register
`"structure"` in `\_HUNT\_QUERIES`), `data/schemas/enemies.schema.json`
(`hunts` enum gains `"structure"`), `game/enemies/CLAUDE.md` /
`game/map/CLAUDE.md` (durable-rule update: the widened `defence` semantics +
the new `structure` category, in the "Prey hunting" sections both docs
already carry).

**Tests**: extend `tools/tests/test\_pathfinder.py` — `find\_path\_to\_nearest\_ defence` now matches `aoe\_defence`/`storm\_priest`/`sun\_scorcher` occupants,
not just `defence`; a new `find\_path\_to\_nearest\_structure` test matrix
(matches `blocker`/`wall\_builder` + the attack types, excludes `economic`/
`meditator`/`painter`/`boost\_\*`/`base`); extend `tools/tests/test\_enemies.py`
if a SiegeCannon-targeting fixture asserts the old narrower building set.

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check --affected`.

### Phase NE-1 — Sniper

**Goal**: a live, ranged enemy that stands off at 2 tiles from an
attack-capable building and fires on cooldown without ever closing to melee.

**Files** — new: none beyond balancing/slots entries. Modified:
`game/enemies/components.py` (`PathAgent` gains `stand\_off\_range: int = 0` +
`in\_range: bool = False`, both default-off; `update()` grows the
Chebyshev-distance-to-committed-target check that halts movement and sets
`in\_range` once `<= stand\_off\_range`, without requiring the existing
blocker/wall scan to fire first; `EnemyCombat.update()`'s gate becomes
`pa.blocked or pa.in\_range`), `game/enemies/enemy.py` (new `Sniper(Enemy)`
subclass: `ETYPE "sniper"`, `REGISTRY\_GROUP "Sniper"`, `STAT\_SUBTREE ("Sniper",)`, wires `stand\_off\_range` from balancing; registered in
`ENEMY\_CLASSES`), `game/enemies/spawner.py` (new `ENABLE\_SNIPER` branch +
composition wiring, the `/add-enemy` pattern), `data/balancing/enemies.json`

* `data/schemas/enemies.schema.json` (new `EnemyTypes.Sniper` block,
`hunts: "defence"`, `start\_round: 26`, `footprint: 1`; era-0 seed grounded
against the existing curve — SiegeCannon era 0 is hp 280/dmg 100/speed
1.0/range 2/atk\_speed 1.9, Raider era 0 is hp 440/dmg 30/speed 0.9 — per the
user's qualitative spec (high dmg, high range, low attack speed, low hp,
low/avg move speed): `hp: 150, dmg: 140, move\_speed: 0.85, attack\_speed: 2.6, attack\_range\_tiles: 2`, `stand\_off\_range: 2`; fully retunable afterward with
no code change), `data/slots.json` (new `Sniper` registry group, grey-X
placeholder eras).

**Visual note**: v1 ships with no new projectile-travel system — the ranged
hit applies instantly on cooldown (same tick model as today's melee, just
without the adjacency requirement). A muzzle-flash/arrow visual is a
follow-up `/replace-visual` pass, not part of this phase's exit gate.

**Tests**: a new `TestSniper` in `tools/tests/test\_enemies.py` mirroring the
existing per-type HP-ledger/hunt fixtures — asserts a Sniper halts at exactly
Chebyshev 2 from its committed target (never reaches `blocked`), fires on its
`attack\_speed` cadence, and that every OTHER type's `stand\_off\_range`
defaults to 0 (byte-identical `update()` path — pin this explicitly, since
`PathAgent` is shared by every type). Headless HP-ledger round scripted to
round 26.

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check --affected`;
live `py game/main.py`, debug-skip to round 26, confirm a Sniper stops short
of its target building and fires without ever closing to melee.

### Phase NE-2 — Digger

**Goal**: a live enemy that walks visibly, submerges untargetable at 6 tiles
from its claimed target, erupts for one large hit, and exclusively claims one
target building at a time across all live Diggers.

**Files** — new: a "dirt pile" decal object (mirrors `game/enemies/ corpse.py`'s `Corpse`/`CorpseFade`/`spawn\_corpse` shape exactly — a
`SpriteAnimator` + a fade/persist component, tagged e.g. `"dirt\_pile"`, never
`"enemy"`); may live in `game/enemies/corpse.py` as a sibling or its own
small module — decide against that file's existing shape at implementation
time. Modified: `game/enemies/components.py` (`PathAgent` gains `no\_melee: bool = False`, default off, skipping `\_blocker\_ahead`/`\_wall\_edge\_ahead`
entirely when set — a Digger must never soft-lock punching an incidental
building at 0 damage en route to its real target; new `BurrowAgent`
component driving `WALKING -> SUBMERGED -> EMERGE -> WALKING` per the design
in the approved plan file — the exact seam for a scene reference at repath
time (a new `Enemy.\_scene` transient, parallel to the existing `\_tilemap`
cache) is an implementation decision for this phase, following `game/ enemies/CLAUDE.md`'s E-11 conventions), `game/enemies/enemy.py` (new
`Digger(Enemy)`: `ETYPE "digger"`, `hunts: "structure"`, `kidnapping: false`,
`Enemy.targetable` override keyed off the `BurrowAgent` SUBMERGED state — the
same duck-typed contract the Boss's second phase already uses), `game/ enemies/spawner.py` (`ENABLE\_DIGGER` branch), `data/balancing/enemies.json` +
schema (new `EnemyTypes.Digger` block, `start\_round: 35`, three new leaves —
`dig\_speed` tiles/sec while burrowed, doubling as overground `move\_speed` per
the user's own phrasing; `dmg` the emerge hit; `dig\_range\_tiles` default 6,
the submerge trigger distance; seed `hp: 900, dmg: 900, move\_speed: 1.0, dig\_range\_tiles: 6`), `data/slots.json` (new `Digger` registry group — walk +
a one-shot dig/emerge animation state; the dirt-pile decal's own slot may
ship grey-X, real art via `/replace-visual` later).

**Exclusive claim mechanism**: on re-target, scan `scene.by\_tag("enemy")` for
other live Diggers' committed `target\_col`/`target\_row` and exclude those
tiles from the goal set passed into `find\_path\_to\_nearest\_structure` (a new
optional `exclude` parameter on that function, threaded through `\_goal\_tiles`
predicate). No target found after exclusion → the Digger stands down
(visible, idle, harmless) rather than falling back to attacking the base —
Diggers "only build towards buildings" per the brief.

**Interrupt handling** (D5): the `BurrowAgent`'s SUBMERGED tick checks
target liveness each frame (mirrors `PathAgent.\_target\_alive`'s existing
block-scan pattern); on death mid-dig it transitions straight to EMERGE at
the current internal position, deals no damage, and immediately re-targets.

**Tests**: a new `TestDigger` in `tools/tests/test\_enemies.py` — submerges at
exactly `dig\_range\_tiles`, is excluded from `scene.by\_tag("enemy")`
targeting/damage while submerged (reuse the Boss `targetable=False` test
pattern), emerges and deals `dmg` to a still-alive target, emerges harmlessly
and re-targets on an interrupted target, and two Diggers never commit to the
same building simultaneously (the claim-exclusion test). A `no\_melee`
regression test confirms a Digger routed adjacent to an unrelated building
never halts/attacks it. Headless HP-ledger round scripted to round 35.

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check --affected`;
live `py game/main.py`, debug-skip to round 35, confirm a Digger walks,
submerges (dirt pile appears, HP bar/targeting disappears), erupts under its
target for a large hit, and a second Digger picks a different building.

### Phase NE-3 — Drummer

**Goal**: a live support enemy whose aura measurably buffs (and un-buffs)
nearby enemies' hp/dmg/move\_speed (+ the variable list's attack\_speed), with
additive multi-source stacking and 4s decay-on-leaving-radius.

**Files** — new: none beyond balancing/slots entries (the two components
below land in `game/enemies/components.py`, matching every other enemy
component). Modified: `game/enemies/components.py` (new `BuffState`
component — declared JSON-safe per-source contribution tracking + decay
timers, added to `Enemy.\_\_init\_\_`'s component list for every type as an
always-present, near-zero-cost component when idle, mirroring `Kidnap`'s
"declared, usually inert" shape; new `DrummerAura` component — each frame
scans `scene.by\_tag("enemy")` within Chebyshev `support\_range`, applies/
refreshes this Drummer's own contribution on each target's `BuffState`,
including the D6 heal-on-apply; contributions past `support\_range` start
their independent 4s decay countdown and un-apply with the D6 shrink+clamp
when it expires), `game/enemies/enemy.py` (new `Drummer(Enemy)`: `ETYPE "drummer"`, `hunts: "base"` — marches at the hole like a Walker per the
brief — footprint 1, `sprite\_scale` slightly above 1.0 for the "slightly
taller" cosmetic ask), `game/enemies/spawner.py` (`ENABLE\_DRUMMER` branch),
`data/balancing/enemies.json` + schema (new `EnemyTypes.Drummer` block,
`start\_round: 25`; nine leaves per the user's own variable list: `hp`,
`move\_speed`, `dmg` self stats — "very low attack damage" — `support\_range`
Chebyshev tiles default 1, `hp\_increase`, `move\_speed\_increase`,
`dmg\_increase`, `attack\_speed\_increase`, `support\_range\_increase`; seed `hp: 300, dmg: 5, move\_speed: 0.9, support\_range: 1, hp\_increase: 0.15, dmg\_increase: 0.15, move\_speed\_increase: 0.15, attack\_speed\_increase: 0.10, support\_range\_increase: 0`), `data/slots.json` (new `Drummer` registry
group).

**Open item carried into this phase's kickoff** (flag, do not silently
resolve): the user's prose ("increases dmg/hp/movement speed") and their
explicit variable list (which also names `attack\_speed\_increase` and
`support\_range\_increase`) don't fully agree on whether attack-speed is
buffed too and whether support range itself grows over eras. This phase
implements the more specific variable list (both fields present) and should
confirm with the user during kickoff if the prose was the intended narrower
scope instead.

**Tests**: a new `TestDrummer` in `tools/tests/test\_enemies.py` — a single
Drummer buffs an enemy's hp (with heal-on-apply)/dmg/move\_speed/attack\_speed
within range 1; the buff decays exactly 4s after the enemy leaves range,
shrinking max HP and clamping current HP down if needed; two Drummers in
range stack additively and decay independently per source; an enemy outside
every Drummer's range is unaffected. Headless HP-ledger round scripted to
round 25.

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check --affected`;
live `py game/main.py`, debug-skip to round 25, confirm visibly buffed
enemies (HP bar/stats) clustered near a Drummer, decaying \~4s after moving
away, and additive stacking near two Drummers.

## 4\. Cross-phase verification (once, at the end)

* `py tools/smoke.py` + the **full** `py tools/testgate.py check` (zero
failures — no affected-tier shortcut on the final handoff).
* Live `py game/main.py` covering all three debug-skip scenarios above in one
session.
* `game/enemies/CLAUDE.md` durable-rule update covering: the widened
`defence` hunt semantics, the new `structure` hunt, `PathAgent. stand\_off\_range`/`in\_range`/`no\_melee`, the `BurrowAgent` state machine, and
the new `BuffState`/`DrummerAura` components — each is exactly the kind of
"when you change enemy conventions, update this doc" change that file calls
out. `game/map/CLAUDE.md`'s "Prey hunting" section gets the D1/D2 hunt
additions.

## 5\. Risks / open items

* **NE-0 is a live balance change to an existing type.** Widening
`SiegeCannon`'s target set is intentional and user-approved, but it changes
existing gameplay from round 14 onward — flag it in the phase's PR
description as a deliberate behavior change, not a side effect to discover
later.
* **NE-2's exclusive-claim mechanism needs a scene reference `PathAgent`/
`Enemy` don't currently cache** (only `\_tilemap` is cached today). The
`Enemy.\_scene` transient is the proposed seam; confirm against `game/ enemies/CLAUDE.md`'s E-11 conventions before landing — this is the single
piece of NE-2 most likely to need a design adjustment during execution.
* **NE-2's `no\_melee` flag must ship correct from the start.** Without it, a
Digger routed adjacent to an unrelated building before reaching its own
`dig\_range\_tiles` trigger would soft-lock (0-damage melee against something
it can never kill, since it has no real attack outside digging). The NE-2
regression test above exists specifically to catch this before live testing.
* **NE-3 is the only phase adding an always-present component
(`BuffState`) to every enemy type**, not just the new one — verify its
inert-state cost is negligible (the `Kidnap` precedent) and that it doesn't
change any existing type's serialized component list in a way a test pins
against.
* **Drummer's variable-list vs. prose discrepancy** (attack\_speed buff +
support-range growth) is called out in NE-3 above; resolve it with the user
at that phase's kickoff rather than guessing silently.
* **Numeric seed values throughout are starting points**, deliberately
grounded against the existing SiegeCannon/Raider era-0 curve but not
independently balance-tested — retune via the editor's balancing panel
post-launch with no code change, per this repo's normal workflow.

