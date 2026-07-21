# Phase ESV-6 — Converge: anchored impact & muzzle VFX (+ the §6 floater cleanup)

Source plan: `planning/EntitySceneVfxPLAN.md` §ESV-6 **and §6 item 1**.
Branch: `phase-esv-6-converge` off `VfxEditor` (ESV-5 already merged as `f0519b8`).
**Cross-package: game (+ a data read that already exists).** Track A × B.

**Read**: `game/CLAUDE.md`, `game/ui/CLAUDE.md`, `game/enemies/CLAUDE.md`.
**Read first**: `docs/briefs/phase-esv-5-sprite-oneshots.md` — this phase builds
directly on its `_play` dispatcher and its ledger/callback pattern. Also skim
`docs/briefs/phase-esv-1-anchors.md` for the anchor conventions.

**This is the FINAL phase of the plan.** After it, all six phases are done.

**Guardrail D4, restated because this is the phase most able to break it**: the
anchors are **VISUAL ONLY**. Damage geometry — Chebyshev range, splash radius,
predictive lead, projectile flight time — keeps measuring from footprint centres.
ESV-1 already made this explicit: `ProjectileHoming.launch(..., origin=None)`
(`game/enemies/combat.py:70-76`, **verified**) takes the *unanchored* point
solely so flight time is invariant under a muzzle anchor. **Do not touch that
parameter, and do not let any anchor reach a damage expression.**

**Landing condition: byte-identical on a fresh checkout.** No manifest in `data/`
authors any `anchors` block today, and `game/anchors.py`'s two entry points both
return `(0.0, 0.0)` when the anchor is absent (**verified**, `game/anchors.py`
docstring + both function bodies). So every change below is a no-op until a
designer drags a handle. Any visible difference with no anchors authored is a bug.

---

## 1. Behavioural spec

### 1.1 The anchor map — which event moves, and by whose anchor

ESV-5 routed all 9 trigger events through one dispatcher,
`FloaterManager._play(event, wx, wy, **kw)` (`game/ui/effects.py:390`,
**verified**). ESV-6 changes **what `wx, wy` is** for a subset of them.

| Event | Anchor | Whose | Rationale |
|---|---|---|---|
| `defender_fire` | `muzzle` | the firing defender | the plan's headline demo |
| `enemy_attack_ranged` | `muzzle` | the attacking enemy | it IS a muzzle spray |
| `enemy_attack_melee` | `muzzle` | the attacking enemy | the weapon's swing point; same authored handle |
| **`projectile_hit`** (NEW) | `impact` | **the target** | §1.3 — the `impact` anchor's reason to exist |
| `building_destroyed` | `impact` | the destroyed building | a body burst = "where the hit landed" |
| `enemy_death` | **none** | — | §1.2 |
| `splash_impact` | **none** | — | §1.2 |
| `building_placed` / `building_level_up` / `building_tier_up` | **none** | — | §1.2 |

### 1.2 Which events deliberately do NOT get an anchor — and why

**Do not "finish the job" by anchoring these. Each exclusion is reasoned:**

- **`enemy_death`** (blood splatters, `effects.py:519`). Splatters are **ground
  decals**. An `impact` anchor is authored at body height — a negative `y`, i.e.
  *upward* — so applying it would lift blood off the ground and leave it floating
  at chest height. Splatters stay at the death point.
- **`splash_impact`** (mortar crater, `effects.py:534`). Same reason: the crater
  is a scorch mark on the ground at the shell's landing point. It has no owning
  sprite whose anchor could even be read — the ledger carries a bare ground
  coordinate (`ProjectileArc._impact` `:197-201`, **verified**).
- **`building_placed` / `building_level_up` / `building_tier_up`**
  (`effects.py:438`). These are **tile celebrations**, fired from `(col + 0.5,
  row + 0.5)` before any building object is necessarily reachable — and
  `spawn_building_vfx(col, row, kind)` receives no object at all, only
  coordinates. Anchoring them would require a scene lookup for a purely
  decorative burst. Leave them.

