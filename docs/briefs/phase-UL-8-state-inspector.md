# Phase UL-8 — State selector and layer inspector

**Behavioral spec**

A designer selects a layer in the outliner (UL-6's work) and sees a form showing the layer's slot, offset, z-order, band, and appearance (tint, color, text, visibility) for the currently selected state (idle/hover/pressed/disabled). Clicking a field immediately writes through the undo stack; clicking the ↺ reset button for that field clears just that override, leaving others intact. Switching the state selector combo (viewport.py's existing `_state_combo`, already populated from `registry.category("ui").animations`) shows the per-state values for the new state without losing the underlying data.

**Schema contract** (from S2 handoff — do not re-derive):
- `states` object keys: `idle`/`hover`/`pressed`/`disabled`, all optional
- Layer-level patch keys (within each state): `align, color, font, label, offset, slot, text_color, text_id, tint, visible`
- Widget-level patch keys: `color, font, label, offset, text_color, tint`
- Fallback rule: `states[state]` if present (even if `{}`), else `states["idle"]` if present, else no patch — **presence drives fallback, not truthiness** (file:docs/handoffs/section-S2.md:15)

**UI contract from viewport**:
- State combo (`_state_combo` in viewport.py, lines 309–312) is already created and hidden by viewport's init; UL-8 must ensure it is shown and wired to update the inspector form when a layer is selected or the state changes. UL-7 (running in parallel, owning most of viewport.py's layer-drawing code) likely already wires state combo to layer rendering — **verify this via UL-7's brief when it lands**; if not, UL-8 will add the layer-rendering side to viewport's render path.

**Two carry-over rulings from S2 (explicit per UL-8 as executor):**

1. **Non-Button holders with unreachable per-state appearance:**
   - `state_of(widget)` resolves a Button's state via its `_state()` method; non-Button widgets (label, panel, backdrop holders) **always resolve to `"idle"`** (file:engine/ui_layers.py:resolve, file:game/ui/skinning.py:state_of).
   - **Ruling:** The per-state inspector will **HIDE or GREY OUT the hover/pressed/disabled state tabs when editing a non-Button layer or widget**, with a tooltip: *"Hover, Pressed, and Disabled states are only available for Button widgets; this holder always appears in the Idle state."* This prevents the designer from editing unreachable state values (ED-30: "invalid input unrepresentable"). The global state selector combo still shows all four states for consistency, but the inspector fields remain locked to idle.

2. **Button's inert per-state fields:**
   - A Button's `states` patch only wires `text_color`/`offset` today; `color`, `tint`, `font`, `label` are schema-valid but do not affect rendering on a Button (file:game/ui/widgets.py:Button.submit, file:game/ui/skinning.py:submit_layers).
   - **Ruling:** The per-state inspector will **HIDE the fields for `color`, `tint`, `font`, `label` when editing a Button's per-state patch**, with a note: *"These fields are not yet wired for per-state Button appearance."* If a future phase wires them (e.g., a rework to support per-state tint on Button), those fields can be unhidden.

**D4 — Band tooltip (write this plainly in the band field/control):**
- "**Under** layers sit behind EVERYTHING on this screen, not just behind their owner widget. Use **Over** for backgrounds between stacked panels." (This is the consequence of D4 and must be discovered in the editor, not in a bug report; file:planning/UiLayeredWidgetsPLAN.md:78–79.)

---

## Architecture plan

**Form layout and state selector wiring:**
- State selector (`_state_combo` in viewport.py, existing) is shown when a layer is selected in screen_details.py's layer inspector section.
- When the combo's text changes, viewport calls `set_screen_state` (existing), and screen_details.py listens to the same combo-changed signal to **refresh the per-state inspector fields** (re-populate their display values from the layer's `states[new_state]` patch, falling back to `idle` per the S2 contract).
- All inspector fields follow the existing pattern in screen_details.py (file:editor/panels/screen_details.py:446–464): `_field_row(controls, field_label, slot)` creates a row with the control(s) + a ↺ reset button. Each edit is an immediate undo-able push through `UIScreenSession`.

