# CLAUDE.md — EDITOR package (router)

Self-contained guide for `editor/` — the PySide6 editor, the designer's single
interface to all game data. You reached here from the root router. Requirements:
SPEC.md §7 (`ED-*`).

This doc is a **router**: it holds the cross-cutting rules + the conventions for
the top-level `editor/*.py` files (run controls, spawnclaude, domains), and points
to `editor/panels/CLAUDE.md` for all panel detail (viewport, selector, balancing,
details, palette, map-details). The panels doc auto-loads when you edit inside
`editor/panels/`. **When you change a panel's architecture, update the panels
doc**; change a top-level module or a cross-cutting rule → update this file.

**Adding an editor feature or panel? Use the `/add-editor-feature` skill.**
**Wiring a new renderable game-element category into the asset-import pipeline?
Use the `/add-asset-importer` skill.** Both encode the full pattern; don't
hand-roll them.

## File scope you may edit
`editor/**`. Never import or edit `game/**`. The editor talks to `engine/`
(rendering, assets, coords) and `data/` (through the validating writer) — nothing
else.

## Architecture (top-level modules)
- `main.py` — Qt shell: docked panels, layout persisted to `.editor_prefs.json`
  (gitignored).
- `panels/` — selector (tree), viewport, balancing form, asset import, palette,
  map-details → **`editor/panels/CLAUDE.md`**.
- `run_controls.py` — Play / Build / Playbuild. Always subprocesses; the editor
  never runs game logic in-process (§ below).
- `spawnclaude.py` — the agent LAUNCHER ("Summon a Drunken Robot"): dispatch a
  `claude` session from a form, a small tweak, or blank/admin (§ below).
- `agent_form_dialog.py` — the generic "Add new X" form, rendered from ONE form
  spec; consumes `agent_forms.py` (§ below).
- `theme.py` — THE light/dark chrome theme (§ below). The only place the app's
  Qt palette/style is set.
- `test_runner.py` (TestRunnerPLAN TR-3) and `test_report.py` (TR-4) — the
  editor's test-run engine and report writer. **Qt-free and pygame-free** (D6),
  both in `TestPurity`: `test_runner` builds the command, streams the child and
  parses it into per-domain counters + one `RunResult`; `test_report` serializes
  that into `.claude/testruns/<stamp>.json` + `.md` and the paste-at-Claude
  prompt. The Qt lives in `panels/test_run_panel.py` + `main.py` (§ below).
- `domains.py` — derived domain list + balancing/schema path helpers (AD-6):
  the list is a function of slots.json ∩ `data/balancing/*.json`, never a
  hardcoded constant.
