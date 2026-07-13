# Phase AD-1 — Form-spec + handoff data layer (pure)

Brief for the coder agent. Source plan: `planning/AgentDispatchPLAN.md`
(§2 Architecture L32–113, §3 Form-spec system L115–217, §5 L264–302,
§6 phase AD-1 L315–339). Branch: `phase-AD-1-7-umbrella` (off `Development`).

**This phase ships NO UI.** Schemas + one real form spec + one pure helper module
+ smoke integration + tests. Do not touch `editor/spawnclaude.py` (AD-2 owns it),
do not create `editor/agent_form_dialog.py` (AD-3 owns it).

---

## 1. Behavioral spec

AD-1 must produce the data substrate that AD-2/AD-3 build on: a schema-validated
**form spec** format, a schema-validated **handoff payload** format, one real
form spec on disk, and the pure Python that turns (spec + user values) into a
handoff file on disk. Everything validates through `engine.data_io`, and
`tools/smoke.py` gates the form specs for free (plan §2 D1, L65–76).

### 1a. `data/schemas/agent_form.schema.json` (new)

Plan §3 L117–164 gives the sketch. Reconcile to house style (`data/CLAUDE.md`
L113–116): add `$id` + `title`, keep draft 2020-12, `additionalProperties:false`
at every object level, a `description` on **every** property, and write the file
in D-3 canonical form (sorted keys, 2-space indent, trailing newline — author it
via `data_io.dumps_deterministic`, never hand-format).

House-style reconciliation notes (do not "fix" these):
- The `allOf` + `if/then` in `$defs/field` is **safe** despite
  `data/CLAUDE.md` L96's "no `allOf` composition" warning: that warning is about
  `allOf` branches that introduce *properties* (which `additionalProperties:false`
  then rejects). Here the `then` branches add only `required`, and every property
  named anywhere is already declared in the parent `properties` — no conflict.
  Keep it: it is what makes `options` mandatory for enums and `minimum`/`maximum`
  mandatory for numerics (ED-30: the dialog derives spinbox ranges from them, so
  invalid input is unrepresentable).
- `type` is in `required`, so the `if` clauses never fire vacuously.

Intended content (canonical order shown; this IS the file):

```json
{
  "$defs": {
    "field": {
      "additionalProperties": false,
      "allOf": [
        {
          "if": { "properties": { "type": { "const": "enum" } } },
          "then": { "required": ["options"] }
        },
        {
          "if": { "properties": { "type": { "enum": ["integer", "number"] } } },
          "then": { "required": ["minimum", "maximum"] }
        }
      ],
      "properties": {
        "default": {
          "description": "Pre-filled widget value; must match the field type.",
          "type": ["string", "number", "boolean"]
        },
        "description": {
          "description": "Widget tooltip explaining the field to the designer.",
          "minLength": 1,
          "type": "string"
        },
        "key": {
          "description": "Payload key under handoff 'values'.",
          "pattern": "^[a-z][a-z0-9_]*$",
          "type": "string"
        },
        "label": {
          "description": "Widget label shown in the form.",
          "minLength": 1,
          "type": "string"
        },
        "maximum": {
          "description": "Upper bound for integer/number fields; required for them (ED-30 spinbox range).",
          "type": "number"
        },
        "minimum": {
          "description": "Lower bound for integer/number fields; required for them (ED-30 spinbox range).",
          "type": "number"
        },
        "options": {
          "description": "Choices for an enum field; required for type 'enum'.",
          "items": { "type": "string" },
          "minItems": 1,
          "type": "array"
        },
        "placeholder": {
          "description": "Placeholder text for string/text widgets.",
          "type": "string"
        },
        "required": {
          "description": "When true the field gates the dialog's Dispatch button. Default false.",
          "type": "boolean"
        },
        "type": {
          "description": "Widget kind: string (line edit), text (multi-line), boolean (checkbox), integer/number (spinbox), enum (combo box).",
          "enum": ["string", "text", "boolean", "integer", "number", "enum"]
        }
      },
      "required": ["key", "label", "type", "description"],
      "type": "object"
    }
  },
  "$id": "agent_form.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": "data/agent_forms/<id>.json (THIRD schema-pairing exception in tools/smoke.py, same pattern as map_file/balancing_history): one agent-dispatch form spec per game thing-type. The editor renders the dialog from this spec; submitting writes a dispatch_handoff.schema.json payload. The free-text description box is built into the dialog, NOT a spec field - every form gets it for free.",
  "properties": {
    "context": {
      "description": "Repo-relative docs the spawned agent reads first; copied verbatim into the handoff.",
      "items": { "minLength": 1, "type": "string" },
      "type": "array"
    },
    "description": {
      "description": "One paragraph shown under the dialog title.",
      "minLength": 1,
      "type": "string"
    },
    "fields": {
      "description": "Structured fields rendered above the git group, in order.",
      "items": { "$ref": "#/$defs/field" },
      "type": "array"
    },
    "git_default": {
      "description": "Pre-selected git mode in the dialog: 'branch' (worktree off Development, ends with a PR) or 'current' (in place, stop-and-confirm).",
      "enum": ["branch", "current"]
    },
    "id": {
      "description": "Must equal the filename stem (loader-enforced); also the branch-name prefix (agent/<id>-<slug>).",
      "pattern": "^[a-z][a-z0-9-]*$",
      "type": "string"
    },
    "schema_version": {
      "const": 1,
      "description": "Spec format version. The renderer rejects unknown versions loudly."
    },
    "selector_context": {
      "description": "Optional data/slots.json category key whose selector-tree node offers this form via right-click (AD-6).",
      "type": "string"
    },
    "skill": {
      "description": "Target slash command; .claude/commands/<skill>.md must exist (AD-4 sweep enforces).",
      "pattern": "^[a-z][a-z0-9-]*$",
      "type": "string"
    },
    "slug_field": {
      "description": "Field key whose value names the auto branch (default 'name'; falls back to the free-text box).",
      "type": "string"
    },
    "title": {
      "description": "Dialog window title, e.g. 'Add New Enemy'.",
      "minLength": 1,
      "type": "string"
    }
  },
  "required": ["schema_version", "id", "title", "description", "skill", "context", "git_default", "fields"],
  "title": "agent_form",
  "type": "object"
}
```

