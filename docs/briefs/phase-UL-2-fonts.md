# Phase UL-2 — Designer-defined font presets

Source: `planning/UiLayeredWidgetsPLAN.md:193-222` (Phase UL-2 block),
decision D6 (`planning/UiLayeredWidgetsPLAN.md:84-93`).

## 1. Behavioral spec

**Goal (verbatim from the plan, `planning/UiLayeredWidgetsPLAN.md:195-197`).**
The designer adds their own font preset (name + size + bold) in the editor's
Theme panel and assigns it to any widget. The seven shipped presets stay
exactly as they are (D6): REQUIRED and PINNED, never resized.

**Today's state (verified, file:line):**

- `data/schemas/fonts.schema.json:1-69` — exactly the 7 keys (`hud_lvl`,
  `hud_phase`, `lg`, `md`, `sm`, `xl`, `xxl`) are declared under `properties`,
  all listed in `required` (lines 58-66), and `additionalProperties: false`
  (line 26) rejects any other key outright. The shared `font_spec` `$def`
  (lines 2-22) is `{size: int 4-72, bold: bool}`, `additionalProperties: false`.
- `engine/render/fonts.py:20-28` — `_FONT_SPECS`, the same 7 keys, `(size,
  bold)` tuples; this is the module's mutable live state, rebuilt in place by
  `configure_fonts`.
- `engine/render/fonts.py:46-54` — `_LAYOUT_H`, the pinned cross-platform
  layout-height table, same 7 keys, plain ints. `layout_h(font_key)`
  (`engine/render/fonts.py:57-70`) returns `_LAYOUT_H[key]`, falling back to
  `_LAYOUT_H["md"]` for any key it doesn't recognize (line 69) — today that
  means EVERY key outside the 7, since nothing else can reach `_FONT_SPECS`
  or `_LAYOUT_H` (the schema blocks it upstream).
- `engine/render/fonts.py:116-121` — `configure_fonts`'s key-set check:
  `unknown = set(doc) - set(_FONT_SPECS)`; `missing = set(_FONT_SPECS) -
  set(doc)`; raises `ValueError` if either is non-empty. This is the "exact
  match, no extras" check the plan (`planning/UiLayeredWidgetsPLAN.md:203-205`)
  says must relax to "the seven must be present, extras allowed."
  `engine/render/fonts.py:110-115`'s docstring already states `_LAYOUT_H` is
  untouched by `configure_fonts` today — that sentence becomes false for
  custom keys once this phase lands and must be updated.
- `editor/theme_ops.py:67-76` — `font_keys(data_dir)` already returns
  `tuple(load_fonts(data_dir).keys())` — i.e. it iterates **whatever keys are
  in the live `fonts.json` doc**, not a hardcoded 7-tuple (the 7-tuple at
  `editor/theme_ops.py:27`, `_FALLBACK_FONT_KEYS`, is ONLY the degrade path
  used when the file itself is unreadable, per its docstring at lines 23-26).
- `editor/panels/screen_details.py:462-468` — `_populate_font_combo(combo)`
  calls `theme_ops.font_keys(self._data_dir)` and adds one combo item per
  key, verbatim, no filtering to a fixed set.
  **Consequence (verified by reading, not asserted): once `fonts.json` is
  allowed to carry extra keys and the Theme panel can write them,
  `_populate_font_combo` already lists them — no code change is structurally
  required in `screen_details.py` for the combo to show custom presets.**
  This phase's `screen_details.py` file-scope entry is therefore
  **verification, not modification**: confirm (ideally with a short assert in
  the new test, or by manual/Quick-Test check) that a custom key written to
  `fonts.json` shows up in both `self.font_combo` and
  `self.default_font_combo`. Do not add a new combo, row, or method — if
  investigation turns up a real gap, the fix is inside `_populate_font_combo`
  or `default_font_combo`'s populate call only (see §3).
