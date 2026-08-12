> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# UH-1 … UH-6 — orchestrator coordination

Wave-1 reconciliation for `/execute-plan-phases planning/UiEditorHonestyPLAN.md
UH-1-UH-6`. Umbrella branch: `phase-UH-1-UH-6-umbrella` (off `Development`).
This file is the **cross-phase contract**; each phase's own brief remains its
primary spec. Where this file and a brief disagree, **this file wins** — it was
written after all six briefs existed and resolves contradictions none of the
planners could see.

## Merge order (binding)

Plan order satisfies every stated dependency, so phases merge into the umbrella
**sequentially in plan order**:

```
UH-1  →  UH-2  →  UH-3  →  UH-4  →  UH-5  →  UH-6
```

Hard dependencies that force this order:

| Dependency | Why |
|---|---|
| UH-2 after UH-1 | UH-2 reads UH-1's `views` structure; without it the editor degrades to today's single view. |
| UH-4 after UH-1 | Both regenerate `data/ui/screen_defaults.json` and edit the exporter + schema. |
| UH-6 after UH-3 | UH-6 repurposes UH-3's Color-disabled state as "Tint" and imports UH-3's skin-resolution helper. UH-6's brief says: if UH-3's diff is absent from your base, STOP. |

UH-3 and UH-5 are independent of everything except their merge slot.

## Resolved contradictions

### R1 — `display_name` insertion point (UH-1 ↔ UH-4) — **RESOLVED in UH-4's favour**

The two briefs disagreed. UH-1's §3 originally told UH-4 to inject the
id→`display_name` lookup at the `_widget_entry`/`_widgets_from_ids` choke point
(`tools/export_ui_layouts.py:75-95`). UH-4 independently **verified** that the
builders and `_widget_entry` never receive the screen id, so a per-screen
mapping cannot resolve there without threading a new argument through every
builder — exactly the functions UH-1 rewrites.

**Decision: UH-4's post-pass wins.** UH-4 adds a `_DISPLAY_NAMES` constant plus
an `_apply_display_names` post-pass called once inside `build_screen_defaults`,
annotating widgets wherever a `widgets` mapping appears (top level *and* inside
each view). UH-4 stays entirely out of `_widget_entry`, `_widgets_from_ids` and
the `_build_*` builders. UH-1's brief §3 item 2 has been **amended in place** to
say so.

**Binding on UH-1:** the widget mapping keeps the key name `widgets` at both the
top level and inside every view value. UH-4's post-pass walks that key name.

### R2 — per-view value shape (UH-1 ↔ UH-2) — **already consistent, now pinned**

UH-2 pinned a contract shape before UH-1's brief existed. UH-1 independently
specified the same thing. Pinned:

```json
"building_panel": {
  "widgets": { "<id>": {"rect": [x,y,w,h], "kind": "...", "label": "..."} },
  "mock_note": "...",
  "views": {
    "unlock":    {"widgets": {...}, "mock_note": "..."},
    "construct": {"widgets": {...}, "mock_note": "..."},
    "upgrade":   {"widgets": {...}, "mock_note": "..."},
    "base_info": {"widgets": {...}, "mock_note": "..."},
    "preview":   {"widgets": {...}, "mock_note": "..."}
  }
}
```

- Each view value has the **same `{widgets, mock_note}` shape** as a per-screen
  entry, so UH-2's resolver returns either interchangeably.
- Top-level `widgets` stays **required** and is UH-1's deterministic first-wins
  union — this is what keeps the game's known-id check
  (`game/ui/skinning.py:190-194`) and every pre-UH-2 editor read working with
  zero format churn.
- Only `building_panel` carries `views`. The other 12 screens are byte-unchanged
  apart from anything UH-4's display names add.
- Widget ids stay **global to the screen** (D2); overrides still write to the one
  `data/ui/screens/building_panel.json`.

### R3 — the plan says `editor/main_window.py`; the real file is `editor/main.py`

