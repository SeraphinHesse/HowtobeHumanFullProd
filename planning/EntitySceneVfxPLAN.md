<!-- status: NOT STARTED — 0/6 phases (ESV-1–ESV-6), authored 2026-07-15 -->

# EntitySceneVfxPLAN.md — Entity Scene Editor + VFX System

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/EntitySceneVfxPLAN.md ESV-1-ESV-6` or
phase-by-phase. Four packages: **data · engine · game · editor**. Design brief
(verified current-state + decisions): the published artifact
`Entity Scene Editor + VFX System — Design Brief`.

## 1. Vision

Two editor capabilities on one plan, both following the same arc — **lift a
hardcoded value into `data/`, give it a handle/lever in the editor viewport,
teach the game to read it back**:

- **Track A — Entity Scene Editor.** When a designer selects an entity (a
  building level or an enemy) in the editor's entity-preview viewport, its
  **attach points** appear as **draggable handles**: the muzzle a defender
  fires from, the impact point where a hit lands, the overhead HP-bar position,
  and other attach points (floater origin, status-icon, beam endpoint). Drag =
  authoring; the game then fires, bars and impacts from those points. Today all
  of these are hardcoded in Python (`combat.py:475` fires from the tile centre
  with **no** muzzle offset; HP-bar position is derived from the sprite's drawn
  top; there is no impact-point concept).

- **Track B — the VFX system.** The game's effects are all procedural today
  (`game/ui/effects.py`) and the `vfx` slot category has two orphan slots with
  no consumers and no art. Three parts: **(1)** six discrete one-shot effects
  become **swappable spritesheets** (import art → it plays; grey-X placeholder +
  procedural fallback until then); **(2)** the effects that stay procedural
  become **tunable + previewable** (colours/counts/lifetimes move to `data/`,
  with editor control levers and a live preview); **(3)** a **reassignable
  trigger table** in `data/` binds each game event to the effect it plays.

**Hard guardrail — purely cosmetic.** Nothing in either track reads or writes
damage, range, splash, or simulation state. The impact anchor decides where the
hit VFX *draws*, never where damage *resolves*.

## 2. Architecture

```
data/                             engine/                         game/ + editor/
─────                             ───────                         ───────────────
sprites/asset_manifest.json       vfx/ (NEW, data-driven)         game/ui/effects.py
  entry.anchors  (NEW, optional)    ├ particle emitters ◄──────┐    thin trigger site
  {muzzle,impact,hp_bar,…}          │  (params injected)       ├─► renders via Renderer
                                    └ PlayOnceVfx (SpriteAnimator  editor/panels/
balancing/vfx.json (NEW domain)        loop_count=1) GameObject     ├ anchor handles (viewport)
  procedural params + defaults                                      ├ vfx preview + levers
  trigger table (event→effect)    engine/render (unchanged path)    └ both consume engine/ + data/
slots.json  vfx category
  vfx_muzzle/hit/explosion/…(NEW)
