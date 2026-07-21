# Phase UH-2 — Editor: per-mode screen views + auto Refresh Layouts on entry

Plan: `planning/UiEditorHonestyPLAN.md` (§4 UH-2; decisions D1/D2 binding).
Branch: `phase-UH-1-UH-6-umbrella`. **Depends on UH-1** (per-mode snapshot
exporter) — merge UH-2 AFTER UH-1; the `views` shape UH-2 consumes is specced
in §3 below and must match what UH-1 ships.

> Naming note: the plan says `editor/main_window.py`; the actual module is
> **`editor/main.py`** (`MainWindow` at `editor/main.py:71`). There is no
> `main_window.py` — every reference below uses the real path.

---

## 1. Behavioral spec

**Today (the lie being fixed).** The exporter flattens ALL of
`building_panel`'s modes into one superimposed snapshot: mode-independent ids
(`panel`, `close_btn`, `action_btn`, `boss_btn`, `rename_dice_btn`,
`boss_close_btn`) + the base-info-only `lightning_btn` + the disjoint
`preview_*` ids of an open ConstructPreview modal, all unioned into one
`widgets` dict (`tools/export_ui_layouts.py:168-212`). The editor renders that
pile as one canvas: the viewport indexes the loaded defaults by screen id in
exactly one place (`ViewportPanel._current_screen_defaults`,
`editor/panels/viewport.py:353-359`) and every render/hit-test/nudge path goes
through it (`viewport.py:435,468,491,505,878`); the details panel does the
same (`ScreenDetailsPanel._current_screen_defaults`,
`editor/panels/screen_details.py:322-325`) to fill its widget list
(`screen_details.py:337-342`). The game never shows this superposition —
that is plan §1 symptom 2.

**After UH-2:**

1. **Five views for Building Panel.** The selector's Screens branch
   (`editor/panels/selector.py:267-319`) shows `building_panel` with five
   child leaves — `unlock`, `construct`, `upgrade`, `base_info`, `preview`
   (display order pinned; NOT the sorted-keys JSON order, see §2). Selecting
   a view leaf opens `building_panel` in screen mode showing ONLY that view's
   widgets — an editable, uncluttered canvas: drag/resize/nudge, per-widget
   form, skin/font/color edits all work exactly as in B4 screen mode
   (`editor/panels/CLAUDE.md` §Phase B4). Selecting the parent
   `building_panel` leaf opens the first view (`unlock`).
2. **Overrides still write to the ONE screen JSON (D2).** The open doc is
   `data/ui/screens/building_panel.json` regardless of active view
   (`UIScreenSession.open`/`save`, `editor/ui_screen_session.py:104-117`;
   path builder `ui_screen_session.py:32-33`). Widget ids are global to the
   screen: an id that appears in several views (e.g. `panel`, `close_btn`)
   carries ONE override that applies in every view and in the game. The
   active view filters what is *shown*, never where an edit is *stored* —
   every `push_*` path (`ui_screen_session.py:132-158`) is untouched.
   Switching views on the same open doc never triggers the dirty prompt
   (same-doc rule, `editor/main.py:363-365`) and never clears the undo
   stack; undo of an edit made in another view is legal (doc-level undo).
3. **Auto Refresh Layouts on screen-mode entry.** Entering screen mode from
   any non-screen mode auto-runs the existing Refresh Layouts subprocess
   (`RunControls.export_layouts()`, `editor/run_controls.py:125-131`, command
   `run_controls.py:41-47`) — ONCE per entry: switching screens or views
   while already in screen mode does NOT re-run it. The entry hook is W3-6's
   `reload_assets()` position: first thing in `_enter_screen_mode()`
   (`editor/main.py:373-385`, reload at `:381`). The editor shows the current
   on-disk defaults immediately; when the subprocess exits 0 the existing
   completion handler swaps in the fresh ones
   (`_on_export_layouts_finished`, `editor/main.py:410-424`, dispatched at
   `:691-692`) — so snapshots can't be stale for longer than one exporter
   run. A refresh/build already in flight refuses the auto-call silently
   (one-tracked-process rule, `run_controls.py:135-137`) — accepted: the
   in-flight run's own completion refreshes, or the stale-but-valid defaults
   stand. Exit ≠ 0 keeps today's status-bar failure path
   (`editor/main.py:422-424`).
