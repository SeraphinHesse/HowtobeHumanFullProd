# Phase UL-6 — Layers in the outliner + undoable ops

## 1. Behavioral specification

**Goal.** A designer selects a widget in the outliner, clicks **Add Layer**, picks art from the `ui` slots, and the layer exists in the saved doc — no programmer involved. The layer appears as a child node under the widget in the tree, stays there through undo/redo, and can be removed or reordered within its band.

**File citations:**

- `planning/UiLayeredWidgetsPLAN.md:379-403` — phase scope and decisions D2, D3, D9, D5.
- `docs/handoffs/section-S2.md:10-16` — exact layer entry schema: `id`, `offset` `[dx,dy,w,h]`, `z`, `band` (`"under"|"over"`), appearance keys (`slot`, `text_id`, `label`, `font`, `align`, `color`, `text_color`, `tint`, `visible`), and optional `states` object.
- `docs/handoffs/section-S2.md:17` — `engine/ui_layers.py` public interface: `resolve(layer_spec, owner_rect, state="idle")`, `ordered(layers, band)`, `validate_offsets(layers)`.
- `editor/panels/CLAUDE.md:813-925` (Phase B4) — screen mode architecture: `ScreenDetailsPanel` form structure, `WidgetTreeWidget` tree contract (line 1078-1091), `widget_display_name`, reset button patterns, live rect editing.

**Quick test (in editor):**
1. `py editor/main.py` → screen mode → `hud` → select Love counter (`love_text`).
2. Click **Add Layer** → pick a `ui` slot (e.g., `_love_bg`) → confirm layer node appears under `love_text` in the outliner.
3. Click **Remove Layer** → confirm node disappears.
4. **Undo twice** → layer reappears, add is undone.
5. **Ctrl+S** (Save) → close and reopen the screen → confirm layers persisted in `data/ui/screens/hud.json`.
6. **Undo in editor** → Ctrl+Z removes the layer from the doc.

---

## 2. Architecture plan

### Session API — `editor/ui_screen_session.py`

Add four new public methods (mirrors of `push_field`, `push_move`, etc.):

- **`layers(widget_id: str) -> list[dict]`** — pure reader. Returns the `"layers"` array from the widget's override, or an empty list if the key is absent. Used by the panel to redraw layer nodes.

- **`add_layer(widget_id: str, layer_id: str, layer_spec: dict) -> None`** — undoable. Pushes ONE command (`_DocFieldCommand` path: `("widgets", widget_id, "layers", layer_id)`, old=None, new=layer_spec). The layer_id MUST be unique within that widget — the validator or panel logic enforces this (details in §3).

- **`remove_layer(widget_id: str, layer_id: str) -> None`** — undoable. Pushes ONE command at path `("widgets", widget_id, "layers", layer_id)`, old=layer_spec (from the current doc), new=None. The pruning logic in `_apply_field` removes the layers array entirely if it becomes empty (consistent with widget/parent behavior).

- **`set_layer_field(widget_id: str, layer_id: str, field_key: str, old_value, new_value) -> None`** — undoable. Pushes ONE command at path `("widgets", widget_id, "layers", layer_id, field_key)`, old=old_value, new=new_value. Used by the inspector (UL-8) to edit individual layer fields. Mirrors `push_field`'s signature.

- **`reorder_layer(widget_id: str, layer_id: str, new_z: int) -> None`** — undoable. Pushes ONE command at path `("widgets", widget_id, "layers", layer_id, "z")`, old=(current z or 0), new=new_z. Simpler than a cascade; only the `z` field changes.

All five methods follow the existing `push_*` contract: pass FULL old/new values (never deltas), guard against `old == new`, and write through `self.undo_stack.push(_DocFieldCommand(...))`. Documentation: "undo one layer operation" text in each command label (e.g., `f"add layer {layer_id} to {widget_id}"`).

### Outliner — `editor/panels/screen_details.py`

**Tree structure change (in `_refresh_widget_list`):**

After building the widget tree (current behaviour), add layer nodes as CHILDREN of their owner widget node. Per-widget:
1. Read `doc_widgets[widget_id].get("layers", [])`
2. For each layer, call `ordered(layers, band)` (D2 — sort by z within band) to get draw order
3. Insert a child `QTreeWidgetItem` for each layer with:
   - **Text (display):** `widget_display_name(layer_id, layer_spec) or layer_id` (mirrors widget naming, but layer ids are programmer-set identifiers, so fallback to id is normal)
   - **Tooltip:** the layer id
   - **UserRole:** `(widget_id, layer_id)` — a **tuple**, not a string, to distinguish from widget nodes (which remain bare widget_id strings). Readers must check `isinstance(role, tuple)` to tell them apart.

