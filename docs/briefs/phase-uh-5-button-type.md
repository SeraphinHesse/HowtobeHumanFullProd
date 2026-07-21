# Phase UH-5 — Editor: "+ Button Type" (new ui slot-registry family)

Plan: `planning/UiEditorHonestyPLAN.md` §4 UH-5 (lines 135–148). Branch:
`phase-UH-1-UH-6-umbrella` (umbrella execution). Package: **editor only**
(`editor/registry_ops.py`, `editor/main.py`, `editor/panels/level_bar.py`
one-liner) + tests.

**PLAN-vs-REALITY correction (binding):** the plan names
`editor/main_window.py`; that file does not exist. The Qt shell — where the
"+ Variant" affordance and its handlers live — is **`editor/main.py`**
(`MainWindow`). Every "main_window.py" reference in the plan's UH-5 and UH-2
rows means `editor/main.py`.

**Design in one sentence:** a new button **family** is a new leaf child group
`{label, slots: [ui_button_<slug>]}` appended under ui → Buttons in
`data/slots.json` — exactly the shape `add_deco_prop` already writes for deco
(`editor/registry_ops.py:259-269`) — reached from the LevelBar's existing
"+ Type" button (`editor/panels/level_bar.py:50-55`), which today is
deco-only.

---

## 1. Behavioral spec

### 1a. Current behavior (baseline, with citations)

- **Data shape.** ui → Buttons is a parent group of 8 leaf children, one per
  button type, each holding one bare-string slot (`data/slots.json:579-631`:
  "Menu Button"/`ui_button` … "Choice Box"/`ui_choice_box`). The ui category's
  frame size is 64×64 (`data/slots.json:576-577`) and its animation vocabulary
  is `["idle","hover","pressed","disabled"]` (`data/slots.json:569-574`). A
  bare-string slot entry inherits the category frame size (the D-rule:
  `data/CLAUDE.md` "slots[] entries: bare key OR frame-size override"); slot
  keys must match `^[a-z][a-z0-9_]*$` (`data/schemas/slots.schema.json:37`).
- **"+ Variant" exists for ui, "+ Type" does not.** `MainWindow._VARIANT_TARGETS`
  includes `"ui": None` (`editor/main.py:501-502`), so every ui leaf offers
  "+ Variant" (another *skin* of an existing type). The LevelBar's second
  button "+ Type" (`editor/panels/level_bar.py:50-55`, signal
  `add_type_requested`) is shown only for deco:
  `can_add_type=category_key == self._DECO_CATEGORY`
  (`editor/main.py:491`), and its handler `_on_add_prop`
  (`editor/main.py:622-640`, wired at `editor/main.py:116`) always calls
  `registry_ops.add_deco_prop`.
- **The pattern to copy.** `registry_ops._append_child_group`
  (`editor/registry_ops.py:238-257`) appends `{label, slots: [slot]}` to a
  group's `children`, writing through `engine.data_io.write_validated` against
  `data/schemas/slots.schema.json`. `add_deco_prop`
  (`editor/registry_ops.py:259-269`) is its one caller today.
- **Skin dropdowns are registry-driven — VERIFIED, but the reload is not
  wired.** All three skin combos populate from
  `self._registry.group_slots("ui")`
  (`editor/panels/screen_details.py:259-265`, called for `skin_combo`,
  `button_skin_combo`, `panel_skin_combo` at
  `editor/panels/screen_details.py:220-222`). A `reload_registry()` method
  exists (`editor/panels/screen_details.py:288-294`) **but is never called
  from anywhere** — `MainWindow._reload_registries()`
  (`editor/main.py:576-580`) refreshes only selector/details/viewport. So the
  plan's "skin combo already registry-driven (verify, no change expected)" is
  half right: population is registry-driven, but "appears in every skin
  dropdown **without restart**" requires one wiring line (§2c). This is also a
  latent staleness bug for today's ui "+ Variant".

### 1b. New behavior

From the editor, with the ui → Buttons tree node selected:

1. The LevelBar shows **"+ Type"** beside "+ Variant" (it already sits beside
   it structurally — `editor/panels/level_bar.py:44-55`).
2. Clicking it opens a small **naming dialog**: the designer types a type name
   (e.g. `Tab`); the dialog live-previews the derived slot key
   (`ui_button_tab`). OK is refused (or the op raises and the status bar
   reports) for an empty/unsluggable name or a collision.