4. **Non-building screens unchanged.** A screen with no `views` entry in
   `screen_defaults.json` behaves byte-for-byte as today: single implicit
   view, no sub-leaves in the tree, same canvas, same widget list. This is
   also the graceful-degrade path if UH-2 runs against a pre-UH-1 defaults
   file (missing/`{}` defaults already degrade via E-37,
   `editor/main.py:394-405`).

---

## 2. Architecture plan

**View state lives in the session** (plan §4 UH-2 files list).
`UIScreenSession` gains a non-doc, non-undoable attribute:

- `self.view = None` (in `__init__`, `ui_screen_session.py:91-96`); `None`
  means "the screen's single implicit view" — every non-building screen.
- `set_view(view_id)` → sets `self.view`, emits new
  `view_changed = Signal(object)` (declared beside `screen_opened`,
  `ui_screen_session.py:89`). `open()` resets `self.view = None`
  (`ui_screen_session.py:104-111`) — the caller (MainWindow) sets the view
  after open. The session does NOT validate view names (it holds only the
  override doc, not defaults) — validity is the caller's job.
- Module-level `VIEW_ORDER = ("unlock", "construct", "upgrade", "base_info",
  "preview")` + `ordered_views(view_ids)` helper (known names in pinned
  order first, unknown names sorted after) near the top of
  `ui_screen_session.py` (below `REPO`, line 29). Needed because D-3
  sorted-keys JSON alphabetizes the `views` object (`base_info` first) but
  the UI must present game-mode order. Selector and MainWindow both import
  it from here — one authority.

