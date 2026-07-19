# Phase A4 — Editor: slice-margins editor + importer verification

Slice 10L-A (`planning/UI_EDITOR_PLAN.md` lines 125–132). Branch:
`phase-10L-finish-umbrella`, one PR. Package: **editor only** (`editor/panels/details.py` + its tests + the panels
doc). Runs in parallel with A5′ (`game/**`) — no file overlap.

**Assumed landed (confirm before coding, do not re-implement):**
- **A2** — `data/schemas/asset_manifest.schema.json`, per-entry optional
  `"slice"`. A2's brief did not exist when this was written, so the assumed
  shape is **a 4-int array `[left, top, right, bottom]`, ints ≥ 0, NOT in
  `required`** (plan line 99). **First thing the coder does: open the landed
  schema and confirm the key name, the array shape and its `maximum`.** If A2
  shipped anything else (e.g. an object `{left,top,right,bottom}`), keep this
  brief's behavior and adapt only the literal written into the entry dict —
  and say so in the PR. `engine.assets.manifest.entry_from_dict` already parses
  `slice` after A2 (plan lines 100–101); the editor never re-implements that.
- **A3** — the `ui` category's `animations` vocab is
  `["idle", "hover", "pressed", "disabled"]` and its groups are
  Buttons / Panels / Icons / Backgrounds (`data/slots.json`, plan lines 112–123).
  Pre-A3 the ui category is `animations: ["idle"]`, one `HUD` group
  (`data/slots.json:529-547`) — the A4 tests below **require** the A3 shape.

---

## 1. Behavioral spec

### 1a. The slice-margins editor (the only new UI)

- **Where:** inside `DetailsPanel` (`editor/panels/details.py`), one row of 4
  spinboxes directly under the existing Offset X/Y row (`details.py:172-183`).
  Labels: `Nine-slice  L: / T: / R: / B:`.
- **Which categories:** **`ui` only.** Category is known from
  `self._context = (category_key, group_path)`, set in `set_context`
  (`details.py:203-207`); MainWindow always calls `set_context` before
  `set_slot` (`editor/main.py:255-256` → `_refresh_levels` → `_apply_slot` →
  `details.set_slot`, `main.py:486`), so the gate is reliable at both points.
  Non-ui (or no context yet) → the row is **hidden** *and* `draft_entry()` must
  **not** emit a `slice` key. Rationale: the plan scopes nine-slice to HUD
  sprites (lines 25–26); world sprites keep uniform zoom scaling.
- **Bounds (invalid input unrepresentable, ED-30):** ints, min `0`; max = the
  slot's frame size on that axis — L/R capped at `frame_w`, T/B capped at
  `frame_h`, from `self.registry.frame_size(slot_key)` (`details.py:267`,
  `engine/assets/registry.py:144-150`). Frame sizes are schema-capped at 1024,
  so any per-axis cap stays inside A2's `slice` maximum. No cross-field
  constraint (L+R ≤ frame_w) is enforced in the UI — the plan makes degenerate
  margins the *backend's* job ("smaller than the summed margins → clamp
  proportionally", lines 107–108).
- **Omit-when-zero (HARD REQUIREMENT):** `slice` is optional. A slot whose four
  margins are all `0` must write **no `slice` key at all**, and must not carry
  one in the emitted draft. Non-sliced art therefore produces byte-identical
  manifest entries to today's. Because `save()` replaces the whole entry
  (`details.py:338`), zeroing the margins on a previously-sliced slot and saving
  **removes** the key — that is the intended "un-slice" path, and it must be
  tested.
- **Draft → preview → save flow** (unchanged plumbing, new field rides along):
  any spin change → `_emit_draft()` (`details.py:439-442`) →
  `draft_changed(slot, entry_dict)` → `viewport.set_preview_draft`
  (`editor/main.py:108`), which parses the dict with `entry_from_dict`
  **in memory, never disk** (`viewport.py:188-200`). `Save` →
  `draft_entry()` → `_write_doc` → `engine.data_io.write_validated` against
  `asset_manifest.schema.json` (`details.py:332-342, 389-393`) → `entry_saved`
  → `viewport.reload_assets()`. Re-selecting the slot re-seeds the four
  spinboxes from the saved entry (`set_slot`, next to the offsets read at
  `details.py:269-272`).
