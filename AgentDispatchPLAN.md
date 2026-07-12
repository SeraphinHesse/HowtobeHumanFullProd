# AgentDispatchPLAN.md — Editor → Claude agent dispatch

Phased, agent-executable plan (same family as `EngineBuildPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases AgentDispatchPLAN.md AD-1-AD-6` or phase-by-phase.

## 1. Vision

Every "thing type" in the game gets an **"Add new X" button** in the editor:
new enemy, new building, new balancing value, new category/subcategory, new
editor feature, new asset importer — and even new *form types* themselves.
Pressing the button opens a form specific to that thing-type: a free-text
description box plus structured fields (booleans, enums, numbers, strings —
the properties common to all things of that type). Submitting the form spawns
a Claude CLI session in a Windows Terminal tab at the repo, pointed at the
correct context docs, which runs the correct skill workflow to build the
thing, verifies it through the exit gate, and lands it.

This generalizes the existing spawnclaude feature (`editor/spawnclaude.py`,
toolbar button **"Summon a Drunken Robot"** — the label stays). The old
`/start-domain` branch+lock path is removed from the spawn dialog (the lock
protocol is SUSPENDED per root `CLAUDE.md`); the **admin** (blank `claude`)
and **small tweak** (`/smalltweak <text>`) modes survive unchanged.

Git behavior is chosen **per run in the form**:
- **New branch** (default for most forms): auto-named `agent/<form-id>-<slug>`
  off `Development`, isolated in a git worktree, ends with a PR.
- **Current branch**: work in place on whatever is checked out; the agent
  stops after the exit gate and summarizes the diff, committing only on the
  user's explicit confirmation (same convention as `/smalltweak`).

## 2. Architecture

```
editor (PySide6)                            .claude/ (agent side)
─────────────────                           ─────────────────────
SpawnClaudeDialog (launcher)                commands/dispatch.md        (new)
  ├─ one entry per form spec ──►            commands/add-form-spec.md   (new, AD-5)
  │    AgentFormDialog                      commands/add-category.md    (new, AD-6)
  ├─ Small tweak ──► /smalltweak <text>     commands/add-*.md           (unchanged)
  └─ Admin       ──► blank claude           dispatch/<ts>-<form>.json   (handoff, gitignored)
AgentFormDialog                             dispatch/done/              (archive)
  └─ submit ──► editor/agent_forms.py       worktrees/<branch>/         (branch-mode isolation)
       build_payload → write_handoff
       → spawnclaude.dispatch(handoff=…)
       → wt -d <repo> cmd /k claude "/dispatch .claude/dispatch/<file>.json"

data/agent_forms/*.json                     ◄── form specs, one per thing-type
data/schemas/agent_form.schema.json         ◄── validates every form spec (smoke-gated)
data/schemas/dispatch_handoff.schema.json   ◄── validates every handoff (write_validated)
```

**Flow**: designer clicks "Add new X" → the generic renderer builds the form
from the JSON spec → submit writes a schema-validated **handoff file** →
a terminal opens running `claude` with the one-token prompt
`/dispatch <relative-handoff-path>` → the `/dispatch` skill reads and
validates the handoff, sets up git per the payload (worktree branch off
`Development`, or in-place on the current branch), then drives the existing
`add-*` skill named in the payload → exit gate → land (PR in branch mode;
stop-and-confirm in current mode) → handoff archived to
`.claude/dispatch/done/`.

### Decisions (with rationale)

- **D1 — Form specs live in `data/agent_forms/*.json`**, all validating
  against one `data/schemas/agent_form.schema.json`.
  `tools/smoke.py::validate_data` gets a **third directory exception**
  (exact precedent: `data/maps/` → `map_file.schema.json`,
  `data/balancing_history/` → `balancing_history.schema.json`): every
  `data/agent_forms/*.json` validates against `agent_form.schema.json`
  regardless of stem. Why not `.claude/forms/`: that would forfeit free
  exit-gate validation, break the editor's `data_dir` injection pattern
  (editor tests run against a temp copy of `data/`), and bypass
  `write_validated` as the one sanctioned write path. `data/` already holds
  editor-tooling data (`balancing_history/`); "schemas over convention" is a
  design pillar.
- **D2 — Handoff files live in `.claude/dispatch/`** (gitignored — transient
  agent I/O, never committed), still written through
  `engine.data_io.write_validated` against
  `data/schemas/dispatch_handoff.schema.json` (`write_validated` takes
  arbitrary paths, so the single-write-path invariant holds; a schema with no
  `data/` content file is legal — `validate_data` skips `data/schemas/`).
  Lifecycle: `/dispatch` archives the file to `.claude/dispatch/done/` on
  completion; the launcher dialog prunes `done/` files older than 30 days and
  unconsumed live handoffs older than 1 day on every open.
- **D3 — Branch mode uses a git worktree**, never an in-place checkout. A
  spawned session doing `git switch -c` in the main tree would yank files
  under the running editor (which has `data/` loaded and could save balancing
  into the wrong branch), and two concurrent spawns would fight over HEAD.
  The repo already runs this exact pattern (`processtodo`,
  `execute-plan-phases`, `.claude/worktrees/`). `/dispatch` runs
  `git worktree add .claude/worktrees/<branch> -b <branch> origin/Development`,
  works there via absolute paths, runs the exit gate there, pushes, opens the
  PR, then `git worktree remove`. The editor's tree is never touched.
  Current-branch mode works in place, with a dirty-tree warning.
- **D4 — Zero skill duplication**: `/dispatch` does git setup + payload
  translation only, then invokes the target skill as a real slash command
  with a composed argument line ending in the handoff path. Existing `add-*`
  skills already take free-text `$ARGUMENTS`, so they need **no changes**;
  they may optionally read the handoff for structured values. Fallback
  (written into `dispatch.md`): if the SlashCommand tool is unavailable, Read
  `.claude/commands/<skill>.md` and follow it with the composed arguments.
  Every skill stays fully usable standalone.
- **D5 — Admin and small-tweak bypass dispatch entirely.** They keep their
  current prompt builders (`None` → blank `claude`; `/smalltweak <text>`),
  write no handoff, and preserve current behavior and tests.
- **D6 — The `/start-domain` path is removed from spawnclaude** (dialog +
  builders). The domain-flow skills (`start-domain`, `resume-domain`,
  `finish-domain`, `merge-domain`) stay on disk with a `SUSPENDED —`
  description prefix. `editor/locks.py` stays (the balancing panel still
  reads `_lock`, which remains in the schemas); `.claude/hooks/scope_guard.py`
  stays fail-open and untouched — `/dispatch` never writes
  `.claude/active_domain` and never touches any `_lock`.

## 3. Form-spec system

### `data/schemas/agent_form.schema.json` (sketch)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schema_version", "id", "title", "description", "skill",
               "context", "git_default", "fields"],
  "properties": {
    "schema_version": { "const": 1, "description": "Spec format version." },
    "id":     { "type": "string", "pattern": "^[a-z][a-z0-9-]*$",
                "description": "Must equal the filename stem; also the branch-name prefix (agent/<id>-...)." },
    "title":  { "type": "string", "minLength": 1, "description": "Dialog window title, e.g. 'Add New Enemy'." },
    "description": { "type": "string", "minLength": 1, "description": "One paragraph shown under the title." },
    "skill":  { "type": "string", "pattern": "^[a-z][a-z0-9-]*$",
                "description": "Target slash command; .claude/commands/<skill>.md must exist (test-enforced)." },
    "context": { "type": "array", "items": { "type": "string", "minLength": 1 },
                 "description": "Repo-relative docs the agent reads first; copied into the handoff." },
    "git_default": { "enum": ["branch", "current"], "description": "Pre-selected git mode in the dialog." },
    "slug_field":  { "type": "string", "description": "Field key that names the auto branch (default 'name'; falls back to free text)." },
    "selector_context": { "type": "string",
                 "description": "Optional slots.json category key whose tree node offers this form via right-click (AD-6)." },
    "fields": { "type": "array", "items": { "$ref": "#/$defs/field" } }
  },
  "$defs": {
    "field": {
      "type": "object", "additionalProperties": false,
      "required": ["key", "label", "type", "description"],
      "properties": {
        "key":   { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        "label": { "type": "string", "minLength": 1 },
        "type":  { "enum": ["string", "text", "boolean", "integer", "number", "enum"] },
        "description": { "type": "string", "minLength": 1, "description": "Widget tooltip." },
        "required":    { "type": "boolean", "description": "Gates the Dispatch button. Default false." },
        "default":     { "type": ["string", "number", "boolean"] },
        "placeholder": { "type": "string" },
        "options":     { "type": "array", "items": { "type": "string" }, "minItems": 1 },
        "minimum":     { "type": "number" }, "maximum": { "type": "number" }
      },
      "allOf": [
        { "if": { "properties": { "type": { "const": "enum" } } },   "then": { "required": ["options"] } },
        { "if": { "properties": { "type": { "enum": ["integer", "number"] } } },
          "then": { "required": ["minimum", "maximum"] } }
      ]
    }
  }
}
```

The **free-text description box is built into the dialog**, not a spec field —
every form gets it for free.

### Example form spec — `data/agent_forms/add-enemy.json`

```json
{
  "schema_version": 1,
  "id": "add-enemy",
  "title": "Add New Enemy",
  "description": "Spawns an agent that adds a new enemy type: thin Enemy subclass, spawner branch, scale-tier stats, registry slots (10F/10G pattern).",
  "skill": "add-enemy",
  "context": ["game/enemies/CLAUDE.md", ".claude/commands/add-enemy.md"],
  "git_default": "branch",
  "slug_field": "name",
  "selector_context": "enemies",
  "fields": [
    { "key": "name", "label": "Enemy name", "type": "string", "required": true,
      "placeholder": "Siege Cannon", "description": "Display name; drives class name, ETYPE, branch slug." },
    { "key": "registry_group", "label": "Registry group", "type": "enum",
      "options": ["Walker", "Raider", "Siege Cannon", "Boss", "New group"],
      "default": "Walker", "description": "REGISTRY_GROUP the variants roll from." },
    { "key": "targets_buildings", "label": "Targets buildings", "type": "boolean",
      "default": false, "description": "Siege-style targeting instead of base pathing." },
    { "key": "era_count", "label": "Era variants", "type": "integer",
      "minimum": 1, "maximum": 8, "default": 4, "description": "How many era slots to add in slots.json." }
  ]
}
```

### Handoff payload — `data/schemas/dispatch_handoff.schema.json`

Written by the editor to `.claude/dispatch/<YYYYMMDD-HHMMSS>-<form-id>.json`
via `write_validated`. Schema: `additionalProperties:false`; `values` is a
permissive object (the form spec already constrained the types at render
time); `git.mode` enum `["branch","current"]`; `git.branch` required only
when mode is `branch` (if/then). Example:

```json
{
  "schema_version": 1,
  "form_id": "add-enemy",
  "skill": "add-enemy",
  "created_at": "2026-07-12T14:03:22Z",
  "free_text": "A slow armored cannon that shells buildings from range; appears era 3.",
  "values": { "name": "Siege Cannon", "registry_group": "Siege Cannon",
              "targets_buildings": true, "era_count": 2 },
  "git": { "mode": "branch", "branch": "agent/add-enemy-siege-cannon", "base": "Development" },
  "context": ["game/enemies/CLAUDE.md", ".claude/commands/add-enemy.md"],
  "spawned_from": { "branch": "phase-start-area-unlock" }
}
```

## 4. The `/dispatch` skill (`.claude/commands/dispatch.md`)

House format (Read-first / Steps / Avoid / Verify / Final report, ≤~60 lines).
Frontmatter: `description:` "Execute a structured agent-dispatch handoff from
the editor — git setup (worktree branch off Development, or current branch),
then drive the target add-* skill."; `argument-hint: <handoff-file path>`;
`allowed-tools:` `Read, Edit, Write, Grep, Glob, SlashCommand, Bash(git *),
Bash(gh pr create*), Bash(py tools/smoke.py*), Bash(py -m unittest*),
Bash(py -c *)`.

Steps:
1. **Read + validate** the handoff at `$ARGUMENTS`:
   `py -c "from engine import data_io; data_io.load_validated(r'<path>', r'data/schemas/dispatch_handoff.schema.json')"`.
   Echo a one-paragraph summary (form, skill, values, git mode). Abort loud on
   any failure.
2. **Read the context files** listed in the payload (token-light routing — do
   not paste whole architecture docs).
3. **Git setup**:
   - `mode: "current"` → `git status --porcelain`; if dirty, list the dirt and
     continue only if it is unrelated to the task. Work in place. Never switch
     branches.
   - `mode: "branch"` → `git fetch origin Development`; if `git.branch`
     already exists, suffix `-2`, `-3`, …;
     `git worktree add .claude/worktrees/<branch> -b <branch> origin/Development`;
     all subsequent work uses **absolute paths inside that worktree**.
   - NEVER write `.claude/active_domain`; NEVER touch any `_lock` (protocol
     suspended).
4. **Invoke the target skill**:
   `/<skill> <values as one readable line> — free text: <free_text> — structured payload: <handoff path>`.
   (Fallback if SlashCommand is unavailable: Read
   `.claude/commands/<skill>.md` and follow it with that composed
   `$ARGUMENTS`.) The target skill runs unmodified.
5. **Exit gate** in the working root: `py tools/smoke.py` +
   `py -m unittest discover -s tools/tests -t .`.
6. **Land**: branch mode → commit, push,
   `gh pr create --base Development` (body includes the payload summary +
   verification + a concrete in-game Quick Test), then `git worktree remove`
   and report the PR URL. Current mode → summarize the diff and **wait for
   explicit user confirmation** before committing (smalltweak convention); no
   PR.
7. **Archive** the handoff to `.claude/dispatch/done/`.

Avoid: force-push / `reset --hard`; committing `build/` / `dist/` / `*.exe`;
edits outside what the target skill's own scope needs; `_lock` writes.

## 5. Editor-side components

- **`editor/agent_forms.py`** (pure — no Qt/pygame, registered in
  `test_editor_viewport.TestPurity`): `forms_dir(data_dir)`,
  `load_form_specs(data_dir)` (each spec via `data_io.load_validated`, sorted
  by id, loud on invalid), `slugify(text, max_len=32)`,
  `default_branch_name(spec, values, free_text)` → `agent/<id>-<slug>`,
  `build_payload(spec, values, free_text, git_mode, branch, repo)`,
  `write_handoff(payload, repo)` → Path (timestamp-named, via
  `write_validated`), `handoff_relpath(path, repo)` → POSIX repo-relative
  string, `prune_done(repo, days=30)`.
- **`editor/agent_form_dialog.py`** (Qt, in TestPurity):
  `AgentFormDialog(spec, data_dir=None, repo=None, parent=None, detach=None)`.
  Renders: title/description labels → built-in free-text `QPlainTextEdit` →
  one row per spec field reusing the balancing idioms (`_NoWheelSpinBox` /
  `_NoWheelDoubleSpinBox` / `_NoWheelComboBox` imported from
  `editor.panels.balancing`, plus `QCheckBox` / `QLineEdit`; spinbox ranges
  from the spec's minimum/maximum so invalid input is unrepresentable, ED-30;
  tooltips from `description`) → git group (`QRadioButton` "New branch off
  Development (ends with a PR)" / "Work on current branch", pre-selected from
  `git_default`; a branch-name `QLineEdit` live-refreshed from the slug field,
  editable, enabled only in branch mode) → Dispatch/Cancel. Dispatch enabled
  only when all `required` fields are non-empty. On accept: `build_payload` →
  `write_handoff` → `spawnclaude.dispatch(handoff=…, repo=…, detach=…)`.
- **`editor/spawnclaude.py`** (modified): remove `domain_choices`,
  `start_domain_prompt`, and the `locks` import; keep `spawn_command`
  (argv contract byte-identical: `["wt", "-d", <repo>, "cmd", "/k", "claude",
  <prompt>]`, prompt as ONE argv element) and `small_tweak_prompt`; add
  `dispatch_prompt(handoff_relpath)` → `f"/dispatch {handoff_relpath}"`;
  re-signature `dispatch(handoff=None, tweak_prompt=None, admin=False,
  repo=None, detach=None)` with precedence **admin > handoff > smalltweak**.
  `SpawnClaudeDialog` becomes the **launcher**: one entry per form spec (from
  `agent_forms.load_form_specs`, fresh per open — no editor restart needed for
  new specs), each opening an `AgentFormDialog`; plus the Small tweak radio +
  line edit; plus the Admin radio. Calls `agent_forms.prune_done` on open.
  `detach` stays injectable end to end (tests capture argv, no real terminal).
- **`editor/main.py`**: wiring unchanged in AD-3 (toolbar button label stays
  "Summon a Drunken Robot"); AD-6 adds the selector context-menu hookup.

## 6. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| AD-1  | Form-spec + handoff data layer (pure) | not started |
| AD-2  | `/dispatch` skill + spawnclaude pure layer | not started |
| AD-3  | Generic form renderer + launcher dialog (end-to-end) | not started |
| AD-4  | Form roster + suspension cleanup | not started |
| AD-5  | Meta-extensibility: the add-form-spec form | not started |
| AD-6  | Category addition + selector integration + DOMAINS derivation | not started |

### Phase AD-1 — Form-spec + handoff data layer (pure)

**Goal**: schemas, one real form spec, the pure helper module, smoke
integration. No UI yet.

**Files** — new: `data/schemas/agent_form.schema.json`,
`data/schemas/dispatch_handoff.schema.json`, `data/agent_forms/add-enemy.json`,
`editor/agent_forms.py`, `tools/tests/test_agent_forms.py`. Modified:
`tools/smoke.py` (third directory exception: `data/agent_forms/` →
`agent_form.schema.json`), `.gitignore` (`.claude/dispatch/`),
`tools/tests/test_editor_viewport.py` (TestPurity += `editor.agent_forms`).

**Tests**: spec loads + validates; an invalid spec (missing min/max on a
numeric field, unknown key) raises before use; `slugify` /
`default_branch_name` cases (spaces, punctuation, length cap, missing
slug field falls back to free text); `build_payload` → `write_handoff`
round-trip into a temp repo dir re-validates against the handoff schema and is
deterministic-format (sorted keys, 2-space indent, trailing newline);
`handoff_relpath` returns POSIX; `prune_done` deletes only old files;
`validate_data` on a temp tree containing `data/agent_forms/x.json` picks
`agent_form.schema.json`. Confirm the editor-test temp-data helper copies
`data/agent_forms/` along with the rest of `data/`; extend it here if not.

**Exit gate**: `py tools/smoke.py` (now also validating the live form spec) +
`py -m unittest discover -s tools/tests -t .`, zero new failures.

### Phase AD-2 — `/dispatch` skill + spawnclaude pure layer

**Goal**: the skill exists and works when fed a hand-written handoff;
spawnclaude's builders speak dispatch and the `/start-domain` path is gone.

**Files** — new: `.claude/commands/dispatch.md` (per §4). Modified:
`editor/spawnclaude.py` (builders + `dispatch()` only — the dialog rewrite is
AD-3; the domain radio code is deleted here and the dialog temporarily lists
only tweak/admin), `tools/tests/test_spawnclaude.py` (rewrite: keep the
argv-shape tests and `TestNoLockWriteAPI` verbatim, drop domain tests, add
`dispatch_prompt` tests — relative POSIX path, single argv element — and
precedence admin > handoff > tweak with an injected fake detach).

**Exit gate**: suite + smoke; **live check**: hand-write a handoff with
`git.mode: "current"` and a trivial payload, run
`claude "/dispatch .claude/dispatch/test.json"` in a terminal, confirm it
reads/validates/summarizes and drives the target skill (may be aborted before
commit). State exactly what was exercised.

### Phase AD-3 — Generic form renderer + launcher dialog (end-to-end)

**Goal**: the full designer path works live: toolbar → launcher → Add New
Enemy form → terminal opens with `/dispatch …` → PR on a branch off
Development.

**Files** — new: `editor/agent_form_dialog.py` (per §5). Modified:
`editor/spawnclaude.py` (`SpawnClaudeDialog` → launcher), `editor/main.py`
(comment/docstring only), `tools/tests/test_editor_viewport.py` (TestPurity +=
`editor.agent_form_dialog`), `tools/tests/test_spawnclaude.py` (dialog tests),
`editor/CLAUDE.md` (rewrite the spawnclaude invariants section — this is the
architectural-change doc update).

**Tests** (offscreen Qt, temp data dir): launcher lists one entry per spec +
tweak + admin; `AgentFormDialog` generates the right widget per field type
with spec-driven ranges/tooltips; Dispatch button gated on required fields;
git radio default follows `git_default`; branch-name line edit live-slugs and
is editable; accepting writes a handoff into a temp repo that validates, and
the injected fake detach captures argv ending in `/dispatch <relative path>`;
admin/tweak behavior unchanged.

**Exit gate**: suite + smoke; **live**: `py editor/main.py`, dispatch a real
Add New Enemy in branch mode, confirm worktree branch `agent/add-enemy-…`,
green exit gate, PR into Development, handoff archived.

### Phase AD-4 — Form roster + suspension cleanup

**Goal**: every existing add-* skill is reachable from a form; the old domain
flow is visibly suspended.

**Files** — new: `data/agent_forms/{add-building,add-balancing-value,
add-editor-feature,add-engine-component,add-asset-importer,replace-visual}.json`.
Modified: `.claude/commands/{start,resume,finish,merge}-domain.md`
(`SUSPENDED —` description prefix + body note pointing at `/dispatch`), root
`CLAUDE.md` / `docs/prompt-templates.md` mentions where they reference the
spawn modes.

**Tests**: extend `test_agent_forms.py` with an all-specs sweep — every spec's
`skill` file exists in `.claude/commands/`, every `context` path exists, id
matches the filename stem, `selector_context` (when present) is a real
`data/slots.json` category key. (Content validation is already free via
smoke.)

**Exit gate**: suite + smoke; spot-live-check one new form (e.g.
add-building) through the dialog to terminal launch (the dispatch may be
cancelled at the git step).

### Phase AD-5 — Meta-extensibility: the add-form-spec form

**Goal**: "Add new form type" is itself a form; the system extends itself.

**Files** — new: `.claude/commands/add-form-spec.md` (Read first:
`data/schemas/agent_form.schema.json` + one sibling spec; Steps: compose the
new spec JSON, write it via `write_validated`, `py tools/smoke.py` to
validate; if the payload's `needs_new_skill` is true, scaffold the target
skill following `add-skill.md`'s house format; Verify: smoke + the spec
appears in the launcher on next dialog open — specs load fresh per open);
`data/agent_forms/add-form-spec.json` (fields: `thing_name` string required,
`target_skill` string, `needs_new_skill` boolean, `git_default` enum; the
free-text box carries the field wishlist).

**Tests**: the AD-4 sweep automatically covers the new spec; add a test that
`load_form_specs` picks up a spec dropped into a temp `agent_forms/`
(fresh-load semantics).

**Exit gate**: suite + smoke; live: dispatch add-form-spec to create a toy
form, confirm it appears in the launcher and validates.

### Phase AD-6 — Category addition + selector integration + DOMAINS derivation

**Goal**: "Add new category/subcategory" works end-to-end; context-sensitive
"Add new X…" on the selector tree; one hardcoding site fixed.

**Files** — new: `.claude/commands/add-category.md` +
`data/agent_forms/add-category.json` (fields: key, display name,
`is_balancing_domain` boolean, frame_w/frame_h integers, animations; skill
steps: extend `data/slots.json` (+ its schema if needed), and when it's a
balancing domain create `data/balancing/<key>.json` with
`"_lock": "UNLOCKED"` + `data/schemas/<key>.schema.json`, then walk the
**enumerated hardcoding checklist**: `.claude/hooks/scope_guard.py::DOMAIN_SCOPE`,
test DOMAINS lists (e.g. `tools/tests/test_balancing_data.py`),
`smalltweak.md`'s domain mentions — the skill names each site explicitly).
Modified: `editor/locks.py` (`DOMAINS` becomes derived: slots.json category
order ∩ categories with an existing `data/balancing/<key>.json`, preserving
D-10 order — a new domain then appears in selector/balancing with zero editor
edits), `editor/panels/selector.py` (right-click context menu on category
nodes emitting `add_requested(form_id)`, built from the specs'
`selector_context` keys), `editor/main.py` (connect `add_requested` → open
`AgentFormDialog`), `editor/panels/CLAUDE.md` (selector architecture note).

**Explicitly deferred**: `scope_guard.py`'s `DOMAIN_SCOPE` table stays
hardcoded — it belongs to the suspended lock protocol, is fail-open without
`active_domain`, and dispatch never activates it; the add-category checklist
covers it for the day the protocol returns.

**Tests**: `locks.DOMAINS` derivation against a temp data tree (add/remove a
balancing file; order follows slots.json); selector context-menu emits the
mapped form id; add-category spec passes the AD-4 sweep.

**Exit gate**: suite + smoke; live: right-click the enemies category → Add
New Enemy opens the form; dispatch add-category for a toy category on a
branch, confirm the editor shows it after the PR branch is checked out.

## 7. Risks / open items

- **Command-line length**: solved by design — the spawned prompt is exactly
  `/dispatch .claude/dispatch/<file>.json` (repo-relative, no spaces;
  `wt -d <repo>` sets cwd). A repo path containing spaces stays safe because
  argv is passed as a list to `QProcess.startDetached` (the proven pattern).
- **Concurrent branch-mode spawns / editor tree stability**: solved by
  worktrees (D3). Residual: two concurrent dispatches editing the *same*
  files still conflict at PR time — accepted, same as processtodo.
  Current-branch mode is inherently single-writer; the dirty-tree warning is
  the guard.
- **OneDrive**: the repo lives under OneDrive; `git worktree` churn can trip
  sync file-locks. Worktrees are short-lived and `processtodo` already uses
  this layout here without reported issues; if it bites, move the worktree
  root out of the synced tree (a one-line change in `dispatch.md`).
- **Stale handoffs**: `done/` archive + `prune_done(30d)` on launcher open;
  unconsumed live handoffs older than a day are also pruned (a spawn that
  never ran).
- **SlashCommand availability inside a skill**: the read-and-follow fallback
  is written into `dispatch.md`, so composition degrades gracefully.
- **`allowed-tools` breadth on `/dispatch`**: it grants `Bash(git *)` + edit
  tools because the downstream skill varies. Acceptable — the target skill's
  own narrow instructions govern behavior, and admin mode already grants
  everything. Flagged for review.
- **Spec evolution**: `schema_version: 1` in both schemas; the renderer
  rejects unknown versions loudly.