- `editor/panels/game_theme.py:158-219` (`_rebuild_form`) and `:223-241`
  (`_build_font_row`) — today's Theme panel builds exactly one row per key
  already present in `self._fonts_doc` (`for key in sorted(self._fonts_doc):`
  at line 186), a size spinbox + bold checkbox, no add/rename/remove
  affordance at all. `_on_save` (`editor/panels/game_theme.py:447-465`) is the
  sole `write_validated` call site, gated on `self._dirty` — the staged
  pattern this phase's add/rename/remove must reuse, not replace.
- `tools/tests/test_theme_data.py:29-37` (`_FIXTURE_FONTS`) pins exactly the 7
  stock keys against `configure_fonts`, and its `_ConfigureMixin`
  (`tools/tests/test_theme_data.py:107-118`) `addCleanup`-restores
  `fonts._FONT_SPECS` (via `_snapshot_fonts`/`_restore_fonts`,
  `tools/tests/test_theme_data.py:69-76`) around every test that calls
  `configure_fonts` — **this restore helper does NOT touch `_LAYOUT_H`**,
  because today nothing ever mutates it. This phase is `_LAYOUT_H`'s first
  runtime mutator; the new `test_font_presets.py` must snapshot/restore
  `fonts._LAYOUT_H` itself (see §2) so it never leaks a custom key's derived
  height into a later test in the same process — do not touch
  `test_theme_data.py` itself, its fixture only ever has the 7 keys so it
  cannot poison `_LAYOUT_H` and must keep passing unmodified.

## 2. Architecture plan

**a) `data/schemas/fonts.schema.json`.** Keep `properties`/`required`
untouched (the 7 keys, `font_spec` shape, unchanged). Replace the blanket
`"additionalProperties": false` with a `patternProperties` entry that routes
any key matching `^[a-z][a-z0-9_]*$` through the same `#/$defs/font_spec`
ref, and keep `additionalProperties: false` so a key that does NOT match the
pattern (or fails the `font_spec` shape) still fails validation:

```json
"patternProperties": {
  "^[a-z][a-z0-9_]*$": { "$ref": "#/$defs/font_spec" }
},
"additionalProperties": false
```

The 7 required keys already match this pattern, so they validate through
both `properties` and `patternProperties` harmlessly (same `$ref`, no
conflict). Update the schema's top-level `description` (currently states
"Adding a NEW preset key is a schema change, deliberately out of scope for
v1" at `data/schemas/fonts.schema.json:27`) to reflect that custom keys are
now additive per D6.

**b) `engine/render/fonts.py` — `configure_fonts`.**
1. Add a fixed reference set for the missing-key check, captured once at
   import time (before any mutation), e.g. `_REQUIRED_KEYS =
   frozenset(_FONT_SPECS)` placed immediately after the `_FONT_SPECS` literal
   at line 28 — **not** `set(_FONT_SPECS)` read live inside `configure_fonts`,
   because `_FONT_SPECS` itself gets extra keys written into it by earlier
   `configure_fonts` calls (tests reconfigure repeatedly in one process); a
   live read would let a stale custom key from a PRIOR call masquerade as
   "required" and break the missing-key check's honesty.
2. In `configure_fonts`, replace the `unknown`/`missing` pair (lines 116-121)
   with: `missing = _REQUIRED_KEYS - set(doc)`; raise `ValueError` if
   `missing` (message shape unchanged, drop the `unknown` half). Every key in
   `doc` — the 7 plus any customs — still gets written into `_FONT_SPECS` via
   the existing `for key, spec in doc.items(): _FONT_SPECS[key] = (...)` loop
   (lines 122-123), unchanged.