3. On accept, a new leaf child `{"label": "Tab", "slots": ["ui_button_tab"]}`
   is appended under ui → Buttons via a validated write to `data/slots.json`.
4. **Immediately, without restart:** the family appears in the selector tree
   under UI → Buttons, in the Details subcategory dropdown (auto-selected,
   ready to import onto — grey-X until art, E-37), in the LevelBar (with
   "+ Variant" available: it is a variant family like the other eight), and in
   **every skin dropdown** (`skin_combo`, `button_skin_combo`,
   `panel_skin_combo` in screen mode).
5. The new slot is a **bare string** — it inherits the ui category's 64×64
   frame size (the D-rule default; `data/slots.json:576-577`) and the 4-state
   animation vocabulary, and stays independently resizable afterwards via the
   existing Frame W/H spinboxes (`registry_ops.set_slot_frame_size`,
   `editor/registry_ops.py:81-121`).

**OUT of scope (plan line 147-148):** new *behavior* widget classes and any
`game/**` change. A new family is art + a skin key; making a widget of a new
KIND remains a dispatched game-code task. Deco/map "+ Type"/"+ Level"
behavior is unchanged.

---

## 2. Architecture plan

### 2a. `editor/registry_ops.py` — the new-family op (pure, TestPurity-safe)

Two additions, placed after `add_deco_prop` (after line 269), reusing
`_append_child_group` and `_all_slots` verbatim:

```python
def button_family_slot(name):
    """Derive the slot key for a new ui button family from a human name.
    Slug = lowercased, every non-[a-z0-9] run collapsed to one "_", trimmed.
    Prefix "ui_button_" is added unless the slug already starts with
    "ui_button" (typing the key itself must not double-prefix).
    Raises ValueError when nothing slug-like survives."""

def add_button_family(data_dir, name):
    """Append a new leaf child group {label, slots: [key]} under
    ui -> Buttons. label = name.strip(); key = button_family_slot(name).
    Raises ValueError (BEFORE any write) when the key collides with any slot
    in the registry (_all_slots) or the label collides with an existing
    Buttons child label. Returns (label, slot_key), like add_deco_prop."""
```

Contract points:

- **Validate before writing.** Load the doc, run both collision checks and the
  slug check, and only then call `_append_child_group` — a rejected add must
  leave `data/slots.json` byte-identical.
- **Bare-string slot entry** — that IS the frame-size default per the D-rules
  (inherit category 64×64); never write an override dict here.
- The write path is `_append_child_group` → `data_io.write_validated` against
  `schemas/slots.schema.json` (`editor/registry_ops.py:244-256`) — the derived
  key satisfying the schema's `^[a-z][a-z0-9_]*$` pattern
  (`data/schemas/slots.schema.json:37`) is guaranteed by the slug rule.
- `ValueError` for name problems, `KeyError` for structural path problems
  (matching the module's existing split; the shell already catches both —
  `editor/main.py:627`).

### 2b. `editor/main.py` — affordance, dialog, handler

- **Gate constant** beside `_VARIANT_TARGETS`/`_DECO_CATEGORY`
  (`editor/main.py:501-503`): `_BUTTON_TYPE_NODE = ("ui", ("Buttons",))`.
- **`_refresh_levels`** (`editor/main.py:482-492`): the `can_add_type` kwarg
  (line 491) becomes
  `category_key == self._DECO_CATEGORY or self._node == self._BUTTON_TYPE_NODE`.
- **Rewire line 116**: `self.levelbar.add_type_requested.connect(self._on_add_type)`
  where the new `_on_add_type` dispatches:
  `self._node == self._BUTTON_TYPE_NODE` → `_on_add_button_type()`, else the
  existing `_on_add_prop()`. The palette's own "+ Add Prop" wiring stays
  pointed at `_on_add_prop` untouched.
