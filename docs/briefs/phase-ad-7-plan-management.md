# Phase AD-7 — Plan management: active-plan mirror + planning-agent spawn

Brief for the AD-7 coder. Source of truth: `planning/AgentDispatchPLAN.md` §6
(phase AD-7, lines 463–531) and §7's last bullet (line 559+). Base branch:
`phase-AD-1-7-umbrella` (off `Development`). AD-1/AD-2/AD-3/AD-4 are merged
before you run.

**Do not re-invent the skills.** `.claude/commands/setcurrentplan.md` and
`.claude/commands/createplan.md` ALREADY EXIST and are **not modified** in this
phase. AD-7 adds only the *editor surface* (`editor/plans.py` + a **Plans
group** in the launcher) and the *form-spec* wiring
(`data/agent_forms/create-plan.json`).

---

## 1. Behavioral spec

### 1.1 Background facts (verified in-repo, do not re-derive)

- `planning/` holds the plan sources of truth. Current contents:
  `AgentDispatchPLAN.md`, `EnemyReworkPLAN.md`, `EngineBuildPLAN.md`,
  `MIGRATION_AGENT_READ_FIRST.md`, `MIGRATION_PLAN.md`, `UI_EDITOR_PLAN.md`,
  plus one non-md file (`DrunkenDonuts_HowToBeHuman_Plan.pdf`).
- Root `PLAN.md` is a **generated mirror**. Its line 1 today is exactly:
  `<!-- active-plan: MIGRATION_PLAN.md | set: 2026-07-13 -->`
  (verified). Root `CLAUDE.md`: "never hand-edit it — edit the source in
  `planning/` and re-run `/setcurrentplan <name>`."
  → **Editor invariant: the editor NEVER writes `PLAN.md` or anything under
  `planning/`.** It reads the marker, and it *spawns the skill* that rewrites
  the mirror. This is exactly the ED-60/62 delegation model already used for
  locks (`editor/locks.py` reads, `/start-domain` writes) — keep it.

### 1.2 `editor/plans.py` — PURE (no Qt, no pygame, no `editor.run_controls`)

Plan §6/AD-7 lines 485–496 specify five helpers. Exact intended behavior:

