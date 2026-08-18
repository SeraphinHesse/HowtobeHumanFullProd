# Phase UL-5 — Per-state appearance

Section S2 of `planning/UiLayeredWidgetsPLAN.md`. Runs AFTER UL-3 (layer
resolve + `layers` schema key) and UL-4 (`submit_layers` / `state_of` stub)
have both landed and merged into `ul-section-S2`. This brief specifies a
CONTRACT for code that does not exist yet at brief-writing time — every claim
about UL-3/UL-4 shapes below is the contract those phases publish, not a
citation of code read after the fact. The one piece of code that *does* exist
today and is cited directly is `game/ui/widgets.py`'s `Button`.

## 1. Behavioral spec

**D9 — reuse the existing four-state vocabulary, no new states.** The
vocabulary is `"idle" | "hover" | "pressed" | "disabled"`, with fallback to
`"idle"` whenever a lookup key is absent. This is not a new concept invented
by this phase — it is `Button._state()`
(`game/ui/widgets.py:564-574`, verified this session), which returns exactly
these four strings in this priority order:

```
flash > 0                          -> "pressed"
not self.enabled                   -> "disabled"
self.pressed (hovered+mouse_down)  -> "pressed"
self.hovered                       -> "hover"
else                                -> "idle"
```

(`self.pressed` is the `@property` at `widgets.py:544-548`: `hovered and
mouse_down`, never true while disabled since `hovered` is itself gated on
`enabled`.)

This priority is why the game's flat (unskinned) fill logic in
`Button.submit` (`widgets.py:576-586`) and the skinned sprite row picked via
`animation=self._state()` (`widgets.py:595-598`) never disagree about what
state a button is in — this phase's per-state appearance patch must resolve
through the SAME `_state()` call, not a re-derived condition, so a third
appearance layer (skin row / flat fill / per-state text-and-offset patch)
cannot disagree with the other two.

**Non-Button widgets have no state.** Panels, labels, and backdrops in this
codebase are plain `SimpleNamespace`-style holders built by the screen's
`build()`/`layout()` step — they carry no `_state()` method, no `hovered`,
no `pressed`, no `enabled` concept. `state_of(widget)` (UL-4's stub, landed
in `game/ui/skinning.py`, currently always returning `"idle"`) is the single
place this is normalized: any widget lacking `_state()` resolves to `"idle"`,
always, forever, on every frame. There is no plan in this phase (or this
plan doc) to add hover/press tracking to non-Button holders.

**Consequence — flag, don't fix:** because a label holder's state is always
`"idle"`, a `states.hover` / `states.pressed` / `states.disabled` patch
authored onto a non-Button widget's override can never be selected by
`state_of()` as written. Only `states.idle` is reachable on a label/panel/
backdrop holder today. This phase implements the fallback rule faithfully
(idle-only reachability is a correct, intentional consequence of D9 applied
to a widget with no state machine) and reports it as an OPEN FINDING for the
section handoff, not a bug fixed in-phase — teaching non-Button holders to
track hover/press is out of scope here.

## 2. Architecture plan

### 2a. Schema — `data/schemas/ui_screen.schema.json`

Two insertion points, both purely additive, both `additionalProperties:
false`, every sub-key optional. Do not touch, reorder, or reformat any other
key in this file.

**Per-widget override object**
(`properties.widgets.patternProperties["^[a-z][a-z0-9_]*$"].properties`).
Current key order at the time this brief is written is `color, font, label,
parent, rect, skin, text_color, text_id, tint, visible`
(read from `data/schemas/ui_screen.schema.json` this session — verify
`layers` sits between `label` and `parent` once UL-3 has actually landed on
this branch; do not reorder it). Insert `states` alphabetically **between
`skin` and `text_color`**:

```json
"states": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "idle":     { "$ref": "#/$defs/widget_state_patch" },
    "hover":    { "$ref": "#/$defs/widget_state_patch" },
    "pressed":  { "$ref": "#/$defs/widget_state_patch" },
    "disabled": { "$ref": "#/$defs/widget_state_patch" }
  }
}
```