- **Viewport preview needs no change.** The entity preview submits a
  `RenderItem` (`viewport.py:512-536`), i.e. the *world* path, which ignores
  `slice` — so a sliced draft previews as a plain scaled sprite. That is
  correct and expected in A4; the nine-slice blit only exists on the HUD path
  (A2 backend + A5′ skinned Button). What A4 must *prove* is that a draft dict
  carrying `slice` still parses and renders (no raise, animations still listed)
  — `set_preview_draft` already catches `ValueError` and falls back
  (`viewport.py:195-198`), but a `slice`-carrying draft must take the **happy**
  path, not the fallback.

### 1b. Importer verification ("mostly free" — prove it, change nothing)

Plan lines 126–128: with the ui vocab extended, `DetailsPanel` already offers
per-row animation dropdowns, fps, hidden, loop and offset. Verify against a
real 4-row button sheet (a synthetic 2×4-frame PNG is fine):

- 4 sheet rows → 4 `RowEditor`s (`details.py:412-425`).
- **Row 0 is locked to `idle`** — its combo contains exactly `["idle"]` and is
  disabled (`details.py:63-65`); E-35 is unrepresentable in the UI, not a
  save-time error.
- Rows 1–3 offer the full ui vocabulary `["idle","hover","pressed","disabled"]`
  and **default to `hover` / `pressed` / `disabled`** — `_load_sheet` seeds row
  `r` with `vocabulary[min(r, len(vocabulary) - 1)]` (`details.py:419-422`).
- Saving that sheet writes an entry whose `rows[*].animation` is
  `["idle","hover","pressed","disabled"]` and validates.

No production code changes are needed for 1b. If a test in 1b fails, the fix is
almost certainly in A3's `slots.json`, not in `details.py` — report it, do not
patch `data/`.

---

## 2. Architecture plan

All production changes are in **`editor/panels/details.py`**. **No new module**
(a new editor module would have to join `TestPurity`'s import list at
`tools/tests/test_editor_viewport.py:196-203` — avoid it).

### Edit 1 — widget construction, `DetailsPanel.__init__`, right after the offsets block (`details.py:172-183`)

Current (the model to mirror):

```python
        offsets = QHBoxLayout()
        offsets.addWidget(QLabel("Offset  X:"))
        self._offset_x = QSpinBox()
        self._offset_y = QSpinBox()
        for spin in (self._offset_x, self._offset_y):
            spin.setRange(-256, 256)
            spin.valueChanged.connect(lambda _v: self._emit_draft())
        offsets.addWidget(self._offset_x)
        offsets.addWidget(QLabel("Y:"))
        offsets.addWidget(self._offset_y)
        offsets.addWidget(QLabel("(−Y = up)"))
        offsets.addStretch(1)
```

Add below it:

```python
        # Nine-slice margins (ui category only): corners fixed, edges stretched
        # by the HUD backend. Omitted from the entry when all four are 0.
        self._slice_row = QWidget()
        slice_layout = QHBoxLayout(self._slice_row)
        slice_layout.setContentsMargins(0, 0, 0, 0)
        self._slice_l = QSpinBox()
        self._slice_t = QSpinBox()
        self._slice_r = QSpinBox()
        self._slice_b = QSpinBox()
        self._slice_spins = (self._slice_l, self._slice_t,
                             self._slice_r, self._slice_b)   # order = manifest order
        slice_layout.addWidget(QLabel("Nine-slice  L:"))
        for label, spin in zip(("T:", "R:", "B:"), self._slice_spins[1:]):
            spin.setRange(0, 1024)
            ...
```