(`slug_field` and `selector_context` are deliberately NOT in `required` —
optional per plan §3.)

### 1b. `data/schemas/dispatch_handoff.schema.json` (new)

Plan §3 L196–217 (prose + example payload) and §2 D2 (L77–85). Not paired with
any `data/` content file — that is legal: `validate_data` skips `data/schemas/`
entirely (`tools/smoke.py` L42–43). Handoffs live in `.claude/dispatch/`
(gitignored), still written through `write_validated` so the single-write-path
invariant holds.

Requirements:
- `additionalProperties: false` at every object level.
- `values` is a **permissive object** (`{"type": "object"}`, no `properties`, no
  `additionalProperties`) — the form spec already constrained types at render
  time.
- `git.mode` is `enum ["branch", "current"]`; `git.branch` is required **only**
  when `mode == "branch"`, via `if/then` on the `git` subschema. `git.base` is
  always present (build_payload always writes `"Development"`).
- `spawned_from` is **declared but NOT required** — see §2 rationale (a temp test
  repo has no `.git`, and the field is informational).

Intended content:

```json
{
  "$id": "dispatch_handoff.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": ".claude/dispatch/<YYYYMMDD-HHMMSS>-<form-id>.json (gitignored, transient agent I/O; no data/ content file pairs with this schema - validate_data skips data/schemas/). Written by editor/agent_forms.write_handoff via engine.data_io.write_validated, read+validated by the /dispatch skill.",
  "properties": {
    "context": {
      "description": "Repo-relative docs the agent reads first; copied from the form spec.",
      "items": { "minLength": 1, "type": "string" },
      "type": "array"
    },
    "created_at": {
      "description": "UTC timestamp of the dispatch, ISO 8601 with a Z suffix.",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
      "type": "string"
    },
    "form_id": {
      "description": "id of the data/agent_forms/<id>.json spec this payload came from.",
      "pattern": "^[a-z][a-z0-9-]*$",
      "type": "string"
    },
    "free_text": {
      "description": "The dialog's built-in free-text description box. May be empty.",
      "type": "string"
    },
    "git": {
      "additionalProperties": false,
      "description": "Git behavior chosen per run in the form.",
      "if": { "properties": { "mode": { "const": "branch" } } },
      "properties": {
        "base": {
          "description": "Branch the work is based on (branch mode); always 'Development'.",
          "minLength": 1,
          "type": "string"
        },
        "branch": {
          "description": "Auto-named agent/<form-id>-<slug>, editable in the dialog. Required in branch mode, absent in current mode.",
          "minLength": 1,
          "type": "string"
        },
        "mode": {
          "description": "'branch' = worktree off Development ending in a PR; 'current' = work in place on the checked-out branch, stop-and-confirm before committing.",
          "enum": ["branch", "current"]
        }
      },
      "required": ["mode", "base"],
      "then": { "required": ["branch"] },
      "type": "object"
    },
    "schema_version": {
      "const": 1,
      "description": "Handoff format version. /dispatch rejects unknown versions loudly."
    },
    "skill": {
      "description": "Slash command /dispatch drives after git setup; .claude/commands/<skill>.md.",
      "pattern": "^[a-z][a-z0-9-]*$",
      "type": "string"
    },
    "spawned_from": {
      "additionalProperties": false,
      "description": "Informational: the branch the editor was on when the dispatch was made. Omitted when it cannot be resolved (no .git).",
      "properties": {
        "branch": {
          "description": "Branch name read from <repo>/.git/HEAD at dispatch time.",
          "minLength": 1,
          "type": "string"
        }
      },
      "required": ["branch"],
      "type": "object"
    },
    "values": {
      "description": "Structured field values keyed by the spec's field keys. Deliberately permissive - the form spec already constrained the types at render time.",
      "type": "object"
    }
  },
  "required": ["schema_version", "form_id", "skill", "created_at", "free_text", "values", "git", "context"],
  "title": "dispatch_handoff",
  "type": "object"
}
```