with a `$defs/widget_state_patch` (or four inlined identical objects if this
schema has no `$defs` section yet — match whatever UL-3 already established
for its own layer-entry sub-object; do not introduce a new schema idiom) of
shape:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "color":      { "<same constraints as the owner's color>" },
    "text_color": { "<same constraints as the owner's text_color>" },
    "tint":       { "<same constraints as the owner's tint>" },
    "font":       { "type": "string" },
    "label":      { "type": "string" },
    "offset": {
      "type": "array",
      "items": { "type": "integer" },
      "minItems": 2,
      "maxItems": 4
    }
  }
}
```

**`offset` semantics (binding, D2-consistent):** `[dx, dy]` or `[dx, dy, dw,
dh]`, meaning "nudge relative to the owner's OWN base rect for THIS
resolution only" — never a new absolute rect. A 2-length offset nudges
position only (`dw`/`dh` default 0, size unchanged); a 4-length offset also
resizes. This mirrors D2's offset philosophy (relative, not absolute) and is
deliberately NOT a `rect` key, so a state patch can never accidentally
replace the owner's authored size/position wholesale.

**Layer-entry object** (inside the `layers` array item schema UL-3 created).
Read the actual key order on this branch once UL-3 has landed before
inserting — this brief's placeholder order is `align, band, color, id,
label, offset, slot, text_color, tint, visible, z` (alphabetical); insert
`states` alphabetically **between `slot` and `text_color`**, same shape as
above (idle/hover/pressed/disabled, each holding the same per-layer
appearance keys the layer entry itself carries, plus its own `offset` with
the identical 2-or-4-length meaning: nudge from the layer's OWN base
`offset`, not a new absolute one).

### 2b. `engine/ui_layers.py` — `resolve(layer_spec, owner_rect, state)`

`state` currently a no-op parameter (per UL-3/UL-4 contract). This phase
makes it load-bearing:

```
patch = (layer_spec.get("states") or {}).get(state) \
        or (layer_spec.get("states") or {}).get("idle") \
        or {}
```

That is the D9 fallback rule, spelled out precisely: **look up the resolved
state key first; if that key is absent from `states` (not merely empty —
absent), fall back to `states.idle`; if `states` itself is absent or empty,
fall back to `{}`** (no patch — base appearance wins outright).

**Merge/precedence rule (binding — S3/S4 build against this without
re-reading this file):**
- Every key `patch` sets OVERRIDES the layer entry's own base value for that
  key, for this resolution only (never mutates `layer_spec` in place).
- Every key `patch` OMITS leaves the base value exactly as `resolve()`
  already computed it before this phase touched the function.
- `patch["offset"]`, if present, overrides the base `offset` for this
  resolution's geometry math — it does not add to it, it replaces it. If
  `patch` has no `offset` key, the base `offset` (or no offset) stands.
- This is a plain shallow dict merge: `{**base_appearance, **patch}`,
  computed AFTER the existing base-appearance assembly `resolve()` already
  does, immediately before its return. No deep merge, no key-by-key special
  casing beyond `offset`'s replace-not-add rule stated above (which is not
  special — `offset` is just another key in the shallow merge; it is called
  out only because "replace not add" is easy to misread as "compose").

### 2c. `game/ui/widgets.py` — owner's own per-state appearance

**`Button.submit`.** A `Button` may carry a `states` attribute (setattr'd
generically by `ScreenSkinning.apply`'s existing loop —
`game/ui/skinning.py:159-160`, confirmed this session: `apply()` already
setattrs any key present in an override doc onto the widget with no
per-key allowlist beyond `_SPEC_TO_ATTR`'s renames, so `states` needs NO
change to `apply()` or `_SPEC_TO_ATTR` to reach the widget — it arrives as
`button.states` automatically once the schema accepts the key). Resolve:

```
patch = getattr(button, "states", {}).get(button._state()) \
        or getattr(button, "states", {}).get("idle") \
        or {}
```

same D9 fallback as 2b, evaluated against the SAME `_state()` call
`submit()` and the skinned-sprite `animation=` argument already use
(`widgets.py:596`) — do not re-derive state from `hovered`/`pressed`/
`enabled` a second time.

Apply `patch.get("text_color")` in place of (or layered under, matching
whatever precedence `button_kwargs`'s existing `text_color` override already
has — the explicit per-call `text_color=` kwarg wins over a `states` patch,
since a caller passing it explicitly is being more specific) the `tcol`
`submit()` already computed, and apply `patch.get("offset")` to `x, y, w, h`
**at draw time only**: compute a locally-scoped nudged rect
(`dx, dy, dw, dh = (list(patch["offset"]) + [0, 0])[:4]`, or the 2-length
form padded to 4) and use THAT for the sprite/rect/label submit calls in
this one `submit()` invocation — `self.rect` itself is never reassigned.
This is the one correctness-critical rule in this phase: mutating
`self.rect` would corrupt hit-testing (`_surface_hit`, `hit()`) on the very
next frame, since those read `self.rect` directly and have no notion of "the
rect I drew last frame, offset by a state patch."

**`submit_label`** (`widgets.py:241`, for non-Button label holders). Needs
the equivalent lookup, but per §1's fallback rule a plain holder has no
`_state()` method — `state_of(widget)` (2d below) already resolves it to
`"idle"` unconditionally, so:

```
patch = getattr(holder, "states", {}).get("idle") or {}
```

is the entire reachable case for a label holder; the `hover`/`pressed`/
`disabled` sub-keys of a label holder's `states` object are validated by the
schema but never selected by any code path today (§1's flagged finding).
Apply `patch.get("color")` (a label's `submit_label` takes `color=`, not
`text_color=` — confirm the exact parameter name against
`widgets.py:241`'s signature before writing this call) the same way, and
`patch.get("offset")` nudges the drawn position only, never the holder's
stored `rect`/position attribute — same non-mutation rule as 2c.

### 2d. `game/ui/skinning.py` — `state_of` body only

UL-4 lands `state_of(self, widget) -> str` as a **`ScreenSkinning` instance
method** (correction to this brief's earlier draft, which called it a
top-level function — it must be a bound method because every one of the 14
screens calls it as `self.skinning.state_of`, and `self.skinning` is a
`ScreenSkinning` instance) always returning `"idle"`. This phase's ENTIRE
diff to this file is the body of that one existing method:

```python
    def state_of(self, widget) -> str:
        fn = getattr(widget, "_state", None)
        return fn() if callable(fn) else "idle"
