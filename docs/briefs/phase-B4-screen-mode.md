> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase B4 — Editor: screen mode (selector/session/viewport/details)

Slice 10L-B (`planning/UI_EDITOR_PLAN.md` lines 318–348). Branch: `phase-10L-finish-umbrella` (the umbrella run executes all of 10L-B as one orchestrated unit). Packages: **editor only** (`editor/panels/`, `editor/*.py` top-level). Extends existing code paths heavily; runs after B1/B2/B3 land.

**Assumed landed and immutable:**
- **B1** — 12 screen JSON files under `data/ui/screens/`, schemas for override format + defaults (planning/UI_EDITOR_PLAN.md lines 278–299).
- **B2** — `game/ui/skinning.py` (override application), test parity pin green (lines 294–307).
- **B3** — `tools/export_ui_layouts.py`, committed `data/ui/screen_defaults.json` + `tools/tests/test_ui_layout_export.py` (lines 309–316).

---

## 1. Behavioral spec

### 1a. Selector gains a Screens branch (planning/UI_EDITOR_PLAN.md lines 319–321)

`editor/panels/selector.py` (`SelectorPanel`):
- **Modifier to tree construction** (`__init__` + existing `refresh_marks` flow): the `ui` category (which exists from A3) gains a **SECOND** top-level child called `Screens`, placed **above the existing slot groups** (Buttons, Panels, Icons, Backgrounds — the group structure of `data/slots.json`).
- **Screens branch contents**: one leaf per `.json` file in `data/ui/screens/`, labeled by the filename stem (e.g. `main_menu`, `pause`, `settings`, … 12 total per B1). Mirroring map leaves: each is stored with a **`_SCREEN_ROLE` data key** (parallel to `_MAP_ROLE` at lines 284–288 of selector.py) holding the screen id.
- **New signal `screen_selected(str)`** — emitted when a screen leaf is selected (the screen id is the parameter). Like `map_selected`, the screen leaf selection **MUST NOT EMIT `node_selected`** — entity-preview machinery (slot drilldown, animation preview) must not respond to screen nodes. Early-return in `_emit_selection` after emitting `screen_selected`, **exact pattern of lines 284–296** (the `_MAP_ROLE` branch).
- **Mirror the map-leaf methods** (lines 200–241): `screen_ids()` (return list of stems from files), `select_screen(screen_id)` (find + expand parents + `setCurrentItem`), `refresh_screens()` (rebuild the Screens branch after B3's exporter runs; like `refresh_maps`, it preserves the selection if the screen still exists).

### 1b. New Qt-only session module — `editor/ui_screen_session.py` (planning/UI_EDITOR_PLAN.md lines 323–325)

**Location**: `editor/ui_screen_session.py` (NEW; Qt-only, no game imports, goes into `TestPurity` import list). Mirrors `editor/map_session.py` (`MapSession`, lines 150–342).

**Pattern (from map_session.py):**
- `UIScreenSession(QObject)`: holds one open screen doc (a dict), a `QUndoStack`, and the path to `data/ui/screens/<id>.json` + schema.
- **Lifecycle**:
  - `__init__(data_dir=None, parent=None)`: store the `data_dir`, initialize `self.doc = None`, `self.undo_stack = QUndoStack(self)`.
  - `open(screen_id)` → load from `data/ui/screens/<screen_id>.json`, schema-validate via `engine.data_io.load_validated`, clear the undo stack, emit `screen_opened(screen_id)` signal (mirrors `map_opened` at line 151).
  - `dirty` property → `self.doc is not None and not self.undo_stack.isClean()` (line 163–164).
  - `save()` → write via `engine.data_io.write_validated(..., <screen_defaults.schema.json>)`, call `self.undo_stack.setClean()` (lines 195–199).
- **Undoable push_* methods** — all inherit from `QUndoCommand` (mirror of `_StrokeCommand` etc. at lines 116–139):
  - `push_move(widget_id, old_rect, new_rect)` — move a widget on the canvas; command stores old/new and mutates `doc["widgets"][widget_id]["rect"]`.
  - `push_resize(widget_id, old_size, new_size)` — resize a widget; command stores and mutates `doc["widgets"][widget_id]["rect"]` (both position and size).
  - `push_field(widget_id, field_key, old_value, new_value)` — generic field edit (label, visible, font, color, text_color, skin); command mutates `doc["widgets"][widget_id][field_key]`.
  - `push_skin_assign(widget_id, old_skin, new_skin)` — assign a slot key as the widget's skin (or None); command mutates `doc["widgets"][widget_id].get("skin")`.
  - `push_background(background_spec)` — set the screen background to `{slot: "..."}` or `{color: "#..."}` (or None); command mutates `doc["background"]`.
  - `push_default_field(field_key, old_value, new_value)` — edit a screen-level default (button_skin, panel_skin, font, text_color); command mutates `doc["defaults"][field_key]`.
  - **Command invariant**: all commands store **full old AND new values** (the `_BaseSetCommand` pattern from map_session.py, lines 59–75), never delta. Undo replaces the whole value; redo re-applies new.
- **Signals**: `screen_opened(str)` (screen_id), mirroring map_session's signals.

### 1c. Viewport gains screen mode (`editor/panels/viewport.py`, planning/UI_EDITOR_PLAN.md lines 326–342)

`ViewportPanel.set_screen_mode(session, defaults)` — NEW method mirroring `set_map_mode` (lines 208–232):
- **Swap the session**: `self._screen_session = session if (session is not None and session.doc is not None) else None`; reset interaction state (`self._selected_widget = None`, `self._selected_field_mode = None`, `self._drag_start = None`).
- **Rebuild coordinates & renderer**: screen mode renders at **1280×720 logical size** (the canonical `data/display.json` resolution, B1/B3 contract), scaled-to-fit the viewport widget (no viewport-driven zoom like map mode — the entire canvas is always visible at a fixed scale, just like the entity preview). Reset camera/zoom accordingly.
- **The `defaults` parameter** is the loaded `data/ui/screen_defaults.json` dict, keyed by screen_id → `{widgets: {<id>: {rect, kind, label}}, mock_note}`. **Graceful degradation is HARD REQUIRED**: if `defaults` is missing (pre-B3, or on a badly-configured dev machine), the screen mode **MUST NOT RAISE** — instead, render a placeholder "no layout defaults yet — click Refresh Layouts" message (HudText, red/warning color) and inert all widget-dependent interaction.
- **Renderer submission** (the `render_frame` path) — submit through **the same `Renderer.submit_hud` path** (ED-22 "one render path") into the same offscreen surface:
  - **Background first** (if overridden in the open doc, else the screen's default from screen_defaults, else skip):
    - slot reference → `HudSprite(slot_key, dest=rect(0,0,1280,720), size=(1280,720))` (whole-screen, no animation — backgrounds are single-frame).
    - color reference → `HudRect(dest=rect(...), color=...)` using primitive helpers (next bullet).
  - **Widgets** — iterate `defaults[screen_id]["widgets"]` + apply overrides from `session.doc`:
    - For each widget id → rect, kind, label from defaults; merge any overrides (rect, skin, font, color, text_color, label) from the open doc.
    - **Skinned widget** (has a `skin` override or a default skin from `defaults["defaults"]["button_skin"]` / `"panel_skin"`): emit `HudSprite(skin_slot, dest=rect, size=rect_size, animation=current_state_row, anim_time_ms=screen_anim_clock)` (the state row is driven by a dropdown widget in screen_details, next; defaults to "idle").
    - **Unskinned widget** (no skin assigned): **render the flat-rect fallback using primitive-level helpers**, NEVER importing `game/ui`. The helpers are **mirrored from the defaults `kind` enum** — exactly the six values `button`, `panel`, `label`, `backdrop`, `bar`, `field` (pinned by `data/schemas/screen_defaults.schema.json`); each kind has a hardcoded rect+label render (e.g. button → bordered rect + centred label, text → just the label). These are the **same primitives the game uses**, achieved by re-implementing (accepted drift per E-37 degrade-to-rect). The helpers live in a new internal module `editor/panels/_screen_primitives.py` (pure, low-level rect/text drawing via `HudRect`/`HudLines`/`HudText`, keyed off `kind` — a single switch statement).
  - **Labels** — each widget's label emitted as `HudText(label, dest_center, font_key, color)` (font and color from defaults + overrides).
  - **Screen animation clock** — the screen accumulates `anim_ms` each frame (from `dt`), passed to every skinned widget (the `anim_time_ms` parameter above). Mirrors the game's per-screen clock model (planning/UI_EDITOR_PLAN.md line 161–162).

- **Interaction (ED-23 mouse + keyboard)**:
  - **Click on a widget** (topmost rect under cursor) → set that widget as `_selected_widget`, draw a **selection outline** (HudLines rectangle around the rect) + **corner resize handles** (HudRects at the four corners, draggable).
  - **Drag to move** (click inside widget, drag) → update rect in real-time; on release, commit ONE undoable `session.push_move(widget_id, old_rect, new_rect)` command.
  - **Drag a corner to resize** → update rect size; on release, commit `session.push_resize(widget_id, old_size, new_size)`.
  - **Arrow keys** (↑ ↓ ← →) — **nudge the selected widget** by 1 or 5 pixels (configurable, default 1); each key press commits an undoable move.
  - **Click on empty space** → deselect (clear outline).
  - **State dropdown** (idle/hover/pressed/disabled) — a new widget in the viewport (similar to the animation dropdown in entity-preview mode, lines 80–82 of viewport.py); changing state updates the animation row passed to skinned HudSprite submissions (live preview of the button states).
  - **No creation/deletion** — only edit existing widgets from the defaults. `Backspace`/`Delete` on a selected widget does nothing (or is not bound).

### 1d. New details panel — `editor/panels/screen_details.py` (planning/UI_EDITOR_PLAN.md lines 336–341)

**Location**: `editor/panels/screen_details.py` (NEW; mirroring `map_details.py` in structure).

**Right-pane form** (shown when a screen is selected, replaces the asset-import DetailsPanel):
- **Top section: widget list** — a `QListWidget` showing every widget id from `defaults[screen_id]["widgets"]`. Clicking a widget sets it as selected in the viewport.
- **Per-widget form** (below the list):
  - **Rect spinboxes** (X, Y, W, H) — import the `_NoWheelSpinBox` widgets **FROM `editor.panels.balancing`** (never copy, never move). Bounds: X/Y can be negative (off-canvas), W/H ≥ 1. Seeded from the open doc's override or the default rect.
  - **Skin combo** — dropdown listing all `ui` category slots from the registry (the slots available for Button/Panel types). Blank entry (no skin). Selecting an entry mutates `session.doc["widgets"][widget_id]["skin"]` via `push_skin_assign`, undoable.
  - **Font combo** — keys from `engine/render/fonts.py` `_FONT_SPECS`: `sm`, `md`, `lg`, `xl`, `xxl`, `hud_phase`, `hud_lvl` (or any keys that exist). Seeded from the default or override.
  - **Color buttons** — three `QPushButton`s labeled "Text Color", "Highlight", "Shadow" (or similar; the exact labels are in the defaults schema). Each opens a `QColorDialog` on click, stores the chosen color as `"#RRGGBB"` in the doc. Import color picker logic (minimal) or wrap Qt's built-in dialog.
  - **Label edit** (QLineEdit) — the widget's displayed text; mutates `session.doc["widgets"][widget_id]["label"]`.
  - **Visible checkbox** — bool; mutates `session.doc["widgets"][widget_id]["visible"]`.
  - **"Reset to default" button** — per field, clears the override by removing that key from `session.doc["widgets"][widget_id]` (so the game picks up the default on next layout). OR, if all overrides are cleared, remove the widget entry entirely (leaving only widgets with at least one override in the doc).

- **Screen-level section** (below the per-widget form):
  - **Background picker** — a combobox listing ui category `Backgrounds` slots (from the registry, mirroring the button-skin picker). Also a color picker button. Selecting a slot mutates `session.doc["background"]` to `{slot: "..."}` via `push_background`, undoable. Selecting a color mutates it to `{color: "#..."}`. Blank = no background.
  - **Defaults section** (collapsible, expanded by default):
    - **`button_skin` combo**, **`panel_skin` combo** — ui slots, blank = no default.
    - **`font` combo** — same keys as the per-widget font, or blank.
    - **`text_color` button** — QColorDialog.
    - Each edit → `session.push_default_field(key, old, new)`, undoable.

- **Save button** — calls `session.save()` (writes to disk via `write_validated`). Greyed out if `not session.dirty`. On save, refresh the viewport (reload defaults if they changed).
- **Session wiring** — panel emits edits as undoable commands (NOT staged like balancing — every user action is a command that immediately appears in the undo stack). The panel is shown/hidden with the viewport mode (screen mode ↔ entity preview mode).

### 1e. Main window — right-stack integration (planning/UI_EDITOR_PLAN.md lines 297–307)

`editor/main.py`:
- **right_stack extension** (currently holds `details` at index 0, `map_details` at index 1; lines 258–260): add **`screen_details`** as index 2 (a third `QStackedWidget` page).
- **`_on_screen_selected(screen_id)` slot** — new, mirroring `_on_map_selected` (lines 297–307):
  - Check if a different screen is already open (`session.doc.screen_id`). If same screen, just enter screen mode (lines 299–301).
  - Call `_resolve_dirty()` (reuse the existing method, lines 330–349) to prompt save/discard/cancel before leaving the current screen.
  - If proceeding, call `session.open(screen_id)` and enter screen mode (line 306).
- **`_enter_screen_mode()` + `_leave_screen_mode()` helpers** (mirroring `_enter_map_mode` at lines 309–320 + `_leave_map_mode` at lines 322–328):
  - `_enter_screen_mode()`: load defaults from `data/ui/screen_defaults.json` (sync with B3 output; if missing, pass an empty dict and graceful-degrade in viewport), call `viewport.set_screen_mode(session, defaults)`, show the palette (NO, palettes are map-only — actually, DON'T show anything extra), switch `right_stack` to screen_details index, enable Ctrl+Z/Y window actions to target the screen session (next bullet).
  - `_leave_screen_mode()`: call `viewport.set_screen_mode(None)`, switch `right_stack` back to `details`.
- **Window-level undo/redo** (Ctrl+Z / Ctrl+Y) — modify the existing `_on_undo` / `_on_redo` methods (if they exist, or create them) to target **whichever session is active** (check `self._in_screen_mode()` or similar flag, route to `self.screen_session.undo_stack` vs. `self.map_session.undo_stack`). The pattern already exists for maps; extend it.
- **"Refresh Layouts" button** (in screen mode) — a toolbar button (or context menu, placement TBD by UI review; the brief specifies the mechanics only):
  - On click, run `py tools/export_ui_layouts.py` as a **tracked QProcess** (like Build in `run_controls.py`, lines 113–150; reuse the `RunControls._launch` infrastructure).
  - Stream output to the Console dock (same pattern as Build output).
  - On success (exit code 0), reload `data/ui/screen_defaults.json` in-memory, call `viewport.refresh_screen_defaults(new_defaults)` to re-render with the new defaults, and refresh the Screens branch (`selector.refresh_screens()`).
  - On failure, show an error in the console and leave the old defaults in place.
- **Selector signal routing** — connect `selector.screen_selected(screen_id)` → `self._on_screen_selected(screen_id)` (mirroring line 281 for maps).

### 1f. Run controls extension — exporter command builder (planning/UI_EDITOR_PLAN.md lines 132–134)

`editor/run_controls.py`:
- Add a pure builder function `export_layouts_command(python_exe=None, repo=None)` — returns a command list to run `tools/export_ui_layouts.py` (headless, no SDL dummy needed; it's pure Python that imports game for layout construction).
  - Pattern: `[python_exe or sys.executable, str(repo / "tools" / "export_ui_layouts.py")]`.
  - Used by `_on_refresh_layouts` in main.py when calling `run_controls._launch("export_layouts", export_layouts_command(...))`.

---

## 2. Architecture plan

### Design: one render path (ED-22), mirrored patterns

B4 **heavily mirrors map mode** to ensure consistency:
- **Session** — `UIScreenSession` is an exact structural mirror of `MapSession` (QUndoStack, open/save lifecycle, dirty property, undoable push_* methods). Both use `QUndoCommand` subclasses with full old/new value storage.
- **Viewport mode** — `set_screen_mode(session, defaults)` mirrors `set_map_mode(session)`, resetting interaction state and rebuilding the renderer at a fixed 1280×720 logical resolution (vs. map mode's variable grid dims).
- **Selection flow** — selector signal (`screen_selected`) → main window slot (`_on_screen_selected`) → dirty check (`_resolve_dirty`) → session.open → viewport.set_screen_mode → right_stack switch, exactly like maps.
- **Undo stack wiring** — window-level Ctrl+Z/Y routed to the active session's undo stack (map or screen), enabling undo across mode switches while a session is open.

### Design: graceful degradation (E-37)

If `data/ui/screen_defaults.json` does not exist (pre-B3, or on a broken dev machine):
- Viewport renders a "no layout defaults yet — click Refresh Layouts" placeholder (HudText, red).
- Every widget-interaction attempt (click, drag, arrow key) is silently ignored.
- The "Refresh Layouts" button remains clickable and functional.
- No crash, no raise, full UI responsiveness.

### Design: strict layering (root CLAUDE.md)

- **Editor NEVER imports `game/ui`** — flat-rect fallback for unskinned widgets is re-implemented as primitive helpers (`editor/panels/_screen_primitives.py`), kept minimal and manually aligned with the game's style (accepted drift per E-37).
- Every new module (`ui_screen_session`, `screen_details`, `_screen_primitives`) goes into `TestPurity`'s import list (tools/tests/test_editor_viewport.py lines 205–215).

---

## 3. File scope + shared-file contract

B4's coder **may touch exactly these files** (on branch `phase-10L-finish-umbrella`, in parallel with A4–A7 which touch `editor/`, `engine/`, and `data/` only; NO overlap):

| File | What B4 does |
|---|---|
| `editor/panels/selector.py` | Add `Screens` branch + `_SCREEN_ROLE` data key; `screen_selected(str)` signal; `screen_ids()`, `select_screen()`, `refresh_screens()` methods; mirror map-leaf pattern exactly (lines 200–241 template). |
| `editor/ui_screen_session.py` | NEW Qt-only session module; `UIScreenSession` class mirroring `MapSession` (~190 lines including docstrings); `open(screen_id)`, `save()`, `dirty` property; typed push_* methods for undo. |
| `editor/panels/viewport.py` | NEW `set_screen_mode(session, defaults)` method (mirroring `set_map_mode`, ~50 lines); screen-mode rendering path (submit background + widgets + labels to HUD); graceful-degrade placeholder; interaction (click, drag, arrow keys); state dropdown for anim preview; "in_screen_mode()" helper. |
| `editor/panels/_screen_primitives.py` | NEW internal module (~100 lines); primitive helpers for flat-rect widget rendering (keyed off `kind` enum from defaults schema); pure HudRect/HudLines/HudText submission. |
| `editor/panels/screen_details.py` | NEW right-pane form panel (~250 lines); widget list; per-widget form (rect spinboxes, skin/font/color combos, label edit, visible checkbox, per-field reset); screen-level defaults section; background picker; Save button; session wiring for every edit as an undoable push_*. |
| `editor/main.py` | `self.screen_details` widget (construct in `__init__`); `right_stack` extend to add screen_details at index 2; `self.screen_session` property; `_on_screen_selected(screen_id)` slot; `_enter_screen_mode()` / `_leave_screen_mode()` / `_in_screen_mode()` helpers; selector signal wiring (`screen_selected` → `_on_screen_selected`); window undo/redo target routing (Ctrl+Z/Y to active session); "Refresh Layouts" button + `_on_refresh_layouts` slot + `run_controls._launch` call; load + cache defaults on screen open. |
| `editor/run_controls.py` | Add `export_layouts_command(python_exe=None, repo=None)` builder function (~3 lines). |
| `tools/tests/test_editor_viewport.py` | Extend `TestPurity` import list (lines 205–215): add `editor.ui_screen_session`, `editor.panels.screen_details`, `editor.panels._screen_primitives`. |
| `editor/CLAUDE.md` | Document screen mode at top level (§Architecture, after run_controls or spawnclaude bullets); mention the new session, "Refresh Layouts" button workflow, undo stack routing. |
| `editor/panels/CLAUDE.md` | NEW subsection (or extend Phase 5 if it exists) documenting screen mode: viewport `set_screen_mode` (1280×720 fixed res, graceful defaults-missing, flat-rect fallback for unskinned), screen_details form structure (widget list, per-widget fields, screen-level defaults), session lifecycle mirroring map mode. |

**B4 MUST NOT touch:**
- `data/ui/screens/*.json`, `data/ui/screen_defaults.json`, `data/schemas/ui_screen*.schema.json` — B1/B3 own these.
- `game/**`, `engine/**` (layering rule; game imports are forbidden in editor code).
- `tools/export_ui_layouts.py` (B3 owns this).
- `tools/smoke.py`, `tools/build.py` (unchanged; smoke already handles `data/ui/screens/` and `data/ui/screen_defaults.json` per B1/B3).
- `conftest.py` — A5′ owns this (hard rule per planning/UI_EDITOR_PLAN.md context).

**Shared-file insertion points:**

1. **`editor/panels/selector.py`**, after existing maps-branch construction (line ~215):
   - Insert screen-branch build: iterate `data/ui/screens/`, create leaves with `_SCREEN_ROLE` data key, add to a `_screens_branch` item.
   - Modify `_emit_selection` (line 280) to check `_SCREEN_ROLE` first and emit `screen_selected` (early-return, no `node_selected`).
   - Add methods `screen_ids()`, `select_screen(screen_id)`, `refresh_screens()` (exact template: lines 200–241).

2. **`editor/main.py`**, `__init__` widget construction:
   - After `self.map_details = MapDetailsPanel(...)` (line ~260), add `self.screen_details = ScreenDetailsPanel(...)`.
   - In `right_stack` setup (lines 258–260), add `self.right_stack.addWidget(self.screen_details)` at index 2.

3. **`editor/main.py`**, signal wiring (after line 281 `self.selector.map_selected`):
   - Add `self.selector.screen_selected.connect(self._on_screen_selected)`.

4. **`editor/main.py`**, window undo/redo (if not already a method):
   - Create or extend `_on_undo` / `_on_redo` to route to `self.map_session.undo_stack` vs. `self.screen_session.undo_stack` based on the active mode.

5. **`editor/run_controls.py`**, after `build_exists()` (line ~47):
   - Add `export_layouts_command(python_exe=None, repo=None)` builder.

---

## 4. Exit gate + Quick Test

### Commands

```
py tools/smoke.py
py tools/testgate.py check --affected
py -m unittest discover -s tools/tests -t .
```

**Gate = ZERO failures** (`GATE PASS`). No baseline, no tolerated failures. A failure in any of the touched files (selector, viewport, main, run_controls) is B4's responsibility.

**NOTE:** The `TestPurity` import list extension adds new modules; verify that the purity test still passes (it will if those modules never import game/*).

### Tests

All B4 tests go into **`tools/tests/test_editor_viewport.py`** (extending existing classes or adding new ones; NO new test module, per hard rule). Use `qt_harness.QtCase` + `self.track()` for every widget.

**Fixture: screen defaults dict** — hand-authored inline fixture conforming to B1's `ui_screen.schema.json` and B3's defaults structure. Example:

```python
FIXTURE_DEFAULTS = {
    "main_menu": {
        "widgets": {
            "btn_new_game": {"rect": [640, 360, 120, 40], "kind": "button", "label": "START"},
            "btn_settings": {"rect": [640, 420, 120, 40], "kind": "button", "label": "SETTINGS"},
            "title": {"rect": [640, 100, 400, 80], "kind": "text", "label": "MAIN MENU"},
        },
        "mock_note": "test fixture"
    }
}
```

**Test classes and methods** (new `TestScreenMode(MapModeCase)` or extend existing if appropriate):

1. `test_selector_shows_screens_branch_above_slots` — `ui` category has a Screens branch as the first child; expand → 12 leaves (one per screen id).
2. `test_screen_leaf_emits_screen_selected_not_node_selected` — click a screen leaf → `screen_selected(str)` signal fires with the screen id; `node_selected` does NOT fire (verify via mock).
3. `test_selector_refresh_screens_preserves_selection` — select `Main Menu`, call `refresh_screens()`, selection is restored to the same screen.
4. `test_screen_session_open_loads_and_validates` — `session.open("main_menu")` → `session.doc` is the loaded dict, schema-validated; `dirty` is False.
5. `test_screen_session_push_move_undoable` — `session.push_move("btn_new_game", old_rect, new_rect)` → undo stack records the command; undo reverts the rect.
6. `test_screen_session_push_field_undoable` — `session.push_field("title", "label", "OLD", "NEW")` → doc is mutated; undo reverts.
7. `test_screen_session_dirty_after_push_clean_after_save` — after a push, `session.dirty` is True; `session.save()` writes to disk and sets `dirty` to False.
8. `test_viewport_set_screen_mode_renders_without_defaults` — graceful degrade: call `viewport.set_screen_mode(session, {})` (empty defaults) → render succeeds, placeholder text is visible, no raise.
9. `test_viewport_set_screen_mode_renders_with_defaults` — call `viewport.set_screen_mode(session, FIXTURE_DEFAULTS["main_menu"])` → render submits HudSprite/HudRect/HudText for each widget; widget count matches expected.
10. `test_viewport_click_selects_topmost_widget` — click inside a widget rect → selection outline appears around it (verify HudLines are submitted).
11. `test_viewport_drag_move_commits_undo_command` — click + drag a widget to a new position → on release, session has a new command in the undo stack; `session.doc` reflects the new rect.
12. `test_viewport_arrow_key_nudges_selected_widget` — select a widget, press left arrow → selected widget moves 1px left; a new undo command is pushed (or accumulated into a "nudge" command, design choice).
13. `test_viewport_state_dropdown_drives_anim_row` — state dropdown defaults to "idle"; select "hover" → next render submits HudSprite with `animation="hover"`; animation list comes from the loaded slot.
14. `test_screen_details_widget_list_mirrors_defaults` — `screen_details.set_session(session)` → widget list shows ids from `FIXTURE_DEFAULTS`; clicking a widget id selects it in the viewport.
15. `test_screen_details_rect_spinboxes_push_move_on_change` — change a rect spinbox → `session.push_move(...)` is called; undo reverts the spinbox value.
16. `test_screen_details_skin_combo_push_skin_assign_on_change` — select a skin in the combo → `session.push_skin_assign(...)` is called; undo reverts the combo.
17. `test_screen_details_reset_to_default_removes_override` — click "reset" on a field → that override key is removed from the doc (or the entire widget entry if it's the last one).
18. `test_screen_details_background_picker_combo_push_background` — select a slot in the background combo → `session.push_background({"slot": "..."})` is called.
19. `test_main_window_on_screen_selected_enters_screen_mode` — select a screen leaf → viewport.in_screen_mode() is True; right_stack shows screen_details.
20. `test_main_window_resolve_dirty_prompts_before_switching_screens` — open screen A, make an edit, select screen B → dialog appears; choose Save → screen A is saved, then screen B opens.
21. `test_purity_new_modules_do_not_import_game` — extend `TestPurity.test_editor_does_not_import_game` to include the three new modules in the import list; run the purity test → passes.

**Note on defaults-loading:** B3 provides `data/ui/screen_defaults.json`; B4 tests use the inline `FIXTURE_DEFAULTS` to avoid live-data brittleness (same pattern as map/entity preview tests).

### Quick Test (human, live editor — deferred to B5 for full round-trip; B4-only slice)

`py editor/main.py` → selector tree → **UI → Screens**:

1. **Screens branch is visible and populated** — expand Screens → see 12 leaves (main_menu, pause, settings, credits, add_name, game_over, levelup, hud, building_panel, cheat_menu, game_log, boss_cutscene).
2. **Select Main Menu** → viewport enters screen mode (canvas shows the menu layout); right pane switches to screen_details; state dropdown appears in viewport.
3. **Placeholder message (pre-B3)** — if `data/ui/screen_defaults.json` does not exist, viewport shows "no layout defaults yet — click Refresh Layouts" in red; no crash; clicking a widget area does nothing.
4. **After B3 lands / Refresh Layouts succeeds** (deferred to B5; state the expected behavior):
   - Widgets render as either skinned HudSprites or flat-rect fallbacks.
   - **Drag a widget** (e.g. "START" button) → moves on screen; release → undo command recorded; Ctrl+Z reverts.
   - **Right pane: change the START button's label** → type "NEW GAME" in the label spinbox → viewport updates in real-time.
   - **Assign a skin** — select `ui_button` from the Skin combo → button renders skinned (if art is imported); click state dropdown to see hover/pressed/disabled rows animating.
   - **Save** → writes `main_menu.json` with overrides; `py tools/smoke.py` passes.
   - **Ctrl+Z round-trip** — undo the label change, redo it, verify the undo stack works end-to-end.

---

## Risks / open items

- **Defaults-missing degradation**: the placeholder "Refresh Layouts" message must render fast and not block the UI. If `defaults` is an empty dict, every widget interaction is a no-op by construction (no attempt to iterate missing keys).
- **Flat-rect fallback drift** from the game's actual style: `_screen_primitives.py` re-implements button/panel/text rendering without importing game/ui (layering rule). The two must stay visually aligned via code review and the parity pin test (B2) — **this is an accepted design trade-off per E-37**.
- **Performance of 1280×720 + 12 screens**: screen mode is fixed-resolution (no viewport zoom like maps), so all 1280×720 HUD submissions are on-screen. If defaults + overrides sum to many widgets (50+), HUD rendering may slow perceptibly; benchmarking deferred to B5 live test. Current HUD path is efficient enough for game UI in-round; editor preview should be fine at 60fps even with 50 widgets.
- **Export subprocess latency**: "Refresh Layouts" runs an out-of-process Python script. On slow machines, the exporter may take 2–5 seconds; the UI must stay responsive (tracked QProcess output streaming handles this per `run_controls.py` pattern). A stuck exporter is caught by the user's manual timeout; no automatic kill is implemented.

---

## Abbreviations & references

- **ED-nn**: SPEC.md requirement (Editor domain).
- **E-nn**: SPEC.md requirement (Engine domain).
- **D-nn**: SPEC.md requirement (Data domain).
- **R-nn**: User requirement (from planning/UI_EDITOR_PLAN.md).
- **QUndoStack/QUndoCommand**: Qt undo/redo framework (used in `map_session.py`, template for this phase).
- **HudSprite/HudRect/HudText/HudLines**: engine/render primitives for HUD (on-screen, unsorted), submitted to `Renderer.submit_hud`.
- **1280×720**: canonical logical resolution from `data/display.json` (game and editor agree on this).
- **Graceful degrade**: E-37 "rendering degrades, never explodes" — no asset, no defaults → fallback rendering, no raise.
- **TestPurity**: hard rule in editor/CLAUDE.md: every new module must be added to the import-game-detection test.