- **`_on_add_button_type(self, name=None)`** — new method inserted directly
  after `_on_add_prop` (after `editor/main.py:640`), mirroring its shape:
  - `name is None` → open the naming dialog (modal); cancelled → return.
    The `name=` parameter is the test seam (same philosophy as
    `dirty_policy` / injectable `detach` elsewhere — tests never exec a modal).
  - `registry_ops.add_button_family(self._data_dir, name)` inside the same
    `except (KeyError, OSError, ValueError)` → status-bar message pattern as
    `_on_add_prop` (`editor/main.py:625-629`).
  - On success: `self._reload_registries()`, then
    `self.details.set_context("ui", ("Buttons",))` +
    `self.details.select_subcategory_label(label)`
    (`editor/panels/details.py:415`) + `self._refresh_levels()` — the exact
    mirror of `_on_add_prop`'s non-map branch (`editor/main.py:635-639`) —
    then a status message. No `palette.reload_registry()` needed (ui slots
    never reach the map palette).
  - **Dialog**: keep it inside `editor/main.py` (a `QInputDialog.getText`
    loop, or a ~20-line `QDialog` with a derived-key preview label — executor's
    choice; the map-details New-map dialog is the precedent for the fancier
    form). **No new module** — if the executor does split one out, it MUST be
    added to `test_editor_viewport.TestPurity`'s import list
    (`editor/CLAUDE.md` hard rule).
- **`_reload_registries`** (`editor/main.py:576-580`): append one line,
  `self.screen_details.reload_registry()` — the missing wire from §1a that
  makes "every skin dropdown, without restart" true, for this phase's new
  families AND for existing ui "+ Variant" adds. `reload_registry` re-reads
  slots.json and repopulates all three skin combos + the background combo
  (`editor/panels/screen_details.py:288-294`); it is selection-state-safe (it
  only rebuilds combo items).

### 2c. `editor/panels/level_bar.py` — tooltip honesty (one line)

The "+ Type" tooltip is deco-specific ("Add a brand-new decoration type…",
`editor/panels/level_bar.py:51-52`). Generalize to "Add a brand-new type (its
own variant family)" — D3 (honest controls) applies to tooltips too. No other
LevelBar change: `set_levels(..., can_add_type=…)` already forces the bar
visible for single-slot lists (`editor/panels/level_bar.py:58-82`).

### 2d. Docs

`editor/panels/CLAUDE.md`'s "+ Variant / + Type" section (~line 171) currently
says "+ Type (deco only)" — update it to record the ui → Buttons target and
the `_reload_registries` → `screen_details.reload_registry()` wire. (Panel
architecture changed → panels doc, per `editor/CLAUDE.md` header.)

---

## 3. File scope + shared-file contract

| File | UH-5 change |
|---|---|
| `editor/registry_ops.py` | ADD `button_family_slot` + `add_button_family` after line 269; module docstring gains one sentence. Nothing existing is modified. |
| `editor/main.py` | **SHARED with UH-2 — see contract below.** Line 116 (connect target), line 491 (`can_add_type` expr), lines 501-503 (+1 const), lines 576-580 (+1 reload line), new methods after line 640 (`_on_add_type`, `_on_add_button_type`, dialog helper). |
| `editor/panels/level_bar.py` | Lines 51-52 tooltip text only. |
| `editor/panels/CLAUDE.md` | "+ Variant / + Type" section update (§2d). |
| `tools/tests/test_registry_ops.py` | New test classes (§4). |
| `tools/tests/test_editor_panels.py` | New window-integration tests beside the existing +Variant/+Type block (lines ~885-974). |

**Must NOT touch:** `editor/panels/screen_details.py` (UH-5 only *calls* its
existing `reload_registry`; UH-2/3/4 own edits to that file),
`data/slots.json` (live content — the Quick Test writes it via the running
editor, tests use `TempDataCase` copies), `data/schemas/slots.schema.json` (the
shape being written is already legal — `add_deco_prop` writes it today),
`editor/panels/selector.py`, `editor/panels/details.py`, any
`game/**`/`engine/**`.

