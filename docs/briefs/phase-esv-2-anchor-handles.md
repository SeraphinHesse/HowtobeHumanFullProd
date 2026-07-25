# Phase ESV-2 — Anchor handles in the viewport

Plan: `planning/EntitySceneVfxPLAN.md` §ESV-2. Track A · **editor only**.
Read `editor/CLAUDE.md` and `editor/panels/CLAUDE.md` — those two, not the game
or engine package docs (you may READ `engine/` to call it; you may not edit it).

**ESV-1 has landed and merged.** It is your data layer: the schema's optional
`anchors` block, `ANCHOR_NAMES` (`engine/assets/manifest.py:28`),
`ManifestEntry.anchor()` (`engine/assets/manifest.py:95`), and
`AssetStore.anchor(slot_key, name)` (`engine/assets/store.py:64-72`). Do not
rebuild any of it, do not edit any of it.

> **THE ONE RULE MOST LIKELY TO BE BROKEN HERE — ED-22, one render path.**
> Handles, their outlines and their labels are submitted through the ENGINE:
> `Renderer.submit_overlay_lines` (`engine/render/renderer.py:79-85`) for
> geometry, `Renderer.submit_hud` (`:96-105`) for any text.
> **QPainter draws exactly one thing in this viewport and it stays that way:
> the converted engine frame** (`editor/panels/viewport.py:961-969`,
> `surface_to_qimage` at `:76`). A handle painted in `paintEvent` is a second
> render path and the phase fails review, even if it looks right. The 2×2
> start-area outline (`editor/panels/viewport.py:851-872`) is the pattern to
> copy verbatim.

---

## 1. Behavioral spec

### 1.1 Where this hangs — the existing entity preview, not a new mode

The viewport already has exactly three modes: map (`in_map_mode()`,
`editor/panels/viewport.py:272`), screen (`in_screen_mode()`, `:308`), and the
fall-through **entity preview** (`render_frame`'s `else` branch,
`editor/panels/viewport.py:799-814`), which submits ONE `RenderItem` for
`self.preview_slot` at the map centre on the `entities` layer. That fall-through
is where anchor handles live. **Add no fourth mode**, no `set_anchor_mode()`, no
new selection state — the selected slot arrives through the existing
`set_preview_slot(slot_key)` (`:197-205`), driven from
`MainWindow._select_slot` (`editor/main.py:646-648`). Handles are visible
whenever the entity preview is showing a slot; they are absent in map mode and
screen mode by construction (those branches never call the handle submitter).

### 1.2 The six names are read from `ANCHOR_NAMES`, never listed in the editor

`engine/assets/manifest.py:28` declares the six (`muzzle`, `impact`, `hp_bar`,
`floater_origin`, `status_icon`, `beam_endpoint`). Only three have game
read-sites today; the other three are authorable and inert **on purpose** so
this UI can be generic (ESV-1 brief §1.1). Import the tuple and iterate it.
A literal list of names anywhere in `editor/` is a review failure — when a
seventh name is declared, this phase's UI must gain it with zero editor edits
(the same argument `editor/domains.py` makes for the derived domain list,
`editor/panels/CLAUDE.md` §Phase 4).

### 1.3 What a handle looks like

- One handle per anchor **present in the effective entry**, plus the one
  currently being authored (§1.6).
- Geometry: a small closed square (or diamond) outline, **fixed screen size**
  — `HANDLE_RADIUS_PX = 6` (half-extent), drawn via `submit_overlay_lines(...,
  width=2, closed=True)`. Fixed *screen* size means zooming does not grow the
  handle; §2.3 is how that is achieved without restating iso math.
- A short crosshair (two 2-point polylines through the centre) so the exact
  pixel is readable at low zoom.
