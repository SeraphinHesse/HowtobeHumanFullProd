# Phase ESV-3b — Scene-object + continuous VFX → `engine/vfx/`, params → `data/balancing/vfx.json`

Source plan: `planning/EntitySceneVfxPLAN.md` §ESV-3. ESV-3 was split by file
ownership: **ESV-3a (LANDED, merged) owns the particle / gold / splatter / slash
/ floater-style effects. ESV-3b (this brief) takes the STATEFUL + CONTINUOUS
effects — the Sun Scorcher beam, the mortar crater, the lightning bolt + ground
marker, and the boss announce banner.**

**Open with these skills, do not hand-roll:** `/add-balancing-value` for the new
keys inside `procedural`, `/add-engine-component` if you add a module under
`engine/vfx/`.

**Landing condition: byte-identical.** Today's constants become the shipped JSON
defaults. Nothing changes on screen. Any pixel difference is a bug in this
phase, not a design choice.

**Read ESV-3a's brief first** — `docs/briefs/phase-esv-3a-vfx-emitters.md`. Its
patterns (`_params_from_balance`, `_ramp`, `_color`, named-stop ramps, injected
`rng=random`, the source-text purity scan) are established and PROVEN; this
phase extends them, it does not re-litigate them.

---

## 1. Behavioral spec

### 1.1 Where the behaviour lives today (all line numbers **verified** post-merge)

`game/ui/effects.py` is 682 lines. This phase's four draw functions:

| Effect | Function | Constants |
|---|---|---|
| Sun Scorcher beam (continuous) | `submit_beams` `:448-469` | `_BEAM_COLORS` `:61` |
| Mortar crater (scene object) | `submit_craters` `:471-483` | `_CRATER_COLOR` `:62` |
| Lightning bolt + flash + marker (scene object) | `submit_lightning` `:487-538` | `_BOLT_SEGMENTS` `:82`, `_BOLT_JITTER` `:83`, `_BOLT_WHITE` `:84`, `_BOLT_YELLOW` `:85`, `_LIGHTNING_MARKER` `:86` |
| Boss announce banner (stateful) | `spawn_boss_events` `:620-630` + `submit_announce` `:632-656` | `_ANNOUNCE_RED` `:65` |

The two scene-object effects own their state OUTSIDE `effects.py`:
- `game/enemies/combat.py`: `CRATER_LIFE = 1.0` `:43`, `CraterFade` `:191-209`
  (`life: float = CRATER_LIFE` `:197`), `Crater(GameObject)` `:212-233`,
  constructed at `:173` inside `ProjectileAOE`'s impact (**verified** — ESV-1
  shifted this file; these are the post-ESV-1 lines).
- `game/core/lightning.py`: `BOLT_LIFE = 0.5` `:32`, `MARKER_LIFE = 1.0` `:33`,
  `LightningFXFade` `:115-132`, `LightningFX(GameObject)` `:135-164`,
  constructed at `:109` inside `strike()`.

The announce's **timings** already live in data (`ui.json` `FX.boss_announce`
`.fade_in/.hold/.fade_out/.enabled`, read `effects.py:232`, `:388`, `:628`,
`:640-648`) — **do not move them.** Only the colour and the alpha ceiling are
un-datafied.

Host draw order (`game/main.py:766-780`, **verified**) — load-bearing, preserve
exactly:

```
766 submit_splatters      (world overlay, ESV-3a)
767 submit_gold_highlights(world overlay, ESV-3a)
769 submit_craters        (world overlay)   <-- ESV-3b
770 submit_lightning      (world overlay + HUD bolt, interleaved internally)
772 submit_beams          (HUD)             <-- ESV-3b
773 submit_hp_bars        (HUD, ESV-1)
774 submit_enemy_hp_bars  (HUD, ESV-1)
776 submit_projectiles    (HUD)
777 submit_fx             (HUD, ESV-3a)
778 submit_boss_bars      (HUD)
780 submit_announce       (HUD, topmost)    <-- ESV-3b
```

### 1.2 The complete tunable table

Every row: today's value (**verified**, cited) → its key under `procedural` in
`data/balancing/vfx.json`. The JSON default MUST equal the "today" column
exactly. **Inline literals are tunables too** — they are the majority here.

#### `procedural.beam` — Sun Scorcher (`effects.py:61`, `:448-469`)

| Today | Value | JSON key |
|---|---|---|
| `_BEAM_COLORS` `:61` | `((255,200,40),(255,110,15),(210,20,10))` | `beam.colors` (**named-stop object**, see §2.5) |
| inline `width=2 + tier` `:469` | `2` | `beam.width_base` |
| inline `top = tile_h * zoom` `:466` | `1.0` | `beam.origin_lift_tiles` |