### 1c. `data/agent_forms/add-enemy.json` (new)

Plan §3 L169–194, verbatim content, re-emitted in D-3 canonical form (sorted
keys; the `fields` array order is preserved — arrays are not sorted). Both
`context` paths were verified to exist (`game/enemies/CLAUDE.md`,
`.claude/commands/add-enemy.md`), and `selector_context: "enemies"` is a real
`data/slots.json` category key — the AD-4 sweep will assert all three.

```json
{
  "context": ["game/enemies/CLAUDE.md", ".claude/commands/add-enemy.md"],
  "description": "Spawns an agent that adds a new enemy type: thin Enemy subclass, spawner branch, scale-tier stats, registry slots (10F/10G pattern).",
  "fields": [
    {
      "description": "Display name; drives class name, ETYPE, branch slug.",
      "key": "name",
      "label": "Enemy name",
      "placeholder": "Siege Cannon",
      "required": true,
      "type": "string"
    },
    {
      "default": "Walker",
      "description": "REGISTRY_GROUP the variants roll from.",
      "key": "registry_group",
      "label": "Registry group",
      "options": ["Walker", "Raider", "Siege Cannon", "Boss", "New group"],
      "type": "enum"
    },
    {
      "default": false,
      "description": "Siege-style targeting instead of base pathing.",
      "key": "targets_buildings",
      "label": "Targets buildings",
      "type": "boolean"
    },
    {
      "default": 4,
      "description": "How many era slots to add in slots.json.",
      "key": "era_count",
      "label": "Era variants",
      "maximum": 8,
      "minimum": 1,
      "type": "integer"
    }
  ],
  "git_default": "branch",
  "id": "add-enemy",
  "schema_version": 1,
  "selector_context": "enemies",
  "skill": "add-enemy",
  "slug_field": "name",
  "title": "Add New Enemy"
}
```

`data/agent_forms/` does not exist yet — this file creates it (git cannot track
an empty directory, so the directory and the spec land together).

---

## 2. Architecture plan

### 2a. `editor/agent_forms.py` (new, PURE)

Plan §5 L266–274. **Purity is a hard rule** (`editor/CLAUDE.md` L58): no
PySide6, no pygame, no `editor.run_controls` import. Allowed imports: stdlib
(`datetime`, `pathlib`, `re`, `unicodedata`) + `engine.data_io`. Module docstring
follows the `editor/registry_ops.py` house pattern (what it is, why it is pure,
why it stays in `TestPurity`).

Module constants:
```python
REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "data"
FORMS_SUBDIR = "agent_forms"
SCHEMA_VERSION = 1
```

Public API (all `data_dir` / `repo` params default to `None` → repo defaults,
matching `editor/locks.py`'s injection convention so tests run against a temp
tree):