```

Method name, its call sites (referenced from 14 screens as
`self.skinning.state_of`, a bound-method reference, per UL-4's contract), and
`submit_layers`'s signature are all unchanged — do not touch anything else in
this file, and do not turn `state_of` back into a module-level function.

## 3. File scope + shared-file contract

Touched this phase:
- `data/schemas/ui_screen.schema.json` — **UL-3's file, now landed.** My
  diff is additive only: one `states` key inserted alphabetically into the
  per-widget override object (between `skin` and `text_color`) and one
  `states` key inserted alphabetically into the layer-entry object (between
  `slot` and `text_color`). No reformatting, no reordering of any
  pre-existing key in either object.
- `engine/ui_layers.py` — **UL-3's file, now landed.** My diff is additive
  only: `resolve()`'s `state` parameter goes from unused to load-bearing via
  the merge described in §2b, added at the end of the function immediately
  before its return. No other function in this file changes.
- `game/ui/widgets.py` — `Button.submit` (§2c) and `submit_label` (§2c) gain
  the per-state lookup/apply described above. No other method changes; no
  new module-level helpers unless a tiny private one (e.g. an offset-padding
  helper) is shared verbatim between the two call sites, in which case name
  it once and use it from both rather than duplicating the padding logic.
- `game/ui/skinning.py` — **UL-4's file.** My diff is the body of `state_of`
  only (§2d), nothing else in this file changes.
- `tools/tests/test_ui_layer_draw.py` — **UL-4's test file, already landed.**
  Extend it; do not restructure existing tests in it.
- `tools/tests/test_hud_panel.py` — touch ONLY if a new/changed `Button`
  behavior needs a targeted assertion (see §4); if you add one, name it
  precisely, e.g. `TestButtonStates::test_hover_state_patch_offsets_draw_not_rect`
  — do not add broad new coverage beyond the parity + one-per-state cases.

No other file changes. This phase does not touch `engine/render/*`,
`game/ui/screens/*.py`, or any `data/ui/screens/*.json` (the Quick Test's
`hud.json` edit in §4 is a manual, uncommitted local check, not part of the
diff this phase lands).

## 4. Exit gate + Quick Test

Tests (extend `tools/tests/test_ui_layer_draw.py`):
- One case per state (`idle`/`hover`/`pressed`/`disabled`) on a layer
  entry's `states` object — assert the resolved appearance (color/
  text_color/tint as applicable) and offset for each, driven through
  `resolve()` directly.
- One case where a layer's `states` has no entry for the requested state
  and no `idle` entry either — assert it falls back to the base appearance
  (`{}` patch, §2b).
- One parity case: a widget/layer with NO `states` key at all draws EXACTLY
  as it does without this phase's code (mirrors D5) — assert byte-identical
  submit output vs. the pre-existing (no-`states`) fixture.
- If `Button.submit`'s offset math needs its own assertion beyond what the
  layer-level tests already cover (specifically: that `self.rect` is
  unchanged after a `states.hover` offset draws), add exactly one targeted
  test to `tools/tests/test_hud_panel.py`, named as in §3, asserting
  `button.rect` is bit-identical before and after a `submit()` call with an
  active offset patch.

Do not add coverage beyond these cases — minimal testing from coders is
house policy.

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_draw.py tools/tests/test_hud_panel.py -q
```

Both must be clean (`GATE PASS` from smoke, all selected tests green) before
handoff. This is a subagent-scoped gate — do not run the full suite, a tier
sweep (`-m core`/`-m editor`/`-m meta`), `testgate check`, or `--affected`
from this phase.

**Quick Test (in-game, run by the orchestrator/user, not the coder):** add a
`hover` state to `hud.btn_end_turn` in `data/ui/screens/hud.json` with a
different `text_color` and a 1px `offset`:

```json
"btn_end_turn": {
  "states": {
    "hover": { "text_color": [255, 255, 0, 255], "offset": [0, -1] }
  }
}
```

Run `py game/main.py`, move the mouse over the End Turn button, and confirm
the label recolours to yellow and nudges up 1px on hover, and returns to its
normal color/position the instant the mouse leaves the button.
