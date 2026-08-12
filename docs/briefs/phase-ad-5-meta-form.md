> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase AD-5 Brief — Meta-extensibility: the `add-form-spec` form

> Coordination artifact for the AD-1..AD-7 subagent batch. Planner filled §1–§4;
> the coder treats §3 as a HARD boundary and §2 as a contract; the reviewer
> verifies the diff against §1/§2/§4. Source plan: `planning/AgentDispatchPLAN.md`
> (§3 form-spec schema + add-enemy example; §6 **Phase AD-5**). Branch:
> `phase-AD-5-meta-form` (under the `phase-AD-1-7-umbrella`).

**Phase goal (plan §6/AD-5):** *"Add new form type" is itself a form; the system
extends itself.* After this phase a designer can press **Summon a Drunken Robot →
Add New Form Type**, describe a new thing-type and its fields in plain text, and
get back a schema-validated `data/agent_forms/<id>.json` (plus, optionally, the
skill it dispatches to) — which then appears as a new button in that same
launcher on its next open, with **no editor restart and no editor code change**.

---

## 0. Known repo state — you are building ON TOP OF AD-1/AD-2/AD-3 (do NOT re-derive)

These are merged into your base before you start. Read the files; do not rebuild them.

- **AD-1** — `data/schemas/agent_form.schema.json` (the spec schema, plan §3),
  `data/agent_forms/add-enemy.json` (your sibling reference spec),
  `editor/agent_forms.py` (`load_form_specs(data_dir)` — **loads specs FRESH on
  every call**, sorted by id, loud on invalid), `tools/tests/test_agent_forms.py`,
  and the **third directory exception** in `tools/smoke.py::validate_data`
  (`data/agent_forms/*.json` → `agent_form.schema.json` regardless of stem).
  *That exception is why writing a spec file into `data/agent_forms/` is
  automatically smoke-gated — you get validation for free and must not touch
  `smoke.py`.*
- **AD-3** — the launcher (`SpawnClaudeDialog`) calls `load_form_specs` **fresh on
  every open**. This is the load-bearing property of this whole phase: a spec file
  that lands on disk shows up in the launcher on the next dialog open.
- **AD-4 (parallel with you)** — appends an **all-specs sweep** `TestCase` to
  `tools/tests/test_agent_forms.py` asserting, for every spec: `id` == filename
  stem, `.claude/commands/<skill>.md` exists, every `context` path exists,
  `selector_context` (if present) is a real `data/slots.json` category key. **Your
  new spec is covered by that sweep automatically — do NOT duplicate it.** It is
  also the reason for the two guards in §2.

Pre-existing suite baseline on `Development`: **17 failures**. "Zero NEW failures"
in §4 is measured against that baseline, not against zero.

---

## 1. Behavioral spec

Two new files. Nothing else is created.

### (a) `.claude/commands/add-form-spec.md` — the skill

House format per `.claude/commands/add-skill.md` (frontmatter `description:` /
`argument-hint:` / `allowed-tools:`; body = restatement → **Read first
(token-light)** → **Steps** → **Avoid** → **Verify** → **Final report**; ≤ ~60
lines; minimal `allowed-tools`, no blanket `Bash`).

- **Read first** = `data/schemas/agent_form.schema.json` (the contract) + one
  sibling spec, `data/agent_forms/add-enemy.json` (the shape).
- **Steps** = compose the new spec JSON from the dispatch payload's `values` +
  `free_text` (the free text carries the **field wishlist**) → write it with
  `engine.data_io.write_validated` against `agent_form.schema.json` → run
  `py tools/smoke.py` to validate → **if `values.needs_new_skill` is true**,
  scaffold the target skill at `.claude/commands/<skill>.md` following
  `add-skill.md`'s house format.
- **Verify** = smoke green + the spec appears in the launcher on the next dialog
  open (specs load fresh per open; no editor restart).

**COMPLETE DRAFT — lift this verbatim (adjust only if the AD-1 schema landed with
different key names):**

