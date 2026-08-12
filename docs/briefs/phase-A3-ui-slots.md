> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase A3 — data: `ui` category expansion (slice 10L-A)

Branch: `phase-A3-ui-slots`. Plan: `planning/UI_EDITOR_PLAN.md` §A3 (lines 112–123),
architecture note lines 70–73. This file is the contract — implement exactly this.

---

## 1. Behavioral spec

### 1.1 What exists today
`data/slots.json:529-547` — the `ui` category:

```json
{ "animations": ["idle"], "display_name": "UI", "frame_h": 64, "frame_w": 64,
  "groups": [ { "label": "HUD",
                "slots": ["ui_button", "ui_panel", "ui_icon_resource"] } ],
  "key": "ui" }
```

A placeholder. **Zero references** to `ui_button` / `ui_panel` / `ui_icon_resource`
or the `HUD` group exist in `game/`, `engine/`, `editor/`, `tools/`, or
`data/sprites/asset_manifest.json` (verified by grep). `ui_icon_resource` is
**dropped**; nothing consumes it. This restructure breaks no code and no art.

### 1.2 Target `ui` category — write it EXACTLY like this

Formatting is `engine.data_io.dumps_deterministic` output (sorted keys, 2-space
indent). Object keys sort (`children` < `label`; `frame_h` < `frame_w` < `key`);
**array order is meaningful and is NOT sorted** — `animations[0]` must stay
`idle`, and `groups[]` order is the editor tree order.

```json
    {
      "animations": [
        "idle",
        "hover",
        "pressed",
        "disabled"
      ],
      "display_name": "UI",
      "frame_h": 64,
      "frame_w": 64,
      "groups": [
        {
          "children": [
            {
              "label": "Button",
              "slots": [
                "ui_button"
              ]
            }
          ],
          "label": "Buttons"
        },
        {
          "children": [
            {
              "label": "Panel",
              "slots": [
                "ui_panel"
              ]
            },
            {
              "label": "Stone Panel",
              "slots": [
                "ui_panel_stone"
              ]
            }
          ],
          "label": "Panels"
        },
        {
          "children": [
            {
              "label": "Love",
              "slots": [
                "ui_icon_love"
              ]
            },
            {
              "label": "XP",
              "slots": [
                "ui_icon_xp"
              ]
            },
            {
              "label": "Lives",
              "slots": [
                "ui_icon_lives"
              ]
            }
          ],
          "label": "Icons"
        },
        {
          "children": [
            {
              "label": "Main Menu",
              "slots": [
                {
                  "frame_h": 270,
                  "frame_w": 480,
                  "key": "ui_bg_main_menu"
                }
              ]
            }
          ],
          "label": "Backgrounds"
        }
      ],
      "key": "ui"
    },
```

Nothing else in `slots.json` changes. Do not touch any other category.

### 1.3 Animation vocabulary
`["idle", "hover", "pressed", "disabled"]` — button states become manifest rows
(plan decision 2). The schema (`data/schemas/slots.schema.json:95-109`) requires
`prefixItems[0].const == "idle"` (row 0 = idle, E-35) and items matching
`^[a-z][a-z0-9_]*$` with `uniqueItems` — all four names validate as-is, **no
schema edit is needed or allowed** in A3. Every ui slot inherits this vocabulary
(`SlotRegistry.animations` is per-category, `engine/assets/registry.py:152-153`),
so the icon/panel/background slots also *offer* hover/pressed/disabled rows in the
importer; partial sheets are fine — a missing row falls back to idle at frame
resolution (`engine/assets/CLAUDE.md`, E-36).

### 1.4 Group structure — WHY it is nested (the load-bearing decision)

**The four groups must each be a PARENT group holding leaf children — a flat
`{label, slots:[...]}` group would silently kill "+ Variant".** Chain of evidence:

- `editor/selection.py:74-86` `variant_target()`: `if group is None or not
  group.children: return None`. A flat leaf group has no `children` → **None** →
  `MainWindow._variant_target` returns None → the "+ Variant" button is dead.
- `editor/registry_ops.py:81-112` `add_variant(data_dir, category_key,
  group_path, subcat_label)` walks `group_path` to a **parent** group, then looks
  for `group["children"]` whose `label == subcat_label` and which has a `slots`
  list (`KeyError` otherwise). It structurally cannot extend a top-level flat
  group.
- This is exactly the shape `enemies` and `deco` already use, and they are the two
  categories that already work with `_VARIANT_TARGETS[...] = None`:
  `enemies`: `Walker → Era 2 → [enemy_stage_2]`; `deco`: `Props → Rock →
  [deco_rock]` (`data/slots.json`, both verified). Mirror them.
- Contrast `backgrounds` (`data/slots.json:642-649`), a flat group: its
  subcategories resolve to the raw slot key and it has no variant affordance —
  pinned by `tools/tests/test_editor_selection.py:46-53`.