- Colour: one constant per state — unselected, selected (the anchor whose row
  is focused in the panel), dragging. Define them beside the existing
  `GRID_COLOR` / `START_AREA_COLOR` / `START_AREA_GHOST_COLOR` constants in
  `editor/panels/viewport.py` (module top). Keep them legible on **both** the
  light and dark chrome themes (`editor/CLAUDE.md` §Theme) — the viewport's own
  `BACKGROUND` fill is theme-independent, so this is easy; do not read the Qt
  palette here.
- The anchor **name** may be labelled next to the handle via
  `Renderer.submit_hud(HudText(...))` — screen-space, engine HUD pass, ED-22
  clean. Optional; if it clutters at small zoom, drop the labels and rely on
  the panel's selection highlight instead. Never a `QLabel` child positioned
  over the frame.

### 1.4 Where a handle sits (the load-bearing placement rule — read twice)

An anchor is **frame-px relative to the sprite anchor**, `+x` right, `-y` up,
measured on the sheet frame (ESV-1 brief §1.2). The renderer blits a frame
**centred on the tile diamond's centre** — `engine/render/renderer.py:130-137`:

```
px, py = coords.world_to_screen(wx + c, wy + c)            # :127-128
s      = fit_factor(frame.frame_w, tile_w, item.fit_tiles) * item.scale   # :129
dest   = (px - w/2 + frame.offset_x*zoom*s,
          py + half_h*zoom - h/2 + frame.offset_y*zoom*s)  # :133-136
```