### 1.3 The new 10th event: `projectile_hit`

**The plan's ESV-6 goal is "the hit/explosion VFX spawns at the target's impact
anchor" — but after ESV-5 there is no hit event to anchor.** The `impact` anchor
is declared in the schema (`data/schemas/asset_manifest.schema.json`, one of six
keys), exposed by `AssetStore.anchor()`, drawn as a draggable handle by ESV-2's
`AnchorsPanel` — and **read by nothing in `game/`** (**verified** by grep). Wiring
it is precisely this phase's job, and that requires the event.

It also closes the plan's own opening complaint (§1 Track B): *"the `vfx` slot
category has two orphan slots with no consumers and no art."* Those two are
`vfx_hit` and `vfx_explosion`. `projectile_hit` is what finally consumes them.

**It ships INERT** — `{"sprite_slot": "", "procedural": ""}` — exactly like
`defender_fire`. Zero visible change on landing; a designer turns it on. This
follows the decision already taken for `defender_fire` and keeps the ordering
rule intact.

**Trigger site**: `ProjectileHoming._impact()` (`game/enemies/combat.py:105-116`,
**verified**). It already holds `self._target`, so the target — and therefore the
target's `impact` anchor — is in hand at the moment of the hit.

### 1.4 §6 item 1 — the floater dead-data gap (this phase resolves it)

`data/balancing/vfx.json`'s `procedural.floaters` block (7 keys) is **dead data**:
`_params_from_balance` (`effects.py:117`) reads `proc["spark"]`,
`["death_burst"]`, `["muzzle"]`, `["slash"]`, `["gold_highlight"]`,
`["splatter"]`, `["beam"]`, `["crater"]`, `["lightning"]`, `["announce"]` — and
**never** `proc["floaters"]` (**verified**). The live values are module constants
at `game/ui/effects.py:62-70`. Two homes for the same seven values (a G-7
violation ESV-3a introduced); a designer editing them in the editor's `vfx`
domain sees no effect in game.

**Resolution (decided by the user): wire the spawn sites, delete the constants.**
Not the other way round — this matches every other ESV-3a/3b port and makes
floater colours designer-tunable, which is the whole point of the domain.

| Constant | Line | Read site | JSON key (`procedural.floaters.*`) |
|---|---|---|---|
| `_UPKEEP_BLUE` | `:62` | `:295` | `upkeep_color` |
| `_XP_PURPLE` | `:63` | `:307` | `xp_color` |
| `_XP_LIFE` | `:64` | `:307` | `xp_life` |
| `_PAINTER_FINISHED` | `:67` | `:315` | `painter_finished_color` |
| `_PAINTER_LOST` | `:68` | `:315` | `painter_lost_color` |
| `_PAINTER_LIFE` | `:69` | `:317` | `painter_life` |
| `_BOOST_WHITE` | `:70` | `:328` | `boost_color` |

*(Line numbers are pre-ESV-5; re-verify against the current file — ESV-5 grew
`effects.py` substantially.)*

The JSON already ships values **identical** to the constants (**verified**), so
this is a visual no-op.

**⚠ `game/ui/hud.py:53` defines its own `_XP_PURPLE = (168, 105, 222)` — a
DIFFERENT colour**, used for the XP-bar pulse at `hud.py:431`. That is **HUD
chrome, not a floater. Do not touch it and do not unify the two.** If you think
it should be ported later, say so in your report; do not act on it.

---

## 2. Architecture plan

### 2.1 The two handles `_play` still lacks: `cs`

ESV-5 wired `self.assets` and `self.scene` onto `FloaterManager` as host-set
attributes (`effects.py:340-341`, host side `game/main.py:283-284`, **verified**),
following the `self.log` precedent. **ESV-6 needs one more: `self.cs`**, because
`game.anchors.world_offset(assets, cs, obj, name)` requires the coordinate
authority and `watch_enemies(scene)` / `watch_buildings(scene, log)` receive no
`cs` argument.