`min(tier, len(colors) - 1)` `:462` is a clamp, not a tunable — with the
named-stop ramp the length is fixed at 3, so the clamp stays literal `2` derived
from the 3-stop shape. State that in a comment; do not add a `tier_max` key.

#### `procedural.crater` — mortar scorch (`effects.py:62`, `:471-483`; `combat.py:43`)

| Today | Value | JSON key |
|---|---|---|
| `_CRATER_COLOR` `effects.py:62` | `(120,78,66)` | `crater.color` |
| inline `int(150 * frac)` `effects.py:483` | `150` | `crater.alpha` |
| `CRATER_LIFE` `combat.py:43` | `1.0` | `crater.life` (see §2.3 — signature decision) |

The `+0.5` tile centring and the 4-point diamond `:480-481` are iso geometry,
not tunables.

#### `procedural.lightning` — bolt + flash + marker (`effects.py:82-86`, `:487-538`; `lightning.py:32-33`)

| Today | Value | JSON key |
|---|---|---|
| `_BOLT_SEGMENTS` `:82` | `8` | `lightning.bolt_segments` |
| `_BOLT_JITTER` `:83` | `6` | `lightning.bolt_jitter_px` |
| `_BOLT_WHITE` `:84` | `(255,255,255)` | `lightning.bolt_color_start` |
| `_BOLT_YELLOW` `:85` | `(255,240,80)` | `lightning.bolt_color_end` |
| inline `width=2` `:515` | `2` | `lightning.bolt_width` |
| inline `20.0` flash radius px `:520` | `20.0` | `lightning.flash_radius_px` |
| inline `(255,250,200)` `:527` | `(255,250,200)` | `lightning.flash_color` |
| inline `int(200 * bolt)` `:527` | `200` | `lightning.flash_alpha` |
| `_LIGHTNING_MARKER` `:86` | `(255,240,120)` | `lightning.marker_color` |
| inline `int(120 * frac)` `:535` | `120` | `lightning.marker_fill_alpha` |
| inline `width=2` `:538` | `2` | `lightning.marker_outline_width` |
| `BOLT_LIFE` `lightning.py:32` | `0.5` | `lightning.bolt_life` (see §2.3) |
| `MARKER_LIFE` `lightning.py:33` | `1.0` | `lightning.marker_life` (see §2.3) |

`0.7071` `:521` is `cos 45°` — octagon geometry, NOT a tunable. `/ (tile_w /
2.0)` `:520` is the same screen-px→world-unit conversion ESV-3a kept literal for
`splatter.radius_px` (brief §1.3) — follow that precedent: `flash_radius_px`
stays a screen-pixel value and the division stays inline.

#### `procedural.announce` — boss banner (`effects.py:65`, `:632-656`)

| Today | Value | JSON key |
|---|---|---|
| `_ANNOUNCE_RED` `:65` | `(220,40,40)` | `announce.color` |
| inline `int(255 * k)` `:650` | `255` | `announce.max_alpha` |

**Not ported:** `_ANNOUNCE_L1`/`_L2` `:66-67` are UI COPY, and copy is the
screen-skinning system's territory (`data/ui/screens/*.json` `label` overrides —
`game/ui/CLAUDE.md` "UI screen customization"). Putting strings in a *balancing*
domain would create a second home for label text. Leave them at `:66-67`.
The `int(...)` truncation, the `layout_h("xl")` positioning and the `+6`/`+8`
offsets `:653-655` are HUD layout, out of scope.

### 1.3 The phase's main trap: which timings are cosmetic

`game/enemies/combat.py` also holds `AOE_TRAVEL_TIME = 0.55` `:42` and
`BEAM_MIN_TICK = 0.02` `:44` (**verified**). These are **SIMULATION TIMING, NOT
COSMETICS** — `AOE_TRAVEL_TIME` decides when a shell's damage lands and feeds
`_predict_lead`'s target lead (`combat.py:518-522`); `BEAM_MIN_TICK` is the beam
damage tick-rate floor (`:475`). Moving either into `vfx.json` would put a
gameplay number in a cosmetics domain and breach guardrail **D4**. **Do not
touch them, do not add keys for them, do not "tidy" them into the same block as
`CRATER_LIFE` just because they are three lines apart.**

`CRATER_LIFE`, `BOLT_LIFE` and `MARKER_LIFE` are pure fade timings: nothing
reads them except a despawn clock on a cosmetic-only GameObject that carries no
Health, no damage and no tag any gameplay query reads
(`combat.py:191-233`, `lightning.py:115-164`). They port.

