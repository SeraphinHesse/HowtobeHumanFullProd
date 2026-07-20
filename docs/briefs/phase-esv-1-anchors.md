# Phase ESV-1 — Anchor schema + game read

Plan: `planning/EntitySceneVfxPLAN.md` §ESV-1 (`planning/EntitySceneVfxPLAN.md:150-173`).
Track A · **cross-package (data + engine + game)**. Read `data/CLAUDE.md` and
`game/CLAUDE.md` (and `engine/assets/CLAUDE.md` for the manifest conventions).
Runs in parallel with **ESV-3a**, which owns the rest of `game/ui/effects.py` —
the file boundary in §3 is hard.

**Landing condition: byte-identical.** With no `anchors` key anywhere in
`data/sprites/asset_manifest.json` (no committed entry carries one, and this
phase adds none), the game renders and fires exactly as today and the manifest
round-trips byte-for-byte. Everything below is a no-op until a designer authors
an anchor in ESV-2.

> **This brief CORRECTS the plan document.** `planning/EntitySceneVfxPLAN.md:161-162`
> says `_fire`/`_fire_splash` "add the muzzle offset to `world_pos`". Done
> literally, that is a **D4 breach** — it moves simulation state. See §1.4.
> The corrected design (visual spawn separated from logical origin) is
> ratified and authoritative; the orchestrator folds it back into the plan doc
> at the end of the run.

---

## 1. Behavioral spec

### 1.1 The schema gains an optional `anchors` block

`data/schemas/asset_manifest.schema.json` — the per-entry object at
`data/schemas/asset_manifest.schema.json:74-155` is
`additionalProperties: false` (`:75`) with `required` =
`[sheet, frame_w, frame_h, offset_x, offset_y, rows]` (`:143-150`). Today
`slice` (`:131-141`) is the **one** optional key; `anchors` becomes the second,
and copies `slice`'s shape exactly: optional, `additionalProperties:false`,
integer-bounded, `description` on every node (D-12).

Declared names — **six, all optional**:

| name | meaning | wired in ESV-1? |
|---|---|---|
| `muzzle` | where a projectile visually emits from | **yes** (`game/enemies/combat.py`) |
| `impact` | where a hit VFX draws on the target | **yes** (parsed + exposed; no draw site yet — see 1.6) |
| `hp_bar` | overhead bar position | **yes** (`game/ui/effects.py`) |
| `floater_origin` | damage/income floater spawn | no — authorable, inert |
| `status_icon` | status-badge attach point | no — authorable, inert |
| `beam_endpoint` | beam terminus on the shooter | no — authorable, inert |

The three inert names are declared **deliberately**: ESV-2's handle code is
generic over the declared name set, so shipping all six now means no schema
migration when their read-sites land (plan risk "Scope of other attach points",
`planning/EntitySceneVfxPLAN.md:306-308`).

Each value is a 2-item integer array `[x, y]`, `minItems: 2`, `maxItems: 2`,
bounds `-4096 .. 4096` (the schema-house pixel bound, `data/CLAUDE.md`
"Bounds policy"; `offset_x`/`offset_y` use ±256 at `:92-99` because they are a
*nudge* — an anchor may sit anywhere on a 1024px frame, so the wider pixel bound
applies).

**Key placement is not a choice.** Schemas are written through
`dumps_deterministic` (sorted keys, D-3), so `anchors` lands **first** in
`properties`, before `frame_h` at `:78` — the existing block is already
alphabetical (`frame_h`, `frame_w`, `offset_x`, `offset_y`, `rows`, `sheet`,
`slice`). Do not hand-place it "after the offsets"; write it and let the
deterministic dump sort it.

### 1.2 D2 — the coordinate convention

