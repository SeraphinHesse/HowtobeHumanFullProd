# Phase UL-7 — Layers in the viewport

## 1. Behavioral Spec

**Goal:** The viewport draws every layer where the game will draw it, and the designer drags it into place.

### Draw path

- Layers are drawn via `engine.ui_layers.resolve(layer_spec, owner_rect, state)` (file: `engine/ui_layers.py:56-120`, signature contract in S2 handoff)
- Both bands (`under` + `over`) are submitted: `under` layers drawn BEFORE their owner widget, `over` layers AFTER
- Within each band, layers are ordered by `engine.ui_layers.ordered(layers, band)` (file: `engine/ui_layers.py:123-152`) — stable sort by `z` ascending, earliest `z` drawn first (so higher `z` paints on top within the band)
- The preview from `data/ui/screen_previews.json` is replayed first (unchanged, override-free by design), then layers composite on top in this submission order: all `under` layers (per widget in screen order), all widgets, all `over` layers (per widget in screen order)
- Layers are drawn as HUD primitives exactly like the game draws them: via `HudSprite` (if `slot` is set), `HudText` (if `text_id` or `label` is set), or `HudRect` (if `color` is set), with tint/color/visibility applied

### Hit-testing

- Layer hit-testing uses the SAME "smallest candidate wins" rule as widget hit-testing (file: `editor/panels/viewport.py:802-839`)
- Hit-test order: first the SELECTED WIDGET's layers only (topmost-first within its two bands), then other widgets' layers, then other widgets themselves
- When a layer is hit, the selection changes to that layer (a `(widget_id, layer_id)` pair per the S3 handoff — layer nodes carry both values in `Qt.ItemDataRole.UserRole`)
- A layer with `visible=false` (post-state-resolution) is not hit-testable
- Layer hit-testing is transparent when outside a layer's resolved rect

### Drag and resize

- Dragging a layer LIVE-mutates its `offset` field in `session.doc["widgets"][widget_id]["layers"][layer_index]` exactly as widget drag LIVE-mutates `session.doc["widgets"][widget_id]["rect"]` (file: `editor/panels/viewport.py:932-958`)
- Resizing a layer adjusts the SECOND and FOURTH elements of the offset `[dx, dy, w, h]` (width and height), keeping the opposite corner anchored like widget resize (file: `editor/panels/viewport.py:859-874`)
- On release, one undoable `push_layer_field(widget_id, layer_id, "offset", old_offset, new_offset)` command commits the change (signature TBD-pending-UL-6 landing; mirror the signature of `session.push_move`/`push_resize` on widgets — call site is `file:editor/panels/viewport.py`, inside `_screen_release` equivalent for layers)
- **TBD-pending-UL-6:** If `push_layer_field` does not exist, the expected shape is `session.push_layer_field(widget_id, layer_id, "offset", old, new)` following the `_DocFieldCommand` pattern for `push_field(widget_id, key, old, new)` (file: `editor/ui_screen_session.py`)

### Layer interaction rect

- A layer's interaction rect (the box the editor hit-tests and outlines) is computed in `editor/panels/_screen_primitives.py` as a pure function
- A layer with a non-zero `offset[2]`/`offset[3]` (width/height) is used verbatim (matches widget resize behavior)
- A layer with zero width OR zero height has that axis grown to the measured size of its resolved text content (if `text_id` or `label` is set after state resolution) or a minimum grabbable size (file: `editor/panels/_screen_primitives.py:111-139`, mirror the `interaction_rect` pattern for widgets)
- Text measurement respects the layer's resolved `align` field (left/center/right per UL-1)

### Visual feedback

- A selected layer is outlined with a bright `HudLines` box + four corner resize handles (mirroring `_submit_screen_selection` for widgets, file: `editor/panels/viewport.py:2302-2346`)
- Anchor layers (zero-area `offset`) show a single marker on the anchor POINT instead of handles, like position-only text anchors (file: `editor/panels/viewport.py:2322-2336`)
- A dimmer outline around every layer in the selected widget's subtree (P-3) shows what will move together if the WIDGET is dragged (layers are children of the widget, so they cascade with widget moves)