So the drawn frame's CENTRE is `(px + offset_x*z*s, py + half_h*z +
offset_y*z*s)`, and the **handle origin** — the screen point an anchor of
`[0, 0]` maps to — is:

```
origin = (px, py + half_h*zoom)          # z = cs.camera.zoom, half_h = tile_h/2
handle = origin + (ax * s * zoom, ay * s * zoom)
```

**`offset_x` / `offset_y` are deliberately EXCLUDED from the origin.** This is
not an oversight and the executor must not "fix" it:

- ESV-1's `screen_offset` (`game/anchors.py:34-50`) is `(ax*s*zoom,
  ay*s*zoom)` with no offset term, and `world_offset` (`:53-70`) applies it
  from `cs.world_to_screen(wx, wy)`.
- In the game the projectile spawned at `world_pos + world_offset(...)` is
  itself drawn through the same `+ half_h*zoom` anchor rule, so the `half_h`
  term **cancels between shooter and projectile**: the game's muzzle point,
  measured against the defender's tile-centred frame anchor, is exactly
  `(ax*s*z, ay*s*z)` from the origin above. Including the entry's
  `offset_x/offset_y` in the editor's origin would put the handle somewhere
  the game never fires from.
- `offset_x/offset_y` are a *nudge from* the same reference the anchor is
  measured against (`data/schemas/asset_manifest.schema.json`, ESV-1 brief
  §1.2), so measuring the anchor from the un-nudged reference is the
  consistent reading.

**Consequence to state in the UI and in the report:** for an entry with
non-zero `offset_x/offset_y`, the drawn art appears shifted relative to the
handle origin. That is correct, and it matches the game. (**Open question for
the orchestrator** — see the closing list: if a designer finds this
counter-intuitive, the fix is to change the *game-side* base in
`game/anchors.py`, which is ESV-1's landed file and out of this phase's scope.
Do not unilaterally compensate in the editor.)

**`s` is the editor's own drawn scale, not the game's.** The preview submits
`RenderItem(... )` with no `fit_tiles`/`scale` (`editor/panels/viewport.py:808-814`),
so their dataclass defaults apply (`fit_tiles=0.0`, `scale=1.0` —
`engine/render/item.py:20-21`) and `fit_factor` returns `1.0`
(`engine/render/renderer.py:37-39`). In the game the same defender may draw at
`s < 1` because of its footprint. **This is fine and is the whole point of
authoring in frame-px:** the unit is scale-invariant, each renderer applies its
own `s`. Compute `s` with `fit_factor(frame_w, cs.geometry.tile_w, fit_tiles)
* scale` from the exact values the preview's `RenderItem` carries — do **not**
hardcode `1.0`, or the handle silently desyncs the day the preview gains a
footprint fit. `frame_w` comes from `AssetStore.frame_size(slot_key)`
(`engine/assets/store.py:52-62`).

### 1.5 Hit-test and drag semantics

- **Hit test** is in SCREEN pixels: `HANDLE_HIT_PX = 10` (Chebyshev or
  Euclidean, pick one and comment it) around the handle's screen point. Test
  handles in reverse submission order so the topmost wins — the same rule
  `_hit_widget` uses in screen mode (`editor/panels/viewport.py:383-397`).
- **Left-press on a handle** starts an anchor drag AND selects that anchor
  (emits selection to the panel). It must **suppress the pan** that the
  entity-preview branch otherwise starts at `editor/panels/viewport.py:1020-1021`
  — the handle check runs FIRST and returns; only a press that hit nothing
  falls through to `self._drag_pos = event.position()`. Right-press still pans
  unconditionally (never grabs a handle), preserving ED-23 feel.
- **Move while dragging** recomputes `(ax, ay)` from the current mouse position
  (§2.3), **rounded to integers** (the schema is integer-typed, ESV-1 brief
  §1.1), clamped to the schema bounds `-4096..4096`. The handle and the panel's
  spinboxes both follow live; **nothing is written to disk during the drag.**
- **Release** commits ONE write (§2.4) — one gesture, one `write_validated`,
  the same coalescing rule as a tilemap paint stroke
  (`editor/panels/CLAUDE.md` §Phase 6, "ONE command per stroke").
- **Release without movement** (a click that produced no change) writes
  nothing; it only selects.
- Dragging a handle off-screen or a slot switching mid-drag cancels the drag
  cleanly (`set_preview_slot` must clear the drag state, as it already clears
  the draft at `editor/panels/viewport.py:201`).
- **No undo stack.** Balancing edits are staged-then-saved and screen edits are
  undoable, but the anchor panel writes immediately like `details.py:save()`
  (`editor/panels/details.py:633-643`) — the existing precedent for a manifest
  write. Undo for the manifest is out of scope; say so in the report.

### 1.6 Authoring an anchor from nothing

Two distinct "nothing" cases; keep them apart.

1. **The slot has a manifest entry but no `anchors` key** (the normal case —
   *no committed entry carries one*, ESV-1 §4.3). The panel shows a row for
   each of the six names with an **absent** state (checkbox unticked, spins
   disabled/blank). Ticking a name creates that anchor at `[0, 0]`, which draws
   a handle at the frame's origin (§1.4) and is immediately draggable. Unticking
   removes the name; removing the **last** name removes the whole `anchors`
   key, so the entry returns byte-identical to its pre-ESV-2 form — the same
   "all-zero ⇒ omit the key" discipline `slice` follows
   (`editor/panels/details.py:583-591`).
2. **The slot has NO manifest entry at all** (the grey-X placeholder, E-37).
   Anchors are **not authorable** — the schema's entry object requires
   `sheet`/`frame_w`/`frame_h`/`offset_x`/`offset_y`/`rows`, so there is
   nothing to attach to and this phase must not synthesise an entry. The panel
   disables every row and shows one line of guidance ("import a spritesheet for
   this slot first"). This is a real state a designer will hit; it must not
   raise, and it must not write.

### 1.7 Two-way sync between the panel and the handle — both directions

There is ONE authoritative value set: the panel's in-memory anchors mapping for
the current slot, seeded from the effective manifest entry. The viewport is a
**view** of it plus a live drag delta. Concretely:

- **Drag → panel.** Viewport emits `anchor_dragged(name, x, y)` on every move
  and `anchor_drag_finished(name, x, y)` on release. The panel updates the two
  spinboxes with signals **blocked** (the established idiom — `editor/main.py:551-552`
  does exactly this for the subcategory combo) so the update cannot re-enter the
  write path, then writes on `anchor_drag_finished`.
- **Panel → handle (external / manual value change).** Any change that did not
  come from a drag — typing in a spinbox (`editingFinished`, not
  `valueChanged`; the `_on_frame_size_changed` comment at
  `editor/panels/details.py:597-616` records why: typing "128" would otherwise
  write three times), ticking/unticking a name, or the whole panel being
  re-seeded after a slot change or a manifest reload — calls
  `viewport.set_anchors(mapping)` and the handle moves on the next frame.
- **Manifest changed elsewhere.** `MainWindow._on_manifest_changed`
  (`editor/main.py:650`) already fans a manifest write out to
  `viewport.reload_assets()` + `selector.refresh_markers()`; it must also
  re-seed the anchors panel, so a Save/Clear from `DetailsPanel` (which
  replaces the whole entry — `editor/panels/details.py:633-643` — and would
  therefore DROP a previously authored `anchors` block if `draft_entry()`
  doesn't carry it) leaves panel and handle agreeing with disk.
  - **This is a real bug you must handle, not a hypothetical.**
    `draft_entry()` (`editor/panels/details.py:566-581`) builds the entry from
    UI state and carries only `slice` as an optional key. After ESV-2, saving
    the import panel would silently erase authored anchors. The **required**
    fix is the minimal one: `draft_entry()` preserves the existing entry's
    `anchors` value verbatim when one exists (the same shape as the `slice`
    branch at `:578-580`), because anchors are not authored by that panel.
    Add a test for it (§4.2 test 6).
- The panel's spins are `_NoWheelSpinBox` **imported from
  `editor.panels.balancing`** — never copied, never re-implemented
  (`editor/CLAUDE.md` §Agent dispatch, and `editor/panels/screen_details.py`
  follows the same rule). Ranges come from the schema bounds (±4096), so an
  out-of-range anchor is unrepresentable (ED-30).

---

## 2. Architecture plan

### 2.1 Three pieces, one of them pure

| piece | file | Qt? | role |
|---|---|---|---|
| pure conversion + write | **NEW** `editor/anchor_ops.py` | no | frame-px ↔ screen-delta math; `write_validated` writes |
| the numeric side panel | **NEW** `editor/panels/anchors_panel.py` | yes | six rows, owns the authoritative mapping |
| handles | `editor/panels/viewport.py` | yes | submit + hit-test + drag; a view of the mapping |

`editor/anchor_ops.py` is modelled on `editor/registry_ops.py` (pure, stdlib +
`engine.data_io`, in `TestPurity`) — see `set_slot_frame_size`
(`editor/registry_ops.py:81-118`) for the read-mutate-`write_validated` shape.
Both new modules join `TestPurity` (§3.3).

### 2.2 Where handle state lives

In `ViewportPanel.__init__`, beside the existing entity-preview state at
`editor/panels/viewport.py:107-110`:

```
self._anchors = {}            # {name: (x, y)} — a VIEW, pushed by the panel
self._anchor_selected = None  # name | None
self._anchor_drag = None      # (name, grab_dx, grab_dy) while dragging
```

`set_anchors(mapping)` / `set_selected_anchor(name)` are the setters, mirroring
`set_selected_widget` (`:316`). `set_preview_slot` (`:197-205`) clears all
three, exactly as it clears `self._draft` at `:201`. The viewport **never reads
the manifest for anchors and never writes them** — it is handed the mapping and
emits deltas. That keeps the drag testable without a disk round-trip and keeps
`AssetStore.anchor()` a single-consumer path.

### 2.3 The mouse ↔ frame-px path (iso math stays in `engine/coords/`)

Two conversions, both of which must go through the coordinate authority — the
closed-form iso expression may not be restated anywhere
(`engine/CLAUDE.md` subsystem table; `engine/coords/` is the sole home).

**(a) frame-px → screen (drawing).** From §1.4:
`handle_screen = cs.world_to_screen(wx, wy) + (0, tile_h/2*zoom) + (ax*s*zoom,
ay*s*zoom)`, where `(wx, wy)` is the preview's world position
(`g.map_cols // 2, g.map_rows // 2`, `editor/panels/viewport.py:810`).
`world_to_screen` is the only coordinate call involved.

