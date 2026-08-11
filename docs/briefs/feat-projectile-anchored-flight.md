# Feature — projectiles fly muzzle → impact, and you can see it in the editor

Designer request: *"make sure that the projectiles which fly from the basic
defenders start at the muzzle point and end at the enemies impact point every
time, and port this into the editor."* Branch `feat/projectile-anchored-flight`
off `VfxEditor`. Cross-package: **game + editor** (+ one pure `game/anchors.py`
helper).

**Read**: `game/CLAUDE.md`, `game/ui/CLAUDE.md`, `game/enemies/CLAUDE.md`,
`editor/CLAUDE.md`, `editor/panels/CLAUDE.md`.

**Guardrail D4 — the hard one for this task.** Everything here is COSMETIC.
Projectile flight TIMING and damage must not move by a single frame. See §2.3.

---

## 1. Why it doesn't work today (all **verified**)

Two independent defects, both in the visual path.

### 1.1 The start is right in world space and wrong on screen

`game/enemies/combat.py` `_fire` already spawns the `Projectile` at the
muzzle-anchored point ("anchor wins outright"). But
`game/ui/effects.py` `submit_projectiles` then adds, at DRAW time:

```python
lift = int(cs.geometry.tile_h * zoom * pr.lift_frac)   # 32 * 1.0 * 0.6 -> 19 px
dest = (int(cx - size / 2), int(cy - lift - size / 2))
```

So the dot renders ~19 px ABOVE the muzzle handle. The lift exists to make an
un-anchored dot read as "flying"; once an anchor is authored it **double-counts**
— the anchor already encodes the height.

### 1.2 The end was never the impact anchor at all

`ProjectileHoming.update` homes toward `target.transform.world_pos` — the
target's tile position. The `impact` anchor is read **only** in `_impact`, to
place the `projectile_hit` VFX. Nothing has ever made the projectile *fly* to it.

---

## 2. The fix

### 2.1 One shared endpoint resolver — `game/anchors.py`

```python
def projectile_point(assets, cs, obj, name, lift_frac):
    """The world point a projectile flies FROM (`name="muzzle"`, the shooter)
    or TO (`name="impact"`, the target).

    Anchor authored -> that exact point ("anchor wins outright", the rule
    fix-anchor-origin-parity established). Absent -> `obj`'s world position
    raised by `lift_frac` TILE HEIGHTS in SCREEN space — exactly where
    `submit_projectiles` used to draw the dot, so the un-anchored look is
    preserved byte-identically now that the lift has moved out of the draw.
    Returns None when `cs`/`obj` is missing (caller falls back)."""
```

Build the lifted fallback with the **two-sample `screen_to_world` trick** the
module already uses — never restate iso math:

```python
sx, sy = cs.world_to_screen(wx, wy)
lift = cs.geometry.tile_h * cs.camera.zoom * lift_frac
return cs.screen_to_world(sx, sy - lift)
```

### 2.2 Game call sites

- **`_fire`** (`combat.py`): the spawn point becomes
  `projectile_point(assets, cs, defender, "muzzle", lift_frac)`. `on_defender_fire`
  keeps firing with that SAME already-computed point (never recomputed).
- **`ProjectileHoming.update`**: home toward
  `projectile_point(self._assets, self._cs, target, "impact", self._lift_frac)`,
  **re-resolved every frame** (the target moves). `None` → today's
  `target.transform.world_pos`.
- **`_lift_frac`**: a transient underscore ref (E-11, like `_assets`/`_cs`), set
  in `_fire`. Thread `lift_frac` from `resolve_combat`'s existing `vfx_balance`
  argument (`procedural.projectile.lift_frac`) — it already receives it for
  `crater_life`, so **no new parameter on `resolve_combat`**.
- **`submit_projectiles`** (`effects.py`): **delete the draw-time lift**.
  `dest = (int(cx - size / 2), int(cy - size / 2))`. The lift now lives in the
  endpoints.

### 2.3 D4 — what must NOT change

- **`launch(target, shooter, scene, origin=...)`'s timer math is untouched.** It
  computes `dist` from the UNANCHORED `origin` to the UNANCHORED
  `target.transform.world_pos`. Do not feed it an anchored or lifted point. The
  parameter exists precisely to keep flight time independent of art.
- `_impact`'s damage block, `AOE_TRAVEL_TIME`, `BEAM_MIN_TICK`, `_predict_lead`,
  `_chebyshev` — untouched.
- **Only the homing MOVEMENT and the spawn point change.** `update()` already
  decouples visual position from `self.timer`; keep it that way.

### 2.4 Scope

**Basic defenders only** — the `ProjectileHoming` path. The mortar's
`ProjectileArc` flies to a predicted GROUND point, not an entity, so no `impact`
anchor applies; leave it and its `splash_impact` event exactly as they are.

---

## 3. The editor half

### 3.1 A `projectile` family in the VFX preview panel

`editor/panels/vfx_preview.py`'s `_EMIT_FAMILIES` (`:109`) lists six particle
families; every other key in `procedural` degrades to *"no preview for 'x' yet"*.
Add **`projectile`** — but it is NOT a `VfxSystem` particle family, so it needs
its own small preview path rather than an `emit_*` call:

- A dot/sprite that flies repeatedly between two points on the preview surface,
  driven by `procedural.projectile` (`stone_size`/`shell_size`,
  `stone_color`/`shell_color`, `lift_frac`) — the SAME
  `editor/vfx_params.py projectile_params` the panel already builds.
