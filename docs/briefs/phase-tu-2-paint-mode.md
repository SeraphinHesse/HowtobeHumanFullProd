> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase TU-2 — Editor: tutorial map paint mode

Source plan: `planning/TutorialPLAN.md` §3 "Phase TU-2" (`planning/TutorialPLAN.md:155-172`),
decision **D1** (`planning/TutorialPLAN.md:53-60`). Depends on **TU-1** landing
first (`engine/tilemap.py` gains `tutorial_flute`/`tutorial_stone` nullable
single-tile markers, the exact `camera_start` shape). **Use the
`/add-editor-feature` skill** (`planning/TutorialPLAN.md:158`) — this brief is
its brief-shaped input, not a replacement for it.

## 0. Assumption this phase is built on (verify before coding)

TU-1 had not landed at brief-writing time. This brief assumes TU-1 lands with
**exactly** the `camera_start` shape, mirrored:

- `TileMapDoc.tutorial_flute` / `TileMapDoc.tutorial_stone`: nullable
  `{"col": int, "row": int, "slot": str}` dicts (engine/tilemap.py:48, the
  `camera_start` field, is the literal pattern — single tile, no 2×2 clamp
  unlike `start_area`).
- `tilemap.tutorial_flute_slot_from_schema(schema)` /
  `tilemap.tutorial_stone_slot_from_schema(schema)`, mirroring
  `camera_start_slot_from_schema` (engine/tilemap.py:299-301) and
  `start_area_slot_from_schema` (engine/tilemap.py:304-306) — both call the
  shared `_object_slot_from_schema(schema, key)` (engine/tilemap.py:283-291).
- `validate_doc` bounds-checks both markers the same way as `camera_start`
  (engine/tilemap.py:109-114): `0 <= col < cols and 0 <= row < rows`, **not**
  the `start_area` 2-cell-short bound (engine/tilemap.py:115-121).