**(b) screen → frame-px (dragging).** The mouse arrives in widget pixels, which
is already the same space `world_to_screen` produces, so the inverse is a plain
subtraction and divide — **no iso math at all**:

```
ax = round((mouse_x - origin_x) / (s * zoom))
ay = round((mouse_y - origin_y) / (s * zoom))
```

Put both in `editor/anchor_ops.py` as pure functions
(`screen_point(origin, ax, ay, s, zoom)` / `frame_px(origin, sx, sy, s, zoom)`)
so they are unit-testable without Qt and cannot drift apart.

**(c) fixed-screen-size handles through a WORLD-point overlay primitive — the
one place the two-sample trick is needed.** `submit_overlay_lines` takes
**world** points (`engine/render/renderer.py:80-85`) and converts at flush
(`:146-147`). A handle must be a constant number of *screen* pixels regardless
of zoom, so convert each corner back:

```
wx0, wy0 = cs.screen_to_world(sx, sy)                 # handle centre
wx1, wy1 = cs.screen_to_world(sx + HANDLE_RADIUS_PX, sy + HANDLE_RADIUS_PX)
dwx, dwy = wx1 - wx0, wy1 - wy0                       # zoom & pan cancel
```

then build the outline from `(wx0 ± dwx, wy0 ± dwy)`. **This is ESV-1's proven
pattern** (`game/anchors.py:67-70`, and its docstring at `:53-60`): the
difference of two `screen_to_world` samples cancels zoom and pan because
`screen_to_world` divides by `z` and subtracts the same pan for both samples.
Do not hand-derive the per-tile deltas.