- `effects.py` `__init__`: add `self.cs = None   # CoordinateSystem, wired by the host`
  beside the ESV-5 pair.
- `game/main.py` `build_gameplay`, in the same `# -- ESV-5 --` fence (rename it
  `ESV-5/6`): `gp["floaters"].cs = cs`. `cs` is in scope — built at `main.py:171`
  and already used by `frame_camera()` inside `build_gameplay` (**verified**).

**`cs` being `None` must degrade to the unanchored point**, never raise —
`world_offset` already returns `(0.0, 0.0)` for a `None` `cs` (**verified**), so
this is free, but pin it with a test: every existing test constructs
`FloaterManager` bare.

**Do NOT change `FloaterManager.__init__`'s signature.** (ESV-3a did, missed a
test module ESV-1 added in parallel, and shipped a textually-clean semantically-
broken merge fixed at integration in `b960d12`.)

### 2.2 Applying the anchor — one helper, not five inline calls

Add one small private method beside `_play`:

```python
def _anchored(self, obj, name, wx, wy):
    """(wx, wy) shifted by `obj`'s manifest `name` anchor. Returns the input
    unchanged when the store/cs/animator/anchor is absent — so a manifest
    with no `anchors` key leaves every caller numerically identical (ESV-1)."""
    dwx, dwy = world_offset(self.assets, self.cs, obj, name)
    return (wx + dwx, wy + dwy)
```

`from game.anchors import world_offset` — `effects.py` already imports
`screen_offset` from that module (`:47`, **verified**), so no new dependency and
no layering change (`game/ui` and `game/enemies` both import `game.anchors`
rather than each other — the ESV-1 §3.3 rule).

Then the two in-file sites become one-liners:

- `watch_enemies` (`:492`/`:495`): `wx, wy = self._anchored(e, "muzzle", *e.transform.world_pos)`
  — computed **once**, before the melee/ranged branch, so both events share it.
- `watch_buildings` (`:459`): `wx, wy = self._anchored(b, "impact", wx, wy)` after
  the existing `b.transform.wx + 0.5, b.transform.wy + 0.5`.

**Do not** duplicate `world_offset`'s math anywhere. It is the one authority
(D2: zoom and pan cancel in the difference of two `screen_to_world` samples).

### 2.3 `defender_fire` — reuse ESV-5's ledger pattern exactly

`_fire` (`combat.py:548-561`) and `_fire_splash` (`:563-…`) **already compute the
muzzle world offset** for the projectile spawn point:
`dwx, dwy = world_offset(assets, cs, defender, "muzzle")` (`:555` and `:583`,
**verified**). **Reuse that value — do not recompute it.**

ESV-5 solved the identical "combat.py can't reach `FloaterManager`" problem with
an optional callback + a `RunState` ledger + a drain method. Copy it verbatim in
shape (**verified** at `combat.py:378`/`:197-201`, `game/core/game_state.py`,
`game/main.py:640-652`/`:704`):

- `resolve_combat(..., on_defender_fire=None)` — a **new optional keyword-only**
  parameter, appended last with a default, threaded to `_fire`/`_fire_splash`.
  Optional, so **zero** existing call sites change (ESV-5's `on_splash_impact`
  proved this: 22 `resolve_combat` call sites, none needed updating).
- `RunState.defender_fire_events` — a new ledger list beside
  `splash_impact_events`.
- `game/main.py`: an `_on_defender_fire(wx, wy)` closure appending to it,
  mirroring `_on_splash_impact` at `:643-644`; and
  `gp["floaters"].spawn_defender_fire_events(session.state)` beside the
  `spawn_splash_impact_events` drain at `:704`.
- `effects.py`: `spawn_defender_fire_events(state)` draining into
  `self._play("defender_fire", wx, wy)`, written exactly like
  `spawn_splash_impact_events` (`:521-534`).

The callback is fired with the **already-anchored** muzzle point, so `_play` needs
no anchor work for this event.

