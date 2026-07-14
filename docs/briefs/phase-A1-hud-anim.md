# Phase A1 — Engine: animated `HudSprite`

Slice 10L-A (`planning/UI_EDITOR_PLAN.md` lines 88–96). Branch:
`phase-A1-A2-engine` (A1 first, then A2 — same coder, shared files; see §3).
Package: **engine only** (`engine/render`). Docs: `engine/CLAUDE.md`,
`engine/render/CLAUDE.md`, `engine/assets/CLAUDE.md`.

---

## 1. Behavioral spec

After A1, a HUD sprite animates exactly like a world sprite does.

**What must be true**

1. `HudSprite` carries an animation selector and a time, exactly like
   `RenderItem` does today (`engine/render/item.py:13-24`:
   `animation: str = "idle"`, `anim_time_ms: int = 0`).
   Plan lines 89–90: *"`HudSprite` gains `animation: str = "idle"` and
   `anim_time_ms: int = 0`"*.
2. The renderer's HUD folding block resolves the frame with both, i.e.
   `assets.frame(hud.slot_key, hud.animation, hud.anim_time_ms)`
   (plan lines 91–93). The store already accepts them —
   `engine/assets/store.py:56` is
   `def frame(self, slot_key, animation="idle", anim_time_ms=0)`. This is a
   **pure mirror** of the world-sprite path at `engine/render/renderer.py:106`.
   Nothing else in the pipeline changes: HUD stays screen-space, no coords
   conversion, no depth sort, still folded after sprites + overlays
   (`engine/render/CLAUDE.md` "HUD pass + fonts").
3. **Two times → two frames.** For a manifest entry whose selected row has a
   multi-frame timeline, submitting the same `HudSprite` at `anim_time_ms=0`
   and at a time inside a later timeline step resolves *different* sheet
   columns, hence different surfaces. Frame selection is
   `Manifest.current_frame(slot, animation, time_ms)`
   (`engine/assets/manifest.py:165-185`) — a pure function of time:
   `elapsed = time_ms % track.total_ms`, then walk the `(col, dur_ms)`
   timeline. Single-frame tracks short-circuit and are time-invariant
   (`manifest.py:177-178`) — a static HUD icon therefore never changes even if
   the caller passes a clock.
4. **Animation-row fallback (already implemented — do NOT re-implement).**
   `current_frame` (`manifest.py:172-176`): a missing *animation* name falls
   back to the **idle row** (row 0); a missing *slot*, or a slot with no usable
   idle track, returns the `PLACEHOLDER` sentinel and the store returns the
   grey-X frame (`store.py:58-64`). So `HudSprite("ui_button",
   animation="hover", …)` against a 1-row (idle-only) sheet draws idle — partial
   sheets are fine, and rendering never raises on missing art
   (`engine/assets/CLAUDE.md` E-36/E-37).
5. **Byte-identical when defaulted.** A `HudSprite` constructed without the two
   new args must produce a `DrawCall` identical to today's, field for field
   (`surface`, `dest`, `size`, `tint`, `flip`) — `animation="idle"`,
   `anim_time_ms=0` is exactly what `store.frame`'s own defaults already apply
   at `renderer.py:139`. The three shipping call sites
   (`game/ui/main_menu.py:60`, `game/ui/levelup.py:102-103`,
   `game/ui/building_ui.py:968`) are untouched and must keep working
   unchanged — verify by not editing `game/` at all.
6. **`engine/render` stays pygame-pure** — `renderer.py`, `item.py`, `hud.py`
   import no pygame (`engine/CLAUDE.md` "Hard rules"; pinned by
   `TestPurity.test_pure_modules_do_not_import_pygame`,
   `tools/tests/test_render.py:423-440`).

Out of scope for A1: nine-slice, `DrawCall.slice`, manifest/schema/backend
changes, any `game/` or `editor/` change. See §3.

---

## 2. Architecture plan

Two edits, in this order.

### Edit 1 — `engine/render/hud.py` (`HudSprite`, currently lines 36-45)

Current:

```python
@dataclass(frozen=True)
class HudSprite:
    """A sprite slot blitted in screen space. dest = (x, y), size = (w, h).
    Resolved to a DrawCall by the renderer via assets.frame(slot_key)."""

    slot_key: str
    dest: tuple
    size: tuple
    tint: tuple = None
    flip: bool = False
```

Target:

```python
@dataclass(frozen=True)
class HudSprite:
    """A sprite slot blitted in screen space. dest = (x, y), size = (w, h).
    Resolved to a DrawCall by the renderer via
    assets.frame(slot_key, animation, anim_time_ms) — same slot/animation/time
    contract as RenderItem, so a HUD element animates like a world sprite. A
    missing animation row falls back to idle (manifest semantics); a
    single-frame track is time-invariant.

    animation/anim_time_ms are appended LAST on purpose: the shipping call
    sites pass (slot_key, dest, size) positionally, so tint/flip must keep
    their positions."""

    slot_key: str
    dest: tuple
    size: tuple
    tint: tuple = None
    flip: bool = False
    animation: str = "idle"
    anim_time_ms: int = 0
```

**Field-order decision (binding).** The new fields go **after `flip`**, not
before `tint` (which is where `RenderItem` keeps them). Reason: `HudSprite` has
positional call sites — `HudSprite(slot, (x, y), (38, 38))` in
`game/ui/building_ui.py:968`, `HudSprite(_BG_SLOT, (0, 0), (view_w, view_h))`
in `game/ui/main_menu.py:60`, `HudSprite(slot, (…), (…))` in
`game/ui/levelup.py:102-103`, plus `HudSprite("icon", (2, 2), (16, 16))` in
`tools/tests/test_hud_items.py:52`. Appending is purely additive and cannot
reorder anything. New call sites (A5, 10L-B) must pass `animation=` /
`anim_time_ms=` **by keyword**.

### Edit 2 — `engine/render/renderer.py` (HUD folding block, lines 137-148)

Current (line 139 is the only line that changes):

```python
        for hud in self._hud:
            if isinstance(hud, HudSprite):
                frame = self._assets.frame(hud.slot_key)
                draw_calls.append(DrawCall(
                    surface=frame.surface,
                    dest=hud.dest,
                    size=hud.size,
                    tint=hud.tint,
                    flip=hud.flip,
                ))
            else:
                draw_calls.append(hud)
```

Target:

```python
        for hud in self._hud:
            if isinstance(hud, HudSprite):
                frame = self._assets.frame(
                    hud.slot_key, hud.animation, hud.anim_time_ms)
                draw_calls.append(DrawCall(
                    surface=frame.surface,
                    dest=hud.dest,
                    size=hud.size,
                    tint=hud.tint,
                    flip=hud.flip,
                ))
            else:
                draw_calls.append(hud)
```

Nothing else in `flush()` moves. `dest`/`size` stay the caller's screen-space
values (HUD sprites deliberately ignore `frame.offset_x/offset_y`,
`fit_tiles`, `zoom` — that is the world path only, `renderer.py:106-122`).

### Edit 3 — docs (`engine/render/CLAUDE.md`)

One line in the "HUD pass + fonts" bullet: `HudSprite` resolves via
`assets.frame(slot_key, animation, anim_time_ms)` (was `assets.frame(slot_key)`)
— HUD sprites animate on the same slot/animation/time contract as `RenderItem`;
defaults (`"idle"`, `0`) keep pre-A1 output byte-identical.

---

## 3. File scope + shared-file contract

**The A1 coder may touch exactly these four files. Nothing else.**

| File | What A1 does |
|---|---|
| `engine/render/hud.py` | add the two defaulted fields to `HudSprite` (after `flip`) + docstring |
| `engine/render/renderer.py` | **line 139 only** — the `self._assets.frame(...)` call inside the `for hud in self._hud:` block (137-148) |
| `tools/tests/test_hud_items.py` | extend (see §4) |
| `engine/render/CLAUDE.md` | one-line HUD-pass doc update |

**Do NOT touch:** `game/**` (the three call sites must prove they still work by
staying unedited), `editor/**`, `data/**`, `engine/assets/**`,
`engine/render/backend.py`, `engine/render/item.py`.

### A1 vs A2 (same coder, same branch, same block — coordinate)

A1 and A2 both edit the HUD folding block of `engine/render/renderer.py`.
The split is binding:

- **A1 owns:** the `assets.frame(hud.slot_key, hud.animation, hud.anim_time_ms)`
  call (renderer.py:139) and `HudSprite`'s two new fields.
- **A2 owns:** adding `slice=` to the `DrawCall(...)` constructed in that same
  block, plus `DrawCall` / `Frame` / `ManifestEntry` / `backend.py` /
  `asset_manifest.schema.json`.