Concretely: one `QLabel` before each spin (`"Nine-slice  L:"`, `"T:"`, `"R:"`,
`"B:"`), every spin `setRange(0, 1024)` initially (re-ranged per slot in
Edit 2) and `spin.valueChanged.connect(lambda _v: self._emit_draft())` — the
same wiring the offset spins use. Trailing `slice_layout.addStretch(1)`.

The row must be a **`QWidget` container**, not a bare layout, so `set_context`
can `setVisible(...)` it in one call. Register it in the panel layout right
after `layout.addLayout(offsets)` (`details.py:196`):

```python
        layout.addLayout(offsets)
        layout.addWidget(self._slice_row)
        layout.addWidget(self._info)
```

and hide it at construction: `self._slice_row.setVisible(False)` (next to
`self._set_buttons_enabled(False, False, False)`, `details.py:199`).

### Edit 2 — `set_slot` (`details.py:254-280`): reset, re-range, seed

Inside the existing `self._loading = True` block:

1. Next to `self._offset_x.setValue(0); self._offset_y.setValue(0)`
   (`details.py:260-261`), add `for spin in self._slice_spins: spin.setValue(0)`
   — reset **before** the `slot_key is None` early return, exactly like the
   offsets.
2. After `fw, fh = self.registry.frame_size(slot_key)` (`details.py:267`),
   re-range: `for spin, cap in zip(self._slice_spins, (fw, fh, fw, fh)):
   spin.setRange(0, cap)`.
3. In the `if entry:` block (`details.py:270-272`, next to the offsets read),
   seed from the entry:

```python
            if entry:
                self._offset_x.setValue(int(entry.get("offset_x", 0)))
                self._offset_y.setValue(int(entry.get("offset_y", 0)))
                margins = entry.get("slice") or ()
                if len(margins) == 4:
                    for spin, value in zip(self._slice_spins, margins):
                        spin.setValue(int(value))
```

(`_loading` is already True here, so seeding emits no draft.)

### Edit 3 — `draft_entry()` (`details.py:319-330`) + one helper

```python
    def draft_entry(self):
        """Current UI state as a manifest-v2 entry dict (None: no rows)."""
        if self.slot_key is None or not self._row_editors:
            return None
        entry = {
            "sheet": f"imported/{self.slot_key}.png",
            "frame_w": self._row_frame_size[0],
            "frame_h": self._row_frame_size[1],
            "offset_x": self._offset_x.value(),
            "offset_y": self._offset_y.value(),
            "rows": [editor.to_dict() for editor in self._row_editors],
        }
        margins = self._slice_margins()
        if margins is not None:
            entry["slice"] = margins
        return entry

    def _slice_margins(self):
        """[l, t, r, b] for a ui slot with at least one non-zero margin;
        None otherwise. `slice` is optional in the manifest — an unsliced
        entry must never grow the key (and re-saving with all-zero margins
        removes it, since save() replaces the whole entry)."""
        if not self._slice_applies():
            return None
        values = [spin.value() for spin in self._slice_spins]
        return values if any(values) else None

    def _slice_applies(self):
        """Nine-slice is a HUD-only feature -> the ui category only."""
        return self._context is not None and self._context[0] == "ui"
```

### Edit 4 — `set_context` (`details.py:203-207`): show/hide gating

After `self._context = (category_key, tuple(group_path))`:

```python
        self._slice_row.setVisible(self._slice_applies())
```

(before the dropdown rebuild; the trailing `self.set_slot(None)` on an empty
category then zeroes the spins as usual.)

### Edit 5 — `clear_entry` (`details.py:344-372`)

In the `self._loading = True` block that already zeroes the offsets
(`details.py:365-368`), also `for spin in self._slice_spins: spin.setValue(0)`
— clearing to the grey-X placeholder must not leave stale margins behind for
the next save.

### Non-edits (state them, don't do them)