Store layer nodes in a separate dict for fast lookup by (widget_id, layer_id): `self._layer_items[(widget_id, layer_id)] = item`.

**Widget form — layer controls section:**

After the "Reset ALL to default" button (current line 367) and BEFORE the screen-level Background section (current line 373), add a clearly named section:

- A `QLabel("Layers")` row (section header)
- A NEW `QListWidget` or `QTableWidget` (the layer list for the selected widget) — or a small group of controls:
  - **Add Layer button** → opens a slot picker (reuse the existing `_NoWheelComboBox` logic from skin combo, or the asset importer, per the panel's discretion) → user picks a slot → calls `self._session.add_layer(widget_id, new_layer_id, {"slot": picked_slot, "offset": [0,0,0,0], "z": 0, "band": "over", ...})` (layer_id can be auto-generated as a UUID or `layer_<timestamp>`, per the panel's design choice; a schema constraint enforces uniqueness within the widget).
  - **Remove Layer button** (enabled only when a layer node is selected in the tree) → calls `self._session.remove_layer(widget_id, layer_id)` and rebuilds the tree.
  - **Reorder buttons** (Up/Down, or drag — design choice) → call `self._session.reorder_layer(...)` to adjust `z` within the same band (or allow moving between bands).

- Update `_set_widget_form_enabled(enabled)` to include the Add button (always enabled when a widget is selected), Remove/Reorder (enabled only if a layer is currently selected in the tree AND a widget is selected).

- On `widget_list.itemSelectionChanged` (or whenever a tree node is selected), check if it's a layer node (UserRole is a tuple) and update Remove/Reorder button states accordingly. If a layer node is selected, the layer list context becomes visible (or highlight the layer in the list); if a widget node is selected, layer controls focus on Add.

**Tree integration:**

- When a widget is expanded, its layer children are visible. When collapsed, layers collapse too.
- Selecting a layer node emits the widget_id to the viewport (so viewport can highlight that widget + its layer), but the form still shows the WIDGET'S controls (rect, skin, font, etc.), NOT the layer's — layer inspection is UL-8's job. The panel may add a read-only label showing the selected layer's id and slot.
- Re-parenting logic remains unchanged (works only on widgets, not layers — layers have no parent concept in this plan).

---

## 3. File scope and shared-file contract

### New files

- **`tools/tests/test_ui_layer_ops.py`** — create from scratch. Structure:

  ```python
  # Test class: TestLayerOps
  # Tests: add_layer (new entry in doc, unique id generated), 
  #        remove_layer (removes entry, prunes empty layers array),
  #        reorder_layer (z field updated), set_layer_field (field patched),
  #        undo/redo round-trips, ids stay unique, doc validates after every op.
  #        Per the plan D5: with no layers authored, the doc stays byte-identical.
  
  # EXPLICIT INSERTION POINTS FOR FUTURE PHASES:
  # - UL-7 will add class TestLayerViewportGeometry (append to this file, do not edit TestLayerOps)
  # - UL-8 will add class TestLayerStateInspector (append to this file, do not edit TestLayerOps)
  ```

  Mark `@pytest.mark.editor` on all tests (Qt required).

### Modified files

#### `editor/ui_screen_session.py`

**Insertion point:** After `push_string` method (line ~360), add the four layer-operation methods described in §2. Example path signature:

```python
def add_layer(self, widget_id, layer_id, layer_spec):
    """Add a layer to a widget, undoably. layer_spec is a complete layer dict 
    (id, offset, z, band, slot, etc. — keys match the schema)."""
    old = None
    new = copy.deepcopy(layer_spec)
    self._push(("widgets", widget_id, "layers", layer_id), old, new,
               f"add layer {layer_id} to {widget_id}")
```

(Other methods follow the same pattern, using `_push` and respecting the old==new guard.)

#### `editor/panels/screen_details.py`

**Insertion point 1 — Layer control UI (in `__init__`):**

After `self.reset_button = ...` (line 367), and BEFORE `bg_label_row = ...` (line 374):

Add a new method `_build_layer_controls(self)` that returns a widget (or list of widgets) to insert into the main layout. This method:
- Creates the Add Layer button, Remove Layer button, Reorder controls (Up/Down or drag)
- Stores them as instance attributes: `self.layer_add_button`, `self.layer_remove_button`, `self.layer_up_button`, `self.layer_down_button`
- Wires signal handlers to session methods
- Returns a composed widget (e.g., a QGroupBox or a QWidget with a layout)