```markdown
---
description: Use when the task is to add a new "Add new X" form type to the editor's agent launcher. Writes a schema-validated form spec into data/agent_forms/ and, if asked, scaffolds the skill that form dispatches to.
argument-hint: <thing name + the fields the form should carry, e.g. "Sound Effect: name, category enum, loop bool">
allowed-tools: Read, Write, Edit, Glob, Bash(py tools/smoke.py*), Bash(py -m unittest*), Bash(py -c *)
---

Add a new agent form type: **$ARGUMENTS**. A "form" is one JSON spec in
`data/agent_forms/`; the editor's launcher renders it generically and dispatches it
— **no editor code is ever written for a new form**. The schema is the contract:
if it validates, it renders.

## Read first (token-light)
1. `data/schemas/agent_form.schema.json` — the contract (field types, required
   keys, id/skill patterns). Do not guess it.
2. `data/agent_forms/add-enemy.json` — a real sibling spec; match its shape.

## Steps
1. **Pick the id** — kebab-case, usually `add-<thing>` (from `thing_name`). The
   file is `data/agent_forms/<id>.json` and the spec's `id` **must equal that
   filename stem** (schema pattern + a test enforce it).
2. **Pick the skill** — `values.target_skill`, else `add-<thing>`. By the end of
   this run `.claude/commands/<skill>.md` MUST exist: a test asserts every spec's
   skill file is on disk.
3. **Compose the spec**: `schema_version: 1`, `id`, `title` ("Add New <Thing>"),
   `description` (one paragraph the dialog shows), `skill`, `context` (2–3
   repo-relative docs the agent should read first — **each path must exist**),
   `git_default` (from `values.git_default`), `slug_field` (the field that names
   the branch), `fields`.
   Turn the free-text wishlist into `fields[]`: `key` (snake_case), `label`,
   `type` (`string|text|boolean|integer|number|enum`), `description` (the widget
   tooltip — required), plus `required` / `default` / `placeholder` as needed.
   `enum` needs `options`; `integer`/`number` need `minimum` AND `maximum` (they
   become the spinbox range, so invalid input is unrepresentable — ED-30).
   **Never add a free-text/description field** — the dialog gives every form one
   for free.
4. **Write it through the validating writer** (the only sanctioned write path —
   deterministic sorted-key output, and an invalid spec never reaches disk).
   Write your draft to a scratch file, then:
   `py -c "from engine import data_io; d=data_io.load_json(r'<scratch>.json'); data_io.write_validated(d, r'data/agent_forms/<id>.json', r'data/schemas/agent_form.schema.json')"`
   then delete the scratch file. Fix and re-run on any ValidationError.
5. **Scaffold the skill** — only if `needs_new_skill` is true: create
   `.claude/commands/<skill>.md` following `.claude/commands/add-skill.md` (three
   frontmatter keys, minimal `allowed-tools`, Read-first / Steps / Avoid / Verify
   / Final report, ≤ ~60 lines). Touch no other command file.

## Avoid
- Hand-formatting the JSON or writing it with a plain file write — use
  `write_validated`.
- `id` != filename stem; a `skill` with no `.claude/commands/<skill>.md`; a
  `context` path that does not exist — each one fails the spec-sweep test.
- Editing `editor/**`, `tools/smoke.py`, `data/schemas/**`, or any other
  `data/agent_forms/*.json` — a new form needs NONE of them.

## Verify
- `py tools/smoke.py` — validates the new spec (the `data/agent_forms/` directory
  exception pairs it with `agent_form.schema.json`).
- `py -m unittest discover -s tools/tests -t .` — the all-specs sweep checks id /
  skill file / context paths.
- Live: reopen **Summon a Drunken Robot** in the editor — the new form is listed
  (specs load fresh on every open; no restart). State what you verified.

## Final report
- The new spec path + the skill path (if scaffolded); the fields and their types;
  the git default; verification performed.
```

### (b) `data/agent_forms/add-form-spec.json` — the spec

Fields per plan §6/AD-5: `thing_name` (string, **required**), `target_skill`
(string), `needs_new_skill` (boolean), `git_default` (enum `branch|current`). The
built-in free-text box carries the **field wishlist** — that is stated in the
spec's `description` and in the free-text placeholder story, not as a spec field.

**COMPLETE intended JSON — lift verbatim:**

```json
{
  "schema_version": 1,
  "id": "add-form-spec",
  "title": "Add New Form Type",
  "description": "Adds a new \"Add new X\" button to this launcher. Describe the thing-type and, in the box below, the fields its form should carry (name, type, bounds, default) — an agent writes the schema-validated form spec, and optionally the skill it dispatches to. The new form appears here the next time you open this dialog.",
  "skill": "add-form-spec",
  "context": [
    "data/schemas/agent_form.schema.json",
    "data/agent_forms/add-enemy.json",
    ".claude/commands/add-skill.md"
  ],
  "git_default": "branch",
  "slug_field": "thing_name",
  "fields": [
    {
      "key": "thing_name",
      "label": "Thing name",
      "type": "string",
      "required": true,
      "placeholder": "Sound Effect",
      "description": "What the new form adds, e.g. 'Sound Effect'. Drives the form id (add-sound-effect), its title, and the branch slug."
    },
    {
      "key": "target_skill",
      "label": "Target skill",
      "type": "string",
      "placeholder": "add-sound-effect",
      "description": "Slash command the new form dispatches to, kebab-case, no leading slash. Leave blank to derive add-<thing-name>."
    },
    {
      "key": "needs_new_skill",
      "label": "Scaffold the skill too",
      "type": "boolean",
      "default": true,
      "description": "On: also create .claude/commands/<target skill>.md following the house format. Off: that skill already exists."
    },
    {
      "key": "git_default",
      "label": "New form's default git mode",
      "type": "enum",
      "options": ["branch", "current"],
      "default": "branch",
      "description": "Which git mode the NEW form will pre-select when a designer runs it: 'branch' (worktree off Development, ends with a PR) or 'current' (work in place)."
    }
  ]
}
```

**Do not confuse the two `git_default`s.** The top-level `git_default` is *this*
form's own pre-selected radio. The `git_default` **field** is a value the designer
picks that the skill copies into the **generated** spec. `values.git_default` has
nothing to do with the git mode of the dispatch run that creates the spec — that
one is chosen by the dialog's radio and lands in the handoff's `git.mode`.

Every `context` path above exists post-AD-1 (the first two are AD-1 artifacts) —
required, because AD-4's sweep asserts it.

---

## 2. Architecture plan — the meta-loop

```
editor launcher (SpawnClaudeDialog)          .claude/ (agent side)
  load_form_specs(data/)  ── fresh per open
  └─ "Add New Form Type" ─► AgentFormDialog(add-form-spec.json)
       submit → build_payload → write_handoff
                └─► .claude/dispatch/<ts>-add-form-spec.json   (schema-validated)
                     └─► wt … claude "/dispatch .claude/dispatch/<ts>-add-form-spec.json"
                          └─► /dispatch : git setup + payload translation
                               └─► /add-form-spec   (THIS PHASE)
                                    ├─ compose spec ─ write_validated ─►
                                    │      data/agent_forms/<new-id>.json
                                    ├─ (if needs_new_skill) ─► .claude/commands/<skill>.md
                                    └─ py tools/smoke.py  ── validates the new spec
  next dialog open → load_form_specs re-reads data/agent_forms/ → NEW BUTTON
```

The loop closes with **zero editor code** in the path: the launcher is a renderer
over `data/agent_forms/*.json`, and `load_form_specs` re-reads the directory on
every open (AD-1/AD-3 property). A new spec file therefore *is* a new feature.

**Why the invalid-spec case is impossible.** The only sanctioned write is
`engine.data_io.write_validated`, which validates **before** anything touches disk
(`jsonschema.validate` then `Path.write_text`). A malformed spec raises and no file
is created, so the launcher never sees a half-written or invalid spec — it cannot
crash at open. Smoke then re-validates the same file through the AD-1 directory
exception, so a hand-edited spec is caught at the exit gate too. Belt and braces,
both free.

**Two guards the skill must honour (each is a test AD-4 will run against your
spec, and against every spec the skill later generates):**

1. **`id` == filename stem.** The schema pins the id *pattern*; only the sweep test
   pins id-to-filename. `write_validated` cannot catch a mismatch, so the skill
   must derive the path from the id (`data/agent_forms/<id>.json`) rather than
   naming the two independently.
2. **`skill` must point at a `.claude/commands/<skill>.md` that exists by the end
   of the run.** If `needs_new_skill` is true the skill file is scaffolded in the
   *same* run, *before* the exit gate. If it is false, the skill must confirm the
   file already exists and abort loud if not — otherwise it lands a spec that
   permanently reds the sweep test for everybody.

**Ordering that avoids a broken intermediate state** — within one dispatch run,
in this order: (1) compose in memory → (2) scaffold the skill file **first** if
`needs_new_skill` (cheap, no validation gate) → (3) `write_validated` the spec
(the atomic "the form now exists" moment; fails before disk on any schema error)
→ (4) `py tools/smoke.py` + suite. Writing the spec *last* means the repo is never
in a state where a form spec references a skill file that does not exist — the
window in which the sweep test could fail is closed before it opens. Since AD-5's
own two files are added in a single commit on a single branch, the same ordering
holds for the merge: `add-form-spec.json` and `add-form-spec.md` are inseparable.

---

## 3. File scope + shared-file contract

**New (2):**
- `.claude/commands/add-form-spec.md`
- `data/agent_forms/add-form-spec.json`

**Modified (1):**
- `tools/tests/test_agent_forms.py` — **APPEND ONE new `unittest.TestCase` class,
  at the end of the file.** Nothing else in that file changes.

  Name it distinctly (e.g. `TestFormSpecFreshLoad`) so it cannot collide with the
  AD-4 sweep class. It must assert the **fresh-load semantics** the whole phase
  rests on:

  - build a temp `data/` dir with an `agent_forms/` subdir (and whatever
    `data/schemas/` copy the AD-1 tests' helper already provides — reuse that
    helper, do not invent a second one);
  - `load_form_specs(tmp_data)` → baseline set of ids;
  - drop a **new valid spec file** into `tmp_data/agent_forms/` (write it via
    `data_io.write_validated` against the real `agent_form.schema.json`, so the
    test also proves the writer path);
  - call `load_form_specs(tmp_data)` **again, in the same process, with no
    reload/restart** → assert the new id is now present (and that the return stays
    sorted by id).

  **Clean-merge contract (AD-4 is appending to this same file in parallel):** keep
  the class fully self-contained — put any imports it needs that are not already at
  module top level *inside* the test methods, add no module-level constants, and
  append strictly at EOF. Then the two branches' diffs are pure additions at the
  same anchor and git merges them without conflict.

**HARD BOUNDARY — do NOT touch:**
`editor/**` (the renderer already handles every field type — a new form needs zero
editor code; that is the point of the phase), `tools/smoke.py` (the directory
exception is AD-1's and already covers you), `data/schemas/**` (the spec schema is
AD-1's contract — if you believe it needs a change, STOP and report instead of
editing), any other `data/agent_forms/*.json` (AD-4 owns the roster), any other
`.claude/commands/*.md` (AD-4 owns the suspension prefixes; `add-skill.md` is read,
never edited), `game/**`, `engine/**`.

---

## 4. Exit gate + Quick Test

**Exit gate (headless, must be green before the PR):**
1. `py tools/smoke.py` — now also validates `data/agent_forms/add-form-spec.json`
   through the AD-1 directory exception. Must report the file count +1 and pass.
2. `py -m unittest discover -s tools/tests -t .` — **zero NEW failures** against
   the 17-failure `Development` baseline. This includes AD-4's all-specs sweep once
   the branches meet on the umbrella: your spec's `id`, `skill` file and `context`
   paths must all resolve.
3. Report exactly what was run (smoke / suite / static read only) — no live editor
   run is claimable from a headless agent.

**NOT doable headlessly → Quick Test for the user, written into the PR body:**

> **Quick Test (needs a desktop session — the agent could not run this):**
> 1. `py editor/main.py` → toolbar → **Summon a Drunken Robot**. Confirm a new
>    **Add New Form Type** entry is listed alongside Add New Enemy.
> 2. Open it. Confirm the four widgets render: *Thing name* (line edit, required —
>    Dispatch stays disabled until it is filled), *Target skill* (line edit),
>    *Scaffold the skill too* (checkbox, on), *New form's default git mode* (combo,
>    `branch`). Confirm the built-in free-text box is present above them.
> 3. Enter a toy thing — e.g. Thing name `Sound Effect`, free text
>    *"fields: name (string, required), category enum ambient|sfx|music, loop
>    boolean default false, gain number 0..2"*. Leave git mode = **New branch**.
>    Dispatch.
> 4. A terminal opens on `/dispatch .claude/dispatch/<ts>-add-form-spec.json`. Let
>    it run: it should create `data/agent_forms/add-sound-effect.json` +
>    `.claude/commands/add-sound-effect.md` in the worktree, go green on smoke, and
>    open a PR.
> 5. Check out that branch, then **reopen Summon a Drunken Robot with the editor
>    still running** (do NOT restart it) — **Add New Sound Effect** must now be in
>    the list, and opening it must render the four fields from step 3 with the
>    enum/number bounds you asked for. That "no restart" step is the phase's whole
>    claim; it is the one thing worth checking by hand.