```

**Flow, Track A**: select entity → editor draws each anchor as an overlay
handle over the live preview (through `submit_overlay_lines`, ED-22 — never
QPainter) → drag maps mouse-world → frame-pixels → `write_validated` into the
manifest entry's `anchors` → game reads the offset at fire/bar/impact time.

**Flow, Track B**: a game event fires → the **trigger table** (`data/`) names
the effect → either a **`PlayOnceVfx`** GameObject spawns at the anchor and
plays a `vfx_*` sheet once (falling back to the procedural emitter when the slot
has no art), or the **data-driven procedural emitter** runs with params from
`balancing/vfx.json`. The editor previews the exact same engine emitter.

### Decisions (with rationale)

- **D1 — Anchors are an OPTIONAL `anchors` key on the asset-manifest entry**,
  per-slot (one set per spritesheet, applied to the whole sheet). Exact
  precedent: the entry already carries `offset_x`/`offset_y` and the optional
  `slice` key (`data/CLAUDE.md`) — a slot with no anchors stays **byte-identical**,
  like an unsliced slot today. Reuses the whole import/validate/`write_validated`
  pipeline; no parallel store. Matches the user's "one anchor set for the whole
  sheet, set per level / per enemy."
- **D2 — Anchor coordinates are frame-pixels relative to the sprite anchor** —
  same convention as `offset_x`/`offset_y`, so a muzzle at `[+18, -40]` means the
  same thing at every zoom and map scale. The drag handle maps mouse-world →
  frame-space; the numeric side panel shows the raw ints.
- **D3 — HP-bar offset is relative to the footprint-fit top, not raw sheet
  pixels.** Since ER-1 the bar rides the sprite's *drawn* top (`_sprite_top`),
  which is the footprint fit, not the sheet size. A raw-pixel offset would float
  for downscaled units. The offset is applied *from* the existing fit anchor.
- **D4 — The impact anchor is VISUAL-ONLY.** Damage geometry (Chebyshev range,
  splash radius, predictive lead) keeps measuring from footprint centres. The
  impact anchor only positions the hit/explosion VFX. This is the guardrail made
  concrete — Track A never touches `resolve_combat`'s math.
- **D5 — The procedural emitters move into `engine/vfx/` as a data-driven
  subsystem**, because the editor **cannot import `game/`** (layering rule) yet
  must render a live preview through the one render path. The subsystem takes
  params as injected plain values/dataclasses (engine stays pure — it does not
  hardcode a data path); **game** loads them from `data/balancing/vfx.json` and
  **editor** loads the same for preview. Behaviour is byte-identical on landing:
  the current `game/ui/effects.py` constants become the shipped defaults. Chosen
  over an `editor/`-side lookalike (accepted for the simple UI-widget fallback,
  but particle systems are too much to keep in sync by eye).
- **D6 — One reusable `PlayOnceVfx` GameObject** (engine, using `SpriteAnimator`
  + `loop_count=1`) drives every sprite one-shot: spawn at a world point,
  despawn on the last frame. Mirrors how enemies pick a sprite by
  `REGISTRY_GROUP` — one mechanism, many slots; a future effect is "add a slot +
  a trigger row," never a new system.
- **D7 — The trigger table lives in `data/` (in the new `vfx` domain)**, mapping
  each game event (`defender_fire`, `enemy_death`, `splash_impact`, …) to the
  effect it plays — a `vfx_*` sprite slot **or** a procedural kind. Reassigning
  an effect is a one-row edit in the editor, never code.
- **D8 — `vfx` becomes a real balancing domain.** Adding `data/balancing/vfx.json`
  + `data/schemas/vfx.schema.json` promotes the asset-only `vfx` category to a
  derived domain automatically (the domain list is `slots.json` categories ∩
  those with a balancing file — `editor/domains.py`, AD-6). Its numeric params
  get a generic balancing form for free; the **live-preview levers** are a
  dedicated panel on top of that domain, not a replacement for it.

Vocabulary/invariants come from root `CLAUDE.md`: one render path (ED-22),
data is the only value store (D-1, schema-first via `write_validated`), strict
layering (`editor/` and `game/` never import each other; both consume `engine/`
+ `data/`), every new editor module joins `test_editor_viewport.TestPurity`,
and **the gate is ZERO**.

## 3. Package routing (read the ONE doc per phase)

| Phase touches | Read |
|---|---|
| manifest `anchors` schema, `vfx.json` domain, `slots.json` vfx slots | `data/CLAUDE.md` |
| `engine/vfx/` emitters + `PlayOnceVfx` | `engine/CLAUDE.md`, `engine/render/CLAUDE.md` |
| combat / HP-bar / effects trigger sites | `game/CLAUDE.md`, `game/enemies/CLAUDE.md`, `game/ui/CLAUDE.md` |
| anchor handles, vfx preview + levers | `editor/CLAUDE.md`, `editor/panels/CLAUDE.md` |

Cross-package phases (ESV-1, ESV-3, ESV-5) are flagged as such — tell the user;
they decide whether the executing agent reads both docs.

## 4. Build order

| Phase | Scope | Track | Status |
|-------|-------|-------|--------|
| ESV-1 | Anchor schema on manifest + game reads offsets (defaults = today) | A · data + game | not started |
| ESV-2 | Anchor handles + numeric panel in the entity-preview viewport | A · editor | not started |
| ESV-3 | Procedural emitters → `engine/vfx/`; params → `data/balancing/vfx.json` | B · engine + game | not started |
| ESV-4 | Procedural preview + control levers panel | B · editor | not started |
| ESV-5 | Sprite one-shots (`PlayOnceVfx`) + trigger table + importer slots | B · data + game + editor | not started |
| ESV-6 | Converge — anchored impact & muzzle VFX | A × B | not started |

Ordering rule: **nothing changes visible behaviour until the piece behind it is
real.** ESV-1 and ESV-3 land as byte-identical no-ops (defaults reproduce
today's values); the visible change arrives with the editor handles (ESV-2),
the levers (ESV-4), imported art (ESV-5), and the convergence (ESV-6).

---

### ESV-1 — Anchor schema + game read (Track A · data + game · cross-package)

**Goal**: the manifest entry gains an OPTIONAL `anchors` block; combat, HP-bar
and impact code read the offset with **today's values as the default**, so the
game looks identical. No editor UI yet.

**Files** — new: none. Modified: `data/schemas/asset_manifest.schema.json`
(add optional `anchors` object: `muzzle`/`impact`/`hp_bar`/… each `[x,y]`
frame-px int pairs, all keys optional, `additionalProperties:false`);
`engine/assets/manifest.py` + `store.py` (parse/expose anchors on the entry,
absent → `None`); `game/enemies/combat.py` (`_fire`/`_fire_splash` add the
muzzle offset to `world_pos` when present); `game/ui/effects.py`
(`submit_enemy_hp_bars`/building bar apply the hp_bar offset relative to
`_sprite_top`, D3). **Executor scouts exact symbols** — this list is indicative.

**Tests**: manifest round-trips with and without `anchors` (byte-identical when
absent); an entry with a muzzle anchor shifts the projectile spawn point by the
declared frame-px (headless, deterministic); an hp_bar offset shifts the bar and
still tracks the footprint fit for a downscaled unit; **no** change to any
damage/range/splash assertion (guardrail D4).

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check` → GATE PASS.
Live: `py game/main.py` a round — projectiles/bars look exactly as before
(defaults reproduce current behaviour).

