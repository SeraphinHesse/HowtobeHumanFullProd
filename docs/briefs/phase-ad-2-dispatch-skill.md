> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase AD-2 Brief — `/dispatch` skill + spawnclaude pure layer

> Coordination artifact for the AD-1..AD-7 subagent batch. Planner filled §1–§4;
> the coder treats §3 as a HARD boundary and §2 as a contract; the reviewer
> verifies the diff against §1/§2/§4. Source plan: `planning/AgentDispatchPLAN.md`
> (§2 Architecture + decisions **D1–D6**, §4 The `/dispatch` skill, §5 editor
> components, §6 Phase AD-2, §7 risks). Branch: off the AD umbrella
> (`phase-AD-1-7-umbrella`), which is off `Development`.

**Phase goal (plan §6, AD-2):** the `/dispatch` skill exists and works when fed a
**hand-written** handoff; spawnclaude's PURE builders speak dispatch and the
`/start-domain` path is gone from spawnclaude. **The dialog rewrite is AD-3** — in
AD-2 the dialog temporarily offers only Small tweak + Admin. Do the minimum in the
dialog; do not over-invest in UI that AD-3 replaces.

---

## Known repo state (verified against current source — do NOT re-derive)

`editor/spawnclaude.py` (185 lines) today:

| Symbol | Line | AD-2 fate |
|---|---|---|
| `from editor import locks, run_controls` | 34 | → `from editor import run_controls` |
| `domain_choices(data_dir=None)` | 41 | **DELETE** |
| `start_domain_prompt(domain)` | 56 | **DELETE** |
| `small_tweak_prompt(text)` | 63 | **KEEP verbatim** |
| `spawn_command(initial_prompt=None, repo=None, wt="wt")` | 71 | **KEEP verbatim** |
| `dispatch(domain=…, tweak_prompt=…, admin=…, repo=…, detach=…)` | 83 | **RE-SIGNATURE** |
| `SpawnClaudeDialog(QDialog)` | 106 | strip domain radios only |

- `run_controls.start_detached(program, arguments, working_dir)`
  (`editor/run_controls.py:64`) is the default injectable launcher; it strips the
  SDL dummy vars. Unchanged by AD-2.
- `editor/main.py:534` constructs `SpawnClaudeDialog(data_dir=self._data_dir,
  repo=REPO, parent=self)`. **`main.py` is NOT in AD-2's scope** → the dialog MUST
  keep accepting `data_dir=` (accepted-and-unused in AD-2; AD-3 uses it for
  `agent_forms.load_form_specs`). Do not drop that kwarg.
- `engine/data_io.py:21` — `load_validated(data_path, schema_path)`;
  `:33` — `write_validated(data, data_path, schema_path)`.
- `tools/tests/test_spawnclaude.py` classes: `TestSpawnCommand` (29),
  `TestPrompts` (57), `TestDomainChoices` (70), `TestDispatch` (86),
  `TestNoLockWriteAPI` (125), `TestDialogGreying` (136). Imports
  `from editor import locks, spawnclaude` and
  `from tools.tests.test_editor_panels import TempDataCase, lock_domain`.