---

## 2. Architecture Plan

### Viewport changes

**File:** `editor/panels/viewport.py`

1. **Draw insertion point:** Layer draw code goes AFTER `_submit_screen_widget` returns (after all widgets are submitted). Create a new `_submit_screen_layers(widget_id, spec, doc, band, scale, ox, oy, state)` method that:
   - Resolves each layer via `engine.ui_layers.resolve(layer_spec, owner_rect, state)`
   - Emits the appropriate HUD primitive (`HudSprite` for slot, `HudText` for text, `HudRect` for color)
   - Handles precedence per S2 handoff: slot wins, then text_id/label, then color; if none, skip

2. **Band submission:** In the main screen-submit loop, call `_submit_screen_layers(..., "under", ...)` near the TOP (before widgets), then `_submit_screen_layers(..., "over", ...)` as the LAST statement before flushing

3. **Hit-testing:** Extend `_hit_widget` or create `_hit_layer` to test layers after widgets:
   - Order layers topmost-first (highest `z` last, reverse submission order)
   - Filter by visibility and hidden-subtree (P-5)
   - Apply smallest-candidate rule
   - Return a `(widget_id, layer_id)` pair when a layer is hit, or fall through to widget hit-testing

4. **Drag/resize:** Extend `_begin_drag`, `_screen_move`, `_screen_release`:
   - Detect whether the selected object is a layer (the selection is now `(widget_id, None)` for widgets or `(widget_id, layer_id)` for layers)
   - LIVE-mutate `doc["widgets"][widget_id]["layers"][layer_index]["offset"]` during move/resize
   - On release, call `session.push_layer_field(widget_id, layer_id, "offset", old, new)` with the old/new offset values

5. **Selection outline:** Extend `_submit_screen_selection`:
   - When the selected object is a layer, outline the layer's interaction rect instead of a widget rect
   - Draw handles or anchor marker per the interaction rect type (zero-area or not)
   - Show the layer's id (or layer index) in the caption above the outline

### _screen_primitives.py changes

**File:** `editor/panels/_screen_primitives.py`

1. **New pure function `layer_interaction_rect`** (signature mirrors `interaction_rect`):
   - Input: `(layer_offset, layer_text, layer_font_key, layer_align, owner_rect)`
   - Apply the same zero-extent-axis growth as `interaction_rect`, but using the layer's resolved text content
   - Return: `(x, y, w, h)` in the layer's own coordinate space (not screen space — caller applies `_to_screen_rect`)

### State handling

- When `self._screen_state` changes (via the existing state combo), re-render layers with the new state value passed to `resolve()`
- The state combo already exists and is populated from `registry.category("ui").animations` — layers use the same state vocabulary (`idle`/`hover`/`pressed`/`disabled`)

---

## 3. File scope and shared-file contract

### Files touched by UL-7