- A stone/shell toggle (the `_strong_check`/`_large_check` precedent at `:285-286`).
- Use `vfx_projectile`/`vfx_shell` art when imported, else the dot — the same
  `assets.animation_total_ms(slot, "idle") is not None` signal the game uses, so
  the two can never disagree about "imported".
- Drive the animation off the panel's existing frame timer; keep it deterministic
  the way the panel already reseeds per `_emit()`.

### 3.2 The projectile drawn at the muzzle handle in the entity preview

`editor/panels/viewport.py`: when the previewed slot has a `muzzle` anchor,
draw the projectile at that handle's screen point, at its real size, so dragging
the handle shows exactly where the shot leaves the barrel.

- Resolve the handle point through `_anchor_draw_params()`/`sprite_anchor_screen`
  — **the same call the handle itself uses**. Never a second computation.
- Submit through `Renderer.submit_hud` (`HudSprite` when the slot has art, else
  `HudRect`) — ED-22, never QPainter.
- Draw it UNDER the handle marker so the crosshair stays readable.

> **PERF — read this before you write it.** `slot_draw_fit` was added in the last
> fix reading two JSON files per call and was called per frame AND per mouse-move
> during a drag: **measured 125–145 ms/frame (~7 fps)**, fixed by memoizing into
> `_draw_fit` (resolved on slot change / registry reload). `vfx.json` is a THIRD
> file. **Memoize it the same way** — resolve once on slot change / reload, never
> inside `render_frame`, `_anchor_draw_params`, `_hit_anchor_handle` or
> `_anchor_move`. Re-measure `render_frame` and report the ms.

---

## 4. File scope

**May modify:** `game/anchors.py`, `game/enemies/combat.py` (the visual spawn +
homing target ONLY), `game/ui/effects.py` (`submit_projectiles`),
`editor/panels/vfx_preview.py`, `editor/panels/viewport.py`,
`editor/vfx_params.py` if needed, `tools/tests/**`, `conftest.py` (TIERS if you
add a module), and the docs describing these (`game/ui/CLAUDE.md`,
`game/enemies/CLAUDE.md`, `editor/panels/CLAUDE.md`).

**Must NOT touch:**
- `launch()`'s timer math, `_impact`'s damage block, `AOE_TRAVEL_TIME`,
  `BEAM_MIN_TICK`, `_predict_lead`, `_chebyshev` — **D4**.
- `ProjectileArc` / the mortar path / `splash_impact` (§2.4).
- `engine/render/renderer.py`'s `sprite_anchor_screen`/`fit_factor`/
  `block_center_offset`/`flush` — feed them, don't change them.
- The five deliberately-unanchored trigger events.
- `data/sprites/asset_manifest.json` — **do not touch the designer's authored
  anchors.**
- New `data/` keys are NOT needed: `procedural.projectile` already carries
  everything (`lift_frac`, sizes, colours). Do not add a schema field unless you
  can say exactly why.

---

## 5. Tests — MINIMAL. A reviewer verifies the rest.

Write **two**, then stop. Do not build out a suite.

1. **Endpoint parity + the D4 pin, in one.** A defender with a `muzzle` anchor
   and a target with an `impact` anchor: the projectile's spawn world point
   equals the muzzle anchor point exactly, and after one `update` it has moved
   TOWARD the target's impact anchor (not its `transform.world_pos`). In the SAME
   test, assert `self.timer` after `launch` is **bit-identical** to the value
   computed from the unanchored positions — the anchors must not move flight
   timing.
2. **Un-anchored is byte-identical.** With no anchors authored, the projectile's
   **drawn screen position** (through `submit_projectiles`) equals what today's
   code produced — i.e. the lift survived the move from draw-time to endpoint.
   Pin the exact pixel. **Run it against the pre-fix code and confirm it PASSES
   there too** — that is what proves the refactor is a no-op for unanchored play.

Fix existing tests only where your change actually breaks them. `TempDataCase`;
never write into `data/`; never assert against live `data/` content; seed RNG.

---

## 6. Exit gate

```bash
py tools/smoke.py
py tools/testgate.py check      # FULL, once, at the end
```

`GATE PASS` or you are not done. The gate is ZERO. `--affected` while iterating;
no manual pytest sanity pass first.

**Note on flakiness:** `test_editor_viewport.py::TestMainWindowVfxMode` and
`::TestMainWindowScreenModeViews` have been observed failing under the gate's
parallel workers and passing serially / on re-run. If you hit exactly those two,
re-run once and say so in your report — do not "fix" them.

### Quick Test (manual)

1. `py editor/main.py` → select a **Stone Thrower** → drag the `muzzle` handle to
   the barrel tip. The projectile now draws **at the handle**, at its real size.
2. Select the **VFX** node → the `projectile` family previews a flying shot;
   retint / resize it and watch the preview follow.
3. Select an **enemy** → drag its `impact` handle to its chest.
4. `py game/main.py`: shots leave the barrel tip and land on the chest — at every
   zoom, and while the enemy walks.
5. Clear both anchors → shots look exactly as they did before this change.

---

## 7. Notes for the executor

- **Report LOUDLY**: the measured `render_frame` ms with a defender previewed
  (§3.2's perf warning); any public signature change; whether the un-anchored
  pixel is truly identical or off by a rounding step (say which, don't hide it).
- **Report, do not fix**: the designer's authored anchors; fixture staleness.
- **Leave a short list of what you did NOT verify** — the reviewer picks it up.
- Tag every claim **measured** / **verified** / **inferred** (`/report`).