Resulting editor behavior (`editor/panels/selector.py:143-151` recurses only while
some child has children of its own): the tree stops at **Buttons / Panels / Icons /
Backgrounds**; the Details subcategory dropdown lists that group's child labels
(`Button`; `Panel`, `Stone Panel`; `Love`, `XP`, `Lives`; `Main Menu`); the level
bar lists that child's slots (one each today, i.e. the skin list). So each leaf is
a **variant family = a skin family**, which is precisely the semantics the plan
asks for.

Group `label` is any non-empty string (schema 27-31) — the labels above are free
choices; keep them verbatim so the tests match.

### 1.5 Frame sizes
- Category default stays **64×64** (`frame_w`/`frame_h`) — `ui_button`,
  `ui_panel`, `ui_panel_stone` and the three icons are bare keys and inherit it.
  The icons' "(64×64)" in the plan IS the category default; **no override for
  them**. Buttons/panels are small source cells stretched to the destination rect
  by A2's nine-slice — the sheet cell size and the on-screen size are different
  questions (`data/CLAUDE.md`: "slicing, not drawing").
- **`ui_bg_main_menu` = 480×270, via the per-slot object form** `{key, frame_w,
  frame_h}` (`slot_entry`, schema 55-83). This solves the whole-sheet gotcha:
  `DetailsPanel._load_sheet` (`editor/panels/details.py:395-401`) slices the
  imported PNG by `registry.frame_size(slot_key)` → `cols, rows = w // fw, h // fh`,
  and `_entry()` (`details.py:320-329`) writes those numbers into the manifest
  entry. Left at 64×64 a 480×270 sheet would be grid-sliced into 7×4 frames
  instead of one. With the override it slices to exactly **1 col × 1 row** — the
  whole-sheet single frame the plan's architecture note (lines 70-73) requires.
- **Where 480×270 comes from:** the existing `backgrounds` category declares
  `frame_w: 480 / frame_h: 270` (`data/slots.json:634-651`) for `main_menu_bg`,
  its committed manifest entry is 480×270 (`data/sprites/asset_manifest.json:1105-1121`),
  and `data/CLAUDE.md` states "backgrounds 480×270 (10K full-frame menu art, drawn
  as a screen-space `HudSprite`)". `data/display.json` gives the logical view as
  1280×720 (`window_w`/`window_h`; the logical surface is view-sized in every
  display mode, `game/main.py:94-105`) — the art is authored at 480×270 and
  upscaled to the full view (`game/ui/main_menu.py:8-11`, "letterbox-safe because
  the host's SCALED logical surface is what gets letterboxed"). **Mirror the
  existing background: 480×270.**
- Loader cross-check (`engine/assets/registry.py:95-104`): a key repeated inside
  one category must agree on its frame size, and a key may not appear in two
  categories. `ui_bg_main_menu` is a NEW key — no collision with `main_menu_bg`.

### 1.6 Note for the reviewer (do not act on it in A3)
10K's asset half is **already shipped**: `backgrounds/main_menu_bg` exists, has
imported art, and is what `game/ui/main_menu.py` draws. `ui_bg_main_menu` is added
per the plan as an *unconsumed* slot so 10L-B's screen-background picker (which
sources **ui** slots from the registry, plan §B4) has something to offer. Nothing
in the game reads it after A3. Flag in the PR that a later phase should decide
whether the picker sources the `backgrounds` category instead of duplicating the
slot.

---

## 2. Architecture plan (edits, in order)

1. **`data/slots.json`** — replace the `ui` category's `animations` array and
   `groups` array with §1.2 verbatim. Everything else in the file untouched.
   Preferred mechanic: edit the JSON, then round-trip it through
   `engine.data_io.write_validated(doc, data/slots.json, data/schemas/slots.schema.json)`
   (a 5-line throwaway script, not committed) so the formatting is canonically
   D-3 and validation is proven at write time — never hand-format.
2. **Validation happens for free.** `engine.assets.load_registry`
   (`engine/assets/registry.py:156-160`) loads through `data_io.load_validated`
   against `slots.schema.json` and **fails loud**; `SlotRegistry.__init__` then
   cross-checks duplicate keys and frame-size agreement (95-104), and
   `_parse_group` normalises the `{key,…}` object form away so `GroupNode.slots`
   stays a tuple of key strings downstream. `tools/smoke.py::validate_data`
   stem-pairs `slots.json` ↔ `schemas/slots.schema.json`, so smoke is the second
   gate.
3. **`editor/main.py:349`** — one line:
   ```python
   _VARIANT_TARGETS = {"enemies": None, "deco": None, "map": {"Background"},
                       "ui": None}
   ```
   (`None` = every leaf subcategory of that category offers it.) Optionally extend
   the surrounding comment: for `ui` the affordance is a **skin** add. No other
   editor change is needed — `_variant_target` (349-367) and
   `_on_add_variant`/`_add_variant_slot` (369-394) are category-agnostic and route
   everything that is not `map` to `registry_ops.add_variant`, which appends
   `<stem>_v<k>` via `next_variant_key` (a bare slot counts as v1, so the first add
   is `_v2`) and reloads every cached registry + reselects the new slot.
