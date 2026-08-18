# Section S3 handoff

**Landed** — branch `ul-section-S3` @ `96f546a`
- UL-6 | `ul-phase-UL-6-layer-ops` | `docs/briefs/phase-UL-6-layer-ops.md` | review: clean (1 LOW)
- UL-7 | `ul-phase-UL-7-layer-viewport` | `docs/briefs/phase-UL-7-layer-viewport.md` | review: clean (2 LOW)
- UL-8 | `ul-phase-UL-8-state-inspector` | `docs/briefs/phase-UL-8-state-inspector.md` | review: 1 HIGH fixed round 1, fix verified clean
- Final section-diff review: clean (1 LOW, informational).

**Interface deltas** (code against these blind):
- `editor/ui_screen_session.py`: `layers(widget_id) -> list[dict]` (deep copy); `add_layer(widget_id, layer_id, layer_spec)`; `remove_layer(widget_id, layer_id)`; `set_layer_field(widget_id, layer_id, field_key, old_value, new_value, text=None)` — the ONE write path for every layer field incl. per-state (`field_key="states"`, value = whole rebuilt object); `reorder_layer(widget_id, layer_id, new_z)`. Internally each op pushes ONE `_DocFieldCommand` with the FULL old/new `layers` array (`layers` is a JSON array, `_set_at`/`_apply_field` only walk dicts) — an emptied array prunes to `None`, not `[]`.
- `WidgetTreeWidget` UserRole payload: layer nodes carry `(widget_id, layer_id)` **tuple**; widget nodes keep bare `widget_id` **string**. `isinstance(role, tuple)` is the discriminator everywhere (selection, drag, drop, undo-refresh).
- `editor/panels/viewport.py`: new `layer_selected(widget_id, layer_id)` Signal, emitted but **UNCONSUMED** — no `.connect()` anywhere (S4/future work). `_hit_layer` picks smallest-candidate within tier (selected widget's layers → other widgets' layers → widgets), ties go to highest `z`. Geometry only via `engine.ui_layers.resolve/ordered` (D3).
- `editor/panels/_screen_primitives.py`: new `layer_interaction_rect(resolved_rect, *, text, font_key, align)` — takes the ALREADY-RESOLVED rect, never re-derives owner+offset.
- `editor/panels/screen_details.py`: new `layer_state_combo` (idle/hover/pressed/disabled) is the panel's OWN combo — **not** wired to `viewport.py`'s floating preview-state dropdown (that link needs `main.py`, out of scope). It sets which state's rows you're editing; the viewport combo sets what the preview draws.
- No schema changes this section (layer/`states` shape is S2's, unchanged).

**Decisions**:
- **Inert-control ruling (UL-8), final**: non-Button holders grey Hover/Pressed/Disabled, pinned to Idle, tooltipped. On a LAYER (not a widget), `color`/`tint`/`font`/`label` per-state keys are **NOT hidden** — `engine.ui_layers.resolve` merges all of them for a layer, unlike the widget-level path S2 flagged as inert. What's actually gated is **precedence**: `_submit_one_layer` draws exactly one primitive (`slot`→`text`→`color`, first match wins), so Tint is live only with a slot; Text stays editable even bare (typing is how you create the text branch) but TextColor requires slot-absent+text-present; Color requires slot-absent+text-absent. This full chain was a HIGH review finding (only Color was gated initially) and is now fixed and tested.
- D4 band tooltip, exact text, on both band controls: *"Under layers sit behind EVERYTHING on this screen, not just behind their owner widget. Use Over for backgrounds between stacked panels."*
- `z`/`band` are never state-patch keys — those two rows always write the base layer entry regardless of the selected state.

**Open findings**:
- (owner: S4 or a small follow-up) `viewport.layer_selected` signal is a live, unconsumed hook — wiring it in `main.py` would let a viewport click drive the inspector directly; today only the outliner selects a layer for inspection.
- (owner: S4) `layer_state_combo` (inspector) and the viewport's preview-state dropdown are two independent controls; linking them is future `main.py` work, not this section's scope.
- (owner: informational, from S2, still true) `under`-band layers sit behind the WHOLE screen, not just their owner — documented in the D4 tooltip and `game/ui/CLAUDE.md`, a real authoring limit with only 2 bands.

**Quick Tests** (for the PR body):
- UL-6: `py editor/main.py` → screen mode → `hud` → select Love counter → Add layer → pick a `ui` slot → save → confirm `data/ui/screens/hud.json` gained a `layers` entry and Ctrl+Z removes it.
- UL-7: drag a layer into place in the editor, save, then `py game/main.py` and confirm it sits exactly where the editor showed it.
- UL-8: switch the state selector to Pressed, move a layer, switch back to Idle, confirm the idle position did not move.

**Gate** (coder-reported, roll-up):
- UL-6: `py tools/smoke.py` → OK; `py -m pytest tools/tests/test_ui_layer_ops.py -q` → 25 passed, 0 failed.
- UL-7: `py tools/smoke.py` → OK; `py -m pytest tools/tests/test_ui_layer_ops.py -q` → 38 passed (25+13), 0 failed.
- UL-8: `py tools/smoke.py` → OK; `py -m pytest tools/tests/test_ui_layer_ops.py -q` → 44 passed after fix round (39 before), 0 failed. One `test_guard` deny mid-run (UL-7's concurrent run in flight) — queue, not refusal, retried clean after lock cleared.
- **D5 golden parity — measured by me**, post-merge on `ul-section-S3`: `git diff --stat plan-uilayeredwidgets-umbrella..ul-section-S3 -- data/ui/screen_previews.json data/ui/screen_defaults.json tools/tests/test_ui_skinning.py` → empty output. Byte-identical, confirmed.
- No file in the section diff touches `data/`; no `game/` import anywhere in `editor/` (grep verified by section-diff reviewer).