- **`reload_registry()`** (`details.py:243-246`) only re-reads the registry.
  After a variant add MainWindow calls `set_context` + `set_slot` again
  (`editor/main.py:394-400`), which re-ranges and re-seeds the spins. **No
  change needed.**
- **`viewport.py`** — nothing. `set_preview_draft` (`viewport.py:188-200`) hands
  the dict to `entry_from_dict`, which A2 taught to parse `slice`; the
  `RenderItem` preview path ignores it. Verify by test only.
- **`editor/main.py`** — nothing. `draft_changed` / `entry_saved` /
  `entry_cleared` (`main.py:108-110`) already carry the entry dict wholesale.
- **`RowEditor`** — nothing. `slice` is entry-level, not per-row.

### Edit 6 — docs: `editor/panels/CLAUDE.md`

Extend the **DetailsPanel** bullet in the "Phase 5 — merged tree / details /
entity preview" section (line ~184) with two sentences:

- the slice-margins editor: 4 spinboxes (L/T/R/B), **ui category only** (gated
  on `self._context[0]`), bounded by the slot's frame size, writing the optional
  manifest `slice` field; **all-zero ⇒ the key is omitted** (a slot with no
  nine-slice keeps a byte-identical entry, and zeroing un-slices on the next
  save). Nine-slice is drawn on the HUD path only — the entity preview
  (`RenderItem`) deliberately ignores it.
- **ui variants = skins**: the `ui` category's leaves offer "+ Variant"
  (`MainWindow._VARIANT_TARGETS`, added in A3) → `ui_button_v2`, … , i.e. one
  slot per button skin; its 4-row vocab is `idle/hover/pressed/disabled`
  (row 0 locked to idle as everywhere).

---

## 3. File scope + shared-file contract

A4's coder works on `phase-10L-finish-umbrella`, **in parallel with A5′** (which
touches `game/**` only) and **B4** (which touches `editor/**` only). **A4 may
touch exactly these four files:**