### 1.4 Explicitly out of scope (do not touch)

- **HUD chrome stays in `game/ui/`**: `submit_hp_bars` `:542-564`,
  `submit_enemy_hp_bars` `:566-616`, `submit_boss_bars` `:658-682`,
  `submit_projectiles` `:423-439`, `submit` (floater text) `:396-406`,
  `_sprite_top` `:178-202`. Their constants `_BOSS_HUD_BAR_W/H` `:68`,
  `_BOSS_HUD_BAR_LIFT` `:69`, `_ENEMY_BAR_STACK` `:76`, `_ENEMY_BAR_FALLBACK`
  `:77`, `_PROJECTILE_STONE` `:92`, `_PROJECTILE_SHELL` `:93` stay put.
- **ESV-3a's territory**: `_params_from_balance` `:111-175`, `_ramp` `:101-108`,
  `_color` `:97-98`, `FloaterManager.spawn_*`, `watch_*`,
  `submit_splatters`/`submit_gold_highlights`/`submit_fx`, and everything under
  `engine/vfx/` that already exists. Read them as the pattern; extend, do not
  rewrite.
- `ui.json` `FX.boss_announce` timings (§1.1).
- `planning/EntitySceneVfxPLAN.md` and root `PLAN.md` — out of scope for every
  phase agent; the coordinator updates the build-order table once, at the end.

### 1.5 Investigation result (report-only, **do not act**)

**The floater constants at `game/ui/effects.py:48-56` are LIVE code, and
`procedural.floaters` in `data/balancing/vfx.json` is DEAD data. This is a
genuine gap in ESV-3a's port, not dead constants and not a fallback.**
(**verified**, three ways:)

1. `_UPKEEP_BLUE` `:48` is read at `:251`; `_XP_PURPLE`/`_XP_LIFE` `:49-50` at
   `:263`; `_PAINTER_FINISHED`/`_PAINTER_LOST`/`_PAINTER_LIFE` `:53-55` at
   `:271-273`; `_BOOST_WHITE` `:56` at `:284`. Every one is on a live spawn
   path.
2. `_params_from_balance` `:111-175` reads `proc["spark"]`, `["death_burst"]`,
   `["muzzle"]`, `["slash"]`, `["gold_highlight"]`, `["splatter"]` — and
   **never** `proc["floaters"]`.
3. `data/balancing/vfx.json:33-61` ships the full `floaters` block
   (`upkeep_color`, `xp_color`, `xp_life`, `painter_finished_color`,
   `painter_lost_color`, `painter_life`, `boost_color`) with values identical to
   the constants — written, schema-valid, and read by nothing at runtime.

So the seven values have **two homes** (a G-7 violation ESV-3a introduced), and
a designer editing them in the editor's new `vfx` domain will see no effect
in-game. It is byte-identical today precisely *because* the JSON is inert.

**ESV-3b does not fix this** — it is ESV-3a's table, and the fix is a
four-line-ish read at `:251/:263/:271-273/:284` plus a `floaters` branch in
`_params_from_balance`. Surface it to the orchestrator as a follow-up
(ESV-3a-fixup or a `/smalltweak`). Executor: **do not touch `:48-56` or
`proc["floaters"]`.**

---

## 2. Architecture plan

### 2.1 How each effect maps onto ESV-3a's shape

ESV-3a's shape is: frozen param dataclasses in `engine/vfx/params.py` → pure
`emit_*(rng, …)` functions in `emitters.py` → mutable objects in `particle.py`
→ `VfxSystem` owns the lists, `update(dt)`, and TWO submit passes
(`system.py:1-14`, **verified**). **Not every ESV-3b effect fits that mould, and
forcing them into it would be wrong.** Three distinct categories:

| Effect | Category | Where it fits |
|---|---|---|
| beam | **stateless draw over live scene state** | params only; the draw reads `BeamAttacker._target` fresh every frame and owns no list |
| announce | **manager-owned scalar clock** | params only; `_announce_age` `:233` stays on `FloaterManager` (its timings are `ui.json`, §1.1) |
| crater | **scene-object** | params for the draw; `life` is on the `CraterFade` component in `game/enemies` |
| lightning | **scene-object + per-frame RNG** | params for the draw; `bolt_life`/`marker_life` on `LightningFXFade` in `game/core` |