Then call `layout.addWidget(self._build_layer_controls())` in the main `__init__` before adding the background section.

Document clearly which controls should be visible/enabled by which conditions (e.g., "Add button enabled when a widget is selected; Remove/Reorder enabled when a layer node is selected").

**Insertion point 2 — Tree node building (in `_refresh_widget_list`):**

After the existing `add(widget_tree.ROOT, None)` recursion (line 606), add layer children:

```python
# After add(...) call above and before blockSignals(False):
doc_widgets = self._doc_widgets()
for widget_id, item in self._tree_items.items():
    layers = doc_widgets.get(widget_id, {}).get("layers", [])
    if layers:
        # Use engine.ui_layers.ordered(...) to sort by z within each band (D2)
        for layer in layers:  # or sorted by z per design
            layer_item = QTreeWidgetItem([layer.get("id", "unnamed")])
            layer_item.setToolTip(0, layer.get("id", "unnamed"))
            layer_item.setData(0, Qt.ItemDataRole.UserRole, (widget_id, layer.get("id")))
            item.addChild(layer_item)
            self._layer_items[(widget_id, layer.get("id"))] = layer_item
```

Also initialize `self._layer_items = {}` in `__init__` alongside `self._tree_items = {}`.

**Insertion point 3 — Selection sync (in `_on_widget_list_selected` or new handler):**

When a tree item is selected, check if it's a layer node (UserRole is a tuple):

```python
widget_id = current.data(0, Qt.ItemDataRole.UserRole)
if isinstance(widget_id, tuple):
    # Layer node selected
    widget_id, layer_id = widget_id
    self._current_layer_id = layer_id
    self.layer_remove_button.setEnabled(True)
    # Emit to viewport: "highlight this widget AND its layer"
    self.widget_selected.emit(widget_id)  # Still emit widget for viewport
else:
    # Widget node selected
    self._current_layer_id = None
    self.layer_remove_button.setEnabled(False)
    # ... existing logic
```

**Insertion point 4 — Enable/disable in `_set_widget_form_enabled`:**

Add the layer buttons to the list that gets enabled/disabled:

```python
def _set_widget_form_enabled(self, enabled):
    for w in (... existing list ..., 
              self.layer_add_button):  # Add is always available when widget selected
        w.setEnabled(enabled)
    if not enabled:
        # Disable layer Remove/Reorder when no widget selected
        for btn in (self.layer_remove_button, self.layer_up_button, self.layer_down_button):
            btn.setEnabled(False)
```

**Insertion point 5 — doc access:**

Ensure `self._doc_widgets()` is available (it should already be — mirrors `self._current_screen_defaults().get("widgets", {})`). If it doesn't exist, add:

```python
def _doc_widgets(self):
    return self.doc.get("widgets", {}) if self.doc else {}
```

### Schema — no changes required

The layer entry schema and the per-widget `layers` array already land in S2 (`data/schemas/ui_screen.schema.json`). UL-6 consumes it as-is.

### Viewport — no changes required

The viewport (`panels/viewport.py`) does NOT draw layers in this phase — that's UL-7. It may opt to highlight the selected widget in a different colour if a layer is selected, but that's optional.

---

## 4. Exit gate and Quick Test

**Exit gate:**
```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_ops.py -q
```

Smoke must pass (data is valid). Pytest must show all tests passing, 0 failures.

**Quick Test (in editor):**

1. `py editor/main.py`
2. Switch to **screen mode** → select screen `hud`
3. In the Widgets tree, select `love_text` (the love counter label)
4. Click **Add Layer** → a slot picker combo appears
5. Pick a `ui` slot (e.g., `_love_bg` or any background-type slot)
6. Confirm:
   - A new child node appears under `love_text` in the tree, labelled with the layer's id
   - The layer data is in memory (form shows it's added, or a read-only label shows layer id + slot)
7. Click **Remove Layer** → node disappears
8. **Ctrl+Z** twice → layer reappears (undo remove, then undo add)
9. **Ctrl+S** (Save) → the editor saves the doc
10. Close and reopen the `hud` screen
11. Confirm the layer is still there in the tree (persisted in the saved JSON)
12. **Ctrl+Z** in the editor → layer is removed from the in-memory doc
13. **Ctrl+Y** (Redo) → layer reappears

All steps must complete without errors. The saved `data/ui/screens/hud.json` must contain the layer entry in the `widgets.love_text.layers` array with the correct slot and offset.