**Verified** by two planners: no `editor/main_window.py` exists. Every phase
that the plan routes to "main_window.py" means `editor/main.py`. Coders use the
real path. The plan doc's §4 wording is corrected in Wave 4 along with the phase
table.

## Shared-file map (who owns which region)

### `editor/panels/screen_details.py` — four claimants, disjoint regions

| Phase | Owns |
|---|---|
| UH-2 | `_current_screen_defaults` (`:322-325`) **only** — changes *which* ids are iterated. Must not restructure `_refresh_widget_list`. |
| UH-3 | module import (add `_screen_rules`); new `_refresh_honest_controls` after `_refresh_reset_buttons` (`:387-398`); one call at the end of `_populate_widget_form` (`:400-445`); one `_refresh_widget_form()` line each in `_on_skin_changed` (`:462-470`), `_on_default_combo_changed` (`:633-640`), `_on_reset_default_field` (`:642-650`). |
| UH-4 | the connect at `:97`; item construction inside `_refresh_widget_list` (`:337-342`); `_on_widget_list_selected` (`:344-348`); `select_widget` (`:350-366`). Moves the selection contract to `Qt.UserRole`. Must not touch `_populate_widget_form` or enable logic. |
| UH-6 | the Color/Tint row + its handlers/reset; `_FONT_KEYS`/`_populate_font_combo`; `_populate_widget_form`'s recompute. Imports UH-3's helper — does not duplicate it. |

The one genuine coupling is **UH-3 → UH-6** inside `_populate_widget_form`
(UH-3 appends a call; UH-6 edits the recompute). Merge order handles it. UH-3
must keep the names `_screen_rules._refresh_honest_controls` and
`TOOLTIP_COLOR_SKINNED` stable — UH-6's diff is pinned to those two spots.

### `editor/main.py` — three claimants

| Phase | Owns |
|---|---|
| UH-2 | ctor signature + `auto_refresh_layouts` keyword (`:72` + init body); one connect near `:111`; `_on_screen_view_selected` (new, after `_on_screen_selected`); `_enter_screen_mode`/`_leave_screen_mode` (`:373-392`). **Nothing outside `:355-424` except the ctor.** |
| UH-5 | levelbar connect `:116`; `_refresh_levels` `:491`; class-const block `:501-503`; `_reload_registries` `:576-580`; new methods after `_on_add_prop` (`:640`). |
| UH-6 | Theme-panel wiring only. Merges last; rebases over both. |

**Known adjacency:** UH-2's connect near `:111` and UH-5's connect at `:116` sit
in the same `__init__` wiring block ~5 lines apart. Both are pure additions, so
this is a mechanical conflict at worst. Whichever lands second rebases; **neither
may relocate the other's region**.

`editor/panels/selector.py`: UH-2 owns `:267-319` / `:352-364` plus the new
`_VIEW_ROLE`/`screen_view_selected`. UH-5 explicitly does **not** touch this
file (its brief lists it under "Must NOT touch") — the concern UH-2 raised is
void. UH-6 touches it last for Theme-panel wiring.

### `tools/export_ui_layouts.py` + `data/schemas/screen_defaults.schema.json`

UH-1 and UH-4 only. Regions disjoint per R1. UH-1 hoists a single `$defs/widget`
node; UH-4 adds `display_name` as one optional property **inside that single
node** and must not fork it. `required` untouched by both.

### `data/ui/screen_defaults.json` — generated, committed, never hand-merged

Both UH-1 and UH-4 regenerate it. **Any merge conflict is resolved by rebasing
the code and re-running `py tools/export_ui_layouts.py`, then committing its
output — never by editing the JSON.** (Plan §5 risk, lines 177-179;
`data/CLAUDE.md` "UI screen data".) The exporter is deterministic, so a correct
rebase reproduces bytes exactly.

## Test-budget rule (every phase)

- Intermediate gates: `py tools/smoke.py` + `py tools/testgate.py check --affected`.
- **The full `py tools/testgate.py check` runs exactly ONCE**, on the finished
  umbrella in Wave 4, right before the PR. Never mid-orchestration.