**Consequence: `VfxSystem` gains NO new lists and NO new `update(dt)` work in
this phase.** Do not invent an `engine/vfx` object to mirror `Crater` /
`LightningFX` — the scene already owns them, they already age in `scene.update`,
and a parallel engine-side list would be a second source of truth for the same
fade. What the engine gains is **params + (optionally) the pure geometry
helpers**, nothing stateful.

Recommended shape (executor may refine; keep one dataclass per §1.2 table):

```python
# engine/vfx/params.py — frozen, NO defaults (a default is a second home, G-7)
BeamParams(colors, width_base, origin_lift_tiles)
CraterParams(color, alpha, life)
LightningParams(bolt_segments, bolt_jitter_px, bolt_color_start,
                bolt_color_end, bolt_width, bolt_life,
                flash_radius_px, flash_color, flash_alpha,
                marker_color, marker_fill_alpha, marker_outline_width,
                marker_life)
AnnounceParams(color, max_alpha)
```

and four new fields on the existing `VfxParams` bundle (`params.py`, ESV-3a).
`VfxParams` is where `FloaterManager` already holds everything
(`effects.py:243`), so the four new blocks arrive through the same
`_params_from_balance` return value with **no `FloaterManager.__init__`
signature change** — see §3's shared-file contract, this matters.

**Where the submit bodies live is a genuine choice, and the two are not equal.**
ESV-3a moved its submit bodies onto `VfxSystem` because it also moved the
*state*. Here there is no state to move. Recommended: **`submit_beams` /
`submit_craters` / `submit_lightning` / `submit_announce` KEEP their bodies in
`effects.py`** and read `self._vfx_params.beam/.crater/.lightning/.announce`
instead of module constants. Rationale: they read `scene.by_tag(...)`,
`BeamAttacker`, `TierState` and `layout_h` — game vocabulary the engine must not
learn (`engine/CLAUDE.md` "No game-specific names in the engine"; ESV-3a brief
§2.2). Pushing them into `engine/vfx/system.py` would drag `by_tag("crater")`
and `BeamAttacker` across the layer boundary. **If the executor instead extracts
the pure GEOMETRY** (e.g. `emitters.bolt_points(rng, sx, sy, params)` returning
a point list, `emitters.diamond(wx, wy, r)`), that is welcome and stays pure —
but the `scene` iteration and the component reads stay on the game side.

### 2.2 Per-effect RNG draw order (required — parity tests cannot be written without it)

Only **lightning** draws. **verified** at `effects.py:505-509`:

```
per LightningFX object, per FRAME, while bolt_frac > 0:
    for i in range(bolt_segments + 1):        # 9 iterations at the default 8
        if 0 < i < bolt_segments:             # i = 1..7
            rng.uniform(-bolt_jitter_px, +bolt_jitter_px)   # ONE draw
        # i == 0 and i == bolt_segments draw NOTHING (jitter = 0.0)
```

⇒ **exactly `bolt_segments - 1` = 7 `uniform` draws per bolt per frame**, in
ascending `i` order, and the endpoints are un-jittered. Get this wrong by one
draw and the whole global stream shifts for every other effect.

Two properties that follow and MUST be preserved:

- **The RNG is consumed at SUBMIT time, not emit time.** This is unlike every
  ESV-3a effect (which draws once at emit). A bolt re-rolls its jitter every
  rendered frame — that shimmer IS the effect. Any refactor that caches the
  points on the FX object would change the visual and fail the Quick Test.
- **`rng` must be the stdlib `random` MODULE**, exactly as ESV-3a passes it
  (`effects.py:244`, `VfxSystem(vfx_params, rng=random)`, **verified**; the
  reasoning is spelled out at `:239-242`). A fresh `random.Random()` would pass
  every seeded test while silently diverging in the live game, because the
  global stream that `submit_lightning` shares with ESV-3a's emitters would no
  longer interleave the same way. Thread the SAME rng object
  `FloaterManager` already holds; do not create a second one.
  - Practical consequence: `submit_lightning` currently calls the module-level
    `random` directly (`:507`). Route it through the injected rng (e.g.
    `self._vfx.rng`, or keep a `self._rng = random` beside `self._vfx`) so a
    seeded test can pin it. `import random` `:30` **stays** either way.

Beam, crater and announce draw ZERO random numbers. Say so in their tests — a
future refactor that adds a draw is a behaviour change.

### 2.3 Scene-object effects: where the lifetime params get injected — **DECISION REQUIRED**

This is the phase's real architectural cost and the executor must not paper over
it.

`crater.life`, `lightning.bolt_life` and `lightning.marker_life` are consumed by
**component defaults on GameObjects constructed deep inside gameplay code**, far
from any `vfx_balance` handle:

- `Crater(self._gx, self._gy, self.radius)` — `combat.py:173`, inside
  `ProjectileAOE`'s impact. `CraterFade.life` defaults to the module constant
  (`combat.py:197`). The only public entry point above it is
  `resolve_combat(scene, tilemap, dt, buildings_balance, …)`.
- `LightningFX(wx, wy, radius_tiles)` — `lightning.py:109`, inside `strike()`.
  `LightningFXFade` has NO `life` field at all; `bolt_frac`/`fade_frac`
  `:157-164` read the module constants directly.

**Measured blast radius (`grep`, whole repo):** `resolve_combat` has **22 call
sites** — `game/main.py:634` plus 21 across 13 test modules (`test_boss`,
`test_combat_anchors`, `test_combat_speed`, `test_death_spawn`,
`test_defence_aoe_beam`, `test_enemies`, `test_levelup`, `test_lightning`,
`test_painter_meditator`, `test_phase_loop`, `test_scenarios`). `strike` is
reached via `Session.lightning_strike` (`game/main.py:410`).

Two options, both real:

- **Option A (recommended if the orchestrator green-lights the churn)** — thread
  the values as **required** constructor arguments down the existing chain:
  `CraterFade(radius=…, life=…)` fed from a `crater_life` carried on
  `ProjectileAOE` (set at `_fire_splash`), fed from a new required
  `resolve_combat(..., vfx_balance)` parameter; `LightningFXFade` gains
  `bolt_life`/`marker_life` fields fed from a new required `strike(..., vfx)`
  argument, threaded from `Session` (which the host constructs once). No
  `None`-defaulted optional — that IS a code-side default and re-creates the
  two-homes problem (G-7). **Cost: 22 call sites to update, in 13 test modules,
  while ESV-2 and ESV-4 run concurrently.**
- **Option B** — ESV-3b ports the DRAW params only (colours/alphas/widths/
  segments/jitter/flash), and the three lifetimes stay module constants with a
  follow-up phase owning the plumbing. Cheap, zero signature churn, but leaves
  three cosmetic numbers un-datafied and the phase's stated goal partly unmet.

**Executor instruction:** attempt **Option A**. The moment the diff to
`tools/tests/` exceeds mechanical argument-threading — i.e. if a test's
*meaning* has to change, not just its call — **STOP and report** rather than
inventing an optional default. Do NOT silently fall back to Option B; that is
the orchestrator's call.

**If you change ANY signature or public attribute path** (`resolve_combat`,
`strike`, `CraterFade`, `LightningFXFade`, `Crater`, `LightningFX`,
`FloaterManager`, `Session`):

1. `grep` the **whole** of `tools/tests/` for every construction/call site and
   update **all** of them. ESV-3a made `vfx_balance` a required third
   `FloaterManager` arg, updated the test modules on its own branch, and missed
   `tools/tests/test_hp_bar_anchors.py` — which ESV-1 added in parallel. The
   merge was textually clean and semantically broken; it was fixed at
   integration in `b960d12`.
2. **Report the signature change LOUDLY** in the final report — a dedicated
   section, not a footnote — so the orchestrator can propagate it to ESV-2 and
   ESV-4, which are running concurrently.

### 2.4 D5 engine purity

`engine/vfx/` must NOT: import `game.*` / `editor.*` / `engine.data_io` / a
balancing loader; `import json` or `from json`; call `open(`; import `pygame`;
or carry game vocabulary in names. The four new param dataclasses are numbers
only — no `scorcher`, no `mortar`, no `boss`. `beam`/`crater`/`lightning`/
`announce` are generic VFX nouns and are fine.

**Extend ESV-3a's source-text scan**, `TestEnginePurity` in
`tools/tests/test_vfx.py:194-221` (**verified**): it globs `engine/vfx/*.py` and
asserts none of `open(`, `import json`, `from json`, `import pygame`,
`from pygame`, `engine.data_io`, `import game`, `from game`, `import editor`,
`from editor` appears in the literal text. If you add a module it is covered
automatically by the glob — **confirm that and say so**; if you add a
subpackage, widen the glob to `**/*.py`.

### 2.5 Colour ramps MUST be named-stop objects

`_BEAM_COLORS` `:61` is a 3-tier ramp, so this applies directly.
`editor/panels/balancing.py`'s `_build_array` has no widget for an array item
that is itself an array and raises `ValueError`, crashing the balancing panel
for the whole domain. Use the existing `$defs/ramp` shape —
`{"stop_0": [...], "stop_1": [...], "stop_2": [...]}` — already defined at
`data/schemas/vfx.schema.json:15-34` (**verified**) and already consumed by
`_ramp` `effects.py:101-108`. `beam.colors` reuses `$defs/ramp` and `_ramp`
verbatim; the tier index maps `stop_0`→tier 0, `stop_1`→tier 1,
`stop_2`→tier 2+.

