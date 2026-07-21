# Fix — anchor origin parity (VFX and HP bars spawn where the handle is)

**A shipped bug, reported live by the designer**: *"all vfx regardless how i
assign them are not spawning at the assigned spots i put in the editor."*
Branch `fix/anchor-origin-parity` off `VfxEditor`. Cross-package:
**engine + game + editor**.

**Read**: `game/CLAUDE.md`, `game/ui/CLAUDE.md`, `editor/CLAUDE.md`,
`editor/panels/CLAUDE.md`, `engine/render/CLAUDE.md`.

**Guardrail D4 still binds.** Purely cosmetic. Nothing here touches damage,
range, splash or simulation state.

---

## 1. Root cause (measured, not inferred)

The editor draws every anchor handle from the sprite's **drawn centre**. Every
game consumer applies the anchor from a **different base**. So a handle dragged
onto a barrel resolves somewhere else in game — always, for every anchor.

| Consumer | Base it uses today | Error vs the handle |
|---|---|---|
| VFX (`game/anchors.py` `world_offset`) | `cs.world_to_screen(wx, wy)` — the entity's tile anchor | `tile_h/2 * zoom` (**16 px** at zoom 1) **plus** the missing `block_center_offset` shift for multi-tile footprints |
| HP bars (`screen_offset` + `_sprite_top`, `game/ui/effects.py:889`, `:940`) | the sprite's drawn **top** | `frame_h * s * zoom / 2` (**32 px** for a 64-px frame at s=1) |

Measured on real data (`enemy_stage_1_v1`, anchor `muzzle: [-19, -8]`, tile_h 32,
zoom 1): editor handle at screen y **200**, game VFX at screen y **184** — a
constant **−16 px**. The designer's authored `hp_bar: [-103, -60]` is them
dragging to compensate for a base that never matched.

### 1.1 The canonical origin (from `engine/render/renderer.py:126-140`)

This is the ONE truth. A sprite is drawn as:

```python
c    = block_center_offset(item.fit_tiles)
px, py = coords.world_to_screen(item.world_pos[0] + c, item.world_pos[1] + c)
s    = fit_factor(frame.frame_w, tile_w, item.fit_tiles) * item.scale
w, h = frame.frame_w * zoom * s, frame.frame_h * zoom * s
dest = (px - w/2 + frame.offset_x*zoom*s,
        py + half_h*zoom - h/2 + frame.offset_y*zoom*s)   # half_h = tile_h/2
```

Therefore the sprite's drawn **centre** in screen space is:

```
centre_x = px + offset_x * zoom * s
centre_y = py + (tile_h / 2) * zoom + offset_y * zoom * s
```

and an anchor `(ax, ay)` resolves to `centre + (ax * zoom * s, ay * zoom * s)`.

**Every** consumer — game and editor — must resolve an anchor through exactly
this expression.

### 1.2 Why the tests passed anyway (fix this too)

`tools/tests/test_esv6_converge.py::TestWatchEnemiesMuzzleAnchor` asserts
`wx == 2.0 + dwx` where `dwx` comes from calling **`world_offset(...)` — the
function under test**. A tautology: it passes for any implementation, correct or
not. It also monkeypatches `fm._play`, so no test ever checked that a pixel lands
where the handle was. **Do not write another assertion of that shape.** §4.1 is
the test that actually pins the bug.

---

## 2. The fix

### 2.1 One shared, pure geometry helper in `engine/`

`editor/` may not import `game/`, so the formula would otherwise be duplicated
and drift again. Put it in **`engine/render/renderer.py`** beside `fit_factor` /
`block_center_offset` (its natural home — they are the two pieces it composes),
exported from `engine.render`:

```python
def sprite_anchor_screen(cs, wx, wy, frame_w, frame_h, fit_tiles, scale,
                         offset_xy, anchor_xy):
    """SCREEN point an `anchor_xy` frame-px anchor resolves to on the sprite
    drawn for world position (wx, wy) — the exact inverse-free companion of
    `flush`'s placement above. `anchor_xy` (0, 0) is the sprite's drawn CENTRE.
    Pure: no pygame, no game vocabulary."""
```

It must reuse `block_center_offset` and `fit_factor` — **never restate them**.
`frame_h` is unused by the centre formula; keep it out of the signature unless
you find a real need (do not add an unused parameter).

### 2.2 `game/anchors.py` — resolve to an absolute world point

Replace the delta-from-transform model, which is what let the base drift.

```python
def anchor_world_point(assets, cs, obj, name):
    """World point of `obj`'s `name` anchor ON THE DRAWN SPRITE, or None when
    the store/cs/animator/slot/anchor is absent. `None` is the caller's cue to
    use its own pre-anchor fallback point (E-37)."""
```

Build it from `sprite_anchor_screen(...)` then `cs.screen_to_world(...)`.

`screen_offset` / `world_offset` stay **only** if something still needs them;
prefer deleting whatever becomes unused rather than leaving two ways to resolve
an anchor. If you keep `world_offset`, it must be defined as
`anchor_world_point(...) - obj.transform.world_pos` so the two cannot disagree.

### 2.3 Game call sites — "anchor wins outright" (designer's decision)

Rule everywhere: **anchor present → use the anchor point; anchor absent → today's
expression, byte-identical.**

- **`watch_enemies`** (`effects.py:581`) — `muzzle` on the attacking enemy;
  fallback `e.transform.world_pos`.
- **`watch_buildings`** (`effects.py:547`) — `impact` on the destroyed building;
  fallback `(b.transform.wx + 0.5, b.transform.wy + 0.5)`.
