# Phase AD-3 — Generic form renderer + launcher dialog (end-to-end)

Brief for the coder. Plan: `planning/AgentDispatchPLAN.md` §2, §3, §5, §6 (AD-3).
Base branch: `phase-AD-1-7-umbrella` (off `Development`), with AD-1 and AD-2
already merged into it.

**Goal (plan §6/AD-3):** the full designer path works live — toolbar "Summon a
Drunken Robot" → launcher → "Add New Enemy" form → terminal opens running
`/dispatch <handoff>` → PR on a branch off `Development`. This is the biggest
phase of the plan; it is the first one where a designer can actually press a
button and get an agent.

**What already exists when you start (do not re-implement, do not re-touch):**
- AD-1 → `editor/agent_forms.py` (pure, Qt-free, already in `TestPurity`):
  `forms_dir(data_dir)`, `load_form_specs(data_dir)`, `slugify(text, max_len=32)`,
  `default_branch_name(spec, values, free_text)`, `build_payload(spec, values,
  free_text, git_mode, branch, repo)`, `write_handoff(payload, repo) -> Path`,
  `handoff_relpath(path, repo) -> POSIX str`, `prune_done(repo, days=30)`.
  Plus `data/agent_forms/add-enemy.json`, `data/schemas/agent_form.schema.json`,
  `data/schemas/dispatch_handoff.schema.json`, and the `tools/smoke.py` directory
  exception.
- AD-2 → `editor/spawnclaude.py` pure layer:
  `dispatch(handoff=None, tweak_prompt=None, admin=False, repo=None, detach=None)`
  (precedence **admin > handoff > tweak**), `dispatch_prompt(handoff_relpath)` →
  `f"/dispatch {handoff_relpath}"`, `small_tweak_prompt`, `spawn_command`
  (argv contract byte-identical: `["wt", "-d", <repo>, "cmd", "/k", "claude",
  <prompt>]`, prompt as ONE argv element), and a domain-free `SpawnClaudeDialog`
  that temporarily lists only tweak/admin. `.claude/commands/dispatch.md` exists.

---

## 1. Behavioral spec

### 1.1 `AgentFormDialog(spec, data_dir=None, repo=None, parent=None, detach=None)`