### 2.4 The write path

`editor/anchor_ops.py`:

```
set_anchor(data_dir, slot_key, name, xy)    # xy = (int, int)
clear_anchor(data_dir, slot_key, name)      # drops the name; drops `anchors`
                                            # entirely when it was the last one
```

Both: load the manifest doc, mutate `doc["entries"][slot_key]["anchors"]`, write
back. **Reuse the existing helpers** `asset_import.load_manifest_doc(data_dir)`
/ `asset_import.write_manifest_doc(data_dir, doc)` — the pair
`editor/panels/details.py:708-712` already uses; `write_manifest_doc` is the
`write_validated` call against `data/schemas/asset_manifest.schema.json`. **Do
not open a second write path** and do not call `json.dump` anywhere
(`editor/CLAUDE.md` hard rules; ED-31).

Missing slot / missing entry ⇒ **no write, return a falsey result**; the caller
(§1.6 case 2) has already disabled the UI, and a defensive no-op here is what
keeps a stale panel from inventing an invalid entry. Never raise into a Qt
event handler (`editor/panels/CLAUDE.md` §Phase 5, "a right-click must never be
able to kill the editor").

### 2.5 The `game/anchors.py` layering decision — **RATIFIED: the editor
re-derives; nothing moves**

`game/anchors.py` is under `game/`, and `editor/` may never import `game/`
(root `CLAUDE.md` design pillar 2; pinned by
`tools/tests/test_editor_viewport.py:728-753`). Decision, with reasoning the
executor must not relitigate:

- **Do not move `game/anchors.py`.** It landed in ESV-1 with tests and two
  game-side consumers; moving it in a concurrent editor phase is a
  cross-package edit outside this phase's file scope.
- **The editor does not actually need it.** `screen_offset` is
  `(ax*s*zoom, ay*s*zoom)` after resolving `s` — and the *only* non-trivial
  ingredient, `fit_factor`, is exported from `engine/render/renderer.py:28-39`
  and is importable by the editor. `game/anchors.py`'s remaining content is a
  `SpriteAnimator`-shaped adapter the editor has no use for (the preview
  submits a bare `RenderItem`, not a `GameObject`), plus `world_offset`, which
  the editor never needs (it works in screen space end to end).
- So `editor/anchor_ops.py` imports `fit_factor` from
  `engine.render.renderer` — **the same rule `game/anchors.py:25` itself
  follows**, and the same rule `game/ui/effects.py:128` follows. There is
  exactly one copy of the fit formula in the repo either way; what is
  duplicated is a multiply, which is not a rule worth a shared module.
- **Boundary question, flagged not assumed:** if a future phase (ESV-6) wants
  one shared resolver, the right move is to relocate `game/anchors.py` to a
  pure engine-adjacent home both packages may import. That is an
  **orchestrator decision** and it touches ESV-1's landed file — it is NOT in
  scope here. Do not do it opportunistically.

### 2.6 Constructor signatures — the Stage-1 integration trap

This phase should need **no** change to any existing constructor signature or
public attribute path (`ViewportPanel`, `DetailsPanel`, `MainWindow` all keep
theirs; new methods and signals only). **If you find you must change one
anyway:** grep **all** of `tools/tests/` for construction sites of that class
before you finish — a concurrent phase may have added a test module that
constructs it, which is exactly how a Stage-1 phase broke despite updating
every call site it could see — and **report the change loudly, in its own
paragraph, in your final report** so the orchestrator can propagate it to
ESV-4.

---

## 3. File scope + shared-file contract

### 3.1 Permitted files

| file | edit | insertion point |
|---|---|---|
| **NEW** `editor/anchor_ops.py` | pure math + `set_anchor`/`clear_anchor` | new file |
| **NEW** `editor/panels/anchors_panel.py` | `AnchorsPanel(QWidget)`, `(data_dir=None, parent=None)` | new file |
| `editor/panels/viewport.py` | handle state (`:107-110`), constants (module top, beside `START_AREA_COLOR`), `set_anchors`/`set_selected_anchor` + the two signals (beside `:88-91`), a `_submit_anchor_handles()` called from the entity-preview branch (after `:814`), the press/move/release branches (`:1020-1021`, `:1043`, `:1060-1061`) | see §3.2 |
| `editor/panels/details.py` | **ONE** change: `draft_entry()` (`:566-581`) preserves an existing `anchors` value | §1.7 |
| `editor/main.py` | wire the panel — **two named insertion points**, §3.2 | `:122` and `:281` |
| `tools/tests/test_editor_viewport.py` | `TestPurity` tuple only | §3.3 |
| `conftest.py` | one `TIERS` line | §3.3 |
| `editor/panels/CLAUDE.md` | a short "Anchor handles (ESV-2)" section | end of the Phase-5 entity-preview section |

### 3.2 `editor/main.py` — the exact anchors (**ESV-4 runs concurrently here**)

ESV-4 also wires a panel into `editor/main.py`. Take these two named points and
**reformat nothing around them**:

1. **Signal wiring — insert a contiguous block immediately AFTER
   `editor/main.py:122`** (`self.details.registry_changed.connect(lambda _slot:
   self._reload_registries())`), before the palette wiring at `:134`. Every
   ESV-2 connection goes in that one block; do not scatter connects through the
   existing ones. ESV-4 should insert **after `:156`** (the end of the
   screen-mode wiring block) so the two additions are never adjacent.
2. **Panel placement — `editor/main.py:281`**
   (`self.right_stack.addWidget(self.details)  # index 0: asset import`).
   Replace that single line with a small container widget (a `QWidget` +
   `QVBoxLayout` holding `self.details` then `self.anchors`) added as
   **index 0**, so indices 1/2 keep their meaning and every existing
   `setCurrentWidget(self.details)` call site
   (`editor/main.py:353`, `:392`) is retargeted to the container — those are the
   **only** two such call sites; grep `setCurrentWidget` to confirm before
   editing. **Do not touch `:282-284`.** ESV-4 must APPEND its page at the end
   (index 3+), which keeps its diff on a different line entirely.
3. Three one-line additions, each on its own line:
   `self.anchors.set_slot(slot)` after `editor/main.py:648`
   (`self.details.set_slot(slot)`); a re-seed call inside
   `_on_manifest_changed` (`:650`); and a `set_slot(None)` on entering map or
   screen mode (`_enter_map_mode` `:340`, `_enter_screen_mode` `:385`) so a
   stale slot's rows are not left live behind another mode.

### 3.3 The two shared tuples — **keep the merge mechanical**

Both ESV-2 and ESV-4 append to these. Rule for both phases: **one new entry per
new line, alphabetically placed, existing lines untouched and unreflowed.** A
git conflict then resolves by keeping both lines.

- `tools/tests/test_editor_viewport.py` `TestPurity` (the import string,
  `:732-746`): add `"editor.anchor_ops, "` and
  `"editor.panels.anchors_panel, "` as **two new lines** in that string —
  do not append them onto the end of an existing line (e.g. `:739` or `:746`),
  which is what turns a trivial merge into a hand-edit.
- `conftest.py` `TIERS` (`:36`, editor block `:50-59`): add
  `"test_editor_anchors": "editor",` as a new line between
  `"test_details_panel"` (`:51`) and `"test_editor_asset_import"` (`:52`).
  `test_tiers.py` fails the run if you forget; an unmarked module silently
  never runs, and an unexpected skip is a failure.

### 3.4 Out of scope — do not touch

- Anything under `game/` (including `game/anchors.py` — §2.5) and anything
  under `engine/` (read and call it; `fit_factor`, `AssetStore.anchor`,
  `ANCHOR_NAMES`, the coords authority, `submit_overlay_lines`, `submit_hud`).
- `engine/vfx/`, `data/balancing/vfx.json` — ESV-3b's territory (engine+game
  only; it does not touch `editor/`).
