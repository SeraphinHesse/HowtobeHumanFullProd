# Phase UL-9 — The pure hit resolver and the action contract

Plan: `planning/UiLayeredWidgetsPLAN.md` §3 Section S4, `#### Phase UL-9`
(`planning/UiLayeredWidgetsPLAN.md:517-535`). Depends on S2 (landed,
`docs/handoffs/section-S2.md`). Branch `ul-section-S4`.

## 1. Behavioral spec

- **Goal (plan):** "Decide, purely, which layer a click lands on and what it
  means. Nothing routes it yet." (`planning/UiLayeredWidgetsPLAN.md:519-520`).
  This phase adds ONLY: (a) two new optional keys on a layer entry in the
  schema, and (b) one new pure function in `engine/ui_layers.py`. No screen,
  no `game/main.py`, no editor panel changes here — that is UL-10
  (`planning/UiLayeredWidgetsPLAN.md:537-563`).
- **D3 — pure resolver lives in `engine/`, pygame-free**
  (`planning/UiLayeredWidgetsPLAN.md:65-70`). `hit()` joins `resolve()` /
  `ordered()` / `validate_offsets()` in `engine/ui_layers.py:1-16` (module
  docstring, `__all__`), which is already covered by `TestPurity`
  (`tools/tests/test_ui_layers.py:1-9`, citing `tools/tests/test_render.py:739`)
  — no separate purity test needed here, the subprocess-import list already
  covers the whole module.
- **D8 — the resolver is PURE, callable twice with identical inputs for an
  identical result, no mutation** (`planning/UiLayeredWidgetsPLAN.md:114-119`).
  `main.py` calls `Hud.hit()` twice per click (arm-on-DOWN, fire-on-UP); UL-10
  builds that caller, but UL-9's `hit()` is the primitive that guarantee rests
  on, so it must not touch `layers`, `state`, or any argument — it only reads
  and returns.
- **D7, AS AMENDED — reserved tokens `close_window` / `back` / `noop`;
  `target` is NOT a closed enum** (`planning/UiLayeredWidgetsPLAN.md:94-113`,
  amendment at :103-113). Original ruling (closed enum, fails validation) is
  superseded — do not implement the pre-amendment version even though the
  Files bullet under UL-9 in the plan body still says "not a closed enum"
  correctly (`planning/UiLayeredWidgetsPLAN.md:527-531`) but an EARLIER draft
  of this same section (`planning/UiLayeredWidgetsPLAN.md:94-96` header line)
  still reads "names one of three RESERVED action tokens" as if closed —
  read the Amendment paragraph as authoritative over the header phrasing.
  Routability (does `target` resolve to a widget id present in this screen,
  or one of the three tokens) is an EDITOR warning — UL-10/inspector
  territory, not built here. UL-9's job is only to make the schema
  permissive: `target` is `type: string, pattern: "^[a-z][a-z0-9_]*$"`, no
  `enum`.
- **Section S4 Publishes** confirms the exact contract UL-10 will consume:
  "`clickable` + `target` on a layer entry, where `target` is a widget id in
  the same screen or one of the three reserved tokens... an id-shaped string
  matching neither WARNS in the editor and still saves" and
  "`engine.ui_layers.hit(...)` — pure, topmost-first (D8)"
  (`planning/UiLayeredWidgetsPLAN.md:471-479`).
- **Existing layer-entry schema** to extend, not replace:
  `data/schemas/ui_screen.schema.json`'s `widgets.<id>.layers[i]` object,
  currently `additionalProperties: false` with keys `id, offset, z, band,
  slot, text_id, label, font, align, color, states, text_color, tint,
  visible` (verified by reading the file directly — this object appears once
  in the schema, nested under `properties.widgets.patternProperties.
  ^[a-z][a-z0-9_]*$.properties.layers.items`). Confirmed against
  `docs/handoffs/section-S2.md`'s "Layer entry" bullet, which lists the same
  key set.