Anchor coords are **frame-pixels relative to the sprite anchor**, the same
convention as `offset_x`/`offset_y` (`:90-100`) and `slice` (`:132`). `+x` is
right, `-y` is up (mirroring `offset_y`'s description at `:97`, "negative =
up"). They are measured on the **sheet frame**, at frame resolution — never at
draw resolution, never at a zoom.

### 1.3 Frame-px → world, for the muzzle (the load-bearing formula)

A sprite's on-screen size is **not** its sheet size: since ER-1 the renderer
fits the frame to the unit's tile footprint. The one expression for that factor
is `engine/render/renderer.py:28-39`:

```
s = fit_factor(frame_w, tile_w, anim.fit_tiles) * anim.scale
```

— exactly what `game/ui/effects.py:128` already computes for `_sprite_top`.
`frame_w` comes from `AssetStore.frame_size(slot_key)`
(`engine/assets/store.py:53-62`), `tile_w` from `cs.geometry.tile_w`,
`fit_tiles`/`scale` from the object's `SpriteAnimator`.

So an anchor `(ax, ay)` in frame-px draws at a **screen** offset from the
sprite's centre anchor of:

```
(dsx, dsy) = (ax * s * zoom, ay * s * zoom)
```

To convert that screen delta into the **world** (fractional tile) delta a
projectile spawn needs, go through the coordinate authority — **never restate
the iso math**; `engine/coords/` is the only place it may live
(`engine/CLAUDE.md`, subsystem table). Take the difference of two
`CoordinateSystem.screen_to_world` calls (`engine/coords/system.py:33-40`):

```
sx, sy   = cs.world_to_screen(wx, wy)
wx2, wy2 = cs.screen_to_world(sx + dsx, sy + dsy)
(dwx, dwy) = (wx2 - wx, wy2 - wy)
```

**Zoom and pan cancel in that difference** — `screen_to_world` divides by `z`
and subtracts the same pan for both samples (`:35-39`), so a muzzle authored at
`[+18, -40]` lands on the same world point at every zoom level and pan, which is
exactly what D2 promises. Do **not** hand-derive `dwx = s*(ax/tile_w +
ay/tile_h)`: it is the same number, but it is a second copy of the iso rule and
it is banned.

`ax == ay == 0` (or no anchor) ⇒ `(0.0, 0.0)` ⇒ every expression below is
numerically unchanged.

### 1.4 Combat read-sites — the visual spawn is NOT the logical origin

**This section supersedes `planning/EntitySceneVfxPLAN.md:161-162`.**

#### Why the plan's phrasing breaks D4 (verified)

`ProjectileHoming.launch()` (`game/enemies/combat.py:61-68`) derives the
projectile's **flight time** from where it was spawned:

```
px, py = self._proj.transform.world_pos                      # :65
tx, ty = target.transform.world_pos                          # :66
dist = math.hypot(tx - px, ty - py)                          # :67
self.timer = dist / self.speed if self.speed > 0 else 0.0    # :68
```

`update()` decrements `self.timer` (`:86`) and calls `_impact()` when it expires
(`:87-88`); `_impact()` is what applies `Health.damage(self.dmg)` (`:95`) — the
"guaranteed damage on arrival" contract in `game/enemies/CLAUDE.md`. Damage
lands on a **timer**, and that timer is a function of the spawn point.

So "add the muzzle offset to `world_pos`" and stop there would make the
damage-arrival **frame** a function of an authored art coordinate. That is
simulation state moving with a cosmetic value — precisely what D4 forbids
(`planning/EntitySceneVfxPLAN.md:85-88`, and the plan's own hard guardrail at
`:37-39`). It would also be nearly invisible: a designer nudging a muzzle would
silently retune every defender's damage-under-fire by a frame or two.

#### The required design — separate the two

- **`_fire()` (`game/enemies/combat.py:474-478`)** spawns the `Projectile` at
  the **muzzle-anchored world point** (`world_pos + world_offset(..., "muzzle")`).
  The shot therefore visibly emits from the handle — which is exactly what
  ESV-2's Quick Test looks for.
- **`ProjectileHoming.launch()` (`:61-68`) gains an explicit `origin=None`
  parameter**, used **solely** for the distance/timer computation at `:65-68`.
  `None` ⇒ fall back to `self._proj.transform.world_pos`, i.e. today's exact
  expression, so **every existing caller and every existing test is
  byte-identical**. Nothing else in `launch` changes; `update()` (`:70-88`) and
  `_impact()` (`:90-101`) are untouched — the projectile still *moves* from
  wherever it was spawned, which is the cosmetic half.
- **`_fire()` passes `origin=<the defender's tile centre>`** — the unmodified
  `defender.transform.world_pos`, the value used today. Flight time is then
  computed from the same two points it has always been computed from, and
  **damage timing is provably invariant under any anchor value**, including
  absurd ones.

Read the two together: the spawn coordinate is art, the `origin` argument is
simulation, and they are now different arguments so they cannot be confused.

#### `_fire_splash()` (`game/enemies/combat.py:481-491`)

Same reasoning, **but no signature change is needed** — and the brief states why
rather than leaving it implied:

- The shell's flight time is the module constant `AOE_TRAVEL_TIME` (0.55s,
  `game/enemies/combat.py:41`), passed to
  `ProjectileArc.launch(gx, gy, defender, scene, AOE_TRAVEL_TIME)` (`:489-490`).
  It is **fixed, not distance-derived**, so moving the spawn point cannot move
  the impact frame. Timing is safe here by construction.