- Pure helpers used by panels: `selection.py`, `map_session.py`, `tilemap_ops.py`,
  `registry_ops.py`, `asset_import.py`, `agent_forms.py`, `theme_ops.py` (UH-6/
  UH-Font-A: fonts/palette/font_manifest/active_font load-validate-write,
  `panels/game_theme.py`'s home), `timeline_curve.py` (TimelinePLAN T3/D7 —
  the Timeline panel's best-case XP-curve calculator; a deliberately
  duplicated twin of `game/core/xp_curve.py`, since this package may never
  import `game/`; pinned equal by a cross-package drift test), `timeline_ops.py`
  (TimelinePLAN T5 — `progression.json` load/assign/clear/add/remove/save,
  enforcing the two uniqueness invariants JSON Schema can't express) — all
  Qt-free/pygame-free, in `TestPurity`.
  `master_sheet_import.py` (GpuAndMasterSheetsPLAN M3 — the MASTER-spritesheet
  registry: copy one big multi-character PNG into `data/sprites/master/`, write
  `data/sprites/master_sheets.json` through the validating writer, list it back
  for `panels/master_sheet_dialog.py`) is Pillow-only, Qt-free/pygame-free and
  in `TestPurity`. It mirrors `asset_import.py` function-for-function **except
  `pad_to_frame`, which is deliberately absent**: centring a master sheet on a
  padded canvas would shift every row and silently mis-cut every `row_start`
  window taken from it.
  `font_import.py` (UH-Font-A: custom .ttf/.otf import, mirrors
  `asset_import.py`'s shape) is Qt-free and in `TestPurity` too, but — like
  `asset_import.py` uses Pillow — it uses pygame for a format-validation
  probe (`pygame.font.Font(path, 12)`), not rendering; ED-22 is unaffected.
  `widget_tree.py` (UiEditorParentingPLAN P-1 — the screen-mode widget
  HIERARCHY resolver: `resolve_parent`/`parent_map`/`build_tree`/
  `descendants`/`ancestors`/`would_cycle`/`legal_parents` over
  `screen_defaults.json`'s optional `parent` key plus the open doc's own
  re-parenting override) is stdlib-only and in `TestPurity` too.
- `ui_screen_session.py` — `UIScreenSession`, screen mode's session (B4, §
  below); Qt-only (a `QUndoStack`), no game imports, in `TestPurity`.

## The selection model (the editor's core invariant)
Exactly one selected node (map / building level / enemy / UI / VFX slot) drives
everything: viewport mode (tilemap editor for maps, entity preview for entities),
balancing panel content, and asset-import context (ED-3). **New editor features
should hang off selection, not add parallel state.**

## Hard rules
- **One render path:** the viewport draws through `engine/render` into an embedded
  surface — never a second Qt-side renderer (ED-22). What the editor shows is what
  the game draws.
- All `data/` writes go through the schema-validating writer; invalid input must be
  unrepresentable in the forms (ED-30/31).
- Asset import keeps full parity with the prototype importer's semantics (ED-40):
  rows = animations, row 0 idle, per-row fps/hidden/loop, offset, animated preview
  via `playback_order`.
- **Every new editor module MUST be added to `test_editor_viewport.TestPurity`'s
  import list.**

## Run controls (`run_controls.py`, Phase 7, ED-50/51/52) — invariants
Full debugging saga (three live bugs, in order found) is in `PLAN.md`'s phase-7
row; the forward-looking invariants:
- Pure, Qt-optional builders (`play_command`, `build_command`, `playbuild_path`,
  `build_exists`) plus `RunControls(QObject)`.
- **Play and Playbuild are DETACHED, not tracked** (`QProcess().startDetached()`,
  instance form — the static overload can't take a custom environment, and a
  tracked `QProcess` crashed with "Signal source has been deleted" when the
  long-lived GUI process finished). Only a one-line `launched(which, started_ok)`
  signal fires — no output streaming.
- **`_real_window_environment()` strips `SDL_VIDEODRIVER`/`SDL_AUDIODRIVER=dummy`**
  from the detached child's env — `viewport.py` sets those in `os.environ` for its
  own offscreen surface, and every spawned subprocess inherited them (so Play/
  Playbuild ran but rendered into an invisible dummy surface — no window). This is
  the ONE tested strip point, reused by spawnclaude too.
- **Build stays tracked** (short-lived, progress matters): one `QProcess` at a time
  (a second `build()` is refused, not queued). Signals: `output(str)` (merged
  stdout+stderr), `started`/`finished`, `build_state_changed(can_playbuild)`.
  Guards with `shiboken6.isValid(self)` before emitting. Gets `PYTHONUNBUFFERED=1`
  injected (into `QProcessEnvironment.systemEnvironment()` + `insert`, never a bare
  env) — Python block-buffers stdout off a tty, so without it the console shows
  nothing until exit. `RunControls` does NOT save/validate — `MainWindow` does that
  before `.play()`.
- **`tools/build.py`** (T-4): PyInstaller `--onedir`; calls
  `tools.smoke.validate_data()` first; invoked as `[sys.executable, "-m",
  "PyInstaller", ...]`. Output `dist/HowToBeHuman/HowToBeHuman.exe`.
- **Frozen-exe data path** (`game/main.py`): use `sys._MEIPASS` (PyInstaller's
  pointer to bundled resources — correct for onedir + onefile), NOT a
  `sys.executable`-relative path (6.x onedir nests `--add-data` under `_internal/`,
  not beside the exe).
- **`export_layouts_command()` + `RunControls.export_layouts()`** (B4): the
  "Refresh Layouts" toolbar button re-runs `tools/export_ui_layouts.py` (B3)
  through the SAME tracked-`QProcess` infrastructure as Build (`_launch`, one
  run at a time — Build and Refresh Layouts can't overlap; a second call while
  one is in flight is refused). `MainWindow._on_build_started`/
  `_on_build_finished` distinguish the two by the shared signals' `which`
  string ("build" vs "export_layouts") — only "build" touches the Build
  toolbar action's enabled state / playbuild availability.

## Screen mode (`ui_screen_session.py`, `panels/screen_details.py`, B4, R3)
Editor authoring for `data/ui/screens/<id>.json` overrides (B1) against B3's
generated `data/ui/screen_defaults.json` layouts — a UI-screen leaf under the
selector's "ui" category ▸ "Screens" branch is a THIRD selection mode
alongside entity preview and tilemap mode, structurally mirroring map mode
end-to-end (session / viewport mode / right-pane panel / dirty-prompt /
undo routing). Panel-level rendering/interaction detail lives in
`editor/panels/CLAUDE.md`; this is the cross-cutting shape.
- **`UIScreenSession(QObject)`** (`editor/ui_screen_session.py`, Qt-only, no
  game imports) is an exact structural mirror of `map_session.MapSession`:
  one open doc (a plain dict, `data/ui/screens/<screen_id>.json`), its own
  `QUndoStack`, `open`/`save`/`dirty`. Every push_* method (`push_move`,
  `push_resize`, `push_field`, `push_skin_assign`, `push_background`,
  `push_default_field`) goes through ONE `_DocFieldCommand`: full old/new
  values, never a delta (`old`/`new` of `None` means "no override" — the key
  is ABSENT, never JSON `null` — and clearing prunes now-empty parent
  containers so a fully-reset widget disappears from the doc rather than
  lingering as `{}`).
- **Widget PARENTING (UiEditorParentingPLAN) is an AUTHORING relationship,
  not a runtime one.** The hierarchy is DATA — an optional `parent` per
  widget in `data/ui/screen_defaults.json` (authored by the exporter) plus an
  optional `parent` override per widget in `data/ui/screens/<id>.json` (the
  designer's own re-parenting, D3). **Nothing in `game/` reads either.**
  Moving a parent cascades at EDIT time and writes updated ABSOLUTE rects for
  the whole subtree in ONE undo command, so the game's documented "no
  cascade" convention (`game/ui/CLAUDE.md`) and its flat `setattr` apply loop
  are untouched. Resizing does NOT cascade. Visibility inherits in the
  editor PREVIEW only. Panel-level detail (the outliner tree, the drag,
  the cascade, the hidden-by-parent note) lives in `editor/panels/CLAUDE.md`;
  the pure resolver is `editor/widget_tree.py`.
  - **`push_field` has ONE sentinel, and only this key needs it.** Every
    push_* method spends `None` on "no override — the key is ABSENT", but
    `parent` has a THIRD state: an explicit JSON `null` meaning "the designer
    rejected the default parent; this widget is a root". `ui_screen_session`
    exports `NO_PARENT` (a deepcopy-stable singleton `_apply_field` writes as
    a real null) and `parent_override(widget_override)`, the ONE accessor
    that reads the three states apart. A caller that reads
    `override["parent"]` directly will silently turn a re-root into a no-op.
- **Window-level undo/redo now ROUTES**: `MainWindow._on_undo`/`_on_redo`
  target `screen_session.undo_stack` while in screen mode, else
  `map_session.undo_stack` (`_active_undo_stack`) — Ctrl+Z/Y work across mode
  switches while a session is open, exactly like the map/screen selection
  split routes `_resolve_dirty(session=None)` (defaults to the map session for
  every pre-B4 call site; screen mode passes `self.screen_session`
  explicitly).
- **Selection flow mirrors maps exactly**: `selector.screen_selected(screen_id)`
  → `MainWindow._on_screen_selected` → `_resolve_dirty(screen_session)` →
  `session.open(screen_id)` → `_enter_screen_mode()` (loads
  `data/ui/screen_defaults.json` fresh, `viewport.set_screen_mode(session,
  defaults)`, `screen_details.set_defaults(defaults)`, `right_stack` →
  `screen_details`) → `_leave_screen_mode()` on any other selection.
  `data/ui/screen_defaults.json` not existing (pre-B3, or a broken dev
  machine) is NOT an error path — `_load_screen_defaults()` degrades to `{}`
  and screen mode's own E-37 placeholder handles it (see the panels doc).
- **Never imports `game/ui`** (layering rule) — the unskinned-widget fallback
  look is re-implemented in `editor/panels/_screen_primitives.py`, an accepted
  drift kept aligned to the game's real skinned look by eye + the B2 parity
  pin, not by sharing code.
- **UH-2: per-mode views + auto Refresh Layouts on entry.** `building_panel`
  carries five VIEWS in `data/ui/screen_defaults.json` (`unlock`/`construct`/
  `upgrade`/`base_info`/`preview` — UH-1's per-mode exporter output), shown as
  child leaves under its Screens-branch leaf; `UIScreenSession.view` (non-doc,
  non-undoable) tracks the active one and both panels'
  `_current_screen_defaults()` resolve it — full detail in
  `editor/panels/CLAUDE.md` "Phase UH-2". Overrides still write to the ONE
  `data/ui/screens/building_panel.json` regardless of active view (D2, ids
  global to the screen). `MainWindow(..., auto_refresh_layouts=True)` auto-runs
  "Refresh Layouts" once per screen-mode entry (never on a view/screen switch
  within screen mode) — tests inject `auto_refresh_layouts=False` everywhere
  except the dedicated auto-refresh tests.

## Agent dispatch (`spawnclaude.py`, `agent_forms.py`, `agent_form_dialog.py`, `plans.py`, AD-1/2/3/6/7) — invariants
The "Summon a Drunken Robot" toolbar button (label is fixed) opens the LAUNCHER.
Phase-8's narrative is in `PLAN.md`; the plan is `planning/completed plans/AgentDispatchPLAN.md`.

- **Forms are DATA, not code.** One form spec per thing-type in
  `data/agent_forms/<id>.json`, validated against `schemas/agent_form.schema.json`
  (`id` == filename stem, loader-enforced). `agent_form_dialog.AgentFormDialog`
  renders a spec — title/description → a **built-in free-text box** (never a spec
  field: every form gets it free) → one row per field → git group → Dispatch. There
  is exactly ONE `field["type"]` → widget switch (`_make_widget`); nothing else may
  branch on it. Adding a form means adding a JSON file, never a dialog class.
- **Specs load FRESH on every launcher open** (`agent_forms.load_form_specs`) — a
  spec written by an agent shows up without an editor restart.
- **Invalid input unrepresentable (ED-30)**: numeric spinbox ranges come from the
  spec's `minimum`/`maximum` (schema-REQUIRED on numeric fields); the `_NoWheel*`
  spin/combo widgets are IMPORTED from `editor.panels.balancing` (their home —
  never copied, never moved). Dispatch is enabled only when every `required` field
  is non-empty (boolean/numeric fields always hold a value, so they never gate).
- **Handoff flow**: `build_payload` → `write_handoff` (through
  `engine.data_io.write_validated`, `schemas/dispatch_handoff.schema.json`) →
  `spawnclaude.dispatch(handoff=<repo-relative POSIX path>)` → `/dispatch <relpath>`
  as claude's opening input. Handoffs live in **gitignored `.claude/dispatch/`**
  (transient agent I/O, not `data/` content); the launcher calls
  `agent_forms.prune_done(repo)` on every open. `editor/agent_forms.py` is PURE
  (stdlib + `engine.data_io`), and both it and `agent_form_dialog.py` are in
  `TestPurity`.
- **Four dispatch modes**, each passing the LITERAL slash command as claude's
  opening input so the skill loads directly: **form** → `/dispatch <handoff>`;
  **plan** → `/setcurrentplan <name>` or `/createplan <brief>` (AD-7, see the Plans
  group below); **small tweak** → `/smalltweak <task>`; **admin** → blank `claude`
  (no input, no scope). Precedence in `dispatch()`: **admin > handoff > plan >
  tweak**. Admin, plan and small tweak bypass the handoff path entirely — they
  write NO handoff.
- **Launcher structure is a seam**: `SpawnClaudeDialog` is built from small
  `_build_*_group()` helpers appended to ONE `QVBoxLayout`, **button box LAST**, so
  a new group is a single `addWidget` line. Form entries are buttons (a door you
  walk through), tweak/admin stay radios governed by the button box.
- **Import direction**: `agent_form_dialog` imports `spawnclaude` at module top;
  `spawnclaude` imports `AgentFormDialog` **lazily inside `_open_form`** — a
  top-level import both ways is a cycle.
- **Terminal launch = Windows Terminal (`wt`) only**: `["wt", "-d", <repo>, "cmd",
  "/k", "claude", <prompt>]`, the prompt as ONE argv element (a repo path with
  spaces stays safe). REUSES `run_controls.start_detached` +
  `_real_window_environment()` (same SDL-dummy strip). `detach` is injectable end
  to end (launcher → form dialog → `dispatch`) so tests capture argv and no real
  terminal ever opens.
- **The branch+lock protocol is REMOVED** (root `CLAUDE.md` §Branching):
  spawnclaude has no domain mode and reads no locks; `editor/domains.py`
  (née `locks.py`) serves the balancing panel's domain derivation only.
- **`.claude/` layout**: `commands/` holds the skills (`dispatch.md` does git setup
  + payload translation, then drives the target `add-*` skill unmodified);
  `dispatch/` holds live handoffs and `dispatch/done/` the archived ones (both
  gitignored). Integration branch = `Development`.
- **Plans group (AD-7, `editor/plans.py` — pure)**: the launcher shows the ACTIVE
  PLAN (root `PLAN.md`'s line-1 `<!-- active-plan: … -->` marker — the single
  source of truth; stripped marker → `None` → "— none set", never a crash) and a
  picker over `planning/*.md`, both read FRESH on every open. **The editor never
  writes root `PLAN.md` or anything under `planning/`** — "Set as current" and the
  "Create a new plan" radio spawn `/setcurrentplan <name>` / `/createplan <brief>`
  to do the writing (the editor reads; spawned skills write), via `dispatch()`'s
  `plan_prompt=` keyword (precedence **admin > handoff > plan > tweak**; the
  prompt is always built by a `plans.*_prompt` builder, never hand-assembled).
  `plans.reveal_command` is the ONE folder-open path (argv, branching on
  `sys.platform`); `spawnclaude.open_planning_folder` splits that argv for the
  same injectable `detach`, so tests capture it and no real explorer opens.

## Theme (`theme.py`) — light / dark chrome
- The **"Dark mode" checkbox on the Agents toolbar**, next to "Summon a Drunken
  Robot", is the switch. `MainWindow._on_theme_toggled` → `theme.apply_theme` +
  `theme.save_theme`; nothing else in the editor may call `setPalette`/`setStyle`
  on the QApplication.
- **Chrome only** — the viewport keeps drawing through `engine/render` (ED-22); a
  theme switch must never reach into how game content is rendered.
- **Dark forces Fusion**; light restores the platform's startup style + palette
  (captured on the first `apply_theme`). The native Windows style ignores a dark
  palette on several widgets, so a dark theme without Fusion half-applies.
- Persisted to `.editor_prefs.json` (gitignored, repo root — the same file ED-1's
  layout persistence will use, so `save_theme` read-modify-writes and preserves
  other keys). Missing/corrupt file → light. `MainWindow(prefs_path=…)` is
  injectable so tests never write the repo's prefs.
- Panel-local `setStyleSheet` colors (the balancing dirty dot, the map-details
  warning banner) are deliberately theme-independent — keep any new hardcoded
  color legible on BOTH backgrounds, or read it from the palette.

## VFX preview (`panels/vfx_preview.py`, ESV-4) — a second `Renderer`, still ED-22

`VfxPreviewPanel` builds its OWN `load_coordinate_system` + `AssetStore` +
`Renderer` + offscreen `pygame.Surface`, structurally copying
`ViewportPanel.__init__`/`_build_store`/`render_frame` (see `editor/panels/
CLAUDE.md` for the panel's own architecture). **A second `Renderer` instance
is not a second render path.** ED-22 bans a second QPainter-drawn surface of
game content, not a second orchestrator object — everything the preview
draws goes out as the same `HudRect`/`HudLines`/overlay primitives
`engine.vfx.VfxSystem` submits for the real game, through the SAME
`engine/render` backend. `panels/sheet_preview.py` already sanctioned this
reading (see the panels doc); the vfx preview is the second precedent.

Layering: `engine.vfx`'s emitters take injected params + an injected RNG
specifically so `editor/` can drive the SAME emitter the game does without
either package importing the other (D5). Since `editor/` may never import
`game/`, the JSON-key -> dataclass adapter game/ui/effects.py owns
(`_params_from_balance`) is DUPLICATED as `editor/vfx_params.py` — a
deliberate, reported drift, precedented by `editor/panels/
_screen_primitives.py` re-implementing `game/ui`'s unskinned widget look for
the same reason. Do not resolve the duplication by importing `game.ui.effects`
or by moving the mapping into `engine/vfx` (that would give the engine
package JSON vocabulary, which D5 exists to prevent).

**M5 — "Use Master Spritesheet…" beside "Import Spritesheet…"** (GpuAndMasterSheetsPLAN
§6/M5, D5). Same visibility rule as the Import button: a family that
resolves to ONE fixed `vfx_*` slot (projectile/shell, crater, beam), via
`_current_import_slot()`. It opens `panels/master_sheet_dialog.MasterSheetDialog`
(construction split from display — `use_master_sheet(sheet, row=None)` is the
model half every test drives, so no test `exec()`s the modal) and links the slot
to the registry entry's **STORED** `file`, copying no bytes. **The sheet owns
the grid (D3)**: `frame_w`/`frame_h` come off the master registry, never
`registry.frame_size(slot)`, and **`slots.json` is not written** — a master
sheet's grid is not a per-slot override.

**ONE row spin, not M4's two** (`Master sheet row`): a `vfx_*` entry is a single
`idle` row — `asset_import.import_idle_sheet`'s shape, which
`use_master_sheet` reproduces exactly — so the window is always one row long
and a second spin could only hold the value the first already implies. The
spin's ceiling is the sheet's real last row, `row_start` is OMITTED at 0 (the
`slice`/`tint_overlay` convention), and moving the spin rewrites **only**
`row_start` on the existing entry, so a row edit made in DetailsPanel survives.
Unlike DetailsPanel this panel has **no Save button**, so both paths write
straight through `asset_import.write_manifest_doc` and then `reload_assets()`
(ED-42) — matching what the Import button beside it already did.

**ESV-6 forced a real (not cosmetic) edit here**, despite that phase's brief
expecting none: `engine.vfx.VfxParams` gained a new REQUIRED field
(`floaters`, no defaults anywhere in that module, G-7), so every direct
`VfxParams(...)` construction needed a `floaters=` argument — including this
file's `params_from_balance`, which `vfx_preview.py:442` calls on every
family switch. Without the matching `floater_params(fl)` helper here, the
panel would raise `TypeError` the instant a designer opened the vfx preview
(confirmed live, not inferred: `TypeError: VfxParams.__init__() missing 1
required positional argument: 'floaters'`). `floaters` still carries no
preview LEVER of its own — `vfx_preview.py`'s `_EMIT_FAMILIES`/graceful-
degrade placeholder for it is unchanged — this is purely what keeps the
dataclass constructible for every OTHER family's preview.

## The VFX roster is editable (VfxAuthoringPLAN VA-6)
`editor/registry_ops.py` could only APPEND until this phase. For the `vfx`
category it now also removes and renames:
- **`add_vfx_effect(data_dir, name)`** — `add_button_family`'s stack one
  category over (slug via `vfx_effect_slot`, validate-before-any-write, a new
  leaf child group under vfx ▸ Effects, ready for its own `_v<k>` variants).
- **`remove_slot(data_dir, slot_key)`** — **refuses while the slot is BOUND**
  to a trigger row rather than orphaning that row; drops the manifest entry;
  drops the leaf group when its last slot goes; unlinks the PNG **only** when
  `asset_import.unreferenced_sheets` clears it, so a slot that LINKED to
  another's art can never delete art the owner still needs. Refuses to remove
  the last effect (an empty `children` list fails the schema).
- **`rename_slot(data_dir, old, new)`** — a FOUR-FILE migration, which is the
  whole point of it existing: `slots.json`, the manifest entry, the owned PNG
  (a LINKED sheet is left pointing where it pointed) and every `triggers` row
  naming the old key. One that moved three of the four would leave either a
  dangling binding or art nobody can reach.

**All three resync the generated `sprite_slot` enum** through
`_resync_vfx_slot_enum` → `tools.gen_sprite_slot_enum.apply_vfx`. Load-bearing,
not housekeeping: that enum is GENERATED (VA-1/D2), so without the resync "Add
effect" hands the designer an effect they cannot BIND, and "Rename" writes a
trigger row that fails its own schema on the way out. Found by
`test_vfx_roster_ops`, which could not bind a slot it had just created. It
CALLS the generator rather than reimplementing it — `test_schema_slot_sync`
pins that one function, and a second copy here would be exactly the drift a
generated enum exists to prevent. `editor -> tools` is the established
direction (`main.py` → `tools.smoke`, `test_runner.py` → `tools.test_domains`)
and the generator is pure `engine` underneath, so `TestPurity` is unaffected.

`"vfx"` also joined `main.py`'s `_VARIANT_TARGETS`, which is what lights up the
existing "+ Variant" button. It could not be listed before VA-1 restructured
that category: a flat `slots` group makes `selection.variant_target()` return
`None`, so the button would have been dead.

## VFX panel: the roster + binding strip (VA-7) and the highlights preview (VA-8)
Two rows above the existing family/lever controls turn VA-6's ops and VA-2's
schema into something a designer reaches:
- **Roster** — Effect / Variant combos + `+ Effect`, `+ Variant`, `Rename…`,
  `Remove`. It reads the live registry through `editor/selection.py`, so it
  adds no parallel state (the single-selection rule's spirit).
- **Binding** — Event combo, Bind / Unbind, the variant `Pick` mode, the misc
  key (shown only in `misc` mode) and the `draw in front` checkbox.

**The two write paths deliberately differ.** Registry edits are STRUCTURAL, so
they go straight to `slots.json` through `registry_ops` and emit
`registry_changed` for the shell to re-read (`DetailsPanel.registry_changed`'s
precedent). Everything else is a BALANCING value and STAGES through
`self._balancing.stage_value` — this panel does not become a second writer of
`vfx.json`, and Save stays the balancing panel's one button. Pinned by a test
that binds an effect and asserts `vfx.json` is byte-unchanged.

Two things worth keeping in mind when editing this strip:
- **Populating the binding row blocks signals throughout.** Without that,
  merely SELECTING an event fires the handlers that stage values, so *looking*
  at an effect would dirty the document. There is a test for exactly that.
- **Every modal is split from its model half** (`name=` / `new_key=` /
  `confirm=`) — `main.py::_on_add_button_type`'s seam — so no test `exec()`s a
  dialog. The delete button's `clicked.connect(lambda: self._on_remove())`
  wrap is load-bearing (an unchecked button emits `clicked(False)`, which
  would land in `confirm` and skip the confirmation). The test for it stubs
  `QMessageBox.question` and asserts it was REACHED rather than clicking
  through a real dialog — the first version opened one and crashed an xdist
  worker.

**VA-8** gave `highlights` a real preview instead of the E-37 placeholder. It
is the one `procedural` key holding SEVEN blocks, so it gets a sub-combo (the
`spark`/`_preset_combo` shape) and `_submit_highlight_preview`, which draws the
selected highlight's diamond through `submit_world_fill` — the same
depth-sorted primitive `game/ui/widgets.py::submit_tile_diamond` uses. The four
polygon points are duplicated rather than imported, because `editor/` may never
import `game/`; what matters is that both go through the one world-fill path,
so the preview cannot drift on the thing that counts (which primitive, at which
depth). Its import button targets `vfx_<highlight>`, so the family resolves to
a fixed slot that depends on the sub-combo. **Respawn needed no preview path at
all** — VA-4/D11 made it a fourth `spark` PRESET, so it rides the existing
spark family.

## Running the tests FROM the editor (TestRunnerPLAN TR-5) — the first QThread

The **"Run tests"** button on the Agents toolbar, immediately after "thats my
prod", pops up `panels/test_run_panel.py` as its own **non-modal window** (R3 —
not a dock) and starts a full run. Panel detail lives in the panels doc; the
cross-cutting shape is here because this is the package's FIRST worker thread.

- **`_TestRunWorker(QObject)` in `main.py` owns the thread**, not the panel:
  `moveToThread` + `thread.started -> worker.run`, one `TestRun` per run.
- **A worker callback may do exactly ONE thing: `emit`.** TR-3 calls
  `on_progress` on the worker thread; touching a widget, the panel or the status
  bar from there is a cross-thread widget write — the classic intermittent
  crash. `MainWindow._on_test_progress/_on_test_finished/_on_test_failed` are
  the ONLY callers of `TestRunPanel.apply_*`.
- **Marshalling is Qt's automatic queued delivery** and nothing else: the
  emitter's thread affinity differs from the receiver's, so `AutoConnection`
  queues each emission onto the GUI event loop. Never hand-roll it with
  `QMetaObject.invokeMethod` or `QTimer.singleShot(0, …)`, and never force
  `Qt.DirectConnection` (that puts the slot back on the worker thread).
- Every `emit` is guarded with `shiboken6.isValid(self)` — the same guard
  `RunControls` uses for the same hazard.
- **`MainWindow.closeEvent` joins the thread** (cancel → `quit()` →
  `wait(5000)`). A live `QThread` whose `QObject`s are being deleted is the
  "Signal source has been deleted" class of crash, and the test harness's
  `destroy()` really frees the C++ object.
- A second run while one is in flight is **refused, not queued** (the Build
  rule). TR-5 writes NOTHING to the guard's ledger and takes NO lock.

## Testing the editor — two rules, both learned the hard way

**1. Every widget you construct in a test must be destroyed.** Subclass
`QtCase` (`tools/tests/qt_harness.py`) and wrap it: `self.track(MainWindow(...))`.
`self.addCleanup(w.close)` is **not** cleanup — Qt's `close()` *hides* a window,
it does not destroy it. Each leaked `MainWindow` kept ~2,972 widgets alive and
made the next one slower to build, which is how the suite became quadratic
(17m 15s for what now takes 2m 31s). `qt_harness.destroy()` is the one idiom;
`test_qt_harness.py` fails if the bare-`close()` pattern comes back.

Leaked widgets also outlived their tests and **wrote into the repo's `data/`** —
painting tiles into real maps, inventing map files. A session fixture now hashes
`data/` before and after the suite and fails the run if anything changed.

**2. Never assert against live `data/` content — pin the fixture.** Use
`TempDataCase.unassign_slot` / `unassign_family` / `drop_slot_variants` and
`MapModeCase.set_active_map` to *guarantee* the state you need. Tests that
merely assumed "the Painter slot has no art" or "first_light is the active map"
are what put 18 tests permanently in the red: an artist imported sheets, a
designer set a different map active, and the tests started failing for reasons
that had nothing to do with the editor. A test that reads today's `data/` is
testing the designer, not the code.

Also: **every new editor module goes into `test_editor_viewport.TestPurity`'s
import list** (the layering guard — `editor/` must never import `game/`).

## Verify before finishing
```bash
py tools/smoke.py                                    # always
py -m pytest tools/tests/test_<panel>.py -q          # the files your change touches
```
**Which tests you may run is ROLE-scoped — the role table in §"Test Suite
Policy" (root `CLAUDE.md`) is the only authority, and a `PreToolUse` hook
enforces it.** A subagent stops at the two commands above. `py -m pytest -m
editor` is a TIER SWEEP (the whole Qt tier, minutes) — main session only, and
rarely worth it over naming the panel's own test file. The single full
`py tools/testgate.py check` belongs to the MAIN SESSION at handoff. The gate is
ZERO failures.
Then launch `py editor/main.py` and exercise the changed panel/control; for
data-writing features, confirm the JSON on disk validates and a Play subprocess
loads it. State exactly what you exercised (live editor run vs static read).