**Per-state field edits:**
- Editing an `idle` field writes to `layers[i]` (the base layer entry).
- Editing a `hover`/`pressed`/`disabled` field writes to `layers[i].states[state]` and leaves other states untouched (file:docs/handoffs/section-S2.md:15: presence drives fallback).
- Resetting a per-state field clears just that key from `states[state]`, leaving the rest of that state's patch intact (same `None = absent` contract as every other push_field).

**Viewport layer rendering:**
- UL-7 owns most of viewport.py's layer-drawing code (including the layer interaction rect from _screen_primitives.py); UL-8 coordinates on where the state selector's value (`self._screen_state`) flows into that rendering.
- **Assumption:** UL-7 already passes `self._screen_state` to `engine.ui_layers.resolve(...)` when drawing layers, and `resolve` applies the per-state patch correctly (file:engine/ui_layers.py:resolve).
- **If assumption breaks:** UL-8 will add the state flow to viewport's layer-draw path (the existing render_frame loop that calls `engine.ui_layers.ordered(...)` and draws each layer).

**Non-Button/Button field visibility:**
- When a non-Button layer is selected, fields for `hover`/`pressed`/`disabled` states are greyed out (QPushButton.setEnabled(False), QComboBox.setEnabled(False)) with the tooltip above.
- When a Button layer is selected, the `color`, `tint`, `font`, `label` fields are hidden (no widget, no space in the form) for each state tab.
- The layer's current `visible` override is always shown and editable (it works for all widget types).

---

## File scope and shared-file contracts

**UL-8 owns these files:**
- Modified: `editor/panels/screen_details.py` — add the state selector combo (or verify it's already visible) and the per-state inspector section below the base layer fields (slot, offset, z, band, tint, color, text, visibility). Add the D4 band tooltip.
- Modified: `editor/panels/viewport.py` — if UL-7 doesn't wire state-driven layer rendering, UL-8 adds it (pass `self._screen_state` to `engine.ui_layers` calls in the layer-draw path).
- Modified: `tools/tests/test_ui_layer_ops.py` — add a new test class `TestLayerStateInspector` (do NOT edit `TestLayerOps` or `TestLayerViewportGeometry`, which UL-6 and UL-7 own respectively).

**Shared-file contracts:**
- **`editor/panels/screen_details.py` insertion point (UL-6 lands first):** UL-6 adds layer add/remove/reorder controls in its own form section. UL-8's state selector and per-state fields should be inserted **below UL-6's layer-ops controls**, as a second subsection of the per-layer inspector. Ask the UL-6 brief (when it lands, ~same time as this brief) where exactly UL-6's controls sit in the form layout; if the brief doesn't exist yet, state your own assumption and flag it for reconciliation with UL-6's coder.
- **`editor/panels/viewport.py` layer rendering (UL-7 lands next):** UL-7 owns the viewport layer-draw loop that calls `engine.ui_layers`. UL-8 expects `self._screen_state` to already be passed through to layer resolution by UL-7's code. Verify this in UL-7's brief; if it hasn't landed yet, coordinate via brief comments on what UL-7 is expected to have wired vs. what UL-8 will add.
- **`tools/tests/test_ui_layer_ops.py` (UL-6 owns `TestLayerOps`, UL-7 owns `TestLayerViewportGeometry`):** UL-8 adds a **new class `TestLayerStateInspector`** at the end of the file (append only, never edit existing classes). Tests: editing a layer's `hover.offset` writes under `states.hover.offset` without touching `idle.offset`; resetting a per-state field removes just that key; non-Button layers can be selected but their non-idle state fields are disabled/greyed.

---

## Exit gate and Quick Test

**Exit gate:**
```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_ops.py -q
```

**Quick Test (in editor):**
1. Open screen mode, select the `hud` screen, select a layer in the outliner.
2. In the state selector combo (top-left of viewport), select "Pressed".
3. Move the layer in the viewport.
4. In the state selector, switch back to "Idle".
5. Confirm the idle position did NOT move (the pressed offset is separate from idle).

(The undo/reset buttons are tested by the pytest suite; the viewport layer selection is tested by UL-7's geometry tests.)