3. **Derive `_LAYOUT_H` for every key in `doc` not already one of the 7
   pinned keys**, once, inside `configure_fonts`, and store it —
   **(architecture call, inferred — the plan's D6 text specifies the
   constraint "once, inside configure_fonts, stored, never measured live at
   each call site" but not the literal derivation formula; this is the
   coder's actual implementation task, not a value to copy):**
   - Build the font at that key's configured `(size, bold)` — reuse
     `get_font`'s own construction logic (SysFont or `_FONT_BYTES`-backed,
     `engine/render/fonts.py:157-178`) or a fresh throwaway
     `pygame.font.SysFont`/`pygame.font.Font`, matching how `TextMetrics.size`
     already measures elsewhere in this module.
     Measure a representative sample (module docstring at
     `engine/render/fonts.py:39-40` says the 7 pinned values ARE exactly this
     kind of `TextMetrics().size("Ag", key)[1]` measurement, just done once by
     a human and hardcoded — reuse "Ag" as the sample glyph string for
     consistency) and store the resulting height into `_LAYOUT_H[key]`.
   - This happens exactly ONCE per `configure_fonts` call, for keys outside
     the pinned 7 — **the 7 pinned entries in `_LAYOUT_H` are never
     overwritten, by this step or anything else** (D6: "the seven shipped
     font presets stay exactly as they are... never resized").
   - Cross-platform reproducibility is NOT at risk here: the pinned-height
     invariant exists to keep the SHIPPED golden baseline
     (`test_ui_skinning.py`, `data/ui/screen_defaults.json`) byte-identical
     between the Windows machine that captured it and Linux CI regenerating
     it — and that baseline only ever uses the 7 pinned presets. A custom
     preset is new, per-project, per-designer data with no committed golden
     entry to diverge from; measuring it once at configure time (which
     already happens once per process boot, same as today) is consistent
     with the constraint as written.
   - A **reconfigure** (calling `configure_fonts` again — the test in §"Tests"
     below exercises this) must re-derive (or otherwise preserve) the custom
     key's `_LAYOUT_H` entry — it must not vanish or raise, since the second
     call's `doc` still carries that key.
4. Update the docstring at `engine/render/fonts.py:110-115` (currently
   "Does NOT touch `_LAYOUT_H`/`layout_h`") to state the seven pinned entries
   are untouched but a custom key's entry is derived here.

**c) `editor/theme_ops.py`.** No existing function needs to change —
`font_keys` already sources live keys (§1). Add whatever small, pure,
Qt-free helper the add/rename/remove UI needs for name validation (e.g. a
`is_valid_preset_name(name, existing_keys)` — matches
`^[a-z][a-z0-9_]*$`, not already present in `existing_keys`) — this module is
already in `TestPurity`'s Qt-free/pygame-free import list
(`editor/theme_ops.py:5-6`), and centralizing the pattern check here (rather
than duplicating a regex literal inside `game_theme.py`) keeps ONE home for
the rule the schema also encodes.

**d) `editor/panels/game_theme.py`.** Add, inside the existing "Fonts"
`CollapsibleSection` built by `_rebuild_form` (`editor/panels/
game_theme.py:178-192`):
- An "Add Preset" affordance (name field + Add button, or equivalent) that,
  on click: validates the name (§c's helper — reject empty, non-matching
  pattern, or a name colliding with any of the 7 pinned keys or an existing
  custom key), inserts `{"size": <a sane default, e.g. 11>, "bold": false}`
  into `self._fonts_doc`, marks it dirty (reuse `_refresh_font_dirty`'s
  dirty-dot/`_dirty` mechanics), and rebuilds the fonts form
  (`_rebuild_form`) so the new row appears with its own size spinbox/bold
  checkbox (`_build_font_row`, unchanged).
- A per-row remove control on CUSTOM rows only — the 7 pinned keys' rows get
  no remove affordance (or a disabled one with a tooltip explaining PINNED),
  enforced in code (not just hidden in the UI) so a pinned key can never be
  popped from `self._fonts_doc` by this path.
- Rename: since a preset is a dict key, "rename" is remove-old-key +
  add-new-key preserving that key's current `{size, bold}`, through the same
  name validation as Add.
- All of the above mutate `self._fonts_doc` and the dirty set exactly like
  `_on_font_size_changed`/`_on_font_bold_changed` already do
  (`editor/panels/game_theme.py:401-419`) — **no new write path**: saving
  still goes through the single existing `theme_ops.write_fonts` call inside
  `_on_save` (`editor/panels/game_theme.py:450-452`), which schema-validates
  the whole doc (including any new patternProperties key) on write.