`lightning.bolt_color_start`/`bolt_color_end` are two independent `$defs/color`
values, not a ramp — they are interpolated by `progress` at `:512-514`, not
indexed by stop. Keep them separate; a ramp object would imply a third stop that
does not exist.

### 2.6 Loading — no new plumbing

`vfx` is already a balancing domain (`game/core/balance.py` `DOMAINS`, ESV-3a);
`game/main.py` already loads it and passes it to `FloaterManager`
(`effects.py:226`, `main.py:264`, **verified**). ESV-3b adds keys **inside** the
existing `procedural` object and new branches inside `_params_from_balance`
`:111-175`. **Do not add a new top-level key** — ESV-5 later adds `triggers` as
the only other top-level sibling. `tools/smoke.py` validates by stem convention,
so no smoke.py edit.

---

## 3. File scope + shared-file contract

**Concurrent phases: ESV-2 and ESV-4 are EDITOR-ONLY** (`editor/panels/…`,
`editor/anchor_ops.py`, `editor/panels/vfx_preview.py` per
`planning/EntitySceneVfxPLAN.md` §ESV-2/§ESV-4). They do not touch `game/` or
`engine/vfx/` source — **but ESV-4 CONSUMES `engine/vfx/`'s public surface for
its live preview.** Therefore: **you may ADD to `engine/vfx/`'s exports; you may
not RENAME or RESHAPE anything ESV-3a exported.** If you believe an existing
dataclass field must change, stop and report — that is a cross-phase break.

### May create

| Path | Contents |
|---|---|
| (optional) a new `engine/vfx/` module | only if the geometry helpers warrant it; `params.py` may simply grow |
| (optional) `tools/tests/test_vfx_scene.py` | §4 tests; extending `tools/tests/test_vfx.py` is equally acceptable |

### May modify — exact insertion points

| File | Exact scope |
|---|---|
| `engine/vfx/params.py` | **APPEND** `BeamParams`/`CraterParams`/`LightningParams`/`AnnounceParams` + four fields on `VfxParams`. Do not reorder or rename existing dataclasses/fields (ESV-4 reads them). |
| `engine/vfx/__init__.py` | add the four names to the imports + `__all__` (keep alphabetical — `:16-38`) |
| `engine/vfx/emitters.py` | **only** if you extract pure geometry (`bolt_points`, `diamond`); append, never rewrite `emit_*` |
| `game/ui/effects.py` | DELETE constants `:61-62`, `:65`, `:82-86` (leave `:66-67` `_ANNOUNCE_L1/L2`, leave `:68-77`, `:92-93`); extend `_params_from_balance` `:111-175` with four blocks (append inside, before the `return` `:173`); bodies of `submit_beams` `:448-469`, `submit_craters` `:471-483`, `submit_lightning` `:487-538`, `submit_announce` `:632-656`; the module docstring's ESV-3a paragraph `:20-28` gains an ESV-3b sentence; `FloaterManager.__init__` `:226-245` may store the new params — **do NOT change its signature** (§2.3 rule 1) |
| `data/balancing/vfx.json` | four new sibling keys **inside** `procedural` (which today holds `death_burst`, `floaters`, `gold_highlight`, `muzzle`, `slash`, `spark`, `splatter` — `:2-197`, **verified**). Deterministic writer only (sorted keys, 2-space indent, D-3) |
| `data/schemas/vfx.schema.json` | four sibling subschemas under `procedural.properties` + `required`; reuse `$defs/color` `:3-14` and `$defs/ramp` `:15-34` |
| `game/enemies/combat.py` | **Option A only** — `CRATER_LIFE` `:43`, `CraterFade.life` `:197`, `Crater.__init__` `:217-223`, the `Crater(...)` call `:173`, `ProjectileAOE`'s param carry, `resolve_combat`'s signature. **`AOE_TRAVEL_TIME` `:42` and `BEAM_MIN_TICK` `:44` are FORBIDDEN (§1.3).** |
| `game/core/lightning.py` | **Option A only** — `BOLT_LIFE`/`MARKER_LIFE` `:32-33`, `LightningFXFade` `:115-132`, `LightningFX.__init__` `:140-146`, `bolt_frac`/`fade_frac` `:156-164`, `strike`'s signature `:86` |
| `game/core/session.py` | **Option A only** — thread `vfx_balance` to `lightning_strike` / `resolve_combat`'s caller |
| `game/main.py` | **Option A only** — the `resolve_combat` call `:634` and the `Session` construction. `vfx_balance` is already loaded and in scope. **Do NOT touch the `:766-780` submit ordering.** |
| `tools/tests/**` | every call site of any signature you change (§2.3) |
| `tools/tests/test_vfx.py` | extend `TestEnginePurity` `:194-221` coverage confirmation; add §4 tests here or in a sibling module |
| `tools/tests/conftest.py` | a `TIERS` entry **if** you add a new test module (required — `test_tiers.py` fails without it) |
| `game/ui/CLAUDE.md` | the "Defence FX (10B)" + "Lightning + cheat menu UI (10H)" + "Boss UI (10G)" sections gain an ESV-3b note (params now in `data/balancing/vfx.json`) |
| `engine/CLAUDE.md` | the `vfx/` subsystem row gains the scene-object params |
| `data/CLAUDE.md` | the ESV-3a `vfx` paragraph's "ESV-3b adds keys inside the same `procedural` object" sentence becomes past tense + names the four blocks |

