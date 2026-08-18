# Phase UL-3 — The layer schema and a pure resolver

Section S2 of `planning/UiLayeredWidgetsPLAN.md`. Landing condition: **no
behaviour change anywhere** — this phase adds vocabulary (a schema key + a
pure module) that nothing calls yet. UL-4 (later in this section) is what
wires a caller to `engine.ui_layers`.

## 1. Behavioral spec

- **D1 — Layers live in the OVERRIDE doc, never in defaults.** Layers are
  authored per-widget inside `data/ui/screens/<id>.json`, validated by
  `data/schemas/ui_screen.schema.json`. This phase touches only that schema
  file (the per-widget object). `data/ui/screen_defaults.json` and its
  schema section (`data/schemas/ui_screen.schema.json:40-72`, the
  `"defaults"` block) are **not** touched — no `layers` key is added there,
  and this brief's diff never goes near lines 1-72 or 143-148 of the schema.
- **D2 — A layer's geometry is an OFFSET `[dx, dy, w, h]` from the owner's
  post-override rect, never absolute.** `w == 0` or `h == 0` means "match the
  owner's w/h". The resolver (`engine/ui_layers.py::resolve`) is the single
  place this rule is implemented; no other code computes a layer rect in this
  phase because no other code calls it yet.
- **D3 — The resolver is pure and pygame-free**, in `engine/ui_layers.py`.
  Both `game/` and `editor/` must be able to resolve a layer to the same rect
  without importing pygame or each other. This mirrors the existing purity
  boundary already enforced for `engine.coords`, `engine.data_io`,
  `engine.render`, `engine.assets`, `engine.assets.manifest`,
  `engine.assets.registry`, `engine.tilemap` — see
  `tools/tests/test_render.py:732-746` (class `TestPurity`, method
  `test_pure_modules_do_not_import_pygame`), whose subprocess-import line is
  at `tools/tests/test_render.py:739-740`:
  ```
  "import engine.coords, engine.data_io, engine.render, engine.assets, "
  "engine.assets.manifest, engine.assets.registry, engine.tilemap; "
  ```
- **D5 — nothing calls the resolver yet.** This phase is schema + pure module
  + tests only. Grep for `ui_layers` outside `engine/ui_layers.py` and
  `tools/tests/test_ui_layers.py` after this phase lands and it must return
  nothing (aside from this brief and the plan doc).
- **Current exact schema shape (verified read of
  `data/schemas/ui_screen.schema.json`, full file, 148 lines):** the
  per-widget object lives at `properties.widgets.patternProperties["^[a-z]
  [a-z0-9_]*$"]` (schema lines 76-141), `additionalProperties: false`
  (line 77), with existing keys in this exact order: `color` (79-88), `font`
  (89-91), `label` (92-94), `parent` (95-101), `rect` (102-109), `skin`
  (110-112), `text_color` (113-122), `text_id` (123-126), `tint` (127-136),
  `visible` (137-139). `label`'s property block closes with `},` at line 94;
  `parent`'s property block opens at line 95. That is the exact insertion
  point below.
