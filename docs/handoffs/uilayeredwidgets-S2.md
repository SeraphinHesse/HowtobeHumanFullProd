# Section S2 handoff

**Landed** — branch `ul-section-S2` @ `f9cc28d`
- `UL-3` | `ul-phase-UL-3-layer-schema` | `docs/briefs/phase-UL-3-layer-schema.md` | review: clean
- `UL-4` | `ul-phase-UL-4-layer-draw` | `docs/briefs/phase-UL-4-layer-draw.md` | review: clean (1 LOW, no fix needed)
- `UL-5` | `ul-phase-UL-5-per-state` | `docs/briefs/phase-UL-5-per-state.md` | review: 2 MED, both fixed round 1
- Final section-diff review: 1 HIGH + 1 MED fixed directly by me (test-domain registration, `game/ui/CLAUDE.md` doc gap); 1 LOW (plan status) also fixed.

**Interface deltas** (code against these blind — S3 wires the editor, S4 extends clickability/life counters):
- `data/schemas/ui_screen.schema.json`, per-widget object gained **`layers`** (array) and **`states`** (object) — full key list now: `color, font, label, layers, parent, rect, skin, states, text_color, text_id, tint, visible`.
- **Layer entry** (`layers[i]`), all keys optional, `additionalProperties: false`: `id`(str), `offset`(int[4] `[dx,dy,w,h]`), `z`(int), `band`(`"under"|"over"`), `slot`(str), `text_id`(str), `label`(str), `font`(str), `align`(`"left"|"center"|"right"`), `color`(int[3-4]), `states`(object), `text_color`(int[3-4]), `tint`(int[3-4]), `visible`(bool).
- **`states` object** (both on the layer entry and the per-widget object): keys `idle`/`hover`/`pressed`/`disabled`, all optional, each a PATCH object.
  - Layer-level patch keys: `align, color, font, label, offset, slot, text_color, text_id, tint, visible` (same as a layer entry minus `id`/`z`/`band`/`states`). `offset`: int array, `minItems:4, maxItems:4`.
  - Widget-level patch keys: `color, font, label, offset, text_color, tint`. `offset`: int array, `minItems:2, maxItems:4` (a `[dx,dy]` 2-length form nudges without resizing; 4-length replaces the base offset entirely).
  - Fallback rule: `states[state]` if that key is PRESENT (an explicit `{}` counts, does not fall through), else `states["idle"]` if present, else no patch — presence drives fallback, not truthiness.
- `engine/ui_layers.py`: `resolve(layer_spec: dict, owner_rect: tuple, state: str = "idle") -> dict` → `{"rect": (x,y,w,h), "slot", "text_id", "label", "font", "align", "color", "text_color", "tint", "visible"}` (each `None`/`True` default when absent); D2 offset math (`0` w/h inherits owner's) + state-patch merge applied. `ordered(layers: list[dict], band: str) -> list[dict]` — filters by `band` (missing defaults to `"over"`), sorts stably by `z` (missing `0`), drops all-but-first of a duplicate non-empty `id`. `validate_offsets(layers: list[dict]) -> list[dict]` — malformed `offset` degrades to `(0,0,0,0)` in a copy, never raises. Pygame-free (`TestPurity` in `tools/tests/test_render.py:739`).
- `game/ui/skinning.py::ScreenSkinning` gained two INSTANCE METHODS (not module functions): `state_of(self, widget) -> str` (a `Button` answers via its own `_state()`; anything else → `"idle"` always) and `submit_layers(self, renderer, screen_id: str, ids: Dict[str, tuple], band: str, state_of) -> None` (`state_of` param is a callable `widget -> str`, normally pass `self.skinning.state_of` by reference). Primitive precedence, first match wins: `slot`→`HudSprite`, `text_id`/`label`→`HudText` (via `strings.T`, empty string draws nothing), `color`→`HudRect`, else skip; `visible is False` skips.
- `game/ui/widgets.py`: `Button.submit` and `submit_label` both apply a per-state patch as a DRAW-TIME-ONLY nudge/recolor — `self.rect`/holder's stored position is NEVER mutated. An explicit call-site `text_color=`/`color=` kwarg always wins over the patch.
- All 14 screens' `submit()` (`tools/export_ui_layouts.py`'s `SCREEN_IDS`) call `submit_layers(..., "under", ...)` near the top and `submit_layers(..., "over", ...)` as the last statement — `building_ui.py` has THREE classes each with their own pair (`ConstructPreview`, `MovePreview`, `BuildingUI`).

**Open findings**:
- (owner: next section, informational) A label/panel/backdrop holder's `states.hover/pressed/disabled` are schema-valid but permanently unreachable — `state_of` only ever resolves such a holder to `"idle"` (no hover/press tracking exists for non-Button widgets). Only `states.idle` does anything on a non-Button today. Deliberate, per UL-5's brief.
- (owner: next section, informational) A `Button`'s `states` patch only wires `text_color`/`offset` — `color`/`tint`/`font`/`label` are schema-valid but inert on a Button today (scope-matched to the brief, not a bug).
- (owner: user/future plan work) `game/ui/CLAUDE.md`'s "an `under` layer sits behind EVERYTHING on that screen" trade-off (D4) is documented but still a real authoring gotcha — a layer between two stacked panels isn't representable with 2 bands.

**Quick Tests** (for the PR body):
- UL-3: `py game/main.py` boots, every screen renders byte-for-byte unchanged (schema + resolver ship unused).
- UL-4: author one `under` layer on `hud.love_text` pointing at an imported `ui` slot in `data/ui/screens/hud.json`; the background sits behind the love number and moves with it when the widget's `rect` override changes.
- UL-5: give `hud.btn_end_turn` a `hover` state with a different `text_color` + 1px offset in `data/ui/screens/hud.json`; the label recolours and nudges on hover, returns on mouse-out.

**Gate**:
- Coder-reported (per amendment, I ran none of the phase-level pytest myself): UL-3 `py tools/smoke.py` OK + `py -m pytest tools/tests/test_ui_layers.py tools/tests/test_render.py -q` → 81 passed, 8 subtests. UL-4 same pattern → 39 passed. UL-5 pytest was DENIED (lock held by UL-4's coder) on first pass; retried clean after fix round → 26 passed, 8 subtests, 0 failed.
- **Measured by me**, post-merge on `ul-section-S2`: `py tools/smoke.py` → OK. `py -m pytest tools/tests/test_ui_layers.py tools/tests/test_render.py tools/tests/test_ui_layer_draw.py tools/tests/test_ui_skinning.py tools/tests/test_hud_panel.py -q` → **146 passed, 16 subtests passed, 0 failed**. `py -m pytest tools/tests/test_test_domains.py -q` (after my DOMAINS fix) → 11 passed.
- **D5 golden parity — verified via git, not pytest**: `git diff --stat plan-uilayeredwidgets-umbrella ul-section-S2 -- data/ui/screen_previews.json data/ui/screen_defaults.json tools/tests/test_ui_skinning.py` → empty output. **Byte-identical, confirmed.**
