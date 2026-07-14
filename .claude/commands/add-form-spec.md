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
3. `.claude/commands/add-skill.md` — only if you must scaffold the target skill.

## Steps
1. **Pick the id** — kebab-case, usually `add-<thing>` (from `thing_name`). The
   file is `data/agent_forms/<id>.json` and the spec's `id` **must equal that
   filename stem** (schema pattern + a test enforce it). Derive the path FROM the
   id; never name the two independently.
2. **Pick the skill** — `values.target_skill`, else `add-<thing>`. By the end of
   this run `.claude/commands/<skill>.md` MUST exist: a test asserts every spec's
   skill file is on disk.
3. **Compose the spec in memory**: `schema_version: 1`, `id`, `title` ("Add New
   <Thing>"), `description` (one paragraph the dialog shows), `skill`, `context`
   (2–3 repo-relative docs the agent should read first — **each path must exist**),
   `git_default` (from `values.git_default`), `slug_field` (the field that names
   the branch), `fields`.
   Turn the free-text wishlist into `fields[]`: `key` (snake_case), `label`,
   `type` (`string|text|boolean|integer|number|enum`), `description` (the widget
   tooltip — required), plus `required` / `default` / `placeholder` as needed.
   `enum` needs `options`; `integer`/`number` need `minimum` AND `maximum` (they
   become the spinbox range, so invalid input is unrepresentable — ED-30).
   **Never add a free-text/description field** — the dialog gives every form one
   for free. **Two `git_default`s, do not confuse them:** `values.git_default` is
   the designer's pick for the **new** form's top-level `git_default` (the radio it
   pre-selects later); the git mode of *this* run is the dialog's own radio, in the
   handoff's `git.mode`.
4. **Scaffold the skill FIRST — before the spec hits disk.** If
   `values.needs_new_skill` is true, create `.claude/commands/<skill>.md` following
   `.claude/commands/add-skill.md` (three frontmatter keys, minimal `allowed-tools`,
   Read-first / Steps / Avoid / Verify / Final report, ≤ ~60 lines). If it is false,
   confirm the file already exists and **abort loud** if it does not. The order is
   deliberate: a spec pointing at a missing `.claude/commands/<skill>.md` reds the
   all-specs sweep for everybody — close that window before it opens. Touch no other
   command file.
5. **Then write the spec through the validating writer** (the only sanctioned write
   path — deterministic sorted-key output, and an invalid spec never reaches disk).
   Write your draft to a scratch file, then:
   `py -c "from engine import data_io; d=data_io.load_json(r'<scratch>.json'); data_io.write_validated(d, r'data/agent_forms/<id>.json', r'data/schemas/agent_form.schema.json')"`
   then delete the scratch file. Fix and re-run on any ValidationError.

## Avoid
- Hand-formatting the JSON or writing it with a plain file write — use
  `write_validated`.
- Writing the spec before the skill file exists (step 4 before step 5, always).
- `id` != filename stem; a `skill` with no `.claude/commands/<skill>.md`; a
  `context` path that does not exist — each one fails the spec-sweep test.
- Editing `editor/**`, `tools/smoke.py`, `data/schemas/**`, or any other
  `data/agent_forms/*.json` — a new form needs NONE of them.

## Verify
- `py tools/smoke.py` — validates the new spec (the `data/agent_forms/` directory
  exception pairs it with `agent_form.schema.json`); the file count goes up by one.
- `py -m unittest discover -s tools/tests -t .` — the all-specs sweep checks id /
  skill file / context paths.
- Live: reopen **Summon a Drunken Robot** in the editor — the new form is listed
  (specs load fresh on every open; no restart). State what you verified.

## Final report
- The new spec path + the skill path (if scaffolded); the fields and their types;
  the git default; verification performed.