**SHARED-FILE CONTRACT — `editor/main.py` (the plan's "main_window.py"), UH-2
lands beside this phase:**

- **UH-5 claims exactly:** the levelbar wiring line 116 (inside the
  `__init__` selection-wiring block, lines 114-122); `_refresh_levels`
  line 491; the class-constant block lines 501-503; `_reload_registries`
  lines 576-580; and a pure insertion after `_on_add_prop` (line 640).
- **UH-2 is expected in:** the screen-mode `__init__` wiring block
  (lines 151-156), `_on_screen_selected` / `_enter_screen_mode` /
  `_leave_screen_mode` (lines ~380-420), and the Refresh-Layouts handlers
  (`_on_build_started`/`_on_build_finished` region). **UH-5 must not edit any
  of those.**
- The only shared *function* is none; the only adjacency risk is `__init__`
  (two different wiring blocks ~35 lines apart) and any UH-2 decision to call
  `_reload_registries` — if UH-2 adds calls to it, UH-5's extra line is
  additive and merge-safe. Whichever phase lands second rebases mechanically;
  neither may relocate the other's regions.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py -m pytest tools/tests/test_registry_ops.py tools/tests/test_editor_panels.py -q
py tools/smoke.py
py tools/testgate.py check        # full, ONCE, at handoff — gate is ZERO
```

**Why the explicit pytest line is mandatory, not belt-and-braces:** the
testgate `--affected` selector has a known **vacuous-pass bug**
(`tools/testgate.py:222-238`, plan §5 lines 183-185): `affected_modules` maps
changed files to test modules via the Graphify blast radius, and an
editor-tier-only diff can select (nearly) nothing yet still print PASS. Until
that is fixed, this phase names its test modules explicitly —
`tools/tests/test_registry_ops.py` and `tools/tests/test_editor_panels.py` —
and runs them directly. The full `check` still runs exactly once before
handing back (router Step 2).

### New unit tests — `tools/tests/test_registry_ops.py`

Table tests (plain `unittest.TestCase`, like `TestNextVariantKey` at lines
16-38):

- `TestButtonFamilySlot`: `"Tab"` → `ui_button_tab`; `"Big Red  Button"` →
  `ui_button_big_red_button`; `"ui_button_tab"` → `ui_button_tab` (no double
  prefix); `""` / `"###"` → `ValueError`.

Registry tests (`TempDataCase`, like `TestAddVariant` at line 41 — **pin the
fixture, never assert live-data specifics**):

- `test_add_button_family_appends_validates_and_inherits_frame_size`: add
  `"Tab"`; returns `("Tab", "ui_button_tab")`; `load_registry` reloads without
  error (schema-valid result + loader cross-checks);
  `reg.group_slots("ui", ("Buttons", "Tab"))` (or equivalent) contains the new
  slot; the raw doc's appended entry `isinstance(str)` (bare — the
  **frame-size default** pin) and `reg.frame_size("ui_button_tab") ==
  reg.category("ui")` frame size (inheritance, not a written 64×64).
- `test_name_collision_raises_and_writes_nothing`: add `"Tab"` once; snapshot
  `slots.json` bytes; adding `"Tab"` again (and `"ui_button_tab"`, the key
  form) raises `ValueError`; file bytes unchanged. (Self-pinned collision —
  do NOT assert against a live family name like "Pause".)
- `test_new_family_is_variantable`: after adding `"Tab"`,
  `registry_ops.add_variant(data_dir, "ui", ("Buttons",), "Tab")` yields
  `ui_button_tab_v2` — proves the created shape is a real variant family
  (the "leaf child, never flat slots" rule in `data/CLAUDE.md`).

### New integration tests — `tools/tests/test_editor_panels.py`

Beside the existing block (lines ~885-974), `QtCase`/`self.track`d,
`TempDataCase`-backed:

- `test_add_type_button_shown_on_ui_buttons_node`: select ui → Buttons →
  `levelbar._add_type_btn` visible; select a non-Buttons ui node and an
  enemies node → hidden (extends the matrix at lines 885-909).
- `test_add_button_type_creates_family_and_refreshes_skin_combos`: select
  ui → Buttons; call `window._on_add_button_type(name="Tab")` (injected —
  no modal); assert Details subcategory shows "Tab", levelbar rebuilt, AND
  `window.screen_details.skin_combo` + `button_skin_combo` item lists contain
  `ui_button_tab` — the **no-restart** pin that fails red if the
  `_reload_registries` wiring line is dropped.
- `test_add_button_type_rejection_reports_not_crashes`: injected duplicate
  name → status-bar message path, no exception, no doc change.

### Quick Test (human, live editor + game)

1. `py editor/main.py` → tree → **UI → Buttons** → LevelBar shows
   **"+ Type"** beside "+ Variant". Click it, type `Tab` (dialog previews
   `ui_button_tab`), OK.
2. Details subcategory now shows **Tab** (grey-X preview); **import a 4-row
   sheet** onto it (rows = idle/hover/pressed/disabled per the ui vocab;
   row 0 locked to idle), optionally set nine-slice margins; Save.
3. Selector → **UI → Screens → hud** (screen mode): the widget skin dropdown
   lists `ui_button_tab` **without restarting the editor**. Assign it to
   `btn_end_turn` (or any button widget), Save.
4. Toolbar **Play** → the widget renders in-game with the new sheet's states
   (hover/press it).
5. `py tools/smoke.py` green afterwards (the live `data/slots.json` +
   manifest writes validate).
