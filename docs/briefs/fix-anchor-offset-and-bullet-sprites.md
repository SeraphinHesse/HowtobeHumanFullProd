# Fix — anchor/offset composition + swappable bullet sprites

Follow-up to `planning/EntitySceneVfxPLAN.md` (complete, PR #62). Two independent
live-testing findings. Branch `fix/anchor-offset-and-bullet-sprites` off
`VfxEditor`. Cross-package: **engine + game + editor + data**.

**Read**: `game/CLAUDE.md`, `game/ui/CLAUDE.md`, `editor/CLAUDE.md`,
`editor/panels/CLAUDE.md`, `data/CLAUDE.md`. **Read first**:
`docs/briefs/phase-esv-1-anchors.md` §1.4 and `docs/briefs/phase-esv-2-anchor-handles.md`
§1.4 — they made the decision Fix 1 reverses, and their reasoning is what you are
overturning deliberately, not by accident.

**Open with `/add-balancing-value`** for the new `procedural.projectile` block.

**Guardrail D4 still binds.** Both fixes are purely cosmetic. Nothing here reads
or writes damage, range, splash or simulation state.

---

## Fix 1 — Compose `offset_x`/`offset_y` into the anchor origin

### 1.1 The defect (all **verified** on this tree)

Three places answer "where is this sprite's anchor point". One disagrees:

| Consumer | Applies the entry's nudge? | Site |
|---|---|---|
| Renderer, drawing the art | **YES** | `engine/render/renderer.py:138-139` — `px - w/2 + frame.offset_x * zoom * s`, and the y twin |
| Game anchor read | no | `game/anchors.py:34-50` `screen_offset` — scales `(ax, ay)` only |
| Editor handle origin | no | `editor/panels/viewport.py:822-838` `_anchor_draw_params` → `origin = (sx, sy + g.tile_h / 2 * zoom)` |

The game and the editor agree with **each other** and disagree with the renderer,
which is why nothing looks broken today — the two wrong ones are consistent.

ESV-2 §1.4 made this an explicit, orchestrator-ratified decision, recorded in
three places (`editor/panels/anchors_panel.py:23-28` module docstring, its
`self._note` label at `:70-74`, and `editor/panels/CLAUDE.md`'s "Handle origin
excludes `offset_x`/`offset_y`" bullet). All three add the same escape clause:
*"the fix belongs on the game side, not here."* **This brief is that fix.** The
designer's reading — the handle should sit on the art — is the correct one.

### 1.2 The change

Fold the nudge into the anchor origin on **both** sides, so all three consumers
measure from where the art actually draws.

**`engine/assets/store.py`** — add an `offset(slot_key)` accessor returning
`(x, y)` ints, `(0, 0)` when the slot or entry is absent. **Mirror `anchor()` at
`store.py:64-72` exactly** — same guard shape, same degrade-never-raise contract.
`ManifestEntry` already carries the fields (`engine/assets/manifest.py:89-90`).

**`game/anchors.py` `screen_offset`** — compose before scaling:

```python
    anchor = assets.anchor(anim.slot_key, name)
    if anchor is None:
        return (0.0, 0.0)          # KEEP: an un-anchored slot must not move
    ax, ay = anchor
    ox, oy = assets.offset(anim.slot_key)
    ax, ay = ax + ox, ay + oy      # NEW: the nudge the renderer already applies
    if ax == 0 and ay == 0:
        return (0.0, 0.0)
    s = _scale_factor(assets, cs, anim)
    return (ax * s * zoom, ay * s * zoom)
```

Two things about that shape, both load-bearing:

- **The `anchor is None` early return stays exactly where it is.** It is what
  keeps all 181 un-anchored entries numerically byte-identical. Do NOT move the
  offset read above it — an entry with a nudge and no anchor must still return
  `(0.0, 0.0)`.
- **The `ax == 0 and ay == 0` short-circuit now tests the COMPOSED pair**, not the
  raw anchor. An anchor authored at `[0, 0]` on a nudged entry now has a real,
  non-zero delta — that is the fix working, not a bug.

**`world_offset`'s docstring** (`game/anchors.py:53-62`) says the zero case means
"no anchor authored, or an anchor authored at [0, 0]". The second clause is no
longer true on a nudged entry. Update it.

**`editor/panels/viewport.py` `_anchor_draw_params`** — fold the same offset into
`origin`. `s` and `zoom` are already computed there; the entry's offset comes from
the same `self._assets` store the method already uses for `frame_size`.

> **This is the ONLY editor code change Fix 1 needs.** `anchor_ops.screen_point`
> and `anchor_ops.frame_px` are pure algebra over a caller-supplied origin, and
> they are exact inverses of each other, so shifting the origin fixes the draw
> AND the drag in one move. **Do not touch `editor/anchor_ops.py`.**

**Delete the note that is no longer true**: `anchors_panel.py`'s `self._note`
`QLabel` (`:70-74`) and its `addWidget` call, plus the module-docstring paragraph
at `:23-28`. Check whether any test asserts on that label's text and update it.

### 1.3 Data impact — **verified, none**

I checked all 183 manifest entries on this exact tree:

- 8 carry a non-zero offset, all `offset_y: 8`: `maw_mortar_t1_lvl1/2/3`,
  `sun_scorcher_t1_lvl1/2/3`, `blocker`, `wall_builder`.
- 2 carry anchors: `stone_thrower_t1_lvl1`, `enemy_stage_1_v1`.
- **The intersection is empty.** No authored anchor moves.

**Re-run that check yourself before you start** — the manifest changed as recently
as `b07e752`, and if a designer has since anchored a mortar, the diff stops being
a no-op and you must say so LOUDLY in your report.

---

## Fix 2 — Swappable bullet sprites

### 2.1 Current state (**verified**)

`game/ui/effects.py` `submit_projectiles` (`:685-701`) draws every in-flight shot
as a `HudRect` dot: `_PROJECTILE_SHELL` when `p.name == "shell"`, else
`_PROJECTILE_STONE`; size `max(2, int((5 if shell else 3) * zoom))`; lifted
`int(cs.geometry.tile_h * zoom * 0.6)` off the ground plane; drawn with
`border_radius=size // 2` so it reads as a circle.

`_PROJECTILE_STONE` / `_PROJECTILE_SHELL` (`:160-161`) are the **last un-ported
cosmetic constants** in the file — ESV-3a/3b/6 moved everything else into
`data/balancing/vfx.json`. The remaining `_BOSS_HUD_BAR_LIFT` /
`_ENEMY_BAR_STACK` / `_ENEMY_BAR_FALLBACK` are HUD bar geometry and stay put.

### 2.2 The change

**`data/slots.json`** — add `vfx_projectile` and `vfx_shell` to the `vfx`
category's single `Effects` group `slots` array (which ESV-5 left at
`["vfx_hit", "vfx_explosion", "vfx_muzzle", "vfx_death", "vfx_slash",
"vfx_crater"]`). Bare strings — the category's 64×64 frame size and `["idle"]`
animation vocabulary apply. **Registry membership IS importability**
(`editor/asset_import.py:139-150` calls `registry.frame_size(slot_key)` and
raises `KeyError` for an unregistered slot), so this is the entire importer
change — **no editor code**.

**`data/balancing/vfx.json` + `data/schemas/vfx.schema.json`** — a new
`procedural.projectile` block. Defaults MUST equal today's values exactly:

| Key | Today | Source |
|---|---|---|
| `stone_color` | `[185, 180, 170]` | `_PROJECTILE_STONE` `:160` |
| `shell_color` | `[70, 60, 55]` | `_PROJECTILE_SHELL` `:161` |
| `stone_size` | `3` | inline `:695` |
| `shell_size` | `5` | inline `:695` |
| `lift_frac` | `0.6` | inline `:698` |

Reuse `$defs/color` for the two colours. `description` + `minimum`/`maximum` on
every numeric key (D-12); `additionalProperties: false`; all keys `required`.
The `max(2, …)` size floor is a degeneracy guard, not a tunable — keep it inline
and say so in a comment. Deterministic validating writer only (D-3).

**`engine/vfx/params.py`** — a frozen `ProjectileParams` dataclass + one field on
the `VfxParams` bundle. **APPEND ONLY**; do not rename or reorder anything.

**`editor/vfx_params.py`** — mirror the new field in its `params_from_balance`.
`VfxParams` gaining a required field is exactly the break ESV-6 hit live
(`TypeError: VfxParams.__init__() missing 1 required positional argument:
'floaters'`, reproduced at `vfx_preview.py:442` on every family switch).
`editor/CLAUDE.md`'s "VFX preview" section documents it. **Do not repeat it** —
change both files in the same commit and verify by constructing the panel.

**`game/ui/effects.py`** — read the block in `_params_from_balance`, delete the
two constants, and give `submit_projectiles` a sprite branch:

- Slot: `vfx_shell` when `p.name == "shell"`, else `vfx_projectile`.
- **Has art → `HudSprite`**, positioned at the same lifted centre the dot uses,
  sized from the params (or the sheet's frame size — your call, but state which
  and why). **No art → today's `HudRect` verbatim**, from the JSON params.
- Reuse the existing art check rather than inventing one — `spawn_play_once`
  (`engine/vfx/play_once.py`) already decides "does this slot have art" via
  `assets.animation_total_ms(slot, "idle")` returning `None`. Use the same signal
  so the two paths can never disagree about what "imported" means.
- `self.assets` is host-wired (ESV-5, `game/main.py:283`) and is `None` in every
  bare-constructed test. **`None` must degrade to the dot, never raise.** Pin it.

`HudSprite` is already imported in this module's neighbourhood
(`game/ui/widgets.py:171` uses it) — projectiles draw on the HUD pass, so a
screen-space `HudSprite` is the right primitive and preserves the existing
"always on top, never depth-sorted" behaviour. Do **not** move projectiles onto
the entities layer; that would change depth sorting and the lift semantics.

### 2.3 Scope boundaries (user decisions)

- **Two shared slots, not per-defender projectile art.** Every defender's stone
  uses `vfx_projectile`; every mortar shell uses `vfx_shell`. A per-building
  projectile slot was considered and explicitly deferred.
- **NOT a trigger-table event.** Projectiles are continuous in-flight objects,
  not one-shots — the same reasoning that keeps beams and lightning procedural
  (`EntitySceneVfxPLAN` §5 "Which effects are truly one-shot vs. continuous").
  Add **no** `triggers` row, spawn **no** `PlayOnceVfx`.

---

## 3. File scope

### May modify

| File | Scope |
|---|---|
| `engine/assets/store.py` | Fix 1 — the `offset()` accessor, mirroring `anchor()` |
| `game/anchors.py` | Fix 1 — `screen_offset` composition + `world_offset`'s docstring |
| `editor/panels/viewport.py` | Fix 1 — `_anchor_draw_params`'s origin ONLY |
| `editor/panels/anchors_panel.py` | Fix 1 — delete `self._note` + its `addWidget` + the docstring paragraph |
| `data/slots.json` | Fix 2 — two slot strings |
| `data/balancing/vfx.json`, `data/schemas/vfx.schema.json` | Fix 2 — `procedural.projectile` |
| `engine/vfx/params.py`, `engine/vfx/__init__.py` | Fix 2 — `ProjectileParams`, append-only |
| `editor/vfx_params.py` | Fix 2 — mirror the new required field |
| `game/ui/effects.py` | Fix 2 — `_params_from_balance`, `submit_projectiles`, delete `:160-161`; module docstring gains a paragraph |
| `tools/tests/fixtures/data/**` | **Surgical** mirror of the three data files only |
| `tools/tests/**` | §4; `conftest.py` `TIERS` entry if you add a module |
| `editor/panels/CLAUDE.md` | rewrite the "Handle origin excludes…" bullet — it now COMPOSES the nudge |
| `game/ui/CLAUDE.md` | the ESV-1 anchor paragraph + a projectile-sprite note |
| `engine/CLAUDE.md`, `data/CLAUDE.md` | the new accessor / the new slots + block |

### Must NOT touch

- **`editor/anchor_ops.py`** — §1.2's box explains why the origin shift is
  sufficient. Editing it would double-apply the offset.
- The `triggers` table, its events, `PlayOnceVfx`, `engine/vfx/play_once.py`.
- `ProjectileHoming.launch`'s `origin` parameter, `AOE_TRAVEL_TIME`,
  `BEAM_MIN_TICK`, `_predict_lead`, `_chebyshev`, every damage/range/splash
  expression — **D4**.
- `game/enemies/corpse.py`, the buildings' animation vocabulary, and anything
  resembling an "entity animation row" trigger effect — **a third reported issue
  was explicitly parked by the user and is OUT OF SCOPE.** Do not pre-empt it.
- `_BOSS_HUD_BAR_LIFT` / `_ENEMY_BAR_STACK` / `_ENEMY_BAR_FALLBACK` and the HP-bar
  submitters.
- `planning/`, root `PLAN.md`.
- Do not reflow `effects.py`/`viewport.py` or run a whole-file formatter.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py
py tools/testgate.py check      # FULL, once, at the end
```

`GATE PASS` or you are not done. **The gate is ZERO.** Use `--affected` while
iterating; the full `check` runs exactly once, at handback. Do **not** run a
manual `pytest` sanity pass first. A red test clearly outside this diff's blast
radius: note it and stop.

### Required tests

`TempDataCase` / the pinned fixture; never write into `data/`; never assert
against live `data/` content; expectations as **literals**; seed every RNG.

1. **Anchor composition** — a fixture entry with `offset_y: 8` and
   `muzzle: [0, -20]` resolves 8 frame-px lower (scaled) than the same entry with
   no offset. Assert the exact composed number, not a direction.
2. **Byte-identity pin** — an entry with a non-zero offset and **no** anchors
   still returns exactly `(0.0, 0.0)` from both `screen_offset` and
   `world_offset`. This is the claim that 181 entries are untouched.
3. **The `[0, 0]` case flips** — an anchor authored at `[0, 0]` on a nudged entry
   now returns a NON-zero delta (it used to short-circuit to zero). Pin it
   explicitly; it is the subtlest behaviour change in the diff.
4. **Editor origin/drag round-trip** — on a nudged slot, a synthetic drag writes
   the frame-px the designer sees, and re-seeding the panel redraws the handle at
   the same screen point. This is the pin that `screen_point` and `frame_px`
   stayed exact inverses after the origin moved.
5. **Guardrail D4 re-pin** — `tools/tests/test_esv6_converge.py::
   TestGuardrailD4BitIdenticalUnderLargeAnchors` must still pass, and extend it so
   the shooter and target ALSO carry a non-zero offset: HP ledger, kill count and
   flight timing bit-identical.
6. **Projectile fallback** — with no art, `submit_projectiles` emits exactly
   today's `HudRect` stream (colour, size, lift, border_radius) built from the
   shipped JSON defaults; the `max(2, …)` floor still applies at low zoom.
7. **Projectile sprite** — with a fixture sheet on `vfx_projectile`, a stone emits
   a `HudSprite`; a shell with art on `vfx_shell` emits its own; a shell with art
   only on `vfx_projectile` still falls back to its dot (the two slots are
   independent).
8. **`assets=None` degrades** — a bare `FloaterManager` emits dots and never
   raises.
9. **Editor constructibility** — `editor/vfx_params.params_from_balance` builds a
   `VfxParams` with the new field, and `VfxPreviewPanel` opens and switches
   families without raising. This is the regression pin for the `6a05689` class
   of break.
10. **Schema** — `procedural.projectile` validates; every numeric key carries
    `description`/`minimum`/`maximum`; the two new slots resolve through
    `registry.frame_size` at 64×64.

### Quick Test (manual)

```bash
py editor/main.py
```
1. Select **Maw Mortar** level 1 (it carries `offset_y: 8`) → tick `muzzle` → drag
   the handle onto the barrel tip. **The handle sits on the art**, and the
   "Handle origin ignores…" note is gone.
2. Select **Stone Thrower** (no offset) → its existing `muzzle: [1, -20]` handle is
   exactly where it was before this change.
3. Import any 64×64 placeholder into `vfx_projectile`.

```bash
py game/main.py
```
4. Build a stone thrower, End Turn → shots draw as the imported sprite. Clear the
   slot → the grey dot returns, unchanged.
5. Bind `triggers.defender_fire.sprite_slot = "vfx_muzzle"` (with art) and Play a
   **mortar**: the flash appears at the barrel tip dragged in step 1, **not 8px
   above it**. This is the end-to-end proof Fix 1 worked.
6. Retint `procedural.projectile.stone_color` in the editor → the dot changes.
7. A full round: kills, base HP and timing unchanged.

---

## 5. Notes for the executor

- **Re-run the offset∩anchors check first** (§1.3). It is a no-op diff only while
  that intersection is empty; the manifest changed as recently as `b07e752`.
- **Report LOUDLY**: any public signature change; whether you sized the projectile
  `HudSprite` from params or from the sheet's frame size, and why; whether any
  test asserted on the deleted note label.
- **Report, do not fix**: the stale `tools/tests/fixtures/data/` snapshot (known,
  unrelated — missing `data/ui/`, several maps, drifted `slots.json`/
  `buildings.json`/`enemies.json`); anything you notice about the parked third
  issue.
- Tag every claim **measured** / **verified** / **inferred** (`/report`).