New module `editor/agent_form_dialog.py` (plan §5, "Editor-side components →
`editor/agent_form_dialog.py`"). A `QDialog` rendered entirely from one form
spec dict (already schema-validated by `agent_forms.load_form_specs`, so the
dialog may trust its shape — but see §1.5 on `schema_version`).

Render order, top to bottom:

1. **Title + description labels.** Window title = `spec["title"]` (e.g. "Add New
   Enemy"); a bold `QLabel` with the title and a word-wrapped `QLabel` with
   `spec["description"]` (plan §3: "One paragraph shown under the title").
2. **Built-in free-text box.** A `QPlainTextEdit` labelled something like
   "Describe it in your own words" with a helpful placeholder. Plan §3 is
   explicit: *"The **free-text description box is built into the dialog**, not a
   spec field — every form gets it for free."* It is therefore NOT enumerated in
   `spec["fields"]`, has no `key`, and feeds `build_payload(..., free_text=…)`.
   It is never `required` (the gating in §1.4 covers spec fields only) — but it
   IS the fallback slug source when `slug_field` is missing (AD-1's
   `default_branch_name` already implements that fallback; the dialog just has to
   pass the live free text in).
3. **One row per `spec["fields"]` entry**, in spec order, in a `QFormLayout`
   (`field["label"]` as the row label). Widget per `field["type"]` — the
   balancing panel's idiom, reused verbatim (plan §5: *"reusing the balancing
   idioms"*; the mapping mirrors `editor/panels/balancing.py::_make_widget`,
   L371-408):

   | `type`     | widget                                            | value getter                  |
   |------------|---------------------------------------------------|-------------------------------|
   | `string`   | `QLineEdit`                                       | `w.text().strip()`            |
   | `text`     | `QPlainTextEdit`                                  | `w.toPlainText().strip()`     |
   | `boolean`  | `QCheckBox`                                       | `w.isChecked()`               |
   | `integer`  | `_NoWheelSpinBox` (from `editor.panels.balancing`)| `int(w.value())`              |
   | `number`   | `_NoWheelDoubleSpinBox` (same import)             | `float(w.value())`            |
   | `enum`     | `_NoWheelComboBox` (same import)                  | `w.currentData()`             |

   - **Imports:** `from editor.panels.balancing import _NoWheelComboBox,
     _NoWheelDoubleSpinBox, _NoWheelSpinBox`. Do not copy-paste those three
     classes into the new module and do not rename/move them — the balancing
     panel is their home and it is out of scope here. (They exist precisely so a
     mouse wheel over a scrollable form can never silently nudge a value;
     `editor/panels/balancing.py` L73-88.)
   - **Ranges from the spec (ED-30).** `setRange(field["minimum"],
     field["maximum"])` for `integer`/`number` — the agent-form schema makes both
     REQUIRED on numeric fields (plan §3 `allOf` if/then), so there is no default
     branch to write: out-of-range input is *unrepresentable*, not merely
     rejected. Give the double spinbox sensible decimals/step (follow balancing:
     4 decimals, 0.1 step) unless the spec suggests otherwise.
   - **Enum options** come from `field["options"]` (schema-required for `enum`);
     add each with `addItem(str(o), o)` so `currentData()` returns the real value,
     exactly as balancing does.
   - **Tooltips.** `widget.setToolTip(field["description"])` on every widget —
     `description` is schema-required on every field and is documented as
     "Widget tooltip" (plan §3).
   - **Defaults.** If `field` carries `default`, seed the widget with it
     (checked / value / `findData` index / text). No `default` → empty
     `QLineEdit`/`QPlainTextEdit`, unchecked box, spinbox at its minimum, combo at
     index 0.
   - **Placeholders.** `field["placeholder"]` → `setPlaceholderText` on
     `QLineEdit`/`QPlainTextEdit` when present.
   - **Required marker.** Fields with `required: true` should read as required in
     the UI (e.g. label suffixed ` *`, plus a one-line hint under the button row
     naming what is still missing). Cosmetic, but it is what makes the gating in
     §1.4 legible instead of mysterious.

4. **Git group** (plan §5): a `QGroupBox`/frame with two `QRadioButton`s in one
   `QButtonGroup`:
   - `"New branch off Development (ends with a PR)"` → git mode `"branch"`
   - `"Work on current branch"` → git mode `"current"`

   Pre-selected from `spec["git_default"]` (enum `branch|current`, schema-required).
   Below them a **branch-name `QLineEdit`**:
   - Seeded and **live-refreshed** from `agent_forms.default_branch_name(spec,
     values, free_text)` — recompute on `textChanged` of the slug field (the field
     whose `key == spec.get("slug_field", "name")`) and on `textChanged` of the
     free-text box (the fallback source). So typing "Siege Cannon" into *Enemy
     name* makes the branch box read `agent/add-enemy-siege-cannon` as you type.
   - **Still editable**: once the user types in the branch box themselves, stop
     auto-overwriting it (track a `_branch_user_edited` flag set from
     `QLineEdit.textEdited` — which fires ONLY on user input, never on
     `setText()`; do not use `textChanged` for this or the auto-refresh will
     immediately flag itself as a user edit).
   - **Enabled only in branch mode** — `setEnabled(mode == "branch")`, re-applied
     on every radio toggle. In current mode the payload's `git.branch` is omitted
     (the handoff schema requires it only when `mode == "branch"`).

5. **Button box**: a `QDialogButtonBox` with a `Dispatch` (AcceptRole) button and
   `Cancel`.

### 1.2 Values

`values()` (or `_collect_values()`) returns `{field_key: value}` for every spec
field, using the getters in the table above. Empty optional strings: prefer
omitting empty-string values over writing `""` — the handoff schema's `values` is
a permissive object (plan §3) so either validates, but the target skill reads the
payload and an absent key is cleaner than an empty one. Booleans/numerics always
present (they always have a concrete widget state).

### 1.3 On accept (plan §5)

```
values    = self.values()
free_text = self._free_text.toPlainText().strip()
git_mode  = "branch" if self._branch_radio.isChecked() else "current"
branch    = self._branch_edit.text().strip() if git_mode == "branch" else None
payload   = agent_forms.build_payload(spec, values, free_text, git_mode, branch, repo)
path      = agent_forms.write_handoff(payload, repo)
spawnclaude.dispatch(handoff=agent_forms.handoff_relpath(path, repo),
                     repo=repo, detach=self._detach)
self.accept()
```

Check AD-1's actual `dispatch`/`write_handoff` contract before wiring: if
`spawnclaude.dispatch(handoff=…)` takes the **relative POSIX string** (per AD-2's
`dispatch_prompt(handoff_relpath)`), pass `handoff_relpath(path, repo)`; if it
takes the `Path`, pass the `Path` and let dispatch relativize. Read the merged
AD-1/AD-2 code and match it — do not guess, and do not change either module's
signature to suit the dialog.

Surface failures instead of swallowing them: wrap the write/dispatch in a
`try/except` and show a `QMessageBox.critical` with the exception text, leaving
the dialog open (a validation failure from `write_validated` is the whole point
of the validating writer — the designer must see it).

### 1.4 Dispatch gating

The Dispatch button is enabled **only when every field with `required: true` has
a non-empty value** (plan §5: *"Dispatch enabled only when all `required` fields
are non-empty"*; the schema documents `required` as "Gates the Dispatch button").
"Non-empty" means: non-blank text for `string`/`text`; a selected item for `enum`;
`boolean`/`integer`/`number` are *always* non-empty (a checkbox and a spinbox
always hold a valid value), so a required numeric/boolean field can never block
dispatch — that is correct and intended, not a bug to fix.

Precedent for the gating idiom: `editor/panels/balancing.py::_SaveMetaDialog`
(L121-148) disables the OK button and re-enables it from a `textChanged` signal.
Do the same: connect each required text-ish widget's change signal to one
`_refresh_dispatch_enabled()` slot, and call it once at the end of `__init__`.
Also call it after seeding defaults, so a spec whose required field has a
`default` starts enabled.

### 1.5 `schema_version`

Plan §7 (Risks): *"`schema_version: 1` in both schemas; the renderer rejects
unknown versions loudly."* If `spec.get("schema_version") != 1`, raise a clear
`ValueError` naming the spec id and the version rather than rendering a
half-understood form. (`load_form_specs` validates against the schema, whose
`schema_version` is `const: 1` today — so this is belt-and-braces for the day a
version 2 exists.)

### 1.6 `SpawnClaudeDialog` becomes the LAUNCHER

`editor/spawnclaude.py`'s dialog (plan §2 diagram; §5 "`editor/spawnclaude.py`
(modified)"). On open it presents, in one vertical layout:

- **Forms group** — one entry per form spec, from
  `agent_forms.load_form_specs(data_dir)` called **FRESH on every open** (plan §5:
  *"fresh per open — no editor restart needed for new specs"*; AD-5's whole
  premise is that a newly-created spec shows up in the launcher on the next dialog
  open). One `QPushButton` per spec labelled `spec["title"]`, tooltipped with
  `spec["description"]`; clicking it opens `AgentFormDialog(spec, data_dir=…,
  repo=…, parent=self, detach=self._detach)` and `exec()`s it. When the form
  dialog is accepted, the launcher closes too (`self.accept()`) — the dispatch has
  already happened inside the form dialog; a rejected form returns to the launcher.
  A button row is deliberately NOT a radio: a form spec is not a "mode you then
  press Dispatch on", it is a door you walk through. Radios remain for the two
  prompt-only modes below.
- **Small tweak** — the existing `QRadioButton` + `QLineEdit`, behavior unchanged
  (`dispatch(tweak_prompt=…)` → `/smalltweak <text>`).
- **Admin** — the existing `QRadioButton`, behavior unchanged (`dispatch(admin=True)`
  → blank `claude`).
- A `Dispatch`/`Cancel` `QDialogButtonBox` governing ONLY the tweak/admin radios
  (the form buttons dispatch through their own dialog).

Additionally, **on open the launcher calls `agent_forms.prune_done(repo)`** (plan
§5 + D2: the launcher prunes stale handoffs on every open). Call it defensively
(`try/except` → ignore) — a failure to prune must never stop a designer from
dispatching.

`detach` stays **injectable end to end**: `SpawnClaudeDialog(detach=…)` →
`AgentFormDialog(detach=…)` → `spawnclaude.dispatch(detach=…)` →
`run_controls.start_detached`. Tests capture argv; no real terminal ever opens
(plan §5: *"`detach` stays injectable end to end (tests capture argv, no real
terminal)"*).

### 1.7 Explicitly unchanged in AD-3

- `spawn_command`'s argv contract (`["wt", "-d", <repo>, "cmd", "/k", "claude",
  <prompt>]`, prompt as ONE argv element — a repo path with spaces stays safe
  because argv is a list, plan §7).
- Admin and small-tweak semantics (plan D5: *"Admin and small-tweak bypass
  dispatch entirely"* — no handoff written).
- The toolbar button label **"Summon a Drunken Robot"** (plan §1, §5).
- Precedence **admin > handoff > tweak** in `dispatch()` (AD-2 settled it).

---

## 2. Architecture plan

### 2.1 `editor/agent_form_dialog.py` layout

```
"""module docstring: what this renders, and the two rules that shaped it —
   the free-text box is built in (plan §3), and spinbox ranges come from the
   spec so invalid input is unrepresentable (ED-30)."""

from pathlib import Path
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QRadioButton, QVBoxLayout)