### 2.4 `projectile_hit` — the same pattern, at the impact

`ProjectileHoming` (`combat.py:55-116`) keeps `_target`/`_shooter`/`_scene` as
**transient underscore refs** set in `on_added`/`launch` (E-11 — not serialized,
not declared fields). Add `_assets`/`_cs`/`_on_hit` the same way, set from `_fire`
(which already has `assets`/`cs` in scope) exactly as `_fire_splash` stashes
`arc._on_impact = on_splash_impact` (`:589`, **verified**).

In `_impact()` (`:105`), **after** the existing damage block and **before**
`scene.despawn`, add a cosmetic-only tail:

```python
# ESV-6: the projectile_hit trigger, at the TARGET's impact anchor.
# Purely visual (D4) — reads nothing the damage block above wrote.
```

Compute `world_offset(self._assets, self._cs, target, "impact")` against the
target's live `transform.world_pos` and push the result onto the ledger via
`_on_hit`. Fire it **whether or not the target was still alive** — a hit VFX on a
target that died in the same frame is correct — but guard `target is None`.

Then the same three pieces as §2.3: `RunState.projectile_hit_events`, an
`on_projectile_hit=None` optional parameter on `resolve_combat` threaded to
`_fire`, a `_on_projectile_hit` closure in `main.py`, and
`spawn_projectile_hit_events(state)` in `effects.py`.

**Only the homing path.** The mortar's `ProjectileArc` already has its own
`splash_impact` event (§1.2) — do not give it a second one.

### 2.5 Data: two new inert trigger rows + the schema enum

`data/balancing/vfx.json` `triggers` gains **`projectile_hit`**:
`{"sprite_slot": "", "procedural": ""}`. `defender_fire` already exists and stays
inert — ESV-6 wires its call site, it does not change its row.

`data/schemas/vfx.schema.json`: add `projectile_hit` to the `triggers` properties
+ `required`, reusing ESV-5's `$defs/trigger_row`. The `sprite_slot` enum already
contains `vfx_hit`/`vfx_explosion`, so no enum change is needed — **verify that
and say so**. Write through the validating deterministic writer (sorted keys,
2-space indent, D-3). Mirror into `tools/tests/fixtures/data/` **surgically** —
ESV-5's executor found the pinned fixture snapshot is already stale in unrelated
ways, so a blanket `--refresh` would drag in drift outside this diff.

### 2.6 The floater port (§1.4)

Add a frozen `FloaterParams` dataclass to `engine/vfx/params.py` beside the
existing ones (no defaults — a default is a second home, G-7), add a field to the
`VfxParams` bundle, read `proc["floaters"]` in `_params_from_balance`, re-point
the four read sites, delete the seven constants.

**APPEND only to `engine/vfx/params.py`** — do not rename or reorder anything
ESV-3a/3b exported; `editor/panels/vfx_preview.py` consumes that surface, and
`6a05689` was already an integration fix for exactly this class of break.

`FloaterParams` is numbers only — no game vocabulary in field names beyond the
generic ones the JSON already uses (`upkeep_color`, `xp_life`, … are fine as
JSON keys; keep the dataclass field names equally neutral).

---

## 3. File scope

### May modify