| Function | Returns | Errors |
|---|---|---|
| `forms_dir(data_dir=None)` | `Path` — `<data_dir or DEFAULT_DATA>/agent_forms`. No I/O, no mkdir. | none |
| `load_form_specs(data_dir=None)` | `list[dict]` — every `*.json` under `forms_dir`, each through `data_io.load_validated(path, <data_dir>/schemas/agent_form.schema.json)`, **sorted by `spec["id"]`**. Missing directory → `[]`. Reads fresh on every call (AD-3/AD-5 rely on this: new specs appear without an editor restart). | `jsonschema.ValidationError` on an invalid spec (loud, propagates). `ValueError` when `spec["id"] != path.stem` — the loader cross-check the schema cannot express (`engine/tilemap.py` precedent). |
| `slugify(text, max_len=32)` | `str` — lowercase; NFKD-fold to ASCII; every run of non-`[a-z0-9]` → `-`; collapse repeats; strip leading/trailing `-`; truncate to `max_len` then re-strip trailing `-`. Empty/`None` input → `""`. Deterministic, no randomness. | none |
| `default_branch_name(spec, values, free_text)` | `str` — `f"agent/{spec['id']}-{slug}"` where `slug = slugify(values.get(spec.get('slug_field', 'name')))`, falling back to `slugify(free_text)` when that is empty. When **both** are empty → `f"agent/{spec['id']}"` (no trailing dash). | none |
| `build_payload(spec, values, free_text, git_mode, branch=None, repo=None)` | `dict` — the dispatch_handoff payload. `schema_version: 1`; `form_id`/`skill`/`context` from the spec; `created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`; `free_text` stripped (`""` when None); `values` a shallow copy of the passed dict; `git = {"mode": git_mode, "base": "Development"}` plus `"branch": branch or default_branch_name(...)` **only when `git_mode == "branch"`**; `spawned_from = {"branch": b}` only when `_current_branch(repo)` resolves. Does NOT touch disk. | `ValueError` when `git_mode` not in `{"branch", "current"}`. |
| `write_handoff(payload, repo=None, data_dir=None)` | `Path` — `<repo>/.claude/dispatch/<YYYYMMDD-HHMMSS>-<form_id>.json` (timestamp derived from `payload["created_at"]`), `mkdir(parents=True, exist_ok=True)` on the dispatch dir, written via `data_io.write_validated(payload, path, <data_dir>/schemas/dispatch_handoff.schema.json)`. On a name collision, suffix `-2`, `-3`, … before `.json`. | `jsonschema.ValidationError` before anything touches disk (write_validated validates first). |
| `handoff_relpath(path, repo=None)` | `str` — repo-relative **POSIX** path (`.claude/dispatch/x.json`), via `Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()`. This is what `/dispatch <relpath>` consumes (plan §7 L535–538: no spaces, one argv element). | `ValueError` when `path` is outside `repo` (let `relative_to`'s ValueError propagate, or re-raise with a clearer message). |
| `prune_done(repo=None, days=30, live_days=1)` | `int` — number of files deleted. Deletes `*.json` under `.claude/dispatch/done/` with mtime older than `days`, AND unconsumed live `*.json` directly under `.claude/dispatch/` older than `live_days` (plan D2 L84–85, §7 L548–550). Missing dirs → `0`, never raises. | none (best-effort; swallow `OSError` per file) |

Private helper:
- `_current_branch(repo)` → `str | None`. **Pure file read, no subprocess**: read
  `<repo>/.git/HEAD`; if it starts with `ref: refs/heads/`, return the rest
  stripped; otherwise (detached HEAD, `.git` is a worktree pointer file, or no
  `.git` at all) return `None`. This is why `spawned_from` is optional in the
  schema — a temp test repo has no `.git`, and the field is informational only.

**Deliberate, minimal deviations from plan §5's literal signatures** (all
additive, all keyword-with-default, so every call shape the plan writes still
works):
- `data_dir=None` on `write_handoff` — keeps schema resolution injectable, so
  tests never depend on the repo tree.
- `live_days=1` on `prune_done` — implements the D2/§7 "unconsumed live handoffs
  older than a day are also pruned" requirement that plan §5's signature omits.
Do not add any other parameters.

### 2b. `tools/smoke.py` — the third directory exception

`validate_data` (L25–56) already has two directory exceptions in the `rglob` loop
at L41–49. Add a third, mirroring the existing `elif history_dir in path.parents`
idiom exactly:

1. After `history_dir = data_root / "balancing_history"` (L39), add
   `forms_dir = data_root / "agent_forms"`.