- **HP bars** (`effects.py:889` buildings, `:940` enemies) — when an `hp_bar`
  anchor is authored, the bar's screen point is
  `cs.world_to_screen(anchor_world_point(...))`, **replacing** the `_sprite_top`
  computation rather than nudging it. **No anchor → `_sprite_top` exactly as
  today** (the ER-1 footprint fit, D3), untouched.
- **`combat.py`** `_fire` / `_fire_splash` — the muzzle spawn point and the
  `on_defender_fire` callback point.
- **`projectile_hit`** — the target's `impact`.

### 2.4 Editor — call the same helper

`editor/panels/viewport.py` `_anchor_draw_params` must resolve through
`sprite_anchor_screen` too, passing the **preview RenderItem's actual**
`fit_tiles`/`scale` (`viewport.py:982-988` submits with the dataclass defaults —
`fit_tiles=0.0`, `scale=1.0`). Do not hand-roll the origin again.

**Known residual, report don't fix:** the editor previews at `fit_tiles=0.0`
while the game draws entities at their real footprint, so for a slot whose frame
is wider than `footprint * tile_w` the two `s` values differ and the handle would
still not match in game. **Measured: `s == 1.0` on both sides for every entity in
`data/` today**, so it is not the live bug. Note it in your report; do not change
the preview's size in this fix.

---

## 3. File scope

**May modify:** `engine/render/renderer.py` (+ `engine/render/__init__.py`
export), `game/anchors.py`, `game/ui/effects.py`, `game/enemies/combat.py`
(anchor read sites ONLY), `editor/panels/viewport.py`, `tools/tests/**`, and the
package docs that describe anchor resolution (`engine/render/CLAUDE.md`,
`game/ui/CLAUDE.md`, `editor/panels/CLAUDE.md`, `engine/assets/CLAUDE.md`).

**Must NOT touch:**
- **The five deliberately-unanchored events stay unanchored** — `building_placed`,
  `building_level_up`, `building_tier_up`, `enemy_death`, `splash_impact`. The
  designer confirmed this. `test_esv6_converge.py::TestExcludedEventsStayUnanchored`
  pins it and must keep passing.
- `ProjectileHoming.launch`'s `origin` parameter, `AOE_TRAVEL_TIME`,
  `BEAM_MIN_TICK`, `_predict_lead`, `_chebyshev`, every damage/range/splash
  expression — **D4**.
- `block_center_offset` / `fit_factor` themselves, and `flush`'s placement math.
- The `triggers` table, `PlayOnceVfx`, `engine/vfx/**`.
- `data/` content — **do not "fix" the designer's authored `hp_bar: [-103, -60]`
  on `enemy_stage_1_v1`.** Once the bug is fixed they will re-drag it; silently
  rewriting their data is worse than leaving it odd.

---

## 4. Tests — MINIMAL. Write ONE. A reviewer verifies the rest.

**Do not build out a test suite for this fix.** Ship the implementation plus the
single test below, then stop. A separate `reviewer` pass owns coverage,
edge cases and the tautology cleanup — duplicating that work here wastes the
session and is explicitly not your job.

### The one test: editor↔game screen parity

For one slot with an authored anchor, assert that

> the SCREEN point the editor draws the handle at
> **equals**
> the SCREEN point the game resolves the anchor to

computed through the two real code paths — the editor's `_anchor_draw_params` +
`anchor_ops.screen_point`, and `cs.world_to_screen(anchor_world_point(...))`.

**Assert the two numbers equal each other. Never assert either against the helper
that produced it** — that is the §1.2 tautology that let this bug ship green.

One case is enough (zoom 1, non-zero `offset_y`, `fit_tiles=0`). **Run it against
the pre-fix code once and confirm it FAILS by ~16 px**, then fix and watch it
pass — report both numbers. A test that never failed proves nothing.

### Keep green, don't extend

`TestExcludedEventsStayUnanchored` and
`TestGuardrailD4BitIdenticalUnderLargeAnchors` must still pass untouched. Fix any
existing test that your signature changes break, but **do not add cases to them**.

---

## 5. Exit gate

```bash
py tools/smoke.py
py tools/testgate.py check        # FULL, once, at the end
```

`GATE PASS` or you are not done. The gate is ZERO. `--affected` while iterating.
No manual pytest sanity pass first. A red test clearly outside this diff's blast
radius: note it and stop.

### Quick Test (manual)

1. `py editor/main.py` → select **Stone Thrower** → drag `muzzle` onto the barrel
   tip. Note roughly where it sits.
2. Bind `triggers.enemy_attack_ranged.sprite_slot` (or leave procedural) and
   `py game/main.py`: the muzzle spray fires **from the barrel tip**, not half a
   tile above it.
3. Drag the handle somewhere obviously different (e.g. far left). Replay — the
   VFX follows it exactly.
4. Author an `hp_bar` anchor on an enemy → the bar appears **at the handle**.
   Clear the anchor → the bar returns to riding the sprite's top exactly as
   before.
5. Zoom in and out mid-round: the VFX stays locked to the same point on the
   sprite at every zoom.

---

## 6. Notes for the executor

- **Report LOUDLY**: the measured pre-fix failure of the §4 parity test (in px);
  any public signature change; whether you deleted `screen_offset`/`world_offset`
  or kept them; the editor-preview `fit_tiles` residual (§2.4).
- **Leave a short list of what you did NOT verify** — the reviewer picks it up.
- **Report, do not fix**: the designer's odd authored `hp_bar` value; the stale
  `tools/tests/fixtures/data/` snapshot.
- Tag every claim **measured** / **verified** / **inferred** (`/report`).
