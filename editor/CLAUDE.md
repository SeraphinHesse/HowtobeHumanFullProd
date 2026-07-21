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
- `domains.py` — derived domain list + balancing/schema path helpers (AD-6):
  the list is a function of slots.json ∩ `data/balancing/*.json`, never a
  hardcoded constant.
- Pure helpers used by panels: `selection.py`, `map_session.py`, `tilemap_ops.py`,
  `registry_ops.py`, `asset_import.py`, `agent_forms.py`, `theme_ops.py` (UH-6:
  fonts/palette load-validate-write, `panels/game_theme.py`'s home) — all
  Qt-free/pygame-free, in `TestPurity`.
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
py tools/testgate.py check     # the gate is ZERO failures
py -m pytest -m editor         # just the Qt tier, while iterating
```
Then launch `py editor/main.py` and exercise the changed panel/control; for
data-writing features, confirm the JSON on disk validates and a Play subprocess
loads it. State exactly what you exercised (live editor run vs static read).