- **Modified:** `editor/panels/viewport.py` — layer draw path (after widget draw), layer hit-testing (after widget hit), layer drag/resize (parallel to widget drag/resize), layer selection outline
- **Modified:** `editor/panels/_screen_primitives.py` — new `layer_interaction_rect` pure function
- **Extended:** `tools/tests/test_ui_layer_ops.py` — new test class `TestLayerViewportGeometry` (new class, do not edit UL-6's `TestLayerOps` class)

### Shared-file reconciliation

**UL-6** (landing first) adds layer outliner nodes to `screen_details.py` and layer undo commands to `ui_screen_session.py`.

**UL-8** (parallel to UL-7, codes after UL-7 lands) extends `screen_details.py` with the per-state inspector and `viewport.py` with state-selected layer visual feedback. UL-8 will also extend the existing state combo (or create a new one) to show layer-specific state previews.

**No conflict:** UL-7 and UL-8 both touch `viewport.py`, but in different parts:
- **UL-7** adds: layer draw logic (new `_submit_screen_layers` method), layer hit-test logic (new `_hit_layer` method or extension to `_hit_widget`), layer drag/resize logic (extension to `_begin_drag`, `_screen_move`, `_screen_release`), layer selection outline (extension to `_submit_screen_selection`)
- **UL-8** adds: state-selected layer visual feedback (inside the layer-draw or selection-outline path, conditional on the selected layer matching the current state), possibly a new dedicated state combo or extension to the existing one

**Insertion points in `viewport.py`:**
- Layer draw: after `_submit_screen_widget` finishes (near line 2300), call `_submit_screen_layers` for each band
- Layer hit-test: inside `_hit_widget`, after testing widgets, check if a layer under the same widget was hit (reorder logic so widgets hit-test first, then layers, then return the smallest overall)
- Layer drag/resize: inside `_screen_press`, check if a layer was hit; inside `_screen_move`, update layer offset; inside `_screen_release`, commit the layer-field push
- Layer selection: inside `_submit_screen_selection`, check if the selected object is a layer and outline/handle it accordingly

**No edit to `screen_details.py` or `data/ui/screen_previews.json`:** UL-6 owns the layer list/controls, UL-8 owns the state inspector. The preview stays override-free by design (layers composite on top at runtime, never baked in).

---

## 4. Exit gate and Quick Test

### Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_ops.py -q
```

### Test cases (append to `TestLayerViewportGeometry` class in `test_ui_layer_ops.py`)

- A layer's resolved screen rect (via `_to_screen_rect(_layer_interaction_rect(...))`) equals the value `engine.ui_layers.resolve` returns for the same owner rect and state
- A layer with zero width/height has its interaction rect grown to text measurement (or minimum) at the layer's resolved font/align
- Hit-testing picks the topmost (highest `z`) layer under the same widget before falling through to other widgets or widgets' layers
- Layer drag LIVE-mutates the offset field; release commits one `push_layer_field` call
- Layer resize adjusts w/h while anchoring the opposite corner (same logic as widget resize)
- Visibility: a layer with `visible=false` (post-state) does not draw and is not hit-testable

### Quick Test (in editor + game)

1. **Editor:** `py editor/main.py` → select a screen with a layer (or add one via UL-6) → click the layer in the viewport → drag it to a new position → observe the outline and handles move with the layer; release and undo with Ctrl+Z
2. **Save:** Save the screen doc (Ctrl+S)
3. **Game:** `py game/main.py` → navigate to the same screen → confirm the layer sits **exactly** where the editor showed it (same screen pixel, accounting for the identity/scaled render pipeline per UR-3)

**Coordinator note for UL-8:** When you plan the state selector, verify whether the existing floating state combo (currently driving widget-state animation) can drive both widget AND layer state simultaneously, or whether a separate combo is needed. The brief assumes you will extend the existing one, but if the interaction is complex, a separate layer-state combo may be cleaner. Document your recommendation in your brief and leave a hook in the viewport's state-selection code for UL-8 to splice in.

---

## Risks and dependencies

- **TBD-pending-UL-6:** The exact signature and behavior of `session.push_layer_field(widget_id, layer_id, "offset", old, new)` — verify this exists and matches the `_DocFieldCommand` pattern once UL-6 lands. If the name or signature differs, this brief's "drag/resize writes through" section will need revision.
- **Layer text measurement:** A layer's `text_id` or `label` may not be resolvable in the editor (the text is dynamic at runtime). The interaction rect will fall back to minimum size if text is empty or missing. This is acceptable (matches anchor widgets).
- **State combo coordination:** UL-8 must coordinate on whether to extend the existing state combo or create a new one. The brief leaves this as "TBD-during-UL-8-planning"; I recommend starting with the assumption that the existing combo suffices (it is already data-driven and state-driven), and only fork it if tests reveal a conflict.