| Function | Behavior |
|---|---|
| `planning_dir(repo=None)` | `Path(repo or REPO) / "planning"`. `REPO = Path(__file__).resolve().parents[1]` (same idiom as `spawnclaude.REPO` / `run_controls.REPO`). |
| `list_plans(repo=None)` | Sorted list of **file names** of `planning/*.md` — e.g. `["AgentDispatchPLAN.md", "EnemyReworkPLAN.md", …]`. Missing `planning/` → `[]` (never crash). Non-`.md` files (the PDF) are excluded by the glob. |
| `active_plan(repo=None)` | Read root `PLAN.md`, parse **line 1 only** for `<!-- active-plan: <name> …-->`; return `<name>` (e.g. `"MIGRATION_PLAN.md"`) or `None`. **Missing `PLAN.md`, empty file, no marker, unreadable → `None`, NEVER an exception** (plan §7: "if a hand-edit strips the marker, `active_plan` returns `None` and the label shows '— none set' (never crashes)"). Single source of truth — no second pointer file. |
| `reveal_command(path)` | Cross-platform folder-open **argv list**: `sys.platform == "win32"` → `["explorer", str(path)]`; `"darwin"` → `["open", str(path)]`; else → `["xdg-open", str(path)]`. Must read `sys.platform` **at call time** (tests patch it). The repo has **no** existing folder-open helper — this is where it is introduced. |
| `set_current_plan_prompt(name)` | `f"/setcurrentplan {name}"`. |
| `create_plan_prompt(text)` | `"/createplan"` when `text` is blank/None; `f"/createplan {text.strip()}"` otherwise (mirrors `small_tweak_prompt`'s shape exactly). |

**Names carry the `.md` extension** (`list_plans`, `active_plan`,
`set_current_plan_prompt`). The plan text says "stems/names" (line 487) —
resolved to **names**, because (a) the PLAN.md marker stores
`MIGRATION_PLAN.md` with the extension, so label/picker/marker compare
identically with zero massaging, and (b) `setcurrentplan.md`'s
`argument-hint:` is `<plan filename in planning/, e.g. MIGRATION_PLAN.md>`.
(The skill *also* accepts a bare stem — step 1 — so a stem would work, but
names keep one representation end-to-end.)

### 1.3 Launcher **Plans group** (plan lines 497–511)

Appended to the AD-3 `SpawnClaudeDialog` launcher (which is the toolbar's
"Summon a Drunken Robot" dialog — label unchanged). Four widgets:

1. **Active-plan `QLabel`** — `"Active plan: MIGRATION_PLAN.md"` from
   `plans.active_plan(repo)`; `"Active plan: — none set"` when it returns
   `None`. Read fresh on every dialog open (same "read fresh, never cache"
   convention as `domain_choices` did for locks).
2. **Plan-picker `QComboBox`** — populated from `plans.list_plans(repo)`.
   Pre-select the active plan if it is in the list. Empty list → combo
   disabled.
3. **"Set as current" `QPushButton`** — spawns a robot running
   `plans.set_current_plan_prompt(<picked name>)` i.e.
   `/setcurrentplan MIGRATION_PLAN.md`, through `spawnclaude.dispatch(...)`
   with the dialog's injectable `detach`. The editor itself does not rewrite
   `PLAN.md`; the spawned skill does. The label refreshes on the **next**
   dialog open (documented, not a bug). Then `self.accept()` — one spawn per
   dialog, same as every other dispatch path. No-op if the combo is empty.
4. **"Open planning folder" `QPushButton`** — launches
   `plans.reveal_command(plans.planning_dir(repo))` through the **same
   injectable `detach`**, so tests capture argv and **no real explorer ever
   opens** under the offscreen harness. This is NOT a claude spawn: it does
   **not** go through `dispatch()`, and it does **not** close the dialog.
5. **"Create a new plan" `QRadioButton`** — a new drunken-robot mode
   *alongside* Small tweak / Admin (registered in the launcher's existing
   `QButtonGroup` so mutual exclusion holds), plus an optional `QLineEdit`
   for the plan brief. On Dispatch it dispatches
   `plans.create_plan_prompt(<line-edit text>)` → `/createplan <brief>`.

**Precedence stays `admin > handoff/plan > tweak`** (plan line 511). AD-2's
`dispatch()` contract (`admin > handoff > tweak`) is preserved verbatim; the
plan route slots in between handoff and tweak (§2.3).

### 1.4 `data/agent_forms/create-plan.json` (plan lines 512–518)

So the planning agent is ALSO a first-class **form** entry in the launcher (and
passes AD-4's all-specs sweep automatically — **do not duplicate that sweep**).
`/setcurrentplan` deliberately stays a **direct, picker-driven spawn**, not a
form (it is parametric on one already-known value).

Complete intended content (validates against AD-1's
`data/schemas/agent_form.schema.json`, whose `required` list is
`schema_version, id, title, description, skill, context, git_default, fields`
— all present below; `id` equals the filename stem; `skill` resolves to the
existing `.claude/commands/createplan.md`; every `context` path exists today;
no `selector_context` because `createplan` maps to no `data/slots.json`
category):

```json
{
  "schema_version": 1,
  "id": "create-plan",
  "title": "Create a New Plan",
  "description": "Spawns the planning agent (/createplan). It scopes a new phased, agent-executable plan doc with you and writes it to planning/ in the plan-doc family shape (build-order table, per-phase Goal/Files/Tests/Exit gate). It does not implement the plan; activate it afterwards with Set as current.",
  "skill": "createplan",
  "context": [
    ".claude/commands/createplan.md",
    "planning/AgentDispatchPLAN.md",
    "CLAUDE.md"
  ],
  "git_default": "current",
  "slug_field": "plan_name",
  "fields": [
    {
      "key": "plan_name",
      "label": "Plan name",
      "type": "string",
      "required": true,
      "placeholder": "AudioPLAN",
      "description": "PascalCase stem ending in PLAN; the doc lands at planning/<name>.md."
    }
  ]
}
```

`git_default: "current"` is deliberate: `/createplan` only writes into
`planning/`, so a worktree branch + PR would be pure ceremony; the
stop-and-confirm current-branch convention fits. The built-in free-text box
(AD-3 renders it for every form — it is not a spec field) carries the plan
brief.

---

## 2. Architecture plan

### 2.1 `editor/plans.py` — module layout

```python
"""Plan management (AD-7): read the active-plan mirror, list the planning/
sources, build the prompts the editor spawns to CHANGE them.

Pure: no Qt, no pygame (TestPurity), and no editor.run_controls import — the
launch primitive stays in spawnclaude/run_controls. The editor NEVER writes
root PLAN.md or anything under planning/: it reads PLAN.md's line-1 marker and
spawns /setcurrentplan or /createplan to do the writing (the ED-60/62
delegation model, same as locks)."""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_MARKER = re.compile(r"<!--\s*active-plan:\s*(?P<name>[^|\s>]+)")

def planning_dir(repo=None) -> Path: ...
def plan_mirror_path(repo=None) -> Path:      # <repo>/PLAN.md  (internal-ish, but public + testable)
def list_plans(repo=None) -> list[str]: ...   # sorted *.md file NAMES; [] if planning/ absent
def active_plan(repo=None) -> str | None: ... # line-1 marker name, else None; never raises
def reveal_command(path) -> list[str]: ...    # argv; branches on sys.platform at call time
def set_current_plan_prompt(name) -> str: ...
def create_plan_prompt(text) -> str: ...
```

`active_plan` implementation notes: open with
`encoding="utf-8", errors="replace"`, read only the first line
(`f.readline()`), wrap the whole read in `except OSError: return None`; a
missing file, an empty file, or a first line without the marker all return
`None`. Do **not** scan later lines — the plan pins the marker to line 1
("Line 1 MUST be the `<!-- active-plan: … -->` marker (the editor and agents
parse it)", `setcurrentplan.md` step 4).

`list_plans`: `sorted(p.name for p in planning_dir(repo).glob("*.md"))`, guarded
by `if not d.is_dir(): return []`.

### 2.2 Hooking the Plans group into AD-3's launcher (no restructuring)

AD-3 builds `SpawnClaudeDialog.__init__` as a series of small
`_build_*_group()` helpers appended to ONE main `QVBoxLayout`, with the
`QDialogButtonBox` built **LAST**. That is your seam:

- Add `self._build_plans_group(layout)` **after the existing group builders and
  before the button box**. Touch nothing else in `__init__`.
- The new **radio** ("Create a new plan") is added to AD-3's existing
  `QButtonGroup` (`self._group`) even though it lives in the Plans group's
  layout — Qt button groups are independent of layout parents, so exclusivity
  with Small tweak / Admin holds with zero restructuring.
- Add exactly ONE branch to `_on_dispatch`, positioned to mirror the
  precedence: `admin` → (AD-3's handoff/form path) → **`create_plan_radio`** →
  `tweak`. Do not reorder AD-3's existing branches.
- **Do not reintroduce a top-level import cycle.** AD-3 imports
  `AgentFormDialog` **lazily inside the launcher method** to break a circular
  import; `editor/plans.py` is a leaf module (imports only stdlib), so
  `from editor import plans` at the top of `spawnclaude.py` is safe — but keep
  the lazy `AgentFormDialog` import exactly as AD-3 left it.

### 2.3 The plan-prompt route through `dispatch()` (AD-2 contract intact)

AD-2 settled: `dispatch(handoff=None, tweak_prompt=None, admin=False,
repo=None, detach=None)`, precedence **admin > handoff > tweak**, and
`dispatch_prompt(handoff_relpath)` takes a **relative POSIX string** (AD-1's
`write_handoff` returns a `Path`; the dialog converts via
`agent_forms.handoff_relpath`). **Do not propose signature changes to
`write_handoff` / `dispatch_prompt` to suit the Plans group.**

Add ONE new keyword:

```python
def dispatch(handoff=None, tweak_prompt=None, plan_prompt=None,
             admin=False, repo=None, detach=None):
    ...
    if admin:
        prompt = None
    elif handoff is not None:
        prompt = dispatch_prompt(handoff)
    elif plan_prompt:
        prompt = plan_prompt          # already a complete slash command
    else:
        prompt = small_tweak_prompt(tweak_prompt)
```

Rationale (decide-and-justify, as required):

- **Why not reuse `tweak_prompt`:** it is a *task description*, not a prompt —
  `dispatch` funnels it through `small_tweak_prompt()`, which would emit
  `/smalltweak /setcurrentplan MIGRATION_PLAN.md`. Wrong by construction.
- **Why not a generic `prompt=` raw escape hatch:** it would let any caller
  bypass the pure builders, which is the one invariant `test_spawnclaude`
  guards (every spawned prompt comes from a named builder). A **plan-scoped**
  keyword keeps the "prompts are built, never hand-assembled at the call site"
  rule: the *only* values ever passed are
  `plans.set_current_plan_prompt(...)` / `plans.create_plan_prompt(...)`.
- **AD-2's contract is untouched:** with `plan_prompt=None` (its default) the
  chain is byte-for-byte `admin > handoff > tweak`. Every existing AD-2 test
  passes unchanged. `handoff` stays above `plan_prompt` (they are mutually
  exclusive in the UI; a deterministic order is still specified).

### 2.4 Folder-open: reconciling `reveal_command`'s argv with `start_detached`

Shape mismatch, stated explicitly:

- `plans.reveal_command(path)` returns **one argv list**:
  `["explorer", "C:\\…\\planning"]`.
- `run_controls.start_detached(program, arguments, working_dir)` takes
  **program and arguments separately** and returns `started_ok: bool`.

Reconcile in `spawnclaude` (Qt side — `plans.py` must not import
`run_controls`, which pulls in PySide6), with a thin sibling of `dispatch()`
that resolves `detach` the same way:

```python
def open_planning_folder(repo=None, detach=None):
    """Reveal planning/ in the OS file manager. NOT a claude spawn — it goes
    through the same injectable `detach` (run_controls.start_detached) purely
    so tests capture argv and no real explorer opens under the offscreen
    harness."""
    repo = Path(repo) if repo is not None else REPO
    detach = detach or run_controls.start_detached
    argv = plans.reveal_command(plans.planning_dir(repo))
    return detach(argv[0], argv[1:], repo)          # split exactly like dispatch()
```

This is the identical `argv[0], argv[1:], repo` split `dispatch()` already
does (`spawnclaude.py` line 101) and that `RunControls.play()` does — so the
argv contract, the space-safe list passing (§7 "Command-line length"), and the
SDL-dummy-var stripping in `_real_window_environment()` all come for free. Note
`explorer.exe` exits non-zero even on success; `startDetached()` reports
*launch* success, not exit code, so this is a non-issue.

### 2.5 VERIFIED skill argument contracts (prompt builders must match)

Both were read in full:

- `.claude/commands/setcurrentplan.md` — `argument-hint: <plan filename in
  planning/, e.g. MIGRATION_PLAN.md>`; step 1 globs `planning/*.md`, matches
  case-insensitively, accepts the bare stem **or** the full name, and aborts on
  ambiguity. It writes root `PLAN.md` with line 1 =
  `<!-- active-plan: <name>.md | set: <date> -->`.
  → `set_current_plan_prompt("MIGRATION_PLAN.md")` → `"/setcurrentplan
  MIGRATION_PLAN.md"`. **Exact match.**
- `.claude/commands/createplan.md` — `argument-hint: <plan name + one-line
  purpose>`; the body reads `$ARGUMENTS` as free text and scopes the plan with
  the user; it explicitly does *not* activate the plan without being asked.
  → `create_plan_prompt("AudioPLAN — port the prototype's audio")` →
  `"/createplan AudioPLAN — port the prototype's audio"`; blank → `"/createplan"`.
  **Exact match.** (Both are single-argv-element prompts, per the existing
  `spawn_command` contract: `["wt","-d",<repo>,"cmd","/k","claude",<prompt>]`.)

Neither command file is modified.

### 2.6 One trap: `TestNoLockWriteAPI`

`tools/tests/test_spawnclaude.py::TestNoLockWriteAPI` iterates `dir(spawnclaude)`
and asserts no symbol name contains `unlock`, `set_lock`, or `release`. Your new
names (`plans`, `open_planning_folder`, `plan_prompt`, `set_current_plan_prompt`
— reached via the `plans` module, not re-exported) are all clean. Keep it that
way; do not name anything `release_plan`, etc.

---

## 3. File scope + shared-file contract

**New**
- `editor/plans.py` — pure helpers (§2.1).
- `data/agent_forms/create-plan.json` — content in §1.4, verbatim.

**Modified (append-only where noted)**
- `editor/spawnclaude.py` — **append the Plans group + the plan-prompt route
  ONLY**: `from editor import plans`; the `plan_prompt=` keyword in
  `dispatch()` (§2.3); `open_planning_folder()` (§2.4); `_build_plans_group()`
  called at AD-3's seam (before the button box); one new branch in
  `_on_dispatch`. **Do NOT restructure AD-3's launcher, do NOT touch AD-2's
  pure builders (`spawn_command`, `small_tweak_prompt`, `dispatch_prompt`), do
  NOT undo AD-3's lazy `AgentFormDialog` import.**
- `tools/tests/test_spawnclaude.py` — **append** Plans-group test classes.
  Leave AD-2/AD-3's classes (and `TestNoLockWriteAPI`) untouched.
- `tools/tests/test_editor_viewport.py` — `TestPurity` holds **ONE import
  string** (not a list). Add `editor.plans` to it — **one line's worth of
  edit**. AD-1 added `editor.agent_forms` and AD-3 added
  `editor.agent_form_dialog` to the same string, so expect it to already read
  `…editor.run_controls, editor.spawnclaude, editor.agent_forms,
  editor.agent_form_dialog, editor.theme, …`; insert `editor.plans` alongside
  them and keep the trailing `; ` + `assert` tail intact.
- `editor/CLAUDE.md` — **append ONE short note** at the END of the spawnclaude
  invariants section (AD-3 rewrites that section; keep your edit strictly
  additive): the launcher now carries a **Plans group** — it *reads* root
  `PLAN.md`'s line-1 active-plan marker and lists `planning/*.md`, but **never
  writes either**; `/setcurrentplan` and `/createplan` are spawned to do the
  writing (same delegation model as locks), and `reveal_command` is the one
  folder-open path, launched through the injectable `detach`.

**HARD BOUNDARY — do not touch:** `editor/agent_forms.py`,
`editor/agent_form_dialog.py`, `editor/locks.py`, `editor/panels/**`,
`editor/main.py`, `tools/smoke.py` (AD-1 already added the
`data/agent_forms/` → `agent_form.schema.json` directory exception; your JSON
is validated for free), `data/schemas/**`, `.claude/commands/**`
(setcurrentplan/createplan already exist and are NOT modified),
`tools/tests/test_agent_forms.py` (AD-4's all-specs sweep already validates
`create-plan.json` — **do not duplicate it**).

**Shared-file contract with sibling phases:** three files in this phase are
also edited by AD-1/AD-3 (`spawnclaude.py`, `test_spawnclaude.py`,
`test_editor_viewport.py`) and one by AD-3 (`editor/CLAUDE.md`). In all four,
AD-7's diff must be **purely additive and at the end of the relevant block** —
new function, new group builder, new test classes, one name in the purity
string, one paragraph at the end of the invariants section. Zero renames, zero
reorderings.

---

## 4. Exit gate + Quick Test

### 4.1 Exit gate (you must run these)

```
py tools/smoke.py                                  # now also validates create-plan.json
py -m unittest discover -s tools/tests -t .        # full suite
```
Zero **NEW** failures (the repo carries 17 pre-existing failures on
`Development` — diff against that baseline, do not "fix" unrelated ones).
Report exactly what you ran and what you observed. If `create-plan.json` fails
smoke, the spec is wrong — fix the JSON, never the schema.

### 4.2 Headless Qt mechanism (use the existing one — do not invent)

`tools/tests/test_spawnclaude.py` already does, at module top **before any
PySide6 import**:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
...
_APP = QApplication.instance() or QApplication(sys.argv)   # one per process
```
and uses `TempDataCase` from `tools/tests/test_editor_panels.py` (copies `data/`
into a temp dir; never mutates the repo). Reuse both. For the plan tests you
also need a **temp REPO** dir (with a `planning/` subdir and a `PLAN.md`) —
build it with `tempfile.TemporaryDirectory()` + `self.addCleanup(...)`, the same
idiom `TempDataCase` uses, and pass it as `repo=`.

### 4.3 Tests to write (plan lines 520–525)

Pure (`editor/plans.py`), against a temp repo dir:
1. `active_plan` parses the line-1 marker → returns `"MIGRATION_PLAN.md"` (test
   the real repo's `PLAN.md` too — it is the live contract).
2. `active_plan` returns `None` on: missing `PLAN.md`, empty `PLAN.md`, and a
   `PLAN.md` whose line 1 is ordinary markdown (markerless) — **and raises
   nothing** in any case.
3. `list_plans` reflects a temp `planning/` (sorted; `.md` only — a `.pdf`
   dropped in is excluded; missing `planning/` → `[]`).
4. `reveal_command` branches per platform — patch
   `editor.plans.sys.platform` to `"win32"` / `"darwin"` / `"linux"` and assert
   `["explorer", p]` / `["open", p]` / `["xdg-open", p]`.
5. `set_current_plan_prompt` / `create_plan_prompt` emit the literal slash
   commands (`"/setcurrentplan X.md"`, `"/createplan brief"`, blank →
   `"/createplan"`).

Dialog (offscreen Qt, injected **fake** `detach` — no real explorer, no real
terminal, ever):
6. The active-plan **label** shows the active plan; shows "— none set" when the
   temp repo has no marker.
7. The **picker** lists exactly `planning/*.md` from the temp repo.
8. **"Set as current"** → the fake detach captures
   `("wt", [..., "/setcurrentplan <picked>.md"], repo)` — one call, prompt as
   the single last argv element.
9. **"Open planning folder"** → the fake detach captures
   `("explorer", [<abs path to temp planning/>], repo)` on win32 (patch
   `sys.platform` for the cross-platform assertion), and the dialog is NOT
   accepted/closed.
10. **"Create a new plan"** radio + brief text → Dispatch captures
    `[..., "/createplan <brief>"]`.
11. **Precedence guard:** `dispatch(admin=True, plan_prompt="/createplan")`
    still yields a blank `claude`; `dispatch(handoff=…, plan_prompt=…)` still
    yields `/dispatch …`; `dispatch(plan_prompt=…, tweak_prompt="x")` yields the
    plan prompt (admin > handoff > plan > tweak).

`create-plan.json` needs **no new test** — AD-4's all-specs sweep in
`tools/tests/test_agent_forms.py` picks it up automatically (skill file exists,
context paths exist, id == stem).

### 4.4 Quick Tests for the USER (put these in the PR body — NOT doable headlessly)

The live checks in plan lines 527–531 require a real desktop session; the coder
must NOT claim them. Write them into the PR verbatim:

1. `py editor/main.py` → click **Summon a Drunken Robot**. The dialog shows
   **"Active plan: MIGRATION_PLAN.md"** and the picker lists the six
   `planning/*.md` files.
2. Click **"Open planning folder"** → Explorer opens on
   `…/HowtobeHumanFullProd/planning`; the dialog stays open.
3. Pick a *different* plan (e.g. `EngineBuildPLAN.md`) → **"Set as current"** →
   a terminal opens running `/setcurrentplan EngineBuildPLAN.md`. Let it finish,
   then confirm root `PLAN.md` line 1 reads
   `<!-- active-plan: EngineBuildPLAN.md | set: <today> -->`. Re-open the dialog
   → the label now shows `EngineBuildPLAN.md`.
   **Then restore:** `/setcurrentplan MIGRATION_PLAN.md` (that is the active
   plan on `Development` — do not leave the mirror switched).
4. Select **"Create a new plan"**, type a brief, Dispatch → a terminal opens on
   `/createplan <brief>` (the planning agent; you may abort it before it writes).
5. Open the **"Create a New Plan"** *form* entry in the launcher → it renders
   the `plan_name` field + the free-text box, defaults to **Work on current
   branch**, and Dispatch is greyed until `plan_name` is filled.

---

### Deviations / flags for review

- **`list_plans` includes `MIGRATION_AGENT_READ_FIRST.md`**, which is a
  companion doc, not a plan. The plan text says "sorted list of `planning/*.md`"
  — followed literally; a hidden filename filter would be exactly the
  "convention over schema" the design pillars forbid. If the designer wants it
  hidden, the clean fix is to move that file (e.g. to `docs/`), not to special-
  case it in the editor. Raised in the PR, not silently patched.
- **"stems/names" ambiguity** in plan line 487 resolved to **names with `.md`**
  (§1.2 rationale).