2. In the chain at L44–49, insert **one** `elif` between the
   `history_dir` branch and the `else`:
   ```python
       elif forms_dir in path.parents:
           schema = schema_dir / "agent_form.schema.json"
   ```
3. Update the `validate_data` docstring (L26–33): "TWO directory exceptions" →
   "THREE", and add the sentence — every `data/agent_forms/*.json` is a form spec
   with an arbitrary stem and validates against `agent_form.schema.json`.

Nothing else in `smoke.py` changes. `validate_data`'s printed count goes 18 → 19.

### 2c. Docs

`data/CLAUDE.md` must be updated in this change (root `CLAUDE.md` exit gate step
3 — the schema-pairing rule is a data-package architectural fact, and the doc
currently claims there is exactly one such exception):
- "What lives here" list (L11–31): add an `agent_forms/` bullet — one form spec
  per thing-type, all validating against `schemas/agent_form.schema.json`, the
  **third** schema-pairing exception; note the handoff schema
  (`schemas/dispatch_handoff.schema.json`) has no `data/` content file because
  handoffs are written to gitignored `.claude/dispatch/`.
- Fix the now-wrong wording at L187–190 ("SCHEMA-PAIRING EXCEPTION (the one
  directory rule)") and L23–24 ("A **second** schema-pairing exception") so the
  three exceptions are stated consistently: `maps/` (except `active_map.json`),
  `balancing_history/`, `agent_forms/`.

Do **not** touch `editor/CLAUDE.md` — plan §6 assigns the spawnclaude/editor
architecture rewrite to AD-3 (L370–371). `editor/agent_forms.py` is a pure helper
of exactly the kind L37–38 already covers.

---

## 3. File scope + shared-file contract

**New (owned entirely by AD-1):**
- `data/schemas/agent_form.schema.json`
- `data/schemas/dispatch_handoff.schema.json`
- `data/agent_forms/add-enemy.json`
- `editor/agent_forms.py`
- `tools/tests/test_agent_forms.py`

**Modified (shared — keep each edit surgical):**

| File | Exact insertion point | Later phases |
|---|---|---|
| `tools/smoke.py` | The `rglob` `if/elif/else` chain (L44–49) + the `history_dir` local (L39) + the `validate_data` docstring (L26–33). One `elif` branch, per §2b. | none |
| `tools/tests/test_editor_viewport.py` | `TestPurity.test_editor_does_not_import_game` (~L190–210) is **one** test building a single `import …` string. Add **exactly one line** to that implicit string concatenation, immediately after `"editor.run_controls, editor.spawnclaude, editor.theme, "` (L199): `"editor.agent_forms, "`. Keep it on its own line and change nothing else. | AD-3 adds `"editor.agent_form_dialog, "` and AD-7 adds `"editor.plans, "` as **sibling lines** at the same anchor — a one-line insert keeps the merge trivial. |
| `.gitignore` | Append under "Editor / tooling state" (after `.claude/active_domain`, L18): `.claude/dispatch/`. | AD-2/AD-3 create `.claude/worktrees/<branch>/` — see §5 note. |
| `data/CLAUDE.md` | Per §2c. | AD-6 revisits for new categories. |
| `tools/tests/test_agent_forms.py` | **You create it.** Structure it as several small `unittest.TestCase` classes with clear names (below), ending with the standard `if __name__ == "__main__": unittest.main()` block. | AD-4 appends an all-specs sweep class; AD-5 appends a fresh-load test — both insert classes **above** the `__main__` block. Leave no trailing helper code after it. |