- **Coordination note (do not act on this, just don't collide):** Section S1
  is concurrently adding an `align` key to this same per-widget object (a
  widget-level `align`, unrelated to the layer-entry `align` below). UL-5
  (later) adds a `states` key to both the per-widget object and the
  layer-entry object. Your diff touches **only** the insertion of `layers`
  between `label` and `parent` — if S1's `align` has already landed in this
  worktree by the time you write, do not reorder around it or touch it;
  insert `layers` strictly between `label` and `parent` regardless of what
  else is present, and do not alphabetize anything else in the object.

## 2. Architecture plan

### 2a. Schema: `data/schemas/ui_screen.schema.json`

Insert a new property `layers` into the per-widget object, positioned
alphabetically between `label` (ends line 94) and `parent` (starts line 95).
Nothing else in the file changes — no reformatting, no reordering of the
other 9 keys, `background`/`defaults` untouched.

```json
            "layers": {
              "items": {
                "additionalProperties": false,
                "properties": {
                  "id": {
                    "type": "string"
                  },
                  "offset": {
                    "items": {
                      "type": "integer"
                    },
                    "maxItems": 4,
                    "minItems": 4,
                    "type": "array"
                  },
                  "z": {
                    "type": "integer"
                  },
                  "band": {
                    "enum": ["under", "over"],
                    "type": "string"
                  },
                  "slot": {
                    "type": "string"
                  },
                  "text_id": {
                    "type": "string"
                  },
                  "label": {
                    "type": "string"
                  },
                  "font": {
                    "type": "string"
                  },
                  "align": {
                    "enum": ["left", "center", "right"],
                    "type": "string"
                  },
                  "color": {
                    "items": {
                      "maximum": 255,
                      "minimum": 0,
                      "type": "integer"
                    },
                    "maxItems": 4,
                    "minItems": 3,
                    "type": "array"
                  },
                  "text_color": {
                    "items": {
                      "maximum": 255,
                      "minimum": 0,
                      "type": "integer"
                    },
                    "maxItems": 4,
                    "minItems": 3,
                    "type": "array"
                  },
                  "tint": {
                    "items": {
                      "maximum": 255,
                      "minimum": 0,
                      "type": "integer"
                    },
                    "maxItems": 4,
                    "minItems": 3,
                    "type": "array"
                  },
                  "visible": {
                    "type": "boolean"
                  }
                },
                "type": "object"
              },
              "type": "array"
            },
```

Every key in the layer-entry object is optional (no `required` array). Key
order inside the entry mirrors the plan's dictation order (`id, offset, z,
band, slot, text_id, label, font, align, color, text_color, tint, visible`)
— this is a new nested object, not an existing one, so there is no pre-existing
alphabetical convention to preserve; keep this order for readability and do
not alphabetize it (the coder must not "fix" this into alpha order — it would
just be gratuitous churn against this brief).

After inserting `layers`, revalidate every existing screen doc under
`data/ui/screens/*.json` against the schema (they have no `layers` key today,
so they must still validate — this is the "no behaviour change" check for the
schema half of this phase). Use whichever validation entry point the repo
already exposes for schema-valid writes (see `data/CLAUDE.md` for the
validating writer / validator invocation) — do not hand-roll a second
validator.

### 2b. New module: `engine/ui_layers.py`

Pure, pygame-free. No imports from `pygame`, `engine.render`, `editor/`, or
`game/`. Public contract (binding — UL-4 and later sections code against
this exactly):

```python
def resolve(layer_spec: dict, owner_rect: tuple, state: str = "idle") -> dict:
    """Compute one layer's absolute rect + resolved appearance.

    layer_spec: one entry from a widget's "layers" array (schema above).
        Every key is optional; absent keys degrade per-key as documented
        below rather than raising.
    owner_rect: (x, y, w, h) — the owning widget's POST-OVERRIDE rect
        (already resolved by whatever placed the widget; this function does
        not know about screen_defaults.json or overrides, only the final
        rect it is handed).
    state: forward-compat parameter for UL-5's "states" sub-object. UL-3
        ships no "states" key in the schema, so this parameter is a documented
        no-op today: passing any string produces the same output. UL-5 will
        make this parameter meaningful without changing resolve()'s
        signature or the shape of its return value.

    Returns a dict:
        {
            "rect": (x, y, w, h),      # ints, owner_rect anchored + D2's
                                        # 0-inherits-owner's-w/h rule applied
            "slot": str | None,
            "text_id": str | None,
            "label": str | None,
            "font": str | None,
            "align": str | None,
            "color": tuple | None,
            "text_color": tuple | None,
            "tint": tuple | None,
            "visible": bool,           # default True when absent from the
                                        # entry (matches the per-widget
                                        # "visible" default already implied
                                        # by the existing schema's boolean
                                        # type with no explicit default —
                                        # document this choice inline in the
                                        # module docstring)
        }

    Rect computation (D2):
        offset = layer_spec.get("offset") -- validated via
            validate_offsets([layer_spec]) first; a malformed offset
            degrades to (0, 0, 0, 0) rather than raising.
        dx, dy, w, h = offset (or the degraded (0,0,0,0))
        ow, oh = owner_rect[2], owner_rect[3]
        out_w = ow if w == 0 else w
        out_h = oh if h == 0 else h
        out_x = owner_rect[0] + dx
        out_y = owner_rect[1] + dy
        rect = (out_x, out_y, out_w, out_h)

    Appearance keys (slot/text_id/label/font/align/color/text_color/tint):
        each is layer_spec.get(key, None) verbatim -- color-shaped values
        (color/text_color/tint) are returned as a tuple() of whatever
        sequence was given (or None if absent); no clamping/validation is
        performed here (schema validation is the authority for value
        correctness, this function only degrades STRUCTURAL problems --
        missing/malformed offset, dangling ids in ordered() -- not value
        range problems).
    """


def ordered(layers: list[dict], band: str) -> list[dict]:
    """Filter + order a widget's layers for one paint band.

    layers: the widget's raw "layers" array (list of layer-spec dicts,
        schema above) -- NOT yet resolved; ordered() does not call resolve().
    band: "under" | "over" -- the caller (UL-4, not this phase) paints
        "under" layers before the owner widget and "over" layers after it.

    Selection: an entry matches `band` if entry.get("band", "over") == band.
        Missing "band" key defaults to "over" (documented choice: an
        undecorated layer entry paints ON TOP of its owner, which is the
        visually safer default -- an accidentally-omitted band still shows,
        rather than silently hiding behind the owner).

    Ordering: stable sort by entry.get("z", 0) ascending (ties keep source
        order -- Python's sort is already stable, so `sorted(matched,
        key=lambda e: e.get("z", 0))` is sufficient, no secondary key
        needed).

    Degrade (dangling/duplicate id): if two or more entries in `layers`
        share the same non-empty "id" value, keep the FIRST occurrence
        (in the original `layers` list order, before filtering/sorting) and
        drop the rest, rather than raising. Entries with no "id" key, or an
        empty-string "id", are never deduped against each other or anything
        else (only a non-empty id collision triggers the drop). This mirrors
        editor/widget_tree.py's D5 precedent: a hand-edited doc must never
        hang a paint handler.

    Returns: a new list (does not mutate `layers`), containing only the
        band-matching, deduped entries, sorted by z.
    """


def validate_offsets(layers: list[dict]) -> list[dict]:
    """Pure structural check: every entry's "offset" (if present) must be a
    4-element sequence of ints.

    Returns a NEW list, same length and order as `layers`, where each entry
    is either the original dict unchanged (offset absent, or present and
    valid: a sequence of exactly 4 int-typed elements) or a shallow copy of
    the entry with "offset" replaced by (0, 0, 0, 0) (offset present but
    malformed: wrong length, non-sequence, or any element not an int --
    bool is NOT accepted as int here even though Python's bool is an int
    subclass, since a stray `true`/`false` in an offset slot is clearly a
    JSON authoring mistake, not a degraded-but-intentional value).
    Does not raise on any input shape, including layers entries that are not
    dicts at all -- a non-dict entry in `layers` is skipped (passed through
    unchanged) since there is nothing to fix on it; resolve() calling
    validate_offsets([layer_spec]) on a non-dict is out of scope for this
    phase (resolve() only receives a single already-dict layer_spec by
    contract; the list form here exists for ordered()'s bulk callers in
    UL-4+).
    """
```

Module-level docstring at the top of `engine/ui_layers.py` must state D1-D3
and the "no caller yet" fact from Behavioral spec above in 3-5 lines, so a
reader who opens the file cold (without this brief) understands why it
exists unused.

## 3. File scope + shared-file contract

**New files:**
- `engine/ui_layers.py` — new module, contract exactly as in §2b.
- `tools/tests/test_ui_layers.py` — new test file (see §4 for required
  cases).

**Modified files:**
- `data/schemas/ui_screen.schema.json` — **shared with Section S1** (adds
  `align` to the same per-widget object) and with UL-5 (adds `states` to the
  same object, landing after this phase). This phase's diff must be **exactly
  one inserted `layers` key**, positioned alphabetically between `label`
  (schema line 92-94) and `parent` (schema line 95-101), with the object
  literal given verbatim in §2a. Nothing else in the 148-line file changes:
  do not touch `background` (lines 6-39), `defaults` (lines 40-72), or any of
  the other 9 existing per-widget keys, and do not reorder or reformat
  anything already present (including anything S1 may have already landed,
  e.g. `align` — insert around it, never move it).
- `tools/tests/test_render.py` — **purity check routed here.** Exact,
  surgical edit: the subprocess-import string at
  `tools/tests/test_render.py:739-740` currently reads
  ```
  "import engine.coords, engine.data_io, engine.render, engine.assets, "
  "engine.assets.manifest, engine.assets.registry, engine.tilemap; "
  ```
  Change it to append `engine.ui_layers` to the import list (after
  `engine.tilemap`):
  ```
  "import engine.coords, engine.data_io, engine.render, engine.assets, "
  "engine.assets.manifest, engine.assets.registry, engine.tilemap, "
  "engine.ui_layers; "
  ```
  This is the only line touched in `test_render.py` — do not touch the rest
  of `TestPurity` (lines 732-746) or anything else in the file.

**Do not touch:** `data/ui/screen_defaults.json` or its schema section
(D1), any file under `editor/` or `game/` (D5 — no caller yet), and do not
add a `states` key anywhere (that is UL-5's addition, landing after this
phase; leaving `additionalProperties: false` on the layer-entry object is
what lets UL-5 add it cleanly later without touching this phase's work).

## 4. Exit gate + Quick Test

Required test cases in `tools/tests/test_ui_layers.py` (name them close to
this; exact wording is the coder's call, scope is not):

- `resolve()` — offset applied to owner_rect (dx/dy/w/h all nonzero).
- `resolve()` — `w == 0` and `h == 0` inherit the owner's w/h (D2's "0
  means match the owner's" case), independently (w=0,h nonzero and vice
  versa) and together.
- `resolve()` — absent `offset` key degrades to `(0,0,0,0)` applied (i.e.
  rect == owner_rect).
- `resolve()` — appearance keys default to `None` (or `True` for `visible`)
  when absent from the entry; a fully-populated entry returns all keys
  verbatim.
- `resolve()` — `state` parameter is a no-op today: calling with
  `state="idle"` vs `state="pressed"` (or any other string) on the same
  layer_spec produces identical output.
- `ordered()` — band filtering: an `"under"` entry is excluded when
  `band="over"` is requested and vice versa.
- `ordered()` — missing `band` key defaults to `"over"` (present when
  `band="over"` requested, absent when `band="under"` requested).
- `ordered()` — z-ordering: entries sort ascending by `z`; missing `z`
  defaults to `0`; ties preserve original list order (stability).
- `ordered()` — duplicate `id`: two entries sharing a non-empty `id` in the
  same list — only the first survives filtering (regardless of what band/z
  it lands in relative to the dropped duplicate).
- `ordered()` — entries with no `id`, or empty-string `id`, are never deduped
  against each other (multiple id-less entries all survive).
- `validate_offsets()` — a valid 4-int offset passes through unchanged.
- `validate_offsets()` — a malformed offset (wrong length, non-int element,
  non-sequence, or a bool in a slot) is replaced with `(0, 0, 0, 0)` in the
  returned copy, and the original input list/dicts are not mutated.
- `validate_offsets()` — absent `offset` key passes through unchanged (no
  offset key added).
- Purity — either add a `TestPurity` case in this new file (mirroring
  `tools/tests/test_core.py`'s ~line 278-290 single-module subprocess
  pattern, importing only `engine.ui_layers` and asserting no pygame leak)
  **or** rely on the `tools/tests/test_render.py:739-740` edit from §3 — this
  phase uses the `test_render.py` route (§3), so `test_ui_layers.py` does NOT
  need its own purity test; do not duplicate it.
- Schema — existing `data/ui/screens/*.json` docs still validate against the
  updated schema (no `layers` key present in any of them today, and the key
  being optional means they must still pass). This can be a single
  parametrized/loop test over the existing screens, or covered by whatever
  schema-validation test file already exercises `ui_screen.schema.json` if
  one exists in `tools/tests/` — if a suitable existing test already asserts
  "all screens validate", extending its coverage implicitly by running it
  unchanged is sufficient; do not create a second one if one already covers
  this.

Run, in order:

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layers.py tools/tests/test_render.py -q
```

Both must pass (`GATE PASS` equivalent — zero red, zero unexpected skip).
Do not run the full suite, a tier sweep (`-m core`/`-m editor`/`-m meta`), or
`testgate --affected` — this is a subagent phase; see the Test Suite Policy
in root `CLAUDE.md`.

**Quick Test (run by the orchestrator or user, not the coder):** launch
`py game/main.py` and confirm it boots and every screen renders byte-for-byte
identical to before this phase (main menu, building panel, HUD, any other
screen the game reaches). This phase adds a schema key and an unused pure
module — nothing should look, behave, or hit-test differently. If anything
visibly changed, this phase's landing condition (D5: no caller exists yet)
was violated somewhere and the diff needs re-checking before it merges.
