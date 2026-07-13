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
- `spawnclaude.py` — dispatch a `claude` session with a domain lock or in
  small-tweak (no-lock) mode (§ below).
- `theme.py` — THE light/dark chrome theme (§ below). The only place the app's
  Qt palette/style is set.
- `locks.py` — read/enforce `_lock` on `data/balancing/*`; the editor obeys the
  same lock rules as agents (ED-62) and **NEVER force-unlocks**.
- Pure helpers used by panels: `selection.py`, `map_session.py`, `tilemap_ops.py`,
  `registry_ops.py`, `asset_import.py` (all Qt-free/pygame-free, in `TestPurity`).

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
- Locked domain → read-only UI with owner shown (ED-32); greyed out in spawnclaude
  (ED-61). **No set/clear/force-unlock exists anywhere in the editor** (a test
  asserts it).
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

## Spawnclaude / locks (`spawnclaude.py`, Phase 8, ED-60/61/62, T-1) — invariants
Full narrative in `PLAN.md`'s phase-8 row; the invariants:
- Pure Qt-free builders (`domain_choices`, `start_domain_prompt`,
  `small_tweak_prompt`, `spawn_command`) + `dispatch()` + `SpawnClaudeDialog` (in
  `TestPurity`). Reads locks via `editor.locks` (ED-61 greying) and NEVER writes
  one.
- **Delegation lock model** (user-confirmed, reconciles ED-60 vs. `locks.py`'s
  "editor never writes locks"): the editor GUI does NOT flip any `_lock` — the
  spawned `/start-domain` skill does, so the branch+lock protocol stays the single
  lock-writer and `/merge-domain` the only unlock (ED-62). A test asserts
  spawnclaude exposes no set/clear/unlock symbol.
- **Three dispatch modes**, each passing the LITERAL slash command as claude's
  opening input so the skill loads directly: **domain** → `/start-domain <domain>`;
  **small tweak** → `/smalltweak <task>` (no lock/scope; the scope guard fail-opens
  when no domain is active); **admin** → blank `claude` (no input/lock/scope).
  Precedence admin > domain > tweak.
- **Terminal launch = Windows Terminal (`wt`) only**: `["wt", "-d", <repo>, "cmd",
  "/k", "claude", <prompt>]`. REUSES `run_controls.start_detached` +
  `_real_window_environment()` (same SDL-dummy strip). `dispatch(detach=…)`
  injectable so tests capture argv.
- **`.claude/` layout**: `commands/` holds the ported skills;
  `hooks/scope_guard.py` is the PreToolUse file-scope guard (reads
  `.claude/active_domain`, fail-open when absent; deny via `permissionDecision:
  "deny"` JSON), wired in `.claude/settings.json` on `Edit|Write|MultiEdit`. Lock
  writes go through `engine.data_io.write_validated` (the lock is a D-11 object).
  Integration branch = `main`.

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