### Must NOT touch

- `game/ui/effects.py:48-56` (the floater constants) and
  `procedural.floaters` — **report only**, §1.5.
- `submit_hp_bars` `:542-564`, `submit_enemy_hp_bars` `:566-616`, `_sprite_top`
  `:178-202`, `submit_boss_bars` `:658-682`, `submit_projectiles` `:423-439`,
  `submit` `:396-406` and their constants (§1.4).
- `_params_from_balance`'s EXISTING six blocks `:121-171`, `_ramp` `:101-108`,
  `_color` `:97-98`, `FloaterManager.spawn_*`/`watch_*`,
  `submit_splatters`/`submit_gold_highlights`/`submit_fx`.
- `combat.py:42` `AOE_TRAVEL_TIME`, `combat.py:44` `BEAM_MIN_TICK` — **D4**.
- `ui.json` `FX.boss_announce`; `_ANNOUNCE_L1`/`_L2` `:66-67`.
- Anything under `editor/` (ESV-2 + ESV-4 own it).
- `planning/EntitySceneVfxPLAN.md`, root `PLAN.md`.
- Do not reflow `game/ui/effects.py`, do not run a whole-file formatter, do not
  renumber constants outside §1.2's tables — ESV-1's HP-bar ranges landed
  recently and a reflow would churn them for nothing.

### Schema requirements (`data/schemas/vfx.schema.json`)

- Every numeric key carries `description` + `minimum` + `maximum` (D-12) — the
  editor derives spinbox ranges from them (ED-30). The existing file is the
  house pattern.
- Colours: `$ref: "#/$defs/color"`. The beam ramp: `$ref: "#/$defs/ramp"`. Do
  NOT introduce an array-of-arrays (§2.5).