| File | Exact scope |
|---|---|
| `game/ui/effects.py` | §2.1 `self.cs`; §2.2 `_anchored` + the two in-file anchor sites; §2.3/§2.4 the two new drain methods; §2.6 the floater port (delete `:62-70`, extend `_params_from_balance`, re-point 4 read sites). Module docstring gains an ESV-6 paragraph. **Do NOT change `__init__`'s signature.** |
| `game/enemies/combat.py` | §2.3/§2.4 — two new **optional keyword-only** params on `resolve_combat` threaded to `_fire`/`_fire_splash`; the `_impact` cosmetic tail; transient `_assets`/`_cs`/`_on_hit` refs on `ProjectileHoming`. **FORBIDDEN: `launch`'s `origin` parameter, `AOE_TRAVEL_TIME`, `BEAM_MIN_TICK`, `_predict_lead`, `_chebyshev`, every damage/range/splash expression (D4).** |
| `game/core/game_state.py` | two new `RunState` ledger lists beside `splash_impact_events` |
| `game/main.py` | two closures + two drain calls, mirroring `:643-644`/`:704`; `gp["floaters"].cs = cs` in the ESV-5 fence. **Do NOT touch the `:766-780` submit ordering.** |
| `engine/vfx/params.py` | §2.6 — **APPEND** `FloaterParams` + one `VfxParams` field |
| `engine/vfx/__init__.py` | export `FloaterParams`, alphabetical |
| `data/balancing/vfx.json` | §2.5 — one new `triggers` row. **Do not touch `procedural`.** |
| `data/schemas/vfx.schema.json` | §2.5 |
| `tools/tests/fixtures/data/**` | surgical mirror of the two files above only |
| `tools/tests/**` | §4; `conftest.py` `TIERS` entry if you add a module |
| `game/ui/CLAUDE.md` | an **ESV-6** bullet: the anchor map (§1.1), the two exclusions and why (§1.2), the floater port, `self.cs` |
| `game/enemies/CLAUDE.md` | the two new optional callbacks on `resolve_combat` |
| `engine/CLAUDE.md` | `FloaterParams` on the `vfx/` row |
| `data/CLAUDE.md` | the 10th trigger row |
| **`planning/EntitySceneVfxPLAN.md`** | §3.1 below — **this phase is the exception**; every other phase was forbidden from touching it |

### §3.1 Close out the plan doc (ESV-6 only)

1. Line 8's marker → `<!-- status: COMPLETE — 6/6 phases (ESV-1–ESV-6), authored 2026-07-15, completed 2026-07-21 -->`.
2. §4's build-order table: every phase's Status → `done`. Note in the ESV-3 row
   that it landed as ESV-3a + ESV-3b.
3. §6: mark **both** items resolved, naming the phase that resolved each — item 1
   (floater dead data) by ESV-6, item 2 (stack-index reachability) by ESV-5.
4. **Do NOT hand-edit root `PLAN.md`.** The orchestrator re-mirrors it with
   `/setcurrentplan` after this branch merges.

### Must NOT touch

- **`game/ui/hud.py:53`'s `_XP_PURPLE`** — §1.4's warning.
- The three tile-celebration events, `enemy_death`, `splash_impact` — §1.2.
- `ProjectileHoming.launch`'s `origin` parameter and every damage/range/splash
  expression in `combat.py` — **D4**.
- `engine/core/sprite_animator.py`.
- ESV-5's `_play`/`_run_procedural` dispatch logic and the `PlayOnceVfx` module —
  ESV-6 changes only the *coordinates* handed to `_play`, never the dispatch.
- `editor/**` — ESV-2 and ESV-5 already delivered the handles and the panel
  routing; this phase needs no editor change. If you believe it does, **stop and
  report** rather than editing.