- `planning/EntitySceneVfxPLAN.md` and root `PLAN.md` — the orchestrator
  updates those. Root `PLAN.md` is a generated mirror; never hand-edit it.
- Any `data/` **content** file. This phase ships the authoring UI; the designer
  authors the values. Do not commit an anchor into
  `data/sprites/asset_manifest.json`.
- `editor/panels/viewport.py`'s map-mode and screen-mode code paths, and
  `_step_zoom` (`:1081-1094`).
- Everything in `editor/panels/details.py` except `draft_entry()`.

---

## 4. Exit gate + Quick Test

### 4.1 Commands

```bash
py tools/smoke.py                       # data validation + 5-frame headless boot
py tools/testgate.py check --affected   # blast radius (Graphify) + the core tier
```

**`--affected`, NOT the full suite** — ESV-4 is editing `editor/main.py` and the
same test tuples concurrently, and a full run would be measuring their diff as
much as yours. Report the ONE line each command prints; the gate is **ZERO**.
Do not paste raw gate output. Do not run the full suite as a mid-task sanity
check; run it once at hand-back only if the orchestrator asks.

### 4.2 Tests to add

New module `tools/tests/test_editor_anchors.py` (tier `editor`, §3.3).
Offscreen Qt via `QtCase`/`self.track(...)` — `close()` is **not** cleanup
(`editor/CLAUDE.md` §Testing, and `test_qt_harness.py` fails if the bare-close
pattern returns). Temp data dir via `TempDataCase`
(`tools/tests/test_editor_panels.py:52`); **never write into `data/`, never
assert against live `data/` content** — pin the fixture entry yourself.