- **`ordered()` / `resolve()` conventions to match** (`engine/ui_layers.py`):
  `ordered(layers, band)` filters+sorts a band's raw layer dicts (not yet
  resolved) and already implements the dangling/duplicate-`id` degrade
  (first occurrence wins, non-empty ids only) — `hit()` should reuse
  `ordered()` for band selection/ordering rather than re-implementing it, to
  stay in sync with paint order (the same function that decides what draws
  on top must decide what is hit first). `resolve(layer_spec, owner_rect,
  state)` turns one raw layer dict into `{"rect": (x,y,w,h), ...}` — `hit()`
  needs the resolved `rect` (for point-in-rect) and needs to read `clickable`
  / `target` off the RAW layer dict (they are not appearance keys, so
  `resolve()` deliberately will not carry them into its output — do not add
  them to `resolve()`'s `_APPEARANCE_KEYS` or output dict).
- **D5 — golden parity.** No existing screen doc author `clickable`, so no
  runtime behavior changes and no generated artifact moves
  (`planning/UiLayeredWidgetsPLAN.md:80-83`). `data/ui/screen_previews.json`,
  `data/ui/screen_defaults.json`, `tools/tests/test_ui_skinning.py` must stay
  byte-identical — verify with `git diff --stat` against `ul-section-S4`'s
  merge base before handoff, same check S2's handoff ran.

## 2. Architecture plan

### 2a. `engine/ui_layers.py` — add `hit()`

Add to `__all__`: `"hit"`. New function, placed after `validate_offsets`
(bottom of file) so the read order stays geometry-first / hit-testing-last:

```python
def hit(layers, owner_rect, mx, my, state="idle"):
    """Which layer (if any) a point lands on, topmost-first. Pure (D8): never
    mutates `layers`, callable any number of times with the same arguments
    for the same result.

    layers: the widget's raw "layers" array (schema:
        data/schemas/ui_screen.schema.json), unresolved -- same shape
        `ordered()`/`resolve()` take.
    owner_rect: (x, y, w, h) -- the owning widget's post-override rect, same
        convention as `resolve()`.
    mx, my: the point to test, in the same coordinate space as owner_rect.
    state: which of the four D9 states the OWNING widget is in (default
        "idle") -- passed through to `resolve()` so a state-patched offset
        moves the hit rect exactly the way it moves the paint rect; a layer
        that is invisible in `state` (resolved "visible" is False) is never
        hit.

    Search order (topmost paints last, so topmost hits first):
        1. "over" band, z-descending (reverse of paint order within the band)
        2. the owner itself (owner_rect, mx, my)
        3. "under" band, z-descending

    Only entries with "clickable": true (default False when absent -- an
    ordinary decorative layer is never a click target) are eligible; a
    non-clickable layer is TRANSPARENT to the click -- the point is tested
    against layers/owner/layers beneath it as if the non-clickable one were
    not there, never blocking or absorbing the click itself.

    Returns:
        {"kind": "layer", "id": str|None, "target": str|None} for a hit
            clickable layer (its raw "id" if authored, else None; "target"
            its raw "target" value if authored, else None -- an unroutable
            or missing target is NOT resolved or validated here, D7 as
            amended: routing/warning is a caller's job, UL-10);
        {"kind": "owner"} for a hit on the owner rect itself, when no
            clickable layer above or at the owner claimed the point;
        None if (mx, my) is outside every clickable layer's rect AND
            outside owner_rect.

    Note: the owner itself is not gated by any "clickable" flag -- it has no
    such key; a caller (UL-10) decides what an "owner" hit means for its own
    widget kind (e.g. a Button always hittable, a bare label never wired to
    call `hit()` at all).
    """
    for band in ("over", None, "under"):
        if band is None:
            if owner_rect[0] <= mx < owner_rect[0] + owner_rect[2] and \
               owner_rect[1] <= my < owner_rect[1] + owner_rect[3]:
                return {"kind": "owner"}
            continue
        band_layers = ordered(layers, band)
        for entry in reversed(band_layers):
            if not entry.get("clickable", False):
                continue
            resolved = resolve(entry, owner_rect, state)
            if not resolved["visible"]:
                continue
            x, y, w, h = resolved["rect"]
            if x <= mx < x + w and y <= my < y + h:
                return {
                    "kind": "layer",
                    "id": entry.get("id"),
                    "target": entry.get("target"),
                }
    return None
```

(Pseudocode above is a strong steer, not verbatim-mandatory — the coder may
adjust variable names/structure, but must preserve: topmost-first within
`over`, then owner, then `under`; `clickable` gates layer eligibility with
`False` default; non-clickable layers pass through transparently rather than
blocking; `visible` (per resolved state) also gates; purity — no argument or
module-level state is mutated; reuse of `ordered()`/`resolve()` rather than
re-deriving band filtering or offset math.)

### 2b. `data/schemas/ui_screen.schema.json` — layer entry keys

In the ONE layer-entry object (`properties.widgets.patternProperties.
^[a-z][a-z0-9_]*$.properties.layers.items`, currently listing `id, offset, z,
band, slot, text_id, label, font, align, color, states, text_color, tint,
visible` as siblings under `properties` with `additionalProperties: false`),
add two sibling keys:

```json
"clickable": {
  "type": "boolean"
},
"target": {
  "type": "string",
  "pattern": "^[a-z][a-z0-9_]*$"
}
```

No `enum` on `target` — this is the load-bearing part of the amendment.
Do NOT add these keys anywhere else (not to the per-widget object's own
`states` patches, not to the layer-level `states.<state>` patch sub-objects —
clickability and target are static per-layer, not per-state; D9's four states
govern appearance only).

## 3. File scope + shared-file contract

**Modified (UL-9 only):**
- `data/schemas/ui_screen.schema.json` — add `clickable`+`target` to the one
  layer-entry object, per §2b above. This is the ONLY schema edit in this
  phase.
- `engine/ui_layers.py` — add `hit()` per §2a, and `"hit"` to `__all__`.
- `tools/tests/test_ui_layers.py` — new tests, see §4 below.

**Explicit ownership boundary (read this before touching anything):**
UL-9 lands on `ul-section-S4` FIRST, ALONE, and must be committed/merged
before UL-10 or UL-11 start. UL-10's coder consumes `hit()` by IMPORTING it
(`from engine.ui_layers import hit`) and MUST NOT edit `engine/ui_layers.py`
or `data/schemas/ui_screen.schema.json` — those two files are UL-9's alone
for this section. UL-10 adds the Clickable checkbox + target picker to
`editor/panels/screen_details.py` and wires `game/ui/skinning.py`'s
`hit_layer()` / each screen's hit path / `game/main.py`'s reserved-token
routing (`planning/UiLayeredWidgetsPLAN.md:537-563`) — none of which this
phase touches. If UL-9 is not yet merged to `ul-section-S4` when UL-10 is
dispatched, UL-10 must block, not improvise its own copy of `hit()`.

**Do not touch:** `data/ui/screens/*.json`, `data/ui/screen_defaults.json`,
`data/ui/screen_previews.json`, `game/**`, `editor/**` — none of these carry
any `clickable`/`target` authoring in this phase (D5 golden parity).

## 4. Exit gate + Quick Test

**Exit gate (run in this order):**
```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layers.py -q
```

**New tests to add to `tools/tests/test_ui_layers.py`** (new `TestHit` class,
following the file's existing `unittest.TestCase` + plain-dict-literal
style seen in `TestResolve`):
- **Topmost wins**: two overlapping `clickable: true` layers in the same
  band with different `z`; `hit()` at the overlap point returns the
  higher-`z` one's `id`/`target`.
- **Non-clickable layer is transparent**: a `clickable`-absent (or `false`)
  layer covering the owner rect; `hit()` at a point inside it but also
  inside the owner rect returns `{"kind": "owner"}`, not a layer hit — the
  non-clickable layer must not block the point from reaching what's beneath.
- **Out-of-bounds click returns `None`**: a point outside both every
  clickable layer's resolved rect and `owner_rect`.
- **Purity (D8)**: build one `layers` list + `owner_rect`, call `hit()` twice
  with IDENTICAL arguments, assert both calls return equal results (`==` on
  the returned dict/`None`) AND assert the `layers` list argument (and each
  entry dict) is unchanged after both calls (e.g. compare a `copy.deepcopy`
  taken before the calls against the list after) — this is the guarantee
  UL-10's "`Hud.hit()` called twice returns the same answer and mutates
  nothing" test
  (`planning/UiLayeredWidgetsPLAN.md:559`) depends on; get it right here so
  UL-10 doesn't discover it broken downstream.
- Also worth one case: a clickable "over" layer takes precedence over an
  owner hit at the same point (band-order test, complements "topmost wins"
  which is within-band).

**Quick Test:** none (plan: "this phase is pure and routes nothing"). Confirm
`py game/main.py` boots and every screen's clicks behave exactly as before —
no `clickable`/`target` is authored in any `data/ui/screens/*.json` yet, so
this is a smoke check, not a scenario: launch the game, click through the
main menu into a level, place a building, end a turn. Nothing should look or
behave different from before this phase.