### ESV-2 — Anchor handles in the viewport (Track A · editor)

**Goal**: selecting an entity shows its anchors as draggable handles over the
live preview; dragging writes the manifest `anchors` via `write_validated`; a
numeric X/Y side panel stays in sync.

**Files** — modified: `editor/panels/viewport.py` (handle draw + hit-test +
drag, submitted through the engine overlay path `submit_overlay_lines`, ED-22 —
never QPainter; hangs off the existing entity-preview selection, not a new
mode); `editor/panels/details.py` or a small new panel module for the numeric
readout (new modules → `TestPurity`). New: possibly
`editor/anchor_ops.py` (pure mouse-world → frame-px + `write_validated`, in
`TestPurity`).

**Tests** (offscreen Qt, temp data dir): a synthetic drag on a handle writes the
expected frame-px into the entry and the on-disk JSON validates; the numeric
panel and the handle agree after a drag and after an external value change;
`TestPurity` import sweep includes every new module.

**Exit gate**: suite + smoke → GATE PASS. Live: `py editor/main.py`, select a
defender, drag the muzzle handle, confirm the JSON on disk, then Play and see
the projectile emit from the new point.

### ESV-3 — Procedural VFX → engine, params → data (Track B · engine + game · cross-package)

**Goal**: the particle/effect emitters move from `game/ui/effects.py` into a
data-driven `engine/vfx/` subsystem; their colours/counts/lifetimes/gravity move
into a new `vfx` balancing domain. **Byte-identical** using today's constants as
the shipped defaults — no visible change.

**Files** — new: `engine/vfx/` package (emitters taking injected params;
submits through `Renderer`, no data-path knowledge); `data/balancing/vfx.json` +
`data/schemas/vfx.schema.json` (procedural params, D8 — becomes a derived domain
automatically). Modified: `game/ui/effects.py` (becomes a thin caller that loads
params from `data/balancing/vfx.json` and drives the engine emitters);
`game/core/balance.py` loader if needed.

**Tests**: an emitter produces the same particle set (count/colour/lifetime) from
the default params as the old constants (pin a representative effect — muzzle,
death burst); `vfx` appears in `editor/domains.domains()` once the balancing file
exists; schema `description`/`minimum`/`maximum` present on every key (D-12).

**Exit gate**: suite + smoke → GATE PASS. Live: `py game/main.py` — every effect
looks unchanged. Update `engine/CLAUDE.md` (new subsystem) + `game/ui/CLAUDE.md`.

### ESV-4 — Procedural preview + control levers (Track B · editor)

**Goal**: an editor panel exposes the procedural params as levers (colour
pickers, counts, lifetimes) with a **live preview** rendered through the one
render path (the editor drives the same `engine/vfx/` emitter).

**Files** — new: `editor/panels/vfx_preview.py` (+ any pure helper; all →
`TestPurity`). Modified: `editor/main.py` wiring (select the `vfx` domain/leaf →
show the preview + levers; writes go through the balancing writer / `write_validated`).

**Tests** (offscreen Qt, temp data dir): a lever edit stages/writes a valid
`vfx.json`; the preview requests the engine emitter with the edited params
(assert the params passed, not pixels); `TestPurity` covers the new modules.