- Every `procedural.*` block other than `floaters`.
- Do not reflow `effects.py`/`combat.py`, do not run a whole-file formatter.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py
py tools/testgate.py check          # FULL check — this is the final phase
```

`GATE PASS` or you are not done. **The gate is ZERO.** Use `--affected` while
iterating and run the full `check` **once**, at the end — this is the plan's last
phase, so the full run is the handback gate. Do **not** run a manual `pytest`
sanity pass first; it duplicates the gate. A red test clearly outside this diff's
blast radius: **note it and stop.**

### Required tests

`TempDataCase` / the pinned fixture; never write into `data/`; never assert
against live `data/` content; expectations as **literals**; seed every RNG.

1. **Muzzle-anchored attack VFX** — an enemy whose manifest entry authors
   `muzzle: [dx, dy]` emits its `enemy_attack_ranged` effect at the anchored
   world point; the same enemy with **no** anchor emits at
   `transform.world_pos` **exactly** (assert equality, not approximate). Same for
   `enemy_attack_melee`.
2. **`defender_fire` fires and is anchored** — a defender with a muzzle anchor
   pushes the anchored point onto the ledger; the drain plays the event there.
   With the shipped inert row this must still be a **no-op emit** (the ledger
   fills, `_play` does nothing) — pin BOTH.
3. **`projectile_hit` at the target's impact anchor** — a homing projectile
   landing on a target with `impact: [dx, dy]` pushes the anchored point; with no
   anchor it pushes `transform.world_pos` exactly. Fires when the target dies in
   the same frame.
4. **Guardrail pin (D4) — the most important test in this phase.** Run an
   existing combat/kill scenario twice: once with no anchors, once with a **large**
   `muzzle` AND `impact` anchor authored on both shooter and target. Assert the HP
   ledger, kill count and projectile flight timing are **bit-identical**. The
   anchors must not move a single point of damage.
5. **`None` handles degrade** — `FloaterManager` with `cs=None` (and with
   `assets=None`) emits at the unanchored point and never raises.
6. **Excluded events stay put** — `enemy_death`, `splash_impact` and the three
   building-celebration events emit at their unanchored points **even when the
   entity authors both anchors**. This pins §1.2 against a future "tidy-up".
7. **Floater params come from data** — the four floater spawn sites read
   `procedural.floaters`; editing the temp-dir JSON changes the emitted floater
   colour/lifetime (proves the wiring is live, not dead again). Plus a
   **source-text guard** that none of the seven constant names appears in
   `game/ui/effects.py` any more — the G-7 fence.
8. **Floater default round-trip** — every value under `procedural.floaters` in
   the fixture equals §1.4's table, as literals. The byte-identity contract.
9. **Schema** — the fixture validates with `projectile_hit`; a `triggers` object
   missing it fails; `vfx_hit`/`vfx_explosion` are accepted `sprite_slot` values.
10. **Engine purity** — `TestEnginePurity`'s glob still covers `engine/vfx/`
    after the `params.py` change; the file-count assertion still holds.

### Quick Test (manual)

```bash
py editor/main.py
```
1. Select a **defender** → drag its **muzzle** handle well off-centre → confirm
   the JSON on disk.
2. Import a placeholder 64×64 sheet into `vfx_muzzle`.
3. Set `triggers.defender_fire.sprite_slot = "vfx_muzzle"`. Save.

```bash
py game/main.py
```
4. Build that defender, End Turn: the flash plays **at the dragged handle**, not
   the tile centre. Go back, move the handle, and it follows.
5. Set `triggers.defender_fire.sprite_slot` back to `""` → defenders emit nothing
   again (the shipped state).
6. Import a sheet into `vfx_hit`, set `triggers.projectile_hit.sprite_slot`, drag
   an **enemy's** `impact` handle → shots burst at that point on the target.
7. **The HP ledger and round outcome are unchanged throughout.** Play a round with
   big anchors and one without: same kills, same base HP, same timing.
8. Floaters (income/upkeep/XP/painter/boost) are the **same colours and
   lifetimes** as before. Then edit `procedural.floaters.xp_color` in the editor
   and confirm the XP floater actually changes — that is the gap closing.
9. Every other effect looks exactly as it did.

---

## 5. Notes for the executor

- **The one INFERRED claim in this brief**: §2.4's assertion that
  `ProjectileHoming._impact` is the right hook and that firing on a
  same-frame-dead target is correct. Read `_impact` yourself before wiring it.
- **Report LOUDLY**: any public signature change; whether the `sprite_slot` enum
  already accepted `vfx_hit`/`vfx_explosion`; and anything you had to do in
  `editor/` (the brief says you should not need to).
- **Report, do not fix**: `game/ui/hud.py:53`'s separate `_XP_PURPLE`; the stale
  `tools/tests/fixtures/data/` snapshot ESV-5 flagged.
- This phase closes the plan — **§3.1 is part of the deliverable**, not optional
  housekeeping.
- Tag every claim **measured** / **verified** / **inferred** (`/report`).