- **`--affected` vacuous-pass bug** (`tools/testgate.py:222-238`, plan §5): the
  affected set is computed from committed `.py` diffs, so an editor-tier-only
  or data-only phase can pass vacuously. Every phase **must additionally run its
  named test modules explicitly** with `py -m pytest`:

| Phase | Explicit modules |
|---|---|
| UH-1 | `test_ui_layout_export.py`, `test_layout_h_invariant.py` |
| UH-2 | `test_editor_viewport.py`, `test_editor_panels.py`, `test_ui_layout_export.py` |
| UH-3 | `test_screen_honest_controls.py` (new), `test_editor_viewport.py` |
| UH-4 | `test_ui_layout_export.py`, `test_editor_viewport.py` |
| UH-5 | `test_registry_ops.py`, `test_editor_panels.py` |
| UH-6 | `test_theme_data.py` (new), `test_button_skin.py`, `test_editor_panels.py`, `test_editor_viewport.py`, `test_tiers.py` |

UH-6 additionally adds `"test_theme_data": "core"` to `conftest.py`'s TIERS —
`test_tiers.py` fails without it.

## Standing orders for every coder

1. **The brief's §3 is a hard file boundary.** Do not edit a file another phase
   owns, even trivially.
2. **Tests never write into `data/`** — copy to a tempdir (`TempDataCase`). A
   session fixture hashes `data/` before/after the suite and fails the run if it
   changed. Never assert against live `data/` content; pin a fixture.
3. **The gate is ZERO failures.** There is no baseline and no tolerated
   pre-existing failure. A red test clearly outside your blast radius: note it in
   your report and stop — do not investigate it.
4. **Uncommitted worktree changes exist and are NOT yours**: `data/slots.json`,
   `data/sprites/asset_manifest.json`, `data/sprites/imported/ui_button_panel.png`,
   `data/ui/screens/building_panel.json`, `data/ui/screens/main_menu.json`. Leave
   them alone — do not revert them, do not fold them into your commit.
5. **Never run destructive git** on uncommitted work (`reset --hard`, `clean`,
   `checkout -- <file>`, force-push). Never commit `build/`, `dist/`, or `*.exe`.
6. Coders **never push and never open PRs** — the orchestrator does that once.
7. If your phase matches an `/add-*` skill (UH-6's Theme panel →
   `/add-editor-feature`), **invoke the skill** rather than hand-rolling.

## Open items carried from the planners (orchestrator rulings)

| # | Item | Ruling |
|---|---|---|
| 1 | UH-4's `boss_btn` / `rename_dice_btn` display-name wording is inferred from ids | Executor confirms strings against `game/ui/building_ui.py`. Not a gate condition. |
| 2 | UH-4 coverage: full `building_panel` mapping gated, other 12 screens "mechanical" | **Partial coverage accepted.** The id fallback (D4) makes unmapped ids harmless. |
| 3 | UH-1's `upgrade` view needs a state object for `upgrade_gate` | Executor pins it: prefer a real headless-constructible run-state, else a `SimpleNamespace` limited to the attributes `upgrade_gate` actually reads. |
| 4 | UH-1's Quick-Test `y=600` literal assumes `view_h=720` | Executor confirms against `data/display.json` after regeneration. Cosmetic. |
| 5 | UH-2's selector needs to read `screen_defaults.json` itself | **Approved as briefed**: a fresh degrade-to-`{}` read mirroring `_load_screen_defaults`. Do not add a MainWindow injection path. |
| 6 | UH-3's pink test may expose a live game bug | If pink does not appear in-game, **file the bug with a repro in the report** — do not expand UH-3's scope to fix it. |

## Out of scope (plan §5, do not drift into these)

- In-game building-panel screen split (needs a design decision → its own plan).
- True-WYSIWYG game-subprocess preview (its own plan).
- Real widget renames (stay per-rename dispatched agent tasks — D4).
- New widget *behavior* classes in UH-5 (game-code tasks).