from editor import agent_forms, spawnclaude
from editor.panels.balancing import (_NoWheelComboBox, _NoWheelDoubleSpinBox,
                                     _NoWheelSpinBox)

REPO = Path(__file__).resolve().parents[1]

def _make_widget(field):     # -> (widget, getter, change_signal_or_None)
    ...

class AgentFormDialog(QDialog):
    def __init__(self, spec, data_dir=None, repo=None, parent=None, detach=None): ...
    def values(self): ...
    def free_text(self): ...
    def git_mode(self): ...
    def branch_name(self): ...
    def _refresh_branch_name(self): ...
    def _refresh_dispatch_enabled(self): ...
    def _on_dispatch(self): ...
```

### 2.2 The widget factory — one place, table-driven

A single module-level `_make_widget(field)` returns a `(widget, getter,
change_signal)` triple:

- `widget` — configured with range/options/default/tooltip/placeholder.
- `getter` — a zero-arg callable closing over the widget, returning the JSON-safe
  value (the table in §1.1).
- `change_signal` — the bound signal to connect to `_refresh_dispatch_enabled`
  (`textChanged` for line/plain-text; `None` for the types that can't be empty).

`__init__` loops `spec["fields"]` once, calls `_make_widget`, stores
`self._widgets[key] = widget` and `self._getters[key] = getter`, adds the row.
There is exactly ONE `type` → widget switch in the codebase-for-forms; nothing
else may branch on `field["type"]`. An unknown type raises `ValueError` naming the
field key (mirrors `balancing.py::_make_widget`'s final `else: raise` — L406-407).

### 2.3 Required-field gating wiring

`self._required = [f["key"] for f in spec["fields"] if f.get("required")]`.
In the field loop, if a field is required and its `change_signal` is not `None`,
`change_signal.connect(self._refresh_dispatch_enabled)`.
`_refresh_dispatch_enabled()` reads `self._getters[k]()` for each required key and
does `self._dispatch_button.setEnabled(all(non_empty))`. Called once at the end of
`__init__` (after defaults are seeded and the button box exists). Same shape as
`_SaveMetaDialog` in `editor/panels/balancing.py` L121-148.

### 2.4 Branch-name live refresh

The slug field key = `spec.get("slug_field", "name")`. If a widget with that key
exists and is a `QLineEdit`, connect its `textChanged` → `_refresh_branch_name`;
also connect the free-text `QPlainTextEdit`'s `textChanged` (the fallback source
inside `default_branch_name`). `_refresh_branch_name` returns immediately if
`self._branch_user_edited`; otherwise it `setText(agent_forms.default_branch_name(
spec, self.values(), self.free_text()))`. The user-edit flag comes from
`self._branch_edit.textEdited` (user-only signal — `setText()` does not emit it).
The git radios' `toggled` drives `self._branch_edit.setEnabled(branch_mode)`.

### 2.5 Launcher structure + the AD-7 seam

**Build `SpawnClaudeDialog` from small `_build_*_group()` helpers**, each returning
a `QWidget`/`QGroupBox` that `__init__` appends to one main `QVBoxLayout` in
order:

```
layout = QVBoxLayout(self)
layout.addWidget(self._build_forms_group(data_dir))
layout.addWidget(self._build_modes_group())      # small tweak + admin
# <-- AD-7 appends: layout.addWidget(self._build_plans_group())
layout.addWidget(self._build_button_box())
```

**This is a deliberate seam for AD-7** (plan §6/AD-7: *"`SpawnClaudeDialog`
launcher gains a Plans group — this lands with the AD-3 launcher rewrite, or as an
increment on it"*). AD-7's coder should be able to add `editor/plans.py`, write one
new `_build_plans_group()` returning a widget (active-plan `QLabel`, plan-picker
`QComboBox`, "Set as current" + "Open planning folder" buttons, "Create a new plan"
radio) and insert exactly ONE `layout.addWidget(...)` line, touching nothing else
in the dialog. Keep the button-box construction last and separate so a group can
be inserted before it. **Say nothing else about plans in AD-3** — no placeholder
group, no stub `plans` import.

The forms group holds `self._form_buttons = {spec["id"]: button}` so tests can
address a form entry by id without depending on layout order.

### 2.6 `detach` threading

`SpawnClaudeDialog.__init__(…, detach=None)` stores `self._detach = detach` (None
means "let `dispatch()` default to `run_controls.start_detached`" — the existing
convention, `spawnclaude.py` L115). It passes `detach=self._detach` into every
`AgentFormDialog` it opens, and into each `dispatch(...)` call for tweak/admin.
`AgentFormDialog` does the same into its one `dispatch(...)` call. No module-level
state, no singletons: the fake launcher a test injects at the launcher reaches the
`wt` argv through the form dialog untouched.

### 2.7 Layering

`editor/` must **never** import `game/` (root `CLAUDE.md` design pillar 2;
`test_editor_viewport.TestPurity` enforces it in a subprocess). `agent_form_dialog`
imports only `PySide6`, `editor.agent_forms`, `editor.spawnclaude`, and
`editor.panels.balancing`. Note the import direction: a top-level editor module
importing from `editor/panels/` is new but harmless (no cycle —
`panels/balancing.py` imports `editor.locks` / `editor.balancing_history` /
`engine.data_io`, never `agent_form_dialog` or `spawnclaude`). Keep it that way;
do not have `balancing.py` import anything from the new module.

`spawnclaude.py` importing `agent_form_dialog` (for the launcher) and
`agent_form_dialog` importing `spawnclaude` (for `dispatch`) **is a cycle** —
avoid it. Two clean options, pick one and note it in the module docstring:
(a) `agent_form_dialog` imports `spawnclaude` at module top; `spawnclaude` imports
`AgentFormDialog` **lazily inside the launcher method** (`from
editor.agent_form_dialog import AgentFormDialog` inside `_open_form`); or
(b) `agent_form_dialog` imports `spawnclaude` lazily instead. Option (a) is
preferred — it keeps `agent_form_dialog`'s imports static/greppable and puts the
one deferred import in the launcher, where it also keeps `spawnclaude`'s pure
builders importable without pulling the whole form dialog in.

---

## 3. File scope + shared-file contract

**New**
- `editor/agent_form_dialog.py` — the whole of §2.1.

**Modified**
- `editor/spawnclaude.py` — **`SpawnClaudeDialog` only**. Rewrite it into the
  launcher per §1.6/§2.5, and update the module docstring's "three modes" prose to
  describe forms/tweak/admin. **Do NOT re-touch the pure builders AD-2 settled**
  (`spawn_command`, `dispatch_prompt`, `small_tweak_prompt`, `dispatch()`): no
  signature changes, no precedence changes, no argv changes. If you believe a
  builder needs to change, stop and say so rather than changing it.
- `editor/main.py` — **comment/docstring only.** Refresh the `_on_spawnclaude`
  docstring (L530-536) and the toolbar comment (L173-175) so they describe the
  launcher instead of the removed domain/lock flow. The `QAction` label **stays
  "Summon a Drunken Robot"** (plan §1, §5), the wiring stays as-is, and the
  `SpawnClaudeDialog(data_dir=…, repo=REPO, parent=self)` call stays. **AD-6 owns
  the real `main.py` edits** (the selector context-menu hookup) — do not
  pre-empt it.
- `tools/tests/test_editor_viewport.py` — **ONE line**: add
  `editor.agent_form_dialog` to the `TestPurity` import string (L194-206). AD-1
  already added `editor.agent_forms`; AD-7 will add `editor.plans`. Touch nothing
  else in that file (this is the file three phases all poke — keep your diff to a
  single line inside the string literal so the merge is trivial).
- `tools/tests/test_spawnclaude.py` — add the dialog tests of §4. Keep the
  argv-shape tests and `TestNoLockWriteAPI` (L125-134) intact; AD-2 already
  rewrote the domain tests away.
- `editor/CLAUDE.md` — **rewrite the "Spawnclaude / locks" invariants section**
  (currently L92-118). This is AD-3's architectural doc update (root `CLAUDE.md`
  exit gate step 3: architectural change → update the package CLAUDE.md). It must
  now state: the launcher/form-dialog split; that form specs are data
  (`data/agent_forms/*.json`, schema-validated, loaded fresh per open); the
  handoff flow (`build_payload` → `write_handoff` → `/dispatch <relpath>`, handoffs
  in gitignored `.claude/dispatch/`); the surviving admin/tweak modes and the
  precedence admin > handoff > tweak; that the `wt` argv contract and the
  `run_controls.start_detached` SDL-strip reuse are unchanged; that the
  branch+lock/`start-domain` path is GONE from spawnclaude (the lock protocol is
  suspended — `editor/locks.py` stays and stays read-only, and the "no
  set/clear/force-unlock anywhere in the editor" invariant + its test still hold);
  and that `editor/agent_forms.py` + `editor/agent_form_dialog.py` are both in
  `TestPurity`. Keep it in the file's existing voice (invariants, not narrative).
  **AD-7 will later append one line about the Plans group** — leave the section
  structured so that is a one-line append.

**HARD BOUNDARY — do not touch:**
`editor/agent_forms.py` (AD-1's, and it is pure — the dialog consumes it, never
extends it), `tools/smoke.py`, `data/**` (including `data/agent_forms/*` and the
schemas — AD-4 adds specs, not you), `editor/locks.py`, `editor/panels/selector.py`
(AD-6), `editor/panels/balancing.py` (import from it; never edit it),
`.claude/commands/**` (AD-2 wrote `dispatch.md`).

If a required behavior seems to demand touching one of those, that is a signal the
plan is wrong — report it, don't route around it.

---

## 4. Exit gate + Quick Test

### 4.1 Exit gate

```
py tools/smoke.py
py -m unittest discover -s tools/tests -t .
```

Both green, **zero NEW failures**. The `Development` baseline has 17 pre-existing
failures — diff against that set; do not "fix" unrelated reds and do not count them
as yours. Report exactly what you ran and what you observed (suite + smoke +
whatever you drove live).

### 4.2 Headless Qt mechanism (cite it, follow it exactly)

Every editor test module does this **before any PySide6/pygame import**, at module
top:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
```

— see `tools/tests/test_spawnclaude.py` L15-17, `tools/tests/test_editor_panels.py`
L20-22, `tools/tests/test_editor_viewport.py` L14-16. Then exactly one
`QApplication` per process: `_APP = QApplication.instance() or QApplication(sys.argv)`
(`test_spawnclaude.py` L26 — Qt allows only one per process). `test_spawnclaude.py`
already has both; your new tests go in that module and inherit them. Temp data
comes from `tools/tests/test_editor_panels.TempDataCase` (L65+), which copies
`data/` into a `tempfile.TemporaryDirectory()` and exposes `self.data_dir` — AD-1
confirmed/extended it to carry `data/agent_forms/`. Use a second
`tempfile.TemporaryDirectory()` as the **temp repo** for handoff writes so nothing
lands in the real `.claude/dispatch/`.

### 4.3 Tests to write (plan §6/AD-3)

In `tools/tests/test_spawnclaude.py`, against `TempDataCase` + a temp repo dir:

1. **Launcher roster** — `SpawnClaudeDialog(data_dir=self.data_dir)` exposes one
   form entry per spec returned by `agent_forms.load_form_specs(self.data_dir)`
   (compare ids, not layout order, via `_form_buttons`), **plus** the small-tweak
   radio + line edit **plus** the admin radio. Assert the "Add New Enemy" title is
   among the button labels.
2. **Fresh-load semantics** — drop a second valid spec JSON into the temp
   `data/agent_forms/`, open a NEW `SpawnClaudeDialog` on the same `data_dir`, and
   assert the new form appears (no editor restart / no module reload).
3. **Widget per field type** — build an `AgentFormDialog` from a synthetic spec
   covering all six types, and assert the concrete classes: `QLineEdit`,
   `QPlainTextEdit`, `QCheckBox`, `_NoWheelSpinBox`, `_NoWheelDoubleSpinBox`,
   `_NoWheelComboBox`. Assert the spinbox's `minimum()`/`maximum()` equal the
   spec's `minimum`/`maximum` (ED-30 — spec-driven range), that every widget's
   `toolTip()` equals the field's `description`, that the enum combo lists exactly
   `options`, and that `default`s are seeded.
4. **Free-text box is built in** — assert the dialog has a free-text
   `QPlainTextEdit` even for a spec whose `fields` list contains no `text` field
   (plan §3).
5. **Dispatch gating** — with a required `string` field empty, the Dispatch button
   is disabled; typing into it enables the button; clearing it disables it again.
6. **Git radio default** — a spec with `git_default: "branch"` opens with the
   branch radio checked and the branch edit ENABLED; a spec with
   `git_default: "current"` opens with the current radio checked and the branch
   edit DISABLED.
7. **Branch name live-slugs and stays editable** — set the slug field to
   "Siege Cannon" and assert the branch edit reads
   `agent/add-enemy-siege-cannon` (delegate the expected value to
   `agent_forms.default_branch_name` rather than hardcoding, so AD-1 stays the
   single source of slug truth); then `setText`-by-user (simulate `textEdited`, or
   call the dialog's edit path) and assert a further slug-field change does NOT
   clobber the user's branch name.
8. **End-to-end accept, no terminal** — with an **injected fake detach**
   (`def fake_detach(program, arguments, working_dir): captured[...] = ...; return True`,
   the shape already used at `test_spawnclaude.py` L90-99), fill a form, call the
   dialog's dispatch handler, then assert:
   - a handoff JSON now exists under the **temp repo**'s `.claude/dispatch/`;
   - it **re-validates** against `data/schemas/dispatch_handoff.schema.json` via
     `engine.data_io.load_validated` (not merely "the file exists");
   - its `values`/`free_text`/`git` match what was entered (branch mode carries
     `git.branch`; current mode does not);
   - the captured argv is `["-d", <repo>, "cmd", "/k", "claude", "/dispatch <relpath>"]`
     shaped — i.e. `program == "wt"` and `arguments[-1] == f"/dispatch {relpath}"`
     with `relpath` a **relative POSIX** path (assert `not Path(relpath).is_absolute()`
     and `"\\" not in relpath`);
   - **no real terminal ever opens** (the fake is the only launcher; never call
     `dispatch()` without `detach=` in a test).
9. **Admin / tweak unchanged** — the existing `TestDispatch` + admin-dialog tests
   still pass through the new launcher: admin dispatches a blank `claude` (last arg
   `"claude"`, no slash command), tweak dispatches `/smalltweak <text>`, and
   **neither writes a handoff** (assert the temp repo's `.claude/dispatch/` is
   still empty afterwards — plan D5).
10. **Purity** — `TestPurity` (in `test_editor_viewport.py`) now imports
    `editor.agent_form_dialog` and still proves no `game.*` module is loaded.

### 4.4 Quick Test for the user (goes in the PR body)

The live half of AD-3's exit gate — plan §6/AD-3: *"live: `py editor/main.py`,
dispatch a real Add New Enemy in branch mode, confirm worktree branch
`agent/add-enemy-…`, green exit gate, PR into Development, handoff archived"* —
**is not doable headlessly by the coding agent.** It opens a real Windows Terminal,
runs a real nested `claude` session, creates a real git worktree and opens a real
PR. The agent must NOT attempt it, must NOT fake it, and must NOT claim it as
verified. Write it into the PR body as an explicit **Quick Test for the user**, and
say plainly in the PR that everything below the line was verified only headlessly
(offscreen Qt + injected fake detach):

> **Quick Test (please run):**
> 1. `py editor/main.py` → click **Summon a Drunken Robot**.
> 2. The launcher lists **Add New Enemy** (one entry per form spec), plus Small
>    tweak and Admin. Click **Add New Enemy**.
> 3. The form shows the description, a free-text box, and one row per field —
>    *Enemy name* (text), *Registry group* (dropdown), *Targets buildings*
>    (checkbox), *Era variants* (spinner clamped 1–8; the mouse wheel over it must
>    do nothing). Hover a field: the tooltip is its description.
> 4. **Dispatch is greyed** until *Enemy name* is filled. Type "Siege Cannon" —
>    the branch box live-fills to `agent/add-enemy-siege-cannon` and stays editable;
>    switching to "Work on current branch" greys the branch box.
> 5. Leave it on **New branch off Development**, add a sentence of free text, press
>    **Dispatch**. A Windows Terminal opens at the repo running
>    `claude "/dispatch .claude/dispatch/<timestamp>-add-enemy.json"`.
> 6. Let it run: it should validate the handoff, create the worktree branch
>    `agent/add-enemy-siege-cannon` off `Development`, drive `/add-enemy`, pass the
>    exit gate, open a PR into `Development`, and archive the handoff to
>    `.claude/dispatch/done/`.
> 7. Re-open the launcher — the pruner has run; the old handoff is gone from the
>    live folder.

Report the headless verification and this Quick Test separately. "Tests pass" is
not "the designer path works"; only step 5-6 above proves the latter, and only the
user can run it.