4. **What "+ Variant" does for ui:** select `UI → Buttons` in the tree, subcategory
   `Button`, press **+ Variant** → `registry_ops.add_variant(data_dir, "ui",
   ("Buttons",), "Button")` → `slots.json` gains `ui_button_v2` in that leaf →
   the level bar shows two skins; import a different sheet onto each. Same for
   `Panels/Panel`, `Icons/Love`, `Backgrounds/Main Menu`
   (`ui_bg_main_menu_v2` — note it inherits **64×64**, not the override; that is
   the documented `add_variant` behavior, pinned by
   `test_registry_ops.test_object_form_entries_do_not_break_the_variant_walk`).
   No game change: nothing consumes ui slots yet (A5/10L-B do).
5. **Tests** — extend the two files named in §3.

Not in A3: the slice-margins editor (A4), the manifest `slice` field (A2), any
`game/` hook (A5). Do not touch them.

---

## 3. File scope + shared-file contract (binding)

A3's coder works alone on branch `phase-A3-ui-slots`, in parallel with the A1+A2
engine coder (who does NOT touch `data/` or `editor/`). A3's file scope:

- `data/slots.json` (**ui category only** — do not touch other categories)
- `editor/main.py` (the `_VARIANT_TARGETS` dict line ONLY — plus its comment if a
  ui note helps)
- `tools/tests/test_assets_registry.py` and `tools/tests/test_registry_ops.py`
  (extend)

**A3 must NOT touch** `data/schemas/asset_manifest.schema.json` (A2 owns it),
`editor/panels/details.py` (A4 owns it), or any `engine/` / `game/` file.
`data/schemas/slots.schema.json` needs **no** change — if you think it does, stop
and say so instead of editing it.

---

## 4. Exit gate + Quick Test

### Commands
```
py -m unittest discover -s tools/tests -t .     # baseline: 1086 tests, 16 failures, 1 skipped
py tools/smoke.py                                # slots.json is schema-paired -> must pass
```
Gate = **no NEW failures**. The 16 are pre-existing on `Development`
(`test_details_panel::TestSubcategoryDropdown`, `test_editor_viewport::TestEntityPreview` ×3,
`test_editor_panels` ×2, `test_editor_map_mode` ×2, `test_run_controls`,
`test_balancing_parity` ×6). Do not "fix" them. Report the failure count before
and after.

### New tests (name them exactly)
- `tools/tests/test_assets_registry.py`, in `TestRealRegistry` (runs against the
  real `data/`) — **`test_ui_vocabulary_and_frame_sizes`**:
  - `self.reg.animations("ui_button") == ("idle", "hover", "pressed", "disabled")`
    (and the same for `ui_icon_love` — vocabulary is per-category);
  - `self.reg.frame_size("ui_button") == (64, 64)`,
    `self.reg.frame_size("ui_icon_love") == (64, 64)`,
    **`self.reg.frame_size("ui_bg_main_menu") == (480, 270)`** (the whole-sheet
    override — this is the assertion that pins the gotcha);
  - `self.reg.category_of("ui_button").key == "ui"`;
  - group shape: `tuple(g.label for g in self.reg.category("ui").groups) ==
    ("Buttons", "Panels", "Icons", "Backgrounds")` and
    `tuple(c.label for c in self.reg.group("ui", ("Icons",)).children) ==
    ("Love", "XP", "Lives")`.
- `tools/tests/test_registry_ops.py`, in `TestAddVariant` (a `TempDataCase`, so it
  writes to a temp copy of `data/`) — **`test_ui_skin_variant`**:
  - `registry_ops.add_variant(self.data_dir, "ui", ("Buttons",), "Button") ==
    "ui_button_v2"`;
  - re-`load_registry(self.data_dir)` (proves the write validated) and
    `reg.group_slots("ui", ("Buttons", "Button")) == ("ui_button", "ui_button_v2")`;
  - **the structural claim**: `editor.selection.variant_target(reg, "ui",
    ("Buttons",), 0) == "Button"` — i.e. the nested group shape is what makes the
    "+ Variant" button live. (Import `from editor import selection` in that file.)

### Human Quick Test (live)
1. `py editor/main.py`.
2. In the tree, expand **UI** → see exactly four groups: **Buttons, Panels, Icons,
   Backgrounds** (no "HUD").
3. Select **Buttons** → the Details subcategory dropdown shows `Button`; the row
   editors offer the animation vocabulary `idle / hover / pressed / disabled` with
   **row 0 locked to `idle`**.
4. Press **+ Variant** → status bar reports the new slot, the level bar gains a
   second entry, and `data/slots.json` now holds `ui_button_v2` under
   `Buttons → Button`. Revert that test write before committing (or commit only
   the intended `ui` category — `git diff data/slots.json` must show no
   `_v2` slot).
5. Select **Backgrounds → Main Menu** and import any 480×270 PNG: the Details
   header must read **`1 cols × 1 rows  (480×270/frame)`** — not a grid. (Clear the
   entry afterwards; A3 commits no art.)