- The impact **location** is `gx, gy = _predict_lead(target, AOE_TRAVEL_TIME)`
  (`:486`) — computed **from the target's** `Movement` waypoint and speed
  (`game/enemies/CLAUDE.md`, "predictive lead"). It reads nothing about the
  shooter, so the shooter's muzzle anchor cannot touch it. Confirm this by
  reading `_predict_lead` before you edit; if it ever grew a shooter term, this
  phase would need the same origin split.
- Therefore `_fire_splash` changes **exactly one line**: `bx, by` at `:485`
  becomes the anchored point. `:486` and `:487-490` are untouched. The shell
  starts at the muzzle and lands where it always did.

#### D4 guardrail, restated as a test obligation

`resolve_combat`'s math — Chebyshev range, Euclidean acquisition, splash radius,
predictive lead, the footprint-centre offsets (`game/enemies/CLAUDE.md`, "The
combat sweep measures from the footprint CENTRE") — is not touched by this
phase. **No existing damage, range, splash or HP-ledger assertion may change.**
If one does, the change is wrong; revert and re-derive. §4.2 test 4 is the pin
that turns "purely cosmetic" from an assertion into a demonstration.

### 1.5 Beams are out of scope

`_update_beam` is instant hitscan with no travel and no spawn point; the beam
line is drawn in `game/ui/effects.py` (`submit_beams`), which is ESV-3a's
territory. `beam_endpoint` is declared in the schema and inert. Do not touch
the beam path.

### 1.6 `impact` in ESV-1

`impact` is parsed, validated and exposed on the entry, and reachable through
the same resolver as `muzzle`. It gets **no draw site** in this phase — the hit
VFX that will consume it is ESV-5/ESV-6 (`planning/EntitySceneVfxPLAN.md:266-278`).
Do not add one. Do not route it into `resolve_combat`.

### 1.7 HP-bar read-sites — D3, compose with the footprint fit

The bar is a fixed-screen-size HUD element anchored through
`cs.world_to_screen(wx + 0.5, wy + 0.5)` (`game/ui/CLAUDE.md`, "Overhead HP
bars"), so the `hp_bar` anchor applies as a **screen** offset — `(ax * s *
zoom, ay * s * zoom)` from 1.3, with **no** `screen_to_world` step.

- **Enemies** — `game/ui/effects.py:620-665`. `_sprite_top(renderer, cs, e, cy,
  zoom)` at `:660` already returns the sprite's real drawn top edge; `pad` is
  applied at `:660-662`. The anchor offset is added **to that result**, i.e.
  `top` (and the `x` at `:661`) shift by the scaled anchor — it composes with
  the fit, it does not replace it. This is D3
  (`planning/EntitySceneVfxPLAN.md:81-84`): a raw-pixel lift floats for a
  downscaled unit, which is exactly the ER-1 bug `_sprite_top` was written to
  fix. **`_sprite_top` itself (`game/ui/effects.py:106-130`) is READ-ONLY in
  this phase.**
- **Buildings** — `game/ui/effects.py:601-618`. This path does **not** call
  `_sprite_top`; it uses a flat `y = int(cy - tile_h * zoom)` at `:616`. Leave
  that expression as the baseline and add the same scaled anchor offset on top
  of it (`x` at `:615` likewise). Do **not** "fix" the building bar to use
  `_sprite_top` — that is a visible behaviour change and it is out of scope.

Absent anchor ⇒ offset `(0, 0)` ⇒ both expressions are the current ones,
character for character in effect.

### 1.8 Tolerance (E-37) is unchanged

`load_manifest()` (`engine/assets/manifest.py:215-237`) **never raises**: absent
file → empty manifest, corrupt file → warn + empty, corrupt entry → warn + skip
that entry. `entry_from_dict()` is the strict layer that raises
(`engine/assets/manifest.py:87-156`). A malformed `anchors` block therefore
raises out of `entry_from_dict` and is turned into warn-and-skip-this-entry by
`load_manifest` — identical to how a bad `slice` behaves today
(pinned by `tools/tests/test_assets_manifest.py:185`).

---

## 2. Architecture plan

### 2.1 Where `anchors` parses

`engine/assets/manifest.py` — the `slice` path is the exact pattern to copy:

- **Field**: `ManifestEntry` is a frozen dataclass at `:75-84`, with
  `slice: tuple = None` at `:84`. Add `anchors: tuple = None` **after** it (a
  second defaulted field; every existing positional construction stays valid).
  Store it as an immutable, deterministic structure — a `tuple` of
  `(name, (x, y))` pairs in the declared-name order, or a `frozenset`-backed
  mapping; **do not store a mutable `dict`** on a frozen dataclass shared across
  the whole game. Expose a tiny accessor (`entry.anchor("muzzle") -> (x, y) |
  None`) so callers never index the raw structure.
- **Parse**: mirror the slice parse at `:133-145`, immediately after it and
  before the `return ManifestEntry(...)` at `:147-156`. Same defensive shape and
  the same lesson from the slice comment at `:134-136` — reject a bare string
  (`"12"` iterates into two perfectly valid-looking ints), reject non-2-length,
  reject non-integers, reject unknown names. `raw.get("anchors")` absent ⇒
  `None`, no other branch taken.
- Add `anchors=…` to the `ManifestEntry(...)` construction at `:147-156`.

### 2.2 How it reaches the game

Two consumers, two shapes of the same value:

- `game/ui/effects.py` already reaches art metadata the right way: `assets =
  getattr(renderer, "assets", None)` then `assets.frame_size(anim.slot_key)`
  (`game/ui/effects.py:123-127`). Anchors follow the same route — the bar code
  needs no new wiring at all, only an accessor on the store.
- `game/enemies/combat.py` has **no** `AssetStore` and no `CoordinateSystem`.
  `resolve_combat(scene, tilemap, dt, buildings_balance, …)`
  (`game/enemies/combat.py:333`) is called from `game/main.py:633` with neither.
  This is solved by the **ratified** extension in §3.3.

**`engine/assets/store.py` — one addition, justified.** `Frame` is constructed
at `engine/assets/store.py:73-75` from `frame_w/frame_h/offset_x/offset_y/slice`.
Anchors are **metadata, not frame geometry** — they do not change how a frame is
cut, scaled or blitted — so **`Frame` and the `frame()` path must NOT gain an
`anchors` field**. What the store does need is a lookup mirroring
`frame_size()` (`:53-62`):

```
AssetStore.anchor(slot_key, name) -> (x, y) | None
```

resolving through `self._manifest.entry(slot_key)` and returning `None` for a
missing slot, a missing entry or a missing name. This is required because
`game/ui` reads art metadata **only** through `renderer.assets` — it has no
`Manifest` handle (`game/ui/effects.py:123`).

### 2.3 The origin split, structurally

`ProjectileHoming` keeps **all** state in components (E-11) and `origin` is not
state — it is consumed once inside `launch()` to compute `self.timer` and then
discarded. Do **not** add an `origin` field to the component: add it as a
parameter with a `None` default, resolve it at the top of `launch()`
(`origin if origin is not None else self._proj.transform.world_pos`), and use
the resolved pair at `:67`. That keeps the component's serialized shape
unchanged and makes the byte-identity of every existing caller structural rather
than conventional.

### 2.4 What happens when absent

Every layer degrades to today's number, not to a special case:

| layer | absent |
|---|---|
| JSON | key omitted; `write_validated` round-trips byte-identically (D-3 sorted-keys dump) |
| `entry_from_dict` | `anchors = None`, no parse branch entered |
| `AssetStore.anchor` | `None` |
| resolver | `(0.0, 0.0)` |
| `_fire` spawn | `bx + 0.0, by + 0.0` |
| `launch(origin=…)` | always the tile centre — invariant even when the anchor is PRESENT |
| bar code | `x + 0`, `y + 0` |

There is no "default anchor" concept and no code-side anchor value anywhere —
`data/` stays the only value store (D-1).

---

## 3. File scope + shared-file contract

**ESV-3a runs in parallel and owns the rest of `game/ui/effects.py`.** Touching
anything in that file outside the two named functions is a merge conflict with
another agent's live work.

### 3.1 Boundary — the permitted files

| file | permitted edit | insertion point |
|---|---|---|
| `data/schemas/asset_manifest.schema.json` | add the `anchors` subschema to the per-entry `properties` | sorts to the head of `properties`, before `frame_h` at `:78`; leave `required` (`:143-150`) and `additionalProperties:false` (`:75`) alone |
| `engine/assets/manifest.py` | add the field + the parse | field after `slice` at `:84`; parse after the slice block at `:133-145`; `anchors=` into the construction at `:147-156` |
| `engine/assets/store.py` | add `anchor(slot_key, name)` only | beside `frame_size` at `:53-62`. **Do not touch `frame()` at `:64-75`** — `Frame` gains nothing |
| `game/enemies/combat.py` | **three** edits, no more: the `origin=None` parameter in `ProjectileHoming.launch` (`:61-68`); the spawn + `origin=` pass in `_fire` (`:475-477`); the spawn line in `_fire_splash` (`:485`) | see §1.4 |
| `game/ui/effects.py` | **`submit_hp_bars` (`:601-618`) and `submit_enemy_hp_bars` (`:620-665`) ONLY** | the `x`/`y` computations at `:615-616` and `:660-662` |
| **NEW** `game/anchors.py` | the shared resolver — §3.3 | new file |
| `game/main.py` | **one** call site | `:633` — see §3.3 |
| `tools/tests/` | new tests, plus a `TIERS` entry per new module | `conftest.py`'s `TIERS` table (`test_tiers.py` fails if you forget) |

### 3.2 ESV-1 must NOT touch

- `game/ui/effects.py` module constants (`:33-103`) — ESV-3a is moving these.
- `game/ui/effects.py` `FloaterManager` internals (`:216-422`).
- Any particle / gold / splatter / slash / beam / crater / projectile-draw path.
- `_sprite_top` (`game/ui/effects.py:106-130`) — **read it, call it, do not edit it.**
- `ProjectileHoming.update()` (`:70-88`) and `_impact()` (`:90-101`) — the
  origin split is confined to `launch()`.
- `_predict_lead` and the `ProjectileArc.launch` ground point
  (`game/enemies/combat.py:486-490`).
- `resolve_combat`'s targeting/range/splash/lead math anywhere else in
  `game/enemies/combat.py`.
- `Frame` / the `frame()` blit path (`engine/assets/store.py:64-75`).
- Any `data/` **content** file. This phase authors **no** anchors; it ships the
  schema and the readers. `data/sprites/asset_manifest.json` is unchanged.

### 3.3 The wiring extension — **RATIFIED**

`game/enemies/combat.py` cannot resolve a muzzle offset from what it is handed
(§2.2): no `AssetStore` (for the anchor and `frame_w`), no `CoordinateSystem`
(for `screen_to_world` and `tile_w`). Both items below are approved as scoped:

1. **NEW `game/anchors.py`** — a small pure module (no pygame; `game/ui`'s
   purity scan and the engine layering both stay satisfied) holding *the one
   expression* for both conversions:
   - `screen_offset(assets, cs, obj, name, zoom) -> (dx, dy)` — §1.3 up to the
     screen delta, for the bar code.
   - `world_offset(assets, cs, obj, name) -> (dwx, dwy)` — the same, then the
     two `cs.screen_to_world` samples of §1.3, for combat.
   Both return `(0.0, 0.0)` for a missing store / animator / slot / anchor. Both
   import `fit_factor` from `engine.render.renderer` (`:28-39`) rather than
   restating it — the same rule `_sprite_top` follows at
   `game/ui/effects.py:128`. `game/ui/effects.py` and `game/enemies/combat.py`
   both import this module; ESV-2 and ESV-6 reuse it.
2. **`game/main.py:633`** — one changed call: thread the already-built `cs` and
   `assets` (`game/main.py:186-192`) into `resolve_combat` as optional kwargs
   defaulting to `None`, following the established optional-argument pattern of
   `on_base_hit` / `on_enemy_death` / `dmg_bonus` (`game/enemies/CLAUDE.md`,
   "Round-loop / XP callbacks"). Default `None` ⇒ every existing headless caller
   and every existing test is byte-identical.

**Still forbidden** (do not invent a fourth mechanism): a module-global setter in
`combat.py`; a new component carrying the anchor; `game/enemies` importing
`game/ui`.

`engine/render/renderer.py` is read-only here (`fit_factor` is imported, not
edited). No new iso math anywhere: `engine/coords/` stays the sole authority.

### 3.4 Docs

Update **`engine/assets/CLAUDE.md`** (the optional-key list — `anchors` becomes
the second optional entry key beside `slice`) and **`data/CLAUDE.md`**
("`slice` (A2) is the one OPTIONAL per-entry key" is now false).
**`game/enemies/CLAUDE.md`** gains a sentence under "Projectiles travel then
deal GUARANTEED damage": the spawn point is cosmetic, the flight time is
computed from `launch(origin=…)` which is always the shooter's tile centre.
`game/ui/CLAUDE.md`'s "Overhead HP bars" section gains one sentence about the
composed offset. Do not touch the root router.

---

## 4. Exit gate + Quick Test

### 4.1 Commands

```bash
py tools/smoke.py                       # data validation + 5-frame headless boot
py tools/testgate.py check --affected   # blast radius + the core tier
```

**`--affected`, not the full suite** — ESV-3a is editing the same file
concurrently and a full run would be measuring their diff as much as yours.
Report the one line each command prints; the gate is **ZERO**. Run the full
`py tools/testgate.py check` exactly once, at hand-back, if the orchestrator
asks for it.

### 4.2 Tests to add

All `TempDataCase`; never write into `data/`, never assert against live `data/`
content. Existing neighbours to sit beside: `tools/tests/test_assets_manifest.py:299`
(valid load), `:185` (bad-slice warn-and-skip), `:272` (absent file).

1. **Round-trip without anchors is byte-identical.** Load a fixture manifest
   with no `anchors` key, write it back through the validating writer, assert
   the bytes are unchanged and `entry.anchors is None`. This is the regression
   pin for the whole phase — nothing currently pins it.
2. **Round-trip with anchors.** A fixture entry carrying all six declared names
   validates, parses to the expected values, and re-serialises byte-identically.
3. **Malformed anchors warn-and-skip.** Mirror
   `test_assets_manifest.py:185`: `"anchors": {"muzzle": "12"}`, a 3-item array,
   a non-integer, and an undeclared name each make `load_manifest` warn and drop
   **that entry only**, never raise (E-37).
4. **THE GUARDRAIL PIN — muzzle shifts the spawn, damage timing does not move.**
   One test, two assertions, and it is the reason the "purely cosmetic" claim is
   demonstrated rather than asserted:
   - **(a)** A defender with a **large** muzzle anchor (large enough that a
     distance-derived timer would visibly shift — e.g. most of a tile) spawns
     its projectile at `world_pos + world_offset(...)`, to a tight tolerance.
   - **(b)** Its damage lands on the **identical frame** as the same scenario
     with no anchor: step a headless scene frame by frame with a fixed `dt`,
     record the frame index on which the target's HP changes and the resulting
     **HP ledger**, and assert both are equal between the anchored and
     un-anchored runs. Seed any RNG (`game/CLAUDE.md`: "Seed the RNG in any test
     whose outcome depends on it").
   Run (b) with at least two very different anchor values, including one
   deliberately absurd, so the invariance is shown to be structural — this test
   is what would have caught the plan document's original phrasing.
5. **Zoom invariance.** The same anchor resolves to the same world offset at two
   different zoom levels (the D2 promise, and the thing a hand-derived formula
   would break).
6. **`launch(origin=…)` default is byte-identical.** Call
   `ProjectileHoming.launch(target, shooter, scene)` with no `origin` and assert
   `timer` equals `hypot(target − proj_spawn) / speed` — today's expression at
   `game/enemies/combat.py:65-68`. This pins the fallback that keeps every
   existing caller unchanged.
7. **`_fire_splash` timing and landing point are untouched.** With a muzzle
   anchor present, assert the shell's flight time is still `AOE_TRAVEL_TIME`
   (`:41`) and the `ProjectileArc` ground point still equals
   `_predict_lead(target, AOE_TRAVEL_TIME)` (`:486`) — unchanged from the
   un-anchored run.
8. **hp_bar shifts the bar and still tracks the fit.** For a **downscaled unit
   (`footprint > 1`, so `fit_factor < 1`)**, assert the bar's y equals
   `_sprite_top(...) - pad*zoom - h + ay*s*zoom` — i.e. the offset **composes**
   with the footprint fit rather than being a raw sheet-pixel lift (D3, and the
   plan's explicit risk at `planning/EntitySceneVfxPLAN.md:293-296`). Assert the
   absent-anchor case reproduces the current expression exactly. Cover the
   building bar (`submit_hp_bars`) the same way against its flat
   `cy - tile_h*zoom` baseline (`game/ui/effects.py:616`).
9. **No existing assertion was edited.** Not a test — a hand-back obligation.
   State explicitly in the report that no damage, range, splash, lead or
   HP-ledger assertion anywhere in the suite was modified (D4).

Every new test module needs a `TIERS` entry in `conftest.py` — an unmarked
module silently never runs, and an unexpected skip is a failure.

### 4.3 Quick Test (in-game)

```
py game/main.py
```

Play one round to the ENEMY phase with at least one basic defender and one
mortar placed, and let an enemy take damage:

- **Projectiles leave the defender's tile centre exactly as before** — same
  visible launch point, same arc for the mortar, same craters where they always
  landed.
- **Enemies die on the same beat** — no perceptible change in how long a shot
  takes to land.
- **HP bars sit exactly where they always sat** — over damaged buildings and
  over enemies, including a multi-tile enemy (a Formation) if one spawns.
- Nothing new is logged at boot (no manifest warnings).

That "exactly as before" **is** the pass condition: no committed entry carries
an `anchors` key, so any visible difference means an offset is being applied
where none was authored. The visible change arrives in ESV-2, when a designer
drags a handle.
