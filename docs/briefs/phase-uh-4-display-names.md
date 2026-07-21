# Phase UH-4 — Tools + editor: widget display names

Plan: `planning/UiEditorHonestyPLAN.md` §4 UH-4 (lines 122–133). Binding
decision **D4** (plan lines 49–51): *display names are cosmetic* — a human
label per widget id, shown in the editor UI only; the code id remains the
contract everywhere on disk. Real renames stay dispatched agent tasks, not
editor buttons.

## 1. Behavioral spec

**Problem.** Widget ids (`action_btn`, `preview_confirm_btn`, …) are
programmer names, and they are the game↔exporter↔override contract
(plan lines 27–29), so they cannot be renamed. Today the editor surfaces the
raw id in exactly one place: the `ScreenDetailsPanel` widget list — each
`QListWidgetItem`'s text IS the id (`editor/panels/screen_details.py:337-342`),
selection sync matches on that text
(`select_widget`, `screen_details.py:354-356`), and the `currentTextChanged`
handler treats the item text as the id (`screen_details.py:97`,
`screen_details.py:344-348`). The viewport never draws the id at all — its
canvas text is the widget's game `label`
(`editor/panels/viewport.py:921,938-947`), and the selection overlay is an
anonymous outline + 4 handles (`viewport.py:950-959`).

**After UH-4:**

