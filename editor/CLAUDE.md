# CLAUDE.md — EDITOR package (router)

Self-contained guide for `editor/` — the PySide6 editor, the designer's single
interface to all game data. You reached here from the root router. Requirements:
SPEC.md §7 (`ED-*`).

This doc is a **router**: it holds the cross-cutting rules + the conventions for
the top-level `editor/*.py` files (run controls, spawnclaude, locks), and points
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
- `locks.py` — read/enforce `_lock` on `data/balancing/*`; the editor obeys the
  same lock rules as agents (ED-62) and **NEVER force-unlocks**.
- Pure helpers used by panels: `selection.py`, `map_session.py`, `tilemap_ops.py`,
  `registry_ops.py`, `asset_import.py`, `agent_forms.py` (all Qt-free/pygame-free,
  in `TestPurity`).

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
- Locked domain → read-only UI with owner shown in the balancing panel (ED-32).
  **No set/clear/force-unlock exists anywhere in the editor** (a test asserts it).
  Spawnclaude no longer reads locks at all (the protocol is SUSPENDED — § below).
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

## Agent dispatch (`spawnclaude.py`, `agent_forms.py`, `agent_form_dialog.py`, AD-1/2/3) — invariants
The "Summon a Drunken Robot" toolbar button (label is fixed) opens the LAUNCHER.
Phase-8's narrative is in `PLAN.md`; the plan is `planning/AgentDispatchPLAN.md`.

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
- **Three dispatch modes**, each passing the LITERAL slash command as claude's
  opening input so the skill loads directly: **form** → `/dispatch <handoff>`;
  **small tweak** → `/smalltweak <task>`; **admin** → blank `claude` (no input, no
  scope). Precedence in `dispatch()`: **admin > handoff > tweak**. Admin and small
  tweak bypass the dispatch path entirely — they write NO handoff.
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
- **The branch+lock protocol is GONE from spawnclaude** (suspended per root
  `CLAUDE.md`): no `domain_choices`, no `start_domain_prompt`, no `/start-domain`
  mode, no lock reads. `editor/locks.py` stays, stays READ-ONLY, and still serves
  the balancing panel; **no set/clear/force-unlock anywhere in the editor** (a test
  asserts spawnclaude exposes no such symbol). `/dispatch` writes no
  `.claude/active_domain`; `.claude/hooks/scope_guard.py` stays fail-open.
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
  to do the writing (same delegation model as locks), via `dispatch()`'s
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

## Verify before finishing
Launch `py editor/main.py` and exercise the changed panel/control; for
data-writing features, confirm the JSON on disk validates and a Play subprocess
loads it. State exactly what you exercised (live editor run vs static read).