**e) `editor/panels/screen_details.py`.** See §1's "today's state" — expected
to need zero or near-zero change (`_populate_font_combo` already sources live
keys). If, after checking against the built Theme panel + a written custom
key, a real gap surfaces, the fix is confined to `_populate_font_combo`'s body
(`editor/panels/screen_details.py:462-468`) or to `default_font_combo`'s
populate call (`editor/panels/screen_details.py:418-419`, itself just a
`self._populate_font_combo(self.default_font_combo)` call — the SAME method,
already shared). **Do not add a new combo, a new form row, or touch
`__init__`'s widget-form construction** (see §3).

## 3. File scope + shared-file contract

**Owned by UL-2, not shared with any other section or phase:**
- `data/schemas/fonts.schema.json`
- `engine/render/fonts.py`
- `editor/theme_ops.py`
- `editor/panels/game_theme.py`
- `tools/tests/test_font_presets.py` (new)

**Shared with Phase UL-1 (same section S1, concurrent, own worktree):**
`editor/panels/screen_details.py`. UL-1 adds a brand-new Alignment combo +
field row inside `__init__`'s widget-form construction, inserted right after
the existing Font row (`form.addRow("Font", font_row)` at
`editor/panels/screen_details.py:299`) and before the Color/tint block
(starting `editor/panels/screen_details.py:301`).

**Explicit split (do not deviate):**
> **UL-2 owns `_populate_font_combo` (and `default_font_combo`'s populate
> call if separate) only; UL-2 does NOT touch `__init__`'s widget-form
> construction, which is UL-1's Alignment-row insertion point.**

Concretely: UL-2 may edit inside the method body at
`editor/panels/screen_details.py:462-468` (`_populate_font_combo`). UL-2 must
NOT edit anything in the `__init__` body between (and including) lines
280-421 — that whole span, not just the Font row, is UL-1's construction
region; the two calls to `_populate_font_combo` at lines 418-419 are call
sites inside that span and must be left exactly as they are (do not move,
rename, or add a third call there — if `default_font_combo` needs different
population logic than `font_combo`, branch INSIDE the method body on which
combo was passed, or add a second small private method called from
`_populate_font_combo`'s existing two call sites, never a new call line in
`__init__`).

Merge order into `ul-section-S1` is UL-1 then UL-2 (both coders run in their
own worktree); since UL-2's only touch to this file is inside an existing
method body untouched by UL-1's row-insertion diff, the two diffs do not
overlap and should merge cleanly in either order — but UL-2's coder must
re-read `_populate_font_combo`'s current body (not assume the citation above
is still current) after UL-1 has landed, in case line numbers shifted.

## 4. Exit gate + Quick Test

```
py tools/smoke.py
py -m pytest tools/tests/test_font_presets.py tools/tests/test_theme_data.py -q
```

`tools/tests/test_font_presets.py` (new) must, at minimum:
- Configure `fonts.py` with the 7 stock keys plus one custom key (e.g.
  `title_big`, `{"size": 34, "bold": true}`), assert `fonts.layout_h
  ("title_big")` returns something other than the `md` fallback (i.e. the
  derivation actually ran) and is a plain `int`.
- Call `configure_fonts` a second time with the same doc (a reconfigure) and
  assert `layout_h("title_big")` still resolves correctly (no crash, no
  disappearance).
- Assert dropping one of the 7 required keys from the doc still raises
  `ValueError` (the missing-key check stays loud).
- `addCleanup`-restore both `fonts._FONT_SPECS` AND `fonts._LAYOUT_H` (plus
  `fonts._cache.clear()`) around every test that calls `configure_fonts`,
  mirroring `tools/tests/test_theme_data.py`'s `_snapshot_fonts`/
  `_restore_fonts` pattern (`tools/tests/test_theme_data.py:69-76`) but
  extended to cover `_LAYOUT_H`, since this phase is its first runtime
  mutator and a leaked custom entry would poison whichever test runs next in
  the same process.

**Quick Test (in game — copied verbatim from
`planning/UiLayeredWidgetsPLAN.md:220-222`):** add a `title_big` preset (size
34, bold) in the Theme panel, point `main_menu`'s title at it, run `py
game/main.py` and confirm the title draws larger while every other screen is
unchanged.