**Exit gate**: suite + smoke → GATE PASS. Live: `py editor/main.py`, retint a
muzzle spray / slow a death burst, watch the preview, save, Play and confirm.

### ESV-5 — Sprite one-shots + trigger table + importer slots (Track B · data + game + editor)

**Goal**: the six discrete effects can be spritesheets. `PlayOnceVfx` plays an
imported `vfx_*` sheet once at a world point; a `data/` trigger table binds
events → effect; unimported slots fall back to the procedural emitter, so day-one
is identical.

**Files** — new: `engine/vfx/play_once.py` (the `PlayOnceVfx` GameObject, D6 —
note `SpriteAnimator` has **no `loop_count` field today**
(`engine/core/sprite_animator.py`); ESV-5 adds the one-shot mechanism, either
as a new animator field or completion-tracking inside `PlayOnceVfx`).
Modified: `data/slots.json` (add `vfx_muzzle`, `vfx_hit`, `vfx_explosion`,
`vfx_death`, `vfx_slash`, `vfx_crater` to the vfx category — note `vfx_hit`/
`vfx_explosion` already exist); `data/balancing/vfx.json` + schema (the trigger
table, D7); `game/ui/effects.py` + the fire/death/impact sites (consult the
table: spawn `PlayOnceVfx` when the slot has art, else the procedural emitter).
The existing asset importer handles the sheets with no editor change (registry +
`/add-asset-importer` semantics).

**Tests**: with no art, each triggered event runs the procedural fallback
(behaviour unchanged); with a fixture sheet, the event spawns a `PlayOnceVfx`
that despawns after one loop; the trigger table validates and an event with a
missing binding is a safe no-op (art tolerance E-37); reassigning a row in the
table swaps which effect an event plays.

**Exit gate**: suite + smoke → GATE PASS. Live: `py editor/main.py` import a
placeholder sheet into `vfx_muzzle`; `py game/main.py` — a defender's shot now
plays the sheet; clear it → procedural muzzle returns.

### ESV-6 — Converge: anchored impact & muzzle VFX (Track A × B)

**Goal**: the two tracks meet — the muzzle VFX (ESV-5) spawns at the muzzle
anchor (ESV-1/2), and the hit/explosion VFX spawns at the target's impact
anchor. Still purely visual (D4).

**Files** — modified: the fire site passes the shooter's muzzle anchor as the
`PlayOnceVfx` spawn point; the impact/death site passes the target's impact
anchor. No new schema — both anchors already exist from ESV-1.

**Tests**: a defender with a muzzle anchor spawns its muzzle VFX at the anchored
world point (headless); a target with an impact anchor spawns the hit VFX there;
damage/kill assertions are unchanged (guardrail).

**Exit gate**: suite + smoke → GATE PASS. Live: drag a muzzle anchor in the
editor, import a muzzle sheet, Play — the flash follows the handle. Confirm HP
ledger is identical to before (nothing touched the sim).

---

## 5. Risks / open items

- **Engine purity vs. data-driven params (D5).** `engine/vfx/` must not learn a
  `data/` path or import a balancing loader — params are injected by each
  consumer. If a phase is tempted to `open()` a JSON inside `engine/`, stop: load
  in `game/`/`editor/` and pass values in. Pin with an engine-layer import test.
- **HP-bar footprint coupling (D3).** The offset must compose with `_sprite_top`
  / ER-1 fit, not replace it. Test a downscaled (footprint > 1) unit explicitly,
  or bars will float — this is the ER-4 cosmetic caveat's neighbourhood.
- **`vfx` domain promotion (D8).** Adding `balancing/vfx.json` changes
  `editor/domains.domains()` output and the selector tree; a few tests assert the
  domain list. Update the pinned fixtures, don't assert against live `data/`.
- **Trigger-table event vocabulary (D7).** The set of events
  (`defender_fire`, `enemy_death`, `splash_impact`, `melee_hit`, …) is a schema
  enum — enumerate it deliberately in ESV-5 from the real fire/death/impact sites
  in `game/ui/effects.py`; adding an event later is a schema + one call-site edit.
- **Which effects are truly one-shot vs. continuous.** The six sprite effects are
  bursts. Beams/lightning are continuous and stay procedural (Part 2) — do not
  force them into `PlayOnceVfx`. Revisit only if a designer asks.
- **Scope of "other attach points" (Track A).** Muzzle / impact / hp_bar are
  concrete in ESV-1. Floater-origin / status-icon / beam-endpoint anchors are the
  same schema shape but need their own game read-sites; land them incrementally
  under ESV-1's schema rather than blocking the phase.