**Do NOT touch:** `editor/spawnclaude.py` (AD-2), `editor/main.py`,
`tools/tests/test_spawnclaude.py` (AD-2/AD-3), `tools/tests/test_smoke_pairing.py`
(its temp tree only stubs `maps/`; AD-1's agent_forms pairing test lives in
`test_agent_forms.py` per plan §6's file list — do not widen the shared surface).

**Verified — no change needed:** `tools/tests/test_editor_panels.py::TempDataCase`
(L65–90) copies the whole `data/` tree with `shutil.copytree(REPO / "data",
self.data_dir)` (L78), so `data/agent_forms/` comes along for free. It then wipes
only `balancing_history/` and normalizes `_lock`s. Plan §6 L335–336 asks you to
confirm this and extend it if not — it is confirmed; **do not extend it.**

---

## 4. Exit gate + Quick Test

### Exit gate (run from the repo root)
1. `py tools/smoke.py` → must print **`smoke: 19 data file(s) schema-valid`**
   (18 today: 5 `balancing/`, 4 `balancing_history/`, 5 `maps/`, `display.json`,
   `geometry.json`, `slots.json`, `sprites/asset_manifest.json` — plus
   `agent_forms/add-enemy.json`) then the two game-run lines and `OK`.
2. `py -m unittest discover -s tools/tests -t .` → **zero NEW failures** against
   the recorded Development baseline (17 pre-existing failures). Report the count
   and name any delta.
3. State explicitly what you verified (smoke + suite; there is no live run in
   AD-1 — no UI exists yet).

### Required tests in `tools/tests/test_agent_forms.py`
Plan §6 L328–336. Suggested class split (names are the contract for AD-4/AD-5
appenders):

- **`TestSlugify`** — spaces → `-` (`"Siege Cannon"` → `siege-cannon`);
  punctuation/case (`"The Hole's Bane!"` → `the-hole-s-bane`, no leading/trailing
  or doubled dashes); `max_len` cap truncates and leaves no trailing dash;
  `""`/`None` → `""`.
- **`TestDefaultBranchName`** — uses `slug_field` (`agent/add-enemy-siege-cannon`);
  falls back to the free text when the slug field is missing/empty; both empty →
  `agent/add-enemy` (no trailing dash).
- **`TestLoadFormSpecs`** — the committed `data/agent_forms/add-enemy.json` loads
  and validates; specs come back sorted by `id`; a temp `agent_forms/` with an
  **invalid** spec raises `jsonschema.ValidationError` (cover BOTH: an integer
  field missing `minimum`/`maximum`, and an unknown top-level key —
  `additionalProperties:false`); an `id`/filename-stem mismatch raises
  `ValueError`; a missing directory returns `[]`.
- **`TestPayloadRoundTrip`** — `build_payload` → `write_handoff` into a
  `tempfile.TemporaryDirectory()` repo: the written file re-validates via
  `data_io.load_validated(path, data/schemas/dispatch_handoff.schema.json)`; its
  text equals `data_io.dumps_deterministic(payload)` (sorted keys, 2-space indent,
  trailing newline); branch mode carries `git.branch`, current mode omits it and
  still validates; an out-of-range `git_mode` raises `ValueError`.
- **`TestHandoffRelpath`** — returns a **POSIX** string
  (`.claude/dispatch/<name>.json`, forward slashes on Windows — assert
  `"\\" not in result`); a path outside the repo raises `ValueError`.
- **`TestPruneDone`** — write two files into `.claude/dispatch/done/`, backdate
  one with `os.utime` (e.g. 40 days) → `prune_done(repo, days=30)` deletes only
  the old one and returns `1`; a fresh live handoff directly under
  `.claude/dispatch/` survives; a backdated live one (2 days) is pruned; missing
  dirs → `0`, no raise.
- **`TestSmokePairing`** — build a temp `data/` tree (copy
  `REPO/data/schemas`, then write `agent_forms/whatever_stem.json` holding a valid
  spec whose `id` is unrelated to the schema stem): `smoke.validate_data(root)`
  returns the file count, proving `agent_form.schema.json` was chosen and not
  `whatever_stem.schema.json` (which does not exist — the old rule would raise
  `FileNotFoundError`); an invalid form file in that directory raises
  `jsonschema.ValidationError`. Mirror the setup idiom of
  `tools/tests/test_smoke_pairing.py::TestPairingRule` (L28–39).

### Quick Test (for the PR body)
No in-game or in-editor surface exists in AD-1 (the UI lands in AD-3), so the
Quick Test is the exit gate itself plus one manual confirmation:

```
py tools/smoke.py                      # -> "smoke: 19 data file(s) schema-valid" ... OK
py -m unittest discover -s tools/tests -t .   # -> no new failures vs baseline
py -c "from editor import agent_forms as a; s=a.load_form_specs()[0]; \
       p=a.build_payload(s, {'name':'Siege Cannon','era_count':2}, 'shells buildings', 'branch'); \
       f=a.write_handoff(p); print(a.handoff_relpath(f)); print(f.read_text())"
```
Expect: `agent/add-enemy-siege-cannon` as `git.branch`, the printed relpath
`.claude/dispatch/<ts>-add-enemy.json` (forward slashes), and the file NOT
appearing in `git status` (gitignored). Delete it afterwards, or leave it —
`prune_done` will collect it.