- `additionalProperties: false` at every object level; all keys `required`.
- Bounds policy per `data/CLAUDE.md`: alphas 0–255, seconds 0–60, pixels ±4096,
  counts 0–10000. `bolt_segments` `minimum: 2` (a 1-segment bolt has no jitter
  point and degenerates to a straight line — say so in the `description`).

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py                        # data validation + 5-frame headless boot
py tools/testgate.py check --affected    # blast radius ∪ core tier
```

**NOT the full suite** — `--affected` is the gate for this phase. `GATE PASS` or
you are not done. A red test clearly outside this diff's blast radius: note it
in the report and stop.

*(Caveat the executor should watch for: under Option A the diff's blast radius
includes `resolve_combat`, so `--affected` will pull in most of the combat
tests. That is expected and correct — it is not a reason to narrow the gate.)*

### Required tests

Every test uses `TempDataCase` / the pinned `FIXTURE_DATA` snapshot
(`tools/tests/fixture_data.py`, the ESV-3a pattern at `test_vfx.py:23-24`),
never writes into `data/`, and **never asserts against live `data/` content**.
**Never re-read the JSON you are validating** — encode expectations as literals,
exactly as `test_vfx.py:44-60` does (`MUZZLE = MuzzleParams(life=0.20, …)`).

1. **Seeded parity, lightning bolt** (the strict one). With
   `random.Random(seed)` and literal `LightningParams`, assert the bolt point
   list equals independently computed expected points, and — the load-bearing
   part — that **exactly `bolt_segments - 1` = 7 `uniform` calls** were consumed,
   with `i == 0` and `i == bolt_segments` un-jittered (§2.2). Assert the
   endpoints' x equals `int(sx)` exactly. Also pin that a SECOND submit of the
   same FX object re-rolls (different points) — the shimmer is the effect.
2. **Seeded parity, bolt colour fade** — at `bolt_frac` 1.0, 0.5 and 0.0 the
   colour equals the literal expected tuple from
   `int((w + (yl - w) * (1 - bolt)) * bolt)` per channel. Zero RNG draws.
3. **Beam parity** — for tiers 0/1/2/3 the colour is `stop_0/stop_1/stop_2/
   stop_2` (the clamp) and the width is `2 + tier`. Zero RNG draws.
4. **Crater + marker alpha parity** — at `frac` 1.0/0.5/0.0 the submitted
   polygon colour is `crater.color + (150/75/0,)` and the lightning marker
   `marker_color + (120/60/0,)`. Zero RNG draws.
5. **Announce parity** — at `k` 1.0/0.5/0.0 the colour is
   `announce.color + (255/127/0,)`; the two banner strings are still
   `_ANNOUNCE_L1`/`_L2` from the module (pinning §1.2's "copy stays put"
   decision). Zero RNG draws.
6. **Lifetime round-trip (Option A only)** — a `Crater` built through the real
   path fades to 0 at `crater.life`; a `LightningFX` at `bolt_life` /
   `marker_life`. Plus a **negative** assertion that `AOE_TRAVEL_TIME` and
   `BEAM_MIN_TICK` are still module constants in `game/enemies/combat.py` and
   appear NOWHERE in `data/balancing/vfx.json` — a source-text guard, the D4
   fence (§1.3). **Write this test even under Option B.**
7. **Purity scan extended** — confirm `TestEnginePurity`
   (`test_vfx.py:194-221`) covers every new `engine/vfx/` module (its glob
   should do so automatically; assert the scanned file COUNT matches the
   package's actual module count so a subpackage cannot slip past the glob).
8. **Schema completeness** — every `"type": "integer"|"number"` leaf under the
   four new blocks carries `description`, `minimum` and `maximum` (D-12). The
   existing generic walker in `test_vfx.py` may already cover the whole file —
   **verify it does and say so** rather than duplicating it.
9. **Default round-trip** — every value under `procedural.beam/.crater/
   .lightning/.announce` in the fixture equals §1.2's "today" column, stated as
   literals in the test. This is the byte-identity contract in test form.

### Quick Test (in-game, manual)

```bash
py game/main.py
```

1. Build a **Sun Scorcher**, End Turn, let it engage: the beam is the same
   yellow line at tier 1, thickening and shifting orange→red as you tier it up,
   starting one tile-height above the building's centre, vanishing the instant
   its target dies.
2. Build a **mortar** (splash defender), let it fire: each shell leaves the
   brown ground diamond that fades out over ~1 s. Same colour, same size, same
   fade curve as on `Development`.
3. Place a **Storm Priest** to unlock lightning, then click to strike during
   ENEMY: the jagged white→yellow bolt from the top of the screen (**it must
   still shimmer frame to frame** — a static bolt means the RNG moved to emit
   time), the expanding pale impact flash, and the yellow ground diamond fading
   over ~1 s at the real blast radius.
4. Reach a **boss round** (or `Ctrl+L` → goto round 10): the red "SOMETHING BIG
   / IS APPROACHING!" banner fades in, holds and fades out on the same timings,
   same red, same position.
5. Every one of the above must look **unchanged from `Development`.** If
   anything reads faster, denser, brighter, thicker or differently coloured, the
   port is wrong — that is the whole acceptance criterion for this phase.

---

## 5. Notes for the executor

- **The one INFERRED claim in this brief**: that `submit_beams`/`submit_craters`
  /`submit_announce` consume zero RNG. Read them yourself before writing test
  3/4/5 — it is a two-minute confirmation and the tests are worthless if it is
  wrong.
- **`beam.origin_lift_tiles` = 1.0 is a judgement call.** `:466` reads
  `int(cs.geometry.tile_h * cs.camera.zoom)` with no literal multiplier; I am
  making the implicit `1.0` explicit so the "crystal-ball height" becomes a
  lever. If you would rather leave it as geometry (like `+0.5` tile centring),
  say so in your report — but then say so *explicitly*, do not silently drop the
  key.
- **Report, do not fix**: the `procedural.floaters` dead-data finding (§1.5).
- **Report LOUDLY**: any signature change (§2.3), so the orchestrator can
  propagate to ESV-2/ESV-4.
- Tag every claim in your report **measured** / **verified** / **inferred**
  (`/report`).