**Open gap, flag to the orchestrator**: `start_area` and `camera_start` each
have a registry slot group under `core` in `data/slots.json` (referenced by
`editor/panels/palette.py:230-244`, `_base_slots`/`_camera_slots`/
`_start_area_slots`, e.g. `registry.group_slots("core", ("Start Area",))`).
TU-1's file list (`planning/TutorialPLAN.md:134-146`) does **not** mention
`data/slots.json`. Without a `core → "Tutorial Flute"` / `core → "Tutorial
Stone"` registry group (each one slot key, `tutorial_flute` / `tutorial_stone`,
const-pinned to match the map schema's `slot` const — same shape as `Start
Area`), this phase's palette buttons have no slot to arm. **Either TU-1 must
add these two registry groups, or TU-2 adds them itself** (a small,
data-package, `write_validated`-only addition, same shape as any existing
`core` group) — decide before implementation starts; do not silently invent a
third option (e.g. a hardcoded slot string with no registry entry breaks the
"+ Variant"-style extensibility every other single-object marker gets for
free, and `refresh_icons()` (editor/panels/palette.py:457-464) expects a real
slot key to resolve an icon or a placeholder).

## 1. Behavioral spec

**Goal (verbatim from plan, `planning/TutorialPLAN.md:157-158`)**: the designer
paints "first flute" and "first stone" onto a map as a **fourth paint mode**
(alongside the existing three: `gametiles`/`background`/`decoration`,
`editor/panels/palette.py:51-56`); markers save through `save_map`
(engine/tilemap.py:273-278, unchanged — `to_dict`/`from_dict` already round-trip
any doc field TU-1 adds).

**Two sub-brushes, one exclusive brush group**: "First Flute" and "First
Stone" are two buttons on a new "Tutorial" mode page, in the SAME exclusive
`QButtonGroup` that already spans all three existing pages
(`editor/panels/palette.py:16-17` docstring; `_brush_group.addButton(btn)` at
`editor/panels/palette.py:334`) — arming one disarms the other and every other
brush, exactly like arming Camera Start disarms Start Area
(`editor/panels/viewport.py:562-578`).

**Paint / erase semantics — identical to the `camera_start` single-object
brush** (`editor/panels/viewport.py:615-620`, `editor/map_session.py:267-290`):
paint places the marker if absent, or **moves** it (repainting anywhere sets
a new position — one undoable command either way, `old == new` short-circuits
a no-op push); erase clears it from any cell (the marker is a single object,
erase doesn't need to hit its exact cell — mirrors `push_camera_remove`,
`editor/map_session.py:280-284`, and `push_start_area_remove`,
`editor/map_session.py:312-315`). A press on the marker's own painted cell
(when no brush is armed, eye on) grabs it into a drag; release re-places it —
mirrors the base/camera/start_area drag-grab block
(`editor/panels/viewport.py:630-642`) and the corresponding release handling
(`editor/panels/viewport.py:684-699`).

**Rendering — never a sprite, always an outline + label**
(`planning/TutorialPLAN.md:160-163`): drawn as a **labeled white diamond
outline** through `Renderer.submit_overlay_lines` (engine/render/renderer.py:79-85,
E-24; **world-space** points, no manual `world_to_screen` needed for the
outline itself) — the exact idiom `_submit_start_area_outline`
(`editor/panels/viewport.py:870-891`) already uses for the 2×2 marker, except
the polygon is the single-tile square `((col,row),(col+1,row),(col+1,row+1),
(col,row+1))` instead of the 2×2 square — iso projection turns that unit
square into the "diamond" the goal names (this is the standard
`world_to_screen` diamond projection every ground tile already renders as;
no new math needed). The **label** ("First Flute" / "First Stone") is a
`HudText` (engine/render/hud.py:25, screen-space) positioned via
`self._coords.world_to_screen(col + 0.5, row + 0.5)` and nudged up a few
pixels — the exact idiom the screen-mode selection caption already uses
(`editor/panels/viewport.py:987-991`, `_submit_screen_selection`) and the
zoom-step math already calls the same `world_to_screen` (`editor/panels/
viewport.py:1126`). Per-marker eye toggle(s) gate both outline and ghost
(mirrors `self._eyes["start_area"]`, `editor/panels/palette.py:50` `EYES`
tuple + `editor/panels/viewport.py:122-123`).

**The other three paint modes are unaffected** — gametiles/background/
decoration brush construction, `_tool_press`/`_tool_release` code-paint/deco/
erase branches, and their tests stay byte-identical; this phase only adds new
branches alongside the existing base/camera/start_area ones.

## 2. Architecture plan

Mirror the `start_area` single-object-marker pattern (`editor/panels/
map_details.py`'s doc block "Starting Area (2×2 marker)" in `editor/panels/
CLAUDE.md`) **twice**, once per marker kind, but as **two brushes on one new
mode page** rather than two brushes on the existing `gametiles` page.

### `editor/map_session.py`
- `_tutorial_flute_slot()` / `_tutorial_stone_slot()` — mirror `_camera_slot()`
  (editor/map_session.py:263-265): `tilemap.tutorial_flute_slot_from_schema(...)`
  / `tutorial_stone_slot_from_schema(...)` off the loaded map schema.
- `push_tutorial_flute_place(col, row)` / `push_tutorial_flute_remove()` /
  `push_tutorial_flute_move(old, new)` and the `_stone` trio — mirror
  `push_camera_place`/`push_camera_remove`/`push_camera_move`
  (editor/map_session.py:267-290) **exactly** (single-tile, no clamp — unlike
  `push_start_area_place`'s `[0, cols-2]` clamp, editor/map_session.py:301-302).
- Two new `QUndoCommand` subclasses, `_TutorialFluteSetCommand` /
  `_TutorialStoneSetCommand`, mirroring `_CameraSetCommand` (whichever class
  backs `push_camera_place`, same file, same shape as `_StartAreaSetCommand`
  at editor/map_session.py:86-89 — `redo` sets `doc.tutorial_flute = new`,
  `undo` restores `old`).

### `editor/panels/palette.py`
- `MODES = ("gametiles", "background", "decoration", "tutorial")` — appending
  to the tuple (`editor/panels/palette.py:51`) is sufficient to get a mode
  toolbar button + an empty page container for free: both the mode-button
  loop (`editor/panels/palette.py:114-122`) and the generic page-skeleton loop
  (`editor/panels/palette.py:148-156`) iterate `MODES` directly.
- `MODE_LABELS["tutorial"] = "Tutorial"` (editor/panels/palette.py:52-56).
- Two new signals: `tutorial_flute_armed = Signal(str)` /
  `tutorial_stone_armed = Signal(str)` (mirror `start_area_armed`, `editor/
  panels/palette.py:71`).
- `arm_tutorial_flute(slot)` / `arm_tutorial_stone(slot)` — mirror
  `arm_start_area` (editor/panels/palette.py:571-578): each clears every OTHER
  armed brush var **including the sibling tutorial brush**, sets its own,
  emits its signal. **Every existing `arm_*` method must also clear the two
  new vars** (`editor/panels/palette.py` has no palette-side armed state today
  — armed state lives in `viewport.py`, see below; palette's `arm_*` methods
  only emit signals, so this note is really about `viewport.py`'s mirrored
  methods).
- `_tutorial_flute_slots()` / `_tutorial_stone_slots()` — mirror
  `_start_area_slots()` (editor/panels/palette.py:240-244):
  `self._registry.group_slots("core", ("Tutorial Flute",))` /
  `(("Tutorial Stone",))`, degrading to `[]` on `KeyError`/`ValueError` (see
  §0's registry-group gap).
- `_add_brush_button`: two new `elif kind == "tutorial_flute":` /
  `elif kind == "tutorial_stone":` branches (editor/panels/palette.py:314-337,
  right after the existing `elif kind == "start_area":` at line 327-328),
  each connecting to `self.arm_tutorial_flute(v)` / `self.arm_tutorial_stone(v)`.
- A new `_rebuild_tutorial()` (mirrors `_rebuild_gametiles`, editor/panels/
  palette.py:360-373, but simpler — two STATIC buttons, not legend-derived):
  clears any existing `("tutorial_flute", *)`/`("tutorial_stone", *)` buttons
  from `self._pages["tutorial"]`'s layout, then adds one button per slot from
  `_tutorial_flute_slots()` (label "First Flute") and `_tutorial_stone_slots()`
  (label "First Stone") via `_add_brush_button`. Call it once from `set_legend`
  alongside `_rebuild_gametiles()`/`_rebuild_background()`
  (editor/panels/palette.py:438-443) — it doesn't depend on the legend, but
  that's the existing "rebuild everything the palette owns" hook and keeps
  the update path singular.
- `_arm_first_of_mode()`: new `elif self._mode == "tutorial":` branch
  (editor/panels/palette.py:484 onward) arming the first Flute slot if one
  exists.
- `EYES = (..., "tutorial")` (editor/panels/palette.py:50) — **one** eye
  gating both markers (simplest; a designer toggling "hide tutorial markers"
  wants both gone together — flag as an implementer's call if per-marker eyes
  are preferred instead, but one eye is the smaller diff and matches "this is
  one feature" more than `start_area`/`camera` being independently toggled
  because they are independent features).

### `editor/panels/viewport.py`
- New armed-state vars in `__init__` (editor/panels/viewport.py:120-123):
  `self._armed_tutorial_flute = None`, `self._armed_tutorial_stone = None`;
  `self._eyes[...]` gains `"tutorial": True`; new drag flags
  `self._tutorial_flute_drag = False` / `self._tutorial_stone_drag = False`
  (reset in `set_map_mode`, editor/panels/viewport.py:247-257, alongside
  `_base_drag`/`_start_area_drag`).
- `arm_tutorial_flute(slot)` / `arm_tutorial_stone(slot)` (viewport-side, the
  actual armed-state setters `PalettePanel`'s signals connect to — mirror
  `arm_start_area`, editor/panels/viewport.py:571-578): each clears
  `_armed_code`/`_armed_deco`/`_armed_base`/`_armed_camera`/
  `_armed_start_area`/the sibling tutorial var. **Every existing
  `arm_code`/`arm_deco`/`arm_base`/`arm_camera`/`arm_start_area` method
  (editor/panels/viewport.py:538-578) must gain two more clears** (the two new
  vars) — this is the one place the new brush must be "wired into" the
  existing exclusivity net; miss one and two brushes can be armed at once.
- `_tool_press` (editor/panels/viewport.py:602-671): insert an
  `_armed_tutorial_flute`/`_armed_tutorial_stone` early-return block right
  after the `_armed_start_area` block (after line 629, before the base-drag
  check at line 630) — paint → `push_tutorial_flute_place`/`_stone_place`,
  erase → the matching `_remove()`. Insert the drag-grab check (cell ==
  marker's own cell, eye on, no brush armed) right after the `start_area`
  drag-grab check (after line 642, before the `_armed_deco` check at 643) —
  sets `_tutorial_flute_drag`/`_tutorial_stone_drag = True`.
- `_tool_move`: unaffected (drag position tracking is drag-flag-agnostic,
  editor/panels/viewport.py:673-682).
- `_tool_release` (editor/panels/viewport.py:684-710): new
  `elif self._tutorial_flute_drag:` / `elif self._tutorial_stone_drag:`
  branches right after `elif self._start_area_drag:` (after line 699, before
  `elif self._stroke is not None:` at line 700) — release cell →
  `push_tutorial_flute_place`/`_stone_place`.
- `_ghost_items` (editor/panels/viewport.py:712-739): insert an early
  `if (self._tutorial_flute_drag or self._tutorial_stone_drag
  or self._armed_tutorial_flute is not None
  or self._armed_tutorial_stone is not None): return` right after the
  existing `start_area` one (after line 727) — the ghost is the outline, not
  a `RenderItem`.
- `_submit_map_items` (editor/panels/viewport.py:839-868): add
  `self._submit_tutorial_outline(doc)` right after
  `self._submit_start_area_outline(doc)` (after line 857).
- New `_submit_tutorial_outline(doc)` (mirrors `_submit_start_area_outline`,
  editor/panels/viewport.py:870-891, called once per marker kind): for each
  of `(doc.tutorial_flute, "First Flute", self._tutorial_flute_drag,
  self._armed_tutorial_flute)` / `(doc.tutorial_stone, "First Stone",
  self._tutorial_stone_drag, self._armed_tutorial_stone)`:
  - if the `tutorial` eye is on, the marker is set, and not mid-drag: submit
    the single-tile outline (`((col,row),(col+1,row),(col+1,row+1),
    (col,row+1))`, `TUTORIAL_COLOR`, `width=2`, `closed=True`) **and** a
    `HudText(label, (sx, sy - 14), "sm", TUTORIAL_COLOR, align="center")`
    where `sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)`
    (mirrors `editor/panels/viewport.py:987-991`'s caption-above-outline
    idiom).
  - ghosting (drag in progress, or armed with the paint tool) draws the same
    two primitives at the (bounds-clamped) hover cell in
    `TUTORIAL_GHOST_COLOR` — mirrors `editor/panels/viewport.py:885-891`.
  - Two new module-level colors, e.g. `TUTORIAL_COLOR = (255, 255, 255)`
    (white, per the goal text) and `TUTORIAL_GHOST_COLOR = (200, 200, 200)`
    (dimmer white) — alongside `START_AREA_COLOR`/`START_AREA_GHOST_COLOR`
    (editor/panels/viewport.py:62-63).

## 3. File scope + shared-file contract

**Modified, TU-2-exclusive** (no other in-flight phase touches these):
- `editor/map_session.py` — new push_*/slot helpers + 2 new `QUndoCommand`
  classes (§2).
- `editor/panels/palette.py` — new mode, signals, arm_* methods, brush-button
  branch, `_rebuild_tutorial`, eye entry (§2).
- `editor/panels/viewport.py` — new armed state, arm_* methods, `_tool_press`/
  `_tool_release`/`_ghost_items` branches, `_submit_tutorial_outline` (§2).
- `data/slots.json` — **only if** TU-1 does not already add the two `core`
  registry groups (§0's flagged gap); if TU-1 lands with them, this phase
  touches nothing here.
- New test module: `tools/tests/test_editor_tutorial_paint.py` (its own file
  — do not append to `tools/tests/test_editor_map_mode.py`, which is already
  large; register it in `conftest.py`'s `TIERS` table as `"editor"`,
  mirroring `"test_editor_map_mode": "editor"`, `conftest.py:53`).

**Shared file — exact insertion point (coordinate with TU-3, TU-4)**:
`editor/panels/CLAUDE.md` is also touched by TU-3 (new Cutscenes panel doc
section) and TU-4 (new Tutorial-section panel doc section). This phase's
insertion point: **append one new bullet at the end of the existing "Phase
6 — tilemap mode" section** (the section currently ends with the "Starting
Area (2×2 marker)" bullet and the "'None' tool" bullet, right before "Phase B4
— screen mode" begins) — i.e. add a new bullet titled **"Tutorial markers (2
single-tile brushes)"** directly after the existing "Starting Area (2×2
marker)" bullet, describing: the 4th mode page, the two exclusive sub-brushes,
paint/move/erase semantics, and the labeled-white-diamond-outline render rule
— same prose shape as the Starting Area bullet it sits next to. **Do not**
touch any other section of the file (TU-3/TU-4 append their OWN new top-level
`## Phase TU-n` sections near the bottom, structurally independent of this
bullet — no line-range overlap expected, but confirm against their landed
briefs before merging if timing overlaps).