1. **Data carries an optional human name.** Each widget entry in
   `data/ui/screen_defaults.json` MAY carry `display_name` (string), emitted
   by `tools/export_ui_layouts.py` from a mapping **authored in the exporter**
   (it is generated-but-committed data; the exporter is the single author —
   `data/CLAUDE.md` "UI screen data": the file is written only by
   `tools/export_ui_layouts.py`). Ids absent from the mapping get **no**
   `display_name` key (the file stays minimal; fallback is the reader's job).
2. **The editor prefers `display_name`, falls back to the id.** Preference
   order everywhere a widget is named in the UI:
   `spec.get("display_name") or widget_id`. Surfaces:
   - `ScreenDetailsPanel` widget list: item **text** = display name; item
     **tooltip** = the code id (always set — the id is the secondary surface,
     per the plan's "tooltip/subtitle" requirement, plan line 128–129); the
     code id is stored in `Qt.ItemDataRole.UserRole` and becomes the ONLY
     thing the selection contract reads.
   - Viewport: the selection overlay
     (`viewport.py:_submit_screen_selection`, 950–959) gains a small caption
     `HudText` above the outline showing the display name of the selected
     widget. This is the one NEW viewport surface; the in-canvas widget
     `label` text (game text, `viewport.py:921`) is untouched.
3. **The code id remains the on-disk contract, unchanged.** Override JSONs
   (`data/ui/screens/<id>.json`) stay keyed by code id; every
   `push_move`/`push_field`/`push_skin_assign` call still receives the code
   id; the `widget_selected` signals in both directions
   (`editor/main.py:155-156`) still carry the code id. `display_name` never
   appears in an override doc — `ui_screen.schema.json` is NOT modified.
4. **Fallback path is first-class.** A widget with no `display_name` (every
   non-mapped screen, plus any future id added before the mapping catches up)
   renders exactly as today: the id string. No warning, no error.
5. **Mapped names, minimum required set** — `building_panel` (the plan's
   motivating screen, plan line 123–124). All 12 ids (verified against the
   committed `data/ui/screen_defaults.json`):

   | id | display_name |
   |---|---|
   | `panel` | Building panel |
   | `close_btn` | Close button |
   | `action_btn` | Unlock / Build / Upgrade button |
   | `boss_btn` | Boss history button |
   | `boss_close_btn` | Boss history close button |
   | `rename_dice_btn` | Rename dice button |
   | `lightning_btn` | Lightning upgrade button |
   | `preview_panel` | Construct preview window |
   | `preview_confirm_btn` | Construct confirm button |
   | `preview_cancel_btn` | Construct cancel button |
   | `preview_close_btn` | Construct preview close button |
   | `preview_dice_btn` | Construct preview dice button |

   (Names for `boss_btn`/`rename_dice_btn` are inferred from the id — the
   executor verifies wording against `game/ui/building_ui.py` before
   authoring.) The other 12 screens SHOULD be mapped too in the same pass
   (mechanical: `btn_end_turn` → "End Turn button", `btn_new_game` → "New
   Game button", `xp_bar` → "XP bar", …); any id left unmapped falls back
   cleanly, so complete coverage is not a gate condition — `building_panel`
   coverage is.
6. **The mapping is per-screen, global to the screen** — one name per
   `(screen_id, widget_id)`. After UH-1, a `building_panel` widget id that
   appears in several per-mode views carries the SAME name in each view by
   construction (single mapping source; matches D2's "override ids stay
   global to the screen", plan lines 42–45).

## 2. Architecture plan

**Exporter** (`tools/export_ui_layouts.py`):
- New module-level constant after `_MOCK_BUILDING_TYPE`
  (`export_ui_layouts.py:64`):
  `_DISPLAY_NAMES: dict[str, dict[str, str]]` — `{screen_id: {widget_id:
  display_name}}`.
- New helper `_apply_display_names(screen_id, entry)` that annotates **every
  `widgets` mapping inside the entry** — the flat `entry["widgets"]` today,
  AND each per-mode view's widgets after UH-1 adds the `views` level (walk by
  key name `"widgets"`, wherever it appears in the entry, so the helper is
  correct against both shapes and needs no edit when UH-1's exact view keys
  land). For each widget id present in `_DISPLAY_NAMES[screen_id]`, set
  `widget["display_name"]`; otherwise leave the dict untouched.
- Called from `build_screen_defaults` (`export_ui_layouts.py:268-278`),
  after the builder returns and before the entry is returned. Builders
  (`_build_*`) and `_widget_entry` (`export_ui_layouts.py:75-90`) are NOT
  modified — they don't know the screen id, and keeping annotation in one
  post-pass keeps the UH-1 merge surface small.
- Determinism is free: `write_validated`'s sorted-keys canonical form
  (`export_ui_layouts.py:11-14`) already makes re-runs byte-identical.

**Schema** (`data/schemas/screen_defaults.schema.json`):
- Add `display_name`: `{"minLength": 1, "type": "string"}` to the widget
  properties object (`screen_defaults.schema.json:16-40`, beside
  `kind`/`label`/`rect`). Do NOT add it to `required`
  (`screen_defaults.schema.json:41-45`) — optional is the whole design.
  `additionalProperties: false` (line 16) means the schema edit, the exporter
  edit and the regenerated JSON must land **in the same commit** or the
  staleness test (`tools/tests/test_ui_layout_export.py:24-39`) and smoke
  validation go red. If UH-1 has factored the widget subschema into `$defs`
  (to share it between the flat and `views` levels), add `display_name` to
  that ONE `$defs` entry instead.

**Editor — shared resolution helper**:
- One pure function so panel and viewport cannot disagree:
  `widget_display_name(widget_id, spec) -> str` (returns
  `spec.get("display_name") or widget_id`) in
  `editor/panels/_screen_primitives.py` (already pure, already in
  `TestPurity` — no import-list change needed).

**Editor — `ScreenDetailsPanel`** (`editor/panels/screen_details.py`):
- `_refresh_widget_list` (`screen_details.py:337-342`): build
  `QListWidgetItem`s with text = display name, tooltip = code id,
  `setData(Qt.ItemDataRole.UserRole, widget_id)`.
- Selection contract moves from item TEXT to UserRole data:
  - The connect at `screen_details.py:97` changes from `currentTextChanged`
    to `currentItemChanged`; `_on_widget_list_selected`
    (`screen_details.py:344-348`) reads `item.data(UserRole)` (None-item
    guard replaces the empty-string guard) and keeps emitting the CODE id on
    `widget_selected`.
  - `select_widget` (`screen_details.py:350-366`): replace
    `findItems(widget_id, MatchExactly)` with a row scan comparing
    `item.data(UserRole) == widget_id` (display names are not guaranteed
    unique; the id is).
- Nothing else in the panel changes — `_populate_widget_form`, the
  enable/disable logic and every `push_*` call keep receiving the code id
  via `self._current_widget`.

**Editor — viewport** (`editor/panels/viewport.py`):
- `_submit_screen_selection` (`viewport.py:950-959`): after the outline +
  handles, submit one `HudText` caption at the outline's top-left
  (y offset a few px above; clamp to the canvas top so a widget at y=0 keeps
  a visible caption), text = `widget_display_name(widget_id,
  defaults["widgets"][widget_id])`, small font (`"sm"`), the existing
  `SELECTION_COLOR`. `HudText` is already imported (used at
  `viewport.py:885`).

## 3. File scope + shared-file contract

**Modified:**
- `tools/export_ui_layouts.py` — `_DISPLAY_NAMES` constant inserted after
  line 64 (`_MOCK_BUILDING_TYPE`); `_apply_display_names` helper beside it;
  one call inside `build_screen_defaults` (lines 268–278). No other region.
- `data/schemas/screen_defaults.schema.json` — one property added to the
  widget subschema (lines 16–40 in the current file, or UH-1's `$defs`
  equivalent). `required` untouched.
- `data/ui/screen_defaults.json` — **regenerated only** (run
  `py tools/export_ui_layouts.py`), never hand-edited.
- `editor/panels/screen_details.py` — ONLY: the connect at line 97,
  `_refresh_widget_list` (337–342), `_on_widget_list_selected` (344–348),
  `select_widget` (350–366).
- `editor/panels/_screen_primitives.py` — new pure helper
  `widget_display_name` appended (no existing function modified).
- `editor/panels/viewport.py` — ONLY `_submit_screen_selection` (950–959).
- `tools/tests/test_ui_layout_export.py`, `tools/tests/test_editor_viewport.py`
  — new tests (see §4).

**No changes to:** `data/schemas/ui_screen.schema.json`, `data/ui/screens/*`,
`editor/ui_screen_session.py`, `editor/main.py`, anything in `game/**`
(the game never reads `display_name`; it never reads `screen_defaults.json`
at all — plan line 85–86).

**SHARED-FILE WARNING — sequencing is binding:**
- **UH-1 also modifies `tools/export_ui_layouts.py` +
  `screen_defaults.schema.json` and regenerates
  `data/ui/screen_defaults.json`** (plan lines 83–87: per-mode mock states, an
  optional `views` level for `building_panel`). **UH-4 merges AFTER UH-1.**
  UH-4's `display_name` must coexist with the `views` shape:
  `_apply_display_names` annotates widgets wherever a `widgets` mapping
  appears in the entry (both the flat level and inside each view), and the
  schema edit goes into whichever single widget subschema UH-1 leaves behind.
  Any merge conflict in `data/ui/screen_defaults.json` is resolved by
  **re-running the exporter — never by hand** (plan lines 177–179;
  `data/CLAUDE.md` "Merge conflicts … resolve by re-running the exporter").
  Insertion points chosen to minimize textual conflict with UH-1: UH-4 stays
  out of the `_build_*` builders and `_widget_entry` entirely.
- **UH-2 also modifies `editor/panels/screen_details.py`** — specifically
  `_refresh_widget_list` (filter the listed ids to the active view, plan
  lines 99–100). Contract: UH-2 owns **which ids are iterated**; UH-4 owns
  **how each list item is constructed** (text/tooltip/UserRole). The two
  edits compose inside the same method; whichever lands second rebases its
  half without touching the other's.
- **UH-3 also modifies `editor/panels/screen_details.py`** — the
  enable/disable + tooltip logic around `_set_widget_form_enabled` /
  `_populate_widget_form` (`screen_details.py:370-445`). UH-4 deliberately
  does NOT touch `_populate_widget_form` or any enable logic (the id's
  secondary surface is the list tooltip, not a form subtitle) — zero region
  overlap with UH-3.
- **UH-2 also touches `editor/panels/viewport.py`** (screen-mode view state).
  UH-4's only viewport region is `_submit_screen_selection`; flag it in the
  PR if UH-2 lands adjacent code.
- Update `editor/panels/CLAUDE.md`'s B4 section (widget-list/selection
  contract now UserRole-based) in the same change — package-doc rule from the
  root router.

## 4. Exit gate + Quick Test

**Tests (new/updated):**
- `tools/tests/test_ui_layout_export.py` — extend: (a) regenerated output
  carries `display_name` for every mapped `building_panel` id (spot-check
  `action_btn` == "Unlock / Build / Upgrade button"); (b) an unmapped id
  carries NO `display_name` key; (c) the existing staleness + determinism
  tests (`test_ui_layout_export.py:24-53`) stay green against the regenerated
  committed file.
- `tools/tests/test_editor_viewport.py` — extend `TestScreenDetailsPanel`
  (`test_editor_viewport.py:612`) and/or `TestViewportScreenMode`
  (`test_editor_viewport.py:360`): list item text shows the display name and
  tooltip/UserRole hold the code id; fallback — an id absent from the mapping
  lists as the raw id; `select_widget(code_id)` still selects the right row;
  round-trip pin — select via the (display-named) list, assign a
  skin/move the rect, `session.save()`, assert the written
  `data/ui/screens/<id>.json` (tempdir — `TempDataCase`, never live `data/`)
  is keyed by the CODE id and contains no `display_name`.
- Purity: `widget_display_name` lives in an already-`TestPurity`-listed
  module; no import-list edit.

**Gate:**
1. `py tools/export_ui_layouts.py` — then commit the regenerated
   `data/ui/screen_defaults.json` **in the same commit** as the exporter +
   schema change (staleness test `test_ui_layout_export.py:24-39` enforces
   this).
2. `py tools/smoke.py` (schema validation of the regenerated file).
3. **Run the named test modules explicitly**:
   `py -m pytest tools/tests/test_ui_layout_export.py tools/tests/test_editor_viewport.py`
   — required because of the known **testgate `--affected` vacuous-pass bug**
   (`tools/testgate.py:222-238`, plan lines 183–185): editor-tier-heavy
   phases must not trust `--affected` selection alone until it is fixed.
4. `py tools/testgate.py check` once, at handback — **GATE PASS** (zero).

**Quick Test (in-editor/in-game):**
`py editor/main.py` → selector: ui → Screens → `building_panel`. The widget
list reads "Unlock / Build / Upgrade button", "Construct confirm button", …
instead of `action_btn`/`preview_confirm_btn`; hovering a row shows the code
id as tooltip. Click "Unlock / Build / Upgrade button" — the viewport
selection outline is captioned with that name. Drag it a few px, Save, then
inspect `data/ui/screens/building_panel.json`: the override is keyed
`action_btn` (code id), no `display_name` anywhere. Play the game and open a
building panel — the moved button is where you dragged it (the game path is
untouched by this phase, so this doubles as a no-regression check).