- **AD-1 (merges before you)** creates `data/schemas/dispatch_handoff.schema.json`,
  `data/schemas/agent_form.schema.json`, `data/agent_forms/add-enemy.json`,
  `editor/agent_forms.py`, and gitignores `.claude/dispatch/`. **AD-2 REFERENCES
  those (the skill's validate step; the handoff shape) but CREATES/EDITS NONE of
  them.** In particular: **`editor/spawnclaude.py` must NOT import
  `editor.agent_forms` in AD-2** — `dispatch()` takes the handoff path as a plain
  string, so AD-2 stays compilable and testable regardless of AD-1's merge order.
  The `agent_forms` → `spawnclaude` call direction is AD-3's wiring.

---

## 1. Behavioral spec — the `/dispatch` skill

New file `.claude/commands/dispatch.md`, house format (frontmatter → intro →
Read first → Steps → Avoid → Verify → Final report, ≤~60 lines; see
`smalltweak.md` / `add-enemy.md` / `execute-phase.md`).

**Frontmatter (plan §4, verbatim intent):**
- `description:` "Execute a structured agent-dispatch handoff from the editor —
  git setup (worktree branch off Development, or current branch), then drive the
  target add-* skill."
- `argument-hint: <handoff-file path>`
- `allowed-tools: Read, Edit, Write, Grep, Glob, SlashCommand, Bash(git *),
  Bash(gh pr create*), Bash(py tools/smoke.py*), Bash(py -m unittest*),
  Bash(py -c *)`
  (§7 flags this breadth as accepted-and-reviewed: the downstream skill varies, and
  the target skill's own narrow instructions govern behavior.)

**The seven steps (plan §4):**

1. **Read + validate** the handoff at `$ARGUMENTS`:
   `py -c "from engine import data_io; data_io.load_validated(r'<path>', r'data/schemas/dispatch_handoff.schema.json')"`.
   Echo a one-paragraph summary (form, skill, values, git mode). **Abort loud** on
   any failure — a malformed handoff never proceeds to git.
2. **Read the context files** listed in the payload's `context` array. Token-light
   routing: read the ONE doc that matches, never paste whole architecture docs.
3. **Git setup**, per `git.mode`:
   - `"current"` → `git status --porcelain`; if dirty, **list the dirt** and
     continue only if it is unrelated to the task. **Work in place. Never switch
     branches.**
   - `"branch"` → `git fetch origin Development`; if `git.branch` already exists,
     uniquify with a `-2` / `-3` / … suffix; then
     `git worktree add .claude/worktrees/<branch> -b <branch> origin/Development`.
     **All subsequent work uses absolute paths inside that worktree** (D3 — the
     editor's tree is never touched; a `git switch -c` in the main tree would yank
     files under a running editor and two concurrent spawns would fight over HEAD).
   - **NEVER write `.claude/active_domain`. NEVER touch any `_lock`.** The branch +
     lock protocol is SUSPENDED (root `CLAUDE.md`; D6). `scope_guard.py` stays
     fail-open and untouched.
4. **Invoke the target skill** (D4 — **zero skill duplication**; existing `add-*`
   skills need **NO changes** and stay fully usable standalone). `/dispatch` does
   git setup + payload translation only, then calls the real slash command with a
   composed argument line:
   `/<skill> <values as one readable line> — free text: <free_text> — structured payload: <handoff path>`.
   **Fallback** (must be written into the skill body): if the SlashCommand tool is
   unavailable, `Read .claude/commands/<skill>.md` and follow it with that composed
   `$ARGUMENTS`.
5. **Exit gate** in the working root (worktree root in branch mode):
   `py tools/smoke.py` + `py -m unittest discover -s tools/tests -t .`.
6. **Land**:
   - branch mode → commit, push, `gh pr create --base Development` (body = payload
     summary + verification performed + a concrete in-game Quick Test), then
     `git worktree remove` and report the PR URL.
   - current mode → summarize the diff and **wait for explicit user confirmation
     before committing** (the `/smalltweak` convention). No PR.
7. **Archive** the handoff to `.claude/dispatch/done/`.

**Avoid** (§4): force-push / `reset --hard` / `git clean`; committing `build/` /
`dist/` / `*.exe`; edits outside what the target skill's own scope needs; any
`_lock` write.

**D6 scope note for the coder:** removing the `/start-domain` path means removing it
**from spawnclaude only**. The four domain-flow skills (`start-domain`,
`resume-domain`, `finish-domain`, `merge-domain`) **stay on disk untouched** —
**AD-4** adds the `SUSPENDED —` description prefix, **not you**. `editor/locks.py`
stays (the balancing panel still reads `_lock`).

### DRAFT `.claude/commands/dispatch.md` — lift this

```markdown
---
description: Execute a structured agent-dispatch handoff from the editor — git setup (worktree branch off Development, or current branch), then drive the target add-* skill.
argument-hint: <handoff-file path>
allowed-tools: Read, Edit, Write, Grep, Glob, SlashCommand, Bash(git *), Bash(gh pr create*), Bash(py tools/smoke.py*), Bash(py -m unittest*), Bash(py -c *)
---

Execute the dispatch handoff at **$ARGUMENTS** — a schema-valid JSON payload the
editor wrote when a designer submitted an "Add new X" form. This skill does git
setup + payload translation ONLY; the real work is done by the target `add-*`
skill named in the payload, invoked unmodified. The branch+lock protocol is
SUSPENDED: this skill NEVER writes `.claude/active_domain` and NEVER touches any
`_lock`.

## Read first (token-light)
1. The handoff itself (Step 1) — it names everything else.
2. Only the docs listed in the payload's `context` array. Do not pull in whole
   architecture docs the payload didn't ask for.

## Steps
1. **Read + validate** the handoff. Fail loud, do not guess:
   `py -c "from engine import data_io; data_io.load_validated(r'$ARGUMENTS', r'data/schemas/dispatch_handoff.schema.json')"`
   Then Read it and echo a one-paragraph summary: form id, target skill, values,
   free text, git mode/branch. If validation fails, STOP and report — never
   proceed to git on a malformed payload.
2. **Read the context files** from the payload's `context` array.
3. **Git setup** — from the payload's `git` block:
   - `mode: "current"` → `git status --porcelain`. If dirty, list the dirt and
     continue ONLY if it is unrelated to this task. Work in place.
     **Never switch branches.**
   - `mode: "branch"` → `git fetch origin Development`. If `git.branch` already
     exists (`git rev-parse --verify`), suffix `-2`, `-3`, … until free. Then
     `git worktree add .claude/worktrees/<branch> -b <branch> origin/Development`
     and do ALL subsequent work with **absolute paths inside that worktree** —
     the user's editor has the main tree open; never yank it.
4. **Invoke the target skill** as a real slash command, unmodified:
   `/<skill> <values as one readable line> — free text: <free_text> — structured payload: <handoff path>`
   If the SlashCommand tool is unavailable, Read `.claude/commands/<skill>.md`
   and follow it with exactly that composed `$ARGUMENTS`.
5. **Exit gate** in the working root (the worktree, in branch mode):
   `py tools/smoke.py` and `py -m unittest discover -s tools/tests -t .`. Green
   smoke; no NEW test failures.
6. **Land**:
   - branch mode → commit, push, `gh pr create --base Development` with a body
     carrying the payload summary, what you verified, and a concrete in-game
     Quick Test. Then `git worktree remove <path>` and report the PR URL.
   - current mode → summarize the diff and **WAIT for the user's explicit
     confirmation before committing** (the `/smalltweak` convention). No PR.
7. **Archive** the handoff into `.claude/dispatch/done/` (create the dir if
   needed).

## Avoid
- Writing `.claude/active_domain` or any `_lock` — the protocol is SUSPENDED.
- `git switch` / `git checkout -b` in the main tree; force-push; `reset --hard`;
  `git clean`.
- Committing `build/`, `dist/`, or any `*.exe`.
- Editing anything the target skill's own file scope doesn't cover.
- Re-implementing the target skill. It runs as written.

## Verify
- Smoke + suite from Step 5, run in the working root. State exactly what you
  exercised (worktree vs in place, smoke, suite, any live run).

## Final report
- Handoff file + form/skill; git mode and branch (or "in place on <branch>");
  changed files; verification results; PR URL (branch mode) or the diff summary
  awaiting confirmation (current mode); where the handoff was archived.
```

---

## 2. Architecture plan — `editor/spawnclaude.py`

**DELETE**
- `domain_choices(data_dir=None)` (L41–53).
- `start_domain_prompt(domain)` (L56–60).
- the `locks` import → `from editor import run_controls` (L34).
- the module docstring's "Domain → `/start-domain`" bullet; rewrite it to describe
  the three surviving modes (**admin** / **dispatch handoff** / **small tweak**) and
  state that the branch+lock protocol is suspended and this module writes no lock.

**KEEP — byte-identical contracts (tests assert these):**
- `spawn_command(initial_prompt=None, repo=None, wt="wt")` →
  `["wt", "-d", <repo>, "cmd", "/k", "claude", <prompt>]`, **prompt as ONE argv
  element** (§7: this is what keeps a repo path with spaces and a prompt with
  spaces safe — argv is a list into `QProcess.startDetached`). Falsy prompt → no
  trailing element (admin mode → blank `claude`).
- `small_tweak_prompt(text)` → `/smalltweak <text>`, or `/smalltweak` when blank.

**ADD**
```python
def dispatch_prompt(handoff_relpath):
    """Claude's opening input for a form dispatch: the literal /dispatch slash
    command with the repo-relative POSIX handoff path appended."""
    return f"/dispatch {handoff_relpath}"
```
It takes the **already-relative POSIX string** (`agent_forms.handoff_relpath`
produces it in AD-1) — `dispatch_prompt` does no path math, so spawnclaude never
imports `agent_forms` and stays trivially unit-testable.

**RE-SIGNATURE**
```python
def dispatch(handoff=None, tweak_prompt=None, admin=False, repo=None, detach=None):
```
Precedence **admin > handoff > smalltweak** (D5: admin and small tweak bypass
dispatch entirely — no handoff written, behavior preserved):
```python
if admin:      prompt = None                       # blank claude
elif handoff:  prompt = dispatch_prompt(handoff)   # /dispatch <relpath>
else:          prompt = small_tweak_prompt(tweak_prompt)
```
`repo` defaults to `REPO`; `detach` defaults to `run_controls.start_detached` and
stays injectable end to end; the return value stays `started_ok` (bool).
**`domain=` is gone — do not keep it as a deprecated alias.**

**Dialog (minimum viable, AD-3 replaces it):** `SpawnClaudeDialog` keeps its
signature `(data_dir=None, repo=None, parent=None, detach=None)` — `main.py:534`
passes `data_dir=` and `main.py` is out of scope, so the kwarg must survive
(accepted, unused, one comment saying AD-3 will use it for form specs). Strip the
domain radio loop, `self._domain_buttons`, and `selected_domain()`; the dialog now
offers exactly **Small tweak (radio + line edit)** and **Admin (radio)**, with Small
tweak checked by default. `_on_dispatch` keeps the admin / tweak branches and drops
the domain branch. Do not add form entries, plan pickers, or a handoff radio here —
that is AD-3/AD-7.

---

## 3. File scope + shared-file contract

**New (AD-2 owns):**
- `.claude/commands/dispatch.md` — the draft above.

**Modified (AD-2 owns):**
- `editor/spawnclaude.py` — exactly the changes in §2.
- `tools/tests/test_spawnclaude.py` — rewrite:
  - **KEEP VERBATIM:** `TestSpawnCommand` (all five argv-shape tests — but change
    the `test_prompt_is_a_single_argv_element` literal from `"/start-domain map"` to
    a dispatch prompt, e.g. `"/dispatch .claude/dispatch/x.json"`; the *assertion*
    stays identical) and **`TestNoLockWriteAPI` verbatim** (it must still pass with
    the `locks` import gone — it is the T-1 guard).
  - **DROP:** `TestDomainChoices` entirely; the domain tests inside `TestDispatch`
    (`test_dispatch_domain_uses_injected_launcher`) and the domain tests inside
    `TestDialogGreying` (`test_locked_domain_button_disabled`,
    `test_default_selection_skips_locked_domain`). Keep
    `test_admin_mode_dispatches_blank` (rename the class if `Greying` no longer
    fits, e.g. `TestDialog`). Drop
    `TestPrompts::test_start_domain_prompt_is_the_literal_slash_command`.
  - **ADD:** `dispatch_prompt` tests — a repo-relative POSIX path
    (`.claude/dispatch/20260713-140322-add-enemy.json`) round-trips into
    `"/dispatch <path>"`, and through `spawn_command` it lands as a **single argv
    element**; plus `dispatch()` **precedence admin > handoff > tweak** with an
    injected fake `detach` (pass all three and assert admin wins; pass handoff +
    tweak and assert handoff wins).
  - **Imports:** after dropping the domain tests, `locks` and `lock_domain` are
    likely unused — remove `from editor import locks` and drop `lock_domain` from
    the `test_editor_panels` import if nothing references it. Keep `TempDataCase`
    only if a surviving test still needs a temp data dir (the dialog tests do not
    strictly need one once domains are gone — plain `unittest.TestCase` is fine;
    if you drop it, drop the import).

**HARD BOUNDARY — do NOT touch (another phase owns these; a diff here is a review
failure):**
- `tools/smoke.py`, `.gitignore`, `editor/agent_forms.py`, `data/schemas/*`,
  `data/agent_forms/*`, `tools/tests/test_agent_forms.py`, and
  `tools/tests/test_editor_viewport.py` — **AD-1**.
- `editor/agent_form_dialog.py`, `editor/main.py`, `editor/CLAUDE.md` — **AD-3**.
- `.claude/commands/{start,resume,finish,merge}-domain.md`, root `CLAUDE.md`,
  `docs/prompt-templates.md` — **AD-4**.
- `editor/locks.py`, `.claude/hooks/scope_guard.py` — untouched by the whole AD
  batch (D6).

**Known, accepted staleness:** `editor/CLAUDE.md`'s spawnclaude section still
documents `domain_choices` / `start_domain_prompt` / "three dispatch modes: domain,
small tweak, admin" after AD-2 lands. **AD-3 owns that rewrite** (plan §6, AD-3
files list: "`editor/CLAUDE.md` (rewrite the spawnclaude invariants section — this
is the architectural-change doc update)"). AD-2 must **say so explicitly in its PR
body** rather than silently leaving the doc wrong, and must **not** edit the file.

---

## 4. Exit gate + Quick Test

**Coder's exit gate (headless, must be green before the PR):**
1. `py tools/smoke.py` — green.
2. `py -m unittest discover -s tools/tests -t .` — **zero NEW failures vs the
   Development baseline** (there are known pre-existing failures; record the
   baseline before you start and diff against it).
3. Confirm nothing outside §3's owned list appears in `git diff --name-only`.

**What the coder CAN verify headlessly (do all of these — this is the substitute for
the live check):**
- `dispatch_prompt(".claude/dispatch/x.json") == "/dispatch .claude/dispatch/x.json"`
  and the composed prompt survives `spawn_command` as **one argv element**.
- Full argv shape unchanged: `["wt", "-d", <repo>, "cmd", "/k", "claude", <prompt>]`.
- `dispatch()` precedence admin > handoff > tweak, via the injected fake `detach`
  (no real terminal ever spawns).
- `.claude/commands/dispatch.md` exists and its YAML frontmatter parses with the
  three expected keys (`description`, `argument-hint`, `allowed-tools`) — a quick
  `py -c` YAML/regex check is enough; it need not become a permanent test.
- `import editor.spawnclaude` succeeds with no `editor.locks` and no
  `editor.agent_forms` dependency (`grep` the module: neither name appears).

**What the coder CANNOT verify — hand it to the user as the PR's Quick Test.** The
plan's AD-2 live check (§6) is an *interactive terminal* exercise and cannot be done
headlessly by a subagent. Write it into the PR body verbatim, as the user's step:

> **Quick Test (user, ~3 min).** In the repo root, hand-write a handoff at
> `.claude/dispatch/test.json` matching `data/schemas/dispatch_handoff.schema.json`
> with `"git": {"mode": "current"}` and a trivial payload (e.g. `form_id`/`skill`
> `add-enemy`, one value, a one-line `free_text`). Then run
> `claude "/dispatch .claude/dispatch/test.json"` in a real terminal. Confirm it:
> (a) validates the handoff and echoes a correct one-paragraph summary; (b) reads
> only the `context` files listed; (c) reports the current branch's dirty state and
> does **not** switch branches; (d) drives `/add-enemy` with the composed argument
> line. **Abort it before it commits** — this test is about the dispatch path, not
> about landing an enemy. Confirm no `.claude/active_domain` file was created and
> `data/balancing/*.json` `_lock` values are unchanged.

**Final report must state the split explicitly:** which checks were run headlessly
(smoke / suite vs baseline / argv + prompt assertions / frontmatter parse) and that
the end-to-end `claude "/dispatch …"` run is **unverified by the agent** and left to
the user's Quick Test.