- **A1 plans and writes NO `slice` work** — not a field, not a param, not a
  TODO. Land A1 (tests green), then start A2 on top.

**Test-file ownership:** A1 owns `tools/tests/test_hud_items.py` (extend it).
A2 owns `test_render.py`, `test_asset_store.py`, `test_assets_manifest.py` —
A1 does not edit those. Only if a new file is unavoidable: `tools/tests/test_hud_anim.py`
(prefer extending `test_hud_items.py`).

---

## 4. Exit gate + Quick Test

### Commands

```
py -m unittest discover -s tools/tests -t .     # 1086 tests, 16 pre-existing failures
py tools/smoke.py
```

**Gate = no NEW failures.** Baseline on Development is **16 failures / 1 skipped**
in: `test_run_controls`, `test_details_panel` (`TestSubcategoryDropdown`),
`test_editor_viewport` (`TestEntityPreview` ×3), `test_editor_panels` ×2,
`test_editor_map_mode` ×2, `test_balancing_parity` ×6. Do **not** try to fix
those. Your new tests must pass, and `test_render.TestPurity` +
`test_hud_items` + `test_asset_store` must stay green.

### New tests — all in `tools/tests/test_hud_items.py`

`FakeAssets.frame` there (line 32-34) already takes `(slot_key,
animation="idle", anim_time_ms=0)` but ignores them. Add a recording fake next
to it (do not change the existing `FakeAssets` signature or its return shape —
other tests depend on it), e.g.:

```python
class RecordingAssets(FakeAssets):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []

    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        self.calls.append((slot_key, animation, anim_time_ms))
        return super().frame(slot_key, animation, anim_time_ms)
```

Add a `class TestHudSpriteAnimation(unittest.TestCase)` with:

1. **`test_defaults_unchanged`** — `HudSprite("icon", (2, 2), (16, 16))` has
   `animation == "idle"` and `anim_time_ms == 0`; flushing it makes the store
   see exactly `("icon", "idle", 0)`, and the emitted `DrawCall` matches the
   pre-A1 one (`surface`, `dest`, `size`, `tint=None`, `flip=False`). Also
   assert the existing positional shape still constructs
   (`HudSprite("icon", (2, 2), (16, 16))` — the game's call form) and that
   `tint`/`flip` are still reachable as the 4th/5th positional fields.
2. **`test_animation_and_time_forwarded`** — submit
   `HudSprite("btn", (0, 0), (64, 32), animation="hover", anim_time_ms=250)`;
   assert the store was called with `("btn", "hover", 250)`.
3. **`test_two_times_resolve_different_frames`** — the plan's acceptance test
   (lines 94-96). Build a **real** `Manifest` from a two-row entry via
   `engine.assets.manifest.entry_from_dict` (pure, no pygame), e.g.
   `{"sheet": "x.png", "frame_w": 16, "frame_h": 16,
     "rows": [{"animation": "idle", "frames": 1},
              {"animation": "hover", "frames": 2, "fps": 10}]}` (100 ms/frame),
   and a tiny pure fake store that returns
   `Frame(surface=manifest.current_frame(slot, animation, t), frame_w=…, frame_h=…)`
   — i.e. surface == the `(row, col)` ref, so the test stays pygame-free.
   Submit the same `HudSprite` at `anim_time_ms=0` and `anim_time_ms=150`
   with `animation="hover"` and assert the two `DrawCall.surface` values are
   `(1, 0)` and `(1, 1)` — **different frames, same row**.
4. **`test_missing_animation_falls_back_to_idle`** — same manifest, submit
   `animation="pressed"` (no such row): the resolved ref's row is **0** (the
   idle row) at any time, per `manifest.py:172-176`.

### Quick Test (human, in-game)

`py game/main.py` → the main menu. `game/ui/main_menu.py:60` submits
`HudSprite(_BG_SLOT, (0, 0), (view_w, view_h))` with no animation args, so the
menu background must look **exactly** as before A1 (this is the
byte-identical-when-defaulted check). Then start a level and open the build
panel: `game/ui/building_ui.py:968` draws the 38×38 building icons via
`HudSprite` — they too must be pixel-identical, and any slot with no imported
art still shows the grey X, never a crash. Nothing should *visibly* animate yet:
A1 is the wiring; A5/10L-B are what will pass a real clock.