| File | What A4 does |
|---|---|
| `editor/panels/details.py` | the slice-margins editor (Edits 1–5) |
| `tools/tests/test_details_panel.py` | extend — slice round-trip, ui-only gating, omit-when-zero, 4-row ui vocab |
| `tools/tests/test_editor_viewport.py` | extend ONLY for the draft-with-slice preview test; **do not** touch its `TestPurity` import list (lines 196-203) — you are adding no module |
| `editor/panels/CLAUDE.md` | doc update (Edit 6; the plan's doc obligation, line 152) |

**A4 must NOT touch:** `data/schemas/*` (A2 owns), `data/slots.json` and
`editor/main.py` (A3 owns), any `engine/**` or `game/**` file. If the slice key
won't validate, that is an A2 problem — report it, do not edit the schema.

---

## 4. Exit gate + Quick Test

### Commands

```
py tools/smoke.py
py tools/testgate.py check --affected
```

**Gate = ZERO failures.** The affected tests (A4's new tests plus
`test_details_panel`, `test_editor_viewport`) must all pass.

### New tests

**`tools/tests/test_details_panel.py` — one new `class TestSliceMargins(DetailsCase)`**
(reuse `DetailsCase` + `make_png`; a ui button sheet is `make_png(p, 2*64, 4*64)`
against ui's 64×64 frame):

1. `test_ui_context_shows_the_slice_row_and_others_hide_it` —
   `set_context("ui", ("Buttons",))` → `panel._slice_row.isVisible()` is True (on
   a shown panel; assert `not isHidden()` headlessly);
   `set_context("buildings", ("Defender",))` → hidden.
2. `test_slice_spin_bounds_come_from_the_frame_size` — on `ui_button` (64×64):
   each spin's `minimum() == 0`, L/R `maximum() == 64`, T/B `maximum() == 64`.
   (Also assert a 64×96 buildings slot would cap T/B at 96 — proves the axis
   mapping, even though the row is hidden there.)
3. `test_slice_round_trips_through_save_and_reload` — ui context, import the
   4-row sheet on `ui_button`, set `(8, 6, 8, 6)`, `save()` → the manifest entry
   (loaded via `self.manifest_doc()`, i.e. **schema-validated**) has
   `entry["slice"] == [8, 6, 8, 6]`; then `panel.set_slot(None)` +
   `panel.set_slot("ui_button")` re-seeds the four spins to `(8, 6, 8, 6)`.
4. `test_all_zero_margins_omit_the_slice_key` — same import, margins untouched,
   `save()` → `"slice" not in entry`; and `draft_entry()` has no `"slice"` key.
5. `test_zeroing_margins_removes_the_key_on_resave` — save with `(8,6,8,6)`,
   set all four back to 0, `save()` again → `"slice" not in entry`.
6. `test_non_ui_category_never_emits_slice` — `set_context("buildings",
   ("Defender",))`, import a 64×96 painter sheet, force a spin value
   (`panel._slice_l.setValue(9)`), `save()` → `"slice" not in entry` and
   `draft_entry()` has no `"slice"`.
7. `test_slice_edit_emits_a_draft` — connect `draft_changed`, change a spin →
   the last emitted dict carries `slice == [ ... ]` (the live-preview path).
8. `test_four_row_button_sheet_offers_the_ui_vocabulary` (the 1b verification) —
   import the 4-row sheet on `ui_button`: 4 `RowEditor`s; row 0 combo items ==
   `["idle"]` and `isEnabled()` is False; rows 1–3 items ==
   `["idle","hover","pressed","disabled"]`, current texts ==
   `"hover"`, `"pressed"`, `"disabled"`; `save()` → the entry's
   `[r["animation"] for r in entry["rows"]]` ==
   `["idle","hover","pressed","disabled"]`.

**`tools/tests/test_editor_viewport.py` — one new test** (extend
`TestEntityPreview`, or a small `TestSlicedDraftPreview(TempDataCase)` beside
it; no `TestPurity` change):

9. `test_draft_with_slice_previews_and_never_touches_disk` — a ui draft dict
   (`sheet: imported/ui_button.png`, `frame_w/h: 64`, 2 rows idle+hover,
   `"slice": [8, 8, 8, 8]`); `set_preview_slot("ui_button")` →
   `set_preview_draft("ui_button", draft)` → `preview_animations() ==
   ("idle", "hover")` (i.e. it took the **happy** path, not
   `set_preview_draft`'s `ValueError` fallback), `render_frame()` raises
   nothing, and the on-disk manifest still has no `ui_button` entry. Write the
   `imported/ui_button.png` into the temp `data/` first (Pillow, as
   `test_details_panel` does) so the store can load it.

### Quick Test (human, live editor — plan lines 146–149, editor half)

`py editor/main.py` → tree → **UI → Buttons → `ui_button`**:

1. **Import Spritesheet…** a 4-row animated button sheet (128×256: 2 frames ×
   4 states at 64×64). Expect 4 Row editors; Row 0 titled "(idle — required)"
   with a locked `idle` combo; Rows 1/2/3 pre-set to hover / pressed / disabled;
   the info line reads `2 cols × 4 rows  (64×64/frame)`.
2. The **Nine-slice L/T/R/B** row is visible (it is NOT, on a Defender or a map
   tile — check one of each). Set e.g. `L=12 T=10 R=12 B=10`.
3. In the viewport, switch the floating animation dropdown through
   idle → hover → pressed → disabled: **the entity preview animates the
   selected row** (this is the "already works via the one render path once A1
   lands" claim — the preview is a world sprite, so it will NOT show the
   nine-slice stretch; that lands with A5′'s skinned HUD button).
4. **Save** → `data/sprites/asset_manifest.json` gains
   `"ui_button": { …, "slice": [12, 10, 12, 10] }` and `py tools/smoke.py`
   stays green. Zero all four, Save again → the `slice` key is **gone** from
   that entry.