**Tests** (`tools/tests/test_editor_tutorial_paint.py`, offscreen Qt, temp
data dir — subclass `MapModeCase`/mirror its harness from
`tools/tests/test_editor_map_mode.py:45-91`):
1. Entering the mode + one click sets `doc.tutorial_flute` (`{"col", "row",
   "slot"}`) — mirrors `TestStartArea.test_click_places_min_corner_and_is_
   undoable` (tools/tests/test_editor_map_mode.py:259-270), undo/redo included.
2. A second click elsewhere **moves** it (same marker, new col/row) rather
   than erroring or adding a second marker.
3. Erase (any cell) clears it — mirrors `test_erase_removes`
   (tools/tests/test_editor_map_mode.py:272-280).
4. Save → `tilemap.load_map` reload round-trips both markers — mirrors
   `test_save_round_trips_to_disk` (tools/tests/test_editor_map_mode.py:307-316).
5. The First Stone brush behaves identically and independently of First
   Flute (arming one disarms the other; both can be placed on the same map
   simultaneously without interfering).
6. **The other three paint modes are unaffected**: a `gametiles`/
   `background`/`decoration` paint/erase/save test (can reuse/adapt an
   existing `TestPaintTools` case) still passes unmodified after this
   change — regression guard that the new branches are additive, not a
   dispatch reordering that swallows an existing case.
7. Render-path test (mirrors `TestRenderPath.test_start_area_outline_through_
   overlay_primitive`, tools/tests/test_editor_map_mode.py:374-389): a placed
   marker emits exactly one `OverlayLines` (closed, 4 points) whose first
   point matches `coords.world_to_screen(col, row)`, gated by the `tutorial`
   eye; also assert a `HudText` (or whatever HUD dataclass carries the label)
   is present in the same frame with the right label string.

## 4. Exit gate

```
py tools/smoke.py
py tools/testgate.py check
```
Both must print `GATE PASS` with zero failures/skips (root `CLAUDE.md`'s
"the gate is ZERO" rule) — no baseline, no tolerated pre-existing failures.

**Live Quick Test**: `py editor/main.py` → open any map → select the new
"Tutorial" mode in the palette → arm "First Flute" → click a buildable tile
near the hole → a labeled white diamond outline appears on that tile → arm
"First Stone" → click a different tile → its own labeled outline appears →
Save → close and reopen the map (or restart the editor and reselect it) →
both markers are still there, still rendered as outlines, no sprite ever
drawn for either.