**Defaults resolution — one changed indexing point per consumer.** Both
`_current_screen_defaults` implementations resolve the active view:
`entry = all_defaults.get(screen_id)`; if `entry` carries `"views"` and the
session's `view` names one, return `entry["views"][view]` (a `{widgets,
mock_note}` sub-dict — same shape as today's per-screen entry); else return
`entry` as today. Because every viewport render/hit/nudge path and the
details panel's widget list already funnel through these two functions
(§1 citations), this single change IS the widget-list filtering — no
per-call-site edits.

**Selector sub-leaves.** `refresh_screens()` (`selector.py:297-319`) gains a
fresh read of `data/ui/screen_defaults.json` via a new private helper beside
`_screen_ids_from_disk` (`selector.py:269-273`) returning
`{screen_id: (view_id, ...)}` (ordered via `ordered_views`; unreadable/
missing file degrades to `{}` → no sub-leaves, mirroring
`_load_screen_defaults`'s degrade). Each view becomes a child
`QTreeWidgetItem` of its screen leaf carrying a new
`_VIEW_ROLE = Qt.ItemDataRole.UserRole + 4` (beside the existing roles,
`selector.py:78-81`) holding `(screen_id, view_id)`. New signal
`screen_view_selected = Signal(str, str)` (beside `screen_selected`,
`selector.py:95`). `_emit_selection` (`selector.py:352-364`) checks
`_VIEW_ROLE` FIRST; a view leaf emits `screen_view_selected(screen_id,
view_id)` + `domain_selected("ui")` and never `node_selected` (the exact
`_SCREEN_ROLE` pattern). `select_screen_view(screen_id, view_id)` beside
`select_screen` (`selector.py:283-295`); the rebuild's
selection-preservation (`selector.py:304-319`) also preserves a selected
VIEW leaf (fall back to the screen leaf if the view vanished).

**MainWindow wiring.** Connect `screen_view_selected` beside the existing
connection (`editor/main.py:111`). New `_on_screen_view_selected(screen_id,
view_id)` beside `_on_screen_selected` (`editor/main.py:360-371`): identical
flow (same-doc fast path, `_resolve_dirty(screen_session)` only when opening
a DIFFERENT screen), then `session.set_view(view_id)` →
`_enter_screen_mode()`. `_on_screen_selected` sets the default view:
`ordered_views(views)[0]` if the screen has views (i.e. `"unlock"` for
building_panel), else `None`. **View switching re-runs `_enter_screen_mode()`
in full** — `viewport.set_screen_mode` already resets widget selection and
drag state (`viewport.py:289-299`) and `screen_details.set_defaults` →
`_on_screen_opened` rebuilds the list/form (`screen_details.py:316-333`), so
no stale-selection handling is needed; the repeated `reload_assets()` is
cheap by design (`editor/panels/CLAUDE.md` "Both calls are cheap").

**Auto-refresh guard.** `MainWindow.__init__` (`editor/main.py:72`) gains
keyword `auto_refresh_layouts=True` (the `prefs_path=` injectability
precedent, `editor/CLAUDE.md` §Theme) stored on self, plus a
`self._screen_mode_entered = False` flag. In `_enter_screen_mode()`
(`editor/main.py:373-385`), immediately after `reload_assets()` (`:381`):
`if self._auto_refresh_layouts and not self._screen_mode_entered:
self.run_controls.export_layouts()`; set `self._screen_mode_entered = True`.
`_leave_screen_mode()` (`editor/main.py:387-392`) resets the flag. No new
subprocess machinery: reuse of the tracked `export_layouts` path means the
completion/refresh/failure handling already exists (`editor/main.py:407-424`).

No new editor module → no `TestPurity` import-list addition
(`editor/CLAUDE.md` "Every new editor module MUST be added to
`test_editor_viewport.TestPurity`" — inapplicable, pin it in the report).

---

## 3. File scope + shared-file contract

**Modified (editor):**

| File | Exact regions UH-2 touches |
|---|---|
| `editor/ui_screen_session.py` | `VIEW_ORDER`/`ordered_views` inserted after `REPO` (line 29); `view_changed` signal beside `screen_opened` (line 89); `self.view = None` in `__init__` (91-96); reset in `open()` (104-111); `set_view()` inserted after `open()` (after line 111). Nothing below `save()` changes. |
| `editor/panels/selector.py` | `_VIEW_ROLE` constant after line 81; `screen_view_selected` signal after line 95; new `_screen_views_from_disk()` helper after `_screen_ids_from_disk` (269-273); `select_screen_view()` after `select_screen` (283-295); `refresh_screens()` body (297-319); `_VIEW_ROLE` branch at the TOP of `_emit_selection` (352-364). |
| `editor/main.py` | `__init__` signature + two attributes (line 72 + init body); one `connect` beside line 111; new `_on_screen_view_selected` after `_on_screen_selected` (360-371); `_enter_screen_mode` (373-385); `_leave_screen_mode` (387-392). **UH-2 touches nothing outside the screen-mode region (lines 355-424) except the ctor.** |
| `editor/panels/viewport.py` | `_current_screen_defaults` (353-359) view resolution + `set_screen_mode` docstring (277-288). Nothing else. |
| `editor/panels/screen_details.py` | `_current_screen_defaults` (322-325) view resolution ONLY. `_refresh_widget_list` (337-342) needs no code change (it iterates the resolved dict) — do not restructure it. |
| `tools/tests/test_editor_viewport.py`, `tools/tests/test_editor_panels.py` | New view tests + audit every `MainWindow(...)` construction site to pass `auto_refresh_layouts=False`, EXCEPT the dedicated auto-refresh test (which stubs `run_controls.export_layouts` with a recorder and asserts exactly one call per entry, zero on view/screen switches within screen mode). |
| `editor/panels/CLAUDE.md` + `editor/CLAUDE.md` (screen-mode sections) | Document views + auto-refresh (architecture changed → package doc rule). |

**SHARED-FILE WARNING** (umbrella branch — land beside, not across):
- `editor/panels/screen_details.py` is ALSO modified by **UH-3** (control
  enable/disable + tooltips: `_populate_widget_form` 400-445,
  `_set_widget_form_enabled` 370-385, new honesty helpers) and **UH-4**
  (display names: item TEXT inside `_refresh_widget_list`'s loop 337-342 +
  form labels). UH-2's only edit is `_current_screen_defaults` (322-325) —
  it changes WHICH widget ids the list iterates; UH-4 changes what TEXT each
  id renders as; UH-3 changes control state after selection. Disjoint
  regions; if UH-4 lands first, UH-2 still only edits 322-325.
- `editor/main.py` is ALSO modified by **UH-5** ("+ Button Type" affordance
  + naming dialog — expected in the selector/context-menu/toolbar wiring,
  NOT in the screen-mode region). UH-2 claims lines 355-424 + the `__init__`
  keyword; UH-5 must not touch those functions, UH-2 touches nothing of
  UH-5's.
- `editor/panels/selector.py` and `editor/ui_screen_session.py` and
  `editor/panels/viewport.py`: UH-2 only (UH-5's selector work is the
  "+ Button Type" context-menu path, `_add_entries` region 385+, disjoint
  from UH-2's Screens-branch region 267-319/352-364 — coordinate if UH-5's
  brief says otherwise).

**DEPENDENCY — UH-1's `views` shape (contract, since no UH-1 brief exists
yet; whoever writes/executes UH-1 must match this or amend BOTH briefs):**
`data/schemas/screen_defaults.schema.json` (currently `additionalProperties:
false`, per-screen `required: ["widgets"]`, schema lines 5-57) gains an
OPTIONAL per-screen `views` key:

```json
"<screen_id>": {
  "widgets": { "<id>": {"rect": [x,y,w,h], "kind": "...", "label": "..."} },
  "mock_note": "...",
  "views": {
    "unlock":    {"widgets": { ... }, "mock_note": "..."},
    "construct": {"widgets": { ... }, "mock_note": "..."},
    "upgrade":   {"widgets": { ... }, "mock_note": "..."},
    "base_info": {"widgets": { ... }, "mock_note": "..."},
    "preview":   {"widgets": { ... }, "mock_note": "..."}
  }
}
```

- Each view value has the SAME `{widgets, mock_note}` shape as a per-screen
  entry (so UH-2's resolver returns either interchangeably).
- Top-level `widgets` stays REQUIRED (schema back-compat; UH-1 keeps it as
  the union — the game-side load-time known-id check and any pre-UH-2 editor
  keep working). The editor ignores it when `views` is present.
- Ids are GLOBAL to the screen (D2): the same id may appear in multiple
  views with the same rect/kind; membership per view is UH-1's exporter
  decision (mode-independent ids in every view; `lightning_btn` in
  `base_info`; `preview_*` only in `preview`; cf.
  `tools/export_ui_layouts.py:179-207`).
- Only `building_panel` carries `views`; all other screens are unchanged
  (no format churn — plan §4 UH-1 goal).
- **Merge order: UH-1 lands first; UH-2 rebases on it.** If UH-2 must build
  before UH-1 lands, it builds against a hand-made fixture defaults file in
  tests (TempDataCase — never live `data/`) and the live editor degrades per
  §1.4 until UH-1's regenerated `data/ui/screen_defaults.json` arrives.

**Not touched:** `tools/export_ui_layouts.py`, `data/**` (UH-2 writes no
data; the regenerated defaults are UH-1's), `game/**`, `engine/**`,
`editor/run_controls.py`.

---

## 4. Exit gate + Quick Test

**Gate:**
1. `py tools/testgate.py check --affected` while iterating; **full
   `py tools/testgate.py check` once at handback — GATE PASS (zero).**
2. **Vacuous-pass guard (binding, plan §5):** testgate's `--affected`
   narrowing can under-select for editor-tier-only diffs
   (`tools/testgate.py:222-238`). This phase is editor-tier-only, so ALSO
   run its test modules explicitly and report their counts:
   ```
   py -m pytest tools/tests/test_editor_viewport.py tools/tests/test_editor_panels.py
   ```
   plus `py -m pytest tools/tests/test_ui_layout_export.py` (pins the UH-1
   `views` shape this phase consumes). A run of 0 collected tests is a FAIL,
   not a pass.
3. Required new tests (plan §4 UH-2): (a) view switching shows/hides the
   right widget sets (viewport `_current_screen_defaults` + details-panel
   list, per view, against a fixture defaults file with `views`); (b)
   overrides round-trip regardless of active view — edit in `construct`,
   save, reopen, identical `building_panel.json` content and the override
   visible from `base_info` too; (c) auto-refresh fires exactly once per
   screen-mode entry and zero times on view/screen switches inside screen
   mode (stubbed `export_layouts`, no real subprocess); (d) regression:
   a no-`views` screen (e.g. `main_menu`) renders and lists identically to
   pre-UH-2. All Qt tests via `QtCase`/`self.track(...)`; all data via
   `TempDataCase` fixtures — never live `data/`.

**Quick Test (in-game, concrete):** `py editor/main.py` → Screens →
Building Panel → `construct` view: only construct-mode widgets are listed
and drawn (no `preview_*`, no `lightning_btn`); the status bar shows
"Layouts refreshed" shortly after entry (the auto-run). Drag `action_btn`
to a clearly different position, Save, Play → in-game, select a buildable
tile to open the building panel's construct mode: the button sits at the
dragged position. Then select `preview` view in the editor: `action_btn`'s
override is still present on the shared doc, and the `preview_*` widgets
appear alone on an uncluttered canvas.