1. **Pure round-trip.** `anchor_ops.frame_px(origin, *anchor_ops.screen_point(
   origin, ax, ay, s, zoom), s, zoom) == (ax, ay)` across a table of `s`/`zoom`
   values including `zoom != 1`. Pure, no Qt.
2. **A synthetic drag writes the expected frame-px and the JSON validates.**
   Drive `ViewportPanel` press/move/release with synthetic positions (the
   established idiom — `editor/panels/CLAUDE.md` §Verify, "live runs are driven
   by synthetic `QTest` events"), computing the target screen point from §1.4's
   formula, then assert the on-disk `anchors` value **and** that re-loading the
   file through the validating reader succeeds. Assert the write happened
   **once**, on release, not per move.
3. **Zoom invariance of the drag.** The same target screen point at two
   different `cs.camera.zoom` values yields the same authored frame-px (the D2
   promise; this is the assertion a hand-derived formula fails).
4. **Panel ↔ handle agree in BOTH directions.** (a) After a synthetic drag, the
   panel's spinbox values equal the handle's authored value. (b) After an
   *external* value change — set the spinbox programmatically and fire
   `editingFinished` — the viewport's handle screen point moves to the matching
   place. Both directions in one test class, explicitly.
5. **A slot with no anchors can gain one, and lose it cleanly.** Fixture entry
   with no `anchors` key → tick `muzzle` → `[0, 0]` on disk, schema-valid →
   drag → new value → untick → the `anchors` key is **absent** again and the
   entry is byte-identical to the fixture. Cover a second name so "remove one
   of two" keeps the block.
6. **A `DetailsPanel` save does not erase anchors** (§1.7). Author an anchor,
   then call `details.save()`, then assert the anchor survives on disk. This is
   the regression pin for the one `draft_entry()` change; it should fail red
   without it.
7. **No entry ⇒ no write, no raise** (§1.6 case 2). Select a slot with no
   manifest entry: the panel's rows are disabled, `anchor_ops.set_anchor`
   returns falsey, and the manifest file is unchanged on disk.
8. **`TestPurity` covers every new module** — `editor.anchor_ops` and
   `editor.panels.anchors_panel` are in the import tuple (§3.3). Not a new
   test; verify the existing one now imports both.
9. **No QPainter regression.** Assert that the handle geometry reached the
   renderer: drive one `render_frame()` with a preview slot + an anchor and
   assert `submit_overlay_lines` was called (inject/spy a `Renderer`, or count
   overlay entries before flush). This is the cheap mechanical pin for ED-22 —
   the rule most likely to be broken here.

### 4.3 Quick Test (in-game, and it spans both apps)

```bash
py editor/main.py
```

1. Select a **defender** (a building leaf with imported art) — the entity
   preview shows it, and the anchors panel appears in the right pane.
2. Tick **muzzle**. A handle appears at the sprite's frame origin. Drag it onto
   the barrel/instrument tip. The X/Y spinboxes track the drag.
3. Type a new Y in the spinbox and press Enter — **the handle jumps to match**
   (the second sync direction).
4. Confirm on disk: `data/sprites/asset_manifest.json`'s entry for that slot now
   carries an `anchors` block with your `muzzle` pair, sorted-key formatted, and
   the file still validates (`py tools/smoke.py`).
5. **Play** from the editor toolbar, place that defender, and let it shoot:
   **the projectile emits from the point you dragged the handle to**, not from
   the tile centre. That last step is the real pass condition — it is the only
   thing that proves the editor's frame-px and ESV-1's game-side resolver agree
   on the convention.
6. Untick the anchor, re-save, and confirm the `anchors` key is gone and the
   entry is back to its original bytes.

State in the report exactly what you exercised — a live editor run plus a live
Play round, or a static read. They are not interchangeable, and step 5 cannot
be verified statically.

---

## Open questions for the orchestrator (do not decide these yourself)

1. **Handle origin vs `offset_x`/`offset_y`** (§1.4). The brief excludes the
   entry's offsets from the handle origin so the editor matches ESV-1's
   game-side base. For an entry with non-zero offsets the art will look shifted
   relative to the handle origin. If a designer calls that wrong, the fix is on
   the **game** side (`game/anchors.py`, ESV-1's landed file), not here.
2. **`game/anchors.py` relocation** (§2.5). Ratified as *not now*. If ESV-6
   wants one shared resolver, the move is a separate, cross-package decision.
3. **No undo for anchor edits** (§1.5). Consistent with `details.py`'s
   immediate manifest write, inconsistent with screen mode's `QUndoStack`.
   Accepted for this phase; flag if the orchestrator wants parity.
