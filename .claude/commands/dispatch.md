---
description: Execute a structured agent-dispatch handoff from the editor — git setup (worktree branch off Development, or current branch), then drive the target add-* skill.
argument-hint: <handoff-file path>
allowed-tools: Read, Edit, Write, Grep, Glob, SlashCommand, Bash(git *), Bash(gh pr create*), Bash(cd *), Bash(py *)
disable-model-invocation: true
---

Execute the dispatch handoff at **$ARGUMENTS** — a schema-valid JSON payload the
editor wrote when a designer submitted an "Add new X" form. This skill does git
setup + payload translation ONLY; the real work is done by the target `add-*`
skill named in the payload, invoked unmodified.

**Two trees, one rule.** The handoff lives at `.claude/dispatch/<f>.json` in the
**MAIN repo tree** (where you started) and is **gitignored** — so it does NOT
exist inside a worktree created in Step 3. Before any git setup, record
`MAIN=$(git rev-parse --show-toplevel)` and resolve the handoff to an **absolute
path** under `MAIN`. Read it there, pass it as an absolute path, and archive it
there. Only the *code work* happens in the worktree.

## Read first (token-light)
1. The handoff itself (Step 1) — it names everything else.
2. Only the docs listed in the payload's `context` array. Do not pull in whole
   architecture docs the payload didn't ask for.

## Steps
1. **Read + validate** the handoff. Fail loud, do not guess:
   `py -c "from engine import data_io; data_io.load_validated(r'<abs handoff>', r'data/schemas/dispatch_handoff.schema.json')"`
   Then Read it and echo a one-paragraph summary: form id, target skill, values,
   free text, git mode/branch. If validation fails, STOP and report — never
   proceed to git on a malformed payload.
2. **Read the context files** from the payload's `context` array.
3. **Git setup** — from the payload's `git` block; `base` defaults to
   `Development` when absent.
   - `mode: "current"` → `git status --porcelain`. If dirty, list the dirt.
     Continue ONLY if it is unrelated to this task. If any dirty file is one the
     target skill would touch (e.g. an uncommitted `data/balancing/enemies.json`
     under `/add-enemy`), **STOP and ask the user** — never edit over their
     work. Otherwise work in place. **Never switch branches.**
   - `mode: "branch"` → `git fetch origin <base>`. Uniquify `git.branch` if it is
     taken **locally or on the remote** — check `git rev-parse --verify <b>` AND
     `git ls-remote --exit-code --heads origin <b>`, suffixing `-2`, `-3`, … until
     both miss (a remote-only collision would otherwise survive to `push` and
     blow up there). Then
     `git worktree add "$MAIN/.claude/worktrees/<branch>" -b <branch> origin/<base>`
     and do all **code** work with absolute paths inside that worktree — the
     user's editor has the main tree open; never yank it.
4. **Invoke the target skill** as a real slash command, unmodified. The payload
   path must be **absolute** (it lives in `MAIN`, not in the worktree):
   `/<skill> <values as one readable line> — free text: <free_text> — structured payload: <MAIN>/.claude/dispatch/<f>.json`
   If the SlashCommand tool is unavailable, Read `.claude/commands/<skill>.md`
   and follow it with exactly that composed `$ARGUMENTS`.
5. **Exit gate** in the working root (the worktree, in branch mode):
   `py tools/smoke.py` and `py -m unittest discover -s tools/tests -t .`. Green
   smoke; **no NEW test failures — the gate is a DIFF, not zero.** Measure the
   baseline on the base branch (or take it from your dispatch prompt) — never
   trust a remembered count. Known shape: 6 deliberate balancing-parity
   divergences + a set of editor/Qt failures in the main tree; parity SKIPS in
   a worktree (see below). Anything beyond the measured set is yours; fix it,
   don't explain it away.
   ⚠️ **`test_balancing_parity` SKIPS inside `.claude/worktrees/`** — it locates
   the prototype repo relative to the checkout (`REPO.parent/HowToBeHuman/…`),
   which does not resolve from a worktree, so it looks green and proves nothing.
   If the target skill touched `data/balancing/*` (`/add-enemy`, `/add-building`,
   `/add-balancing-value`), re-run `py -m unittest tools.tests.test_balancing_parity`
   **from the MAIN tree** before landing.
6. **Land**:
   - branch mode → stage only the files the target skill changed (by explicit
     path), commit, push, `gh pr create --base <base>` with a body carrying the
     payload summary, what you verified, and a concrete in-game Quick Test.
   - current mode → summarize the diff and **WAIT for the user's explicit
     confirmation before committing** (the `/smalltweak` convention). No PR.
7. **Archive, THEN clean up — in that order.** Move the handoff into
   `<MAIN>/.claude/dispatch/done/` (both paths are in `MAIN`, so this cannot be
   invalidated by worktree removal — but do it first anyway, so a literal reading
   never archives into a deleted tree):
   `py -c "import pathlib,shutil; d=pathlib.Path(r'<MAIN>/.claude/dispatch/done'); d.mkdir(parents=True,exist_ok=True); shutil.move(r'<abs handoff>', d / '<f>.json')"`
   (a copy is acceptable if the move fails). Only then, in branch mode,
   `git worktree remove "$MAIN/.claude/worktrees/<branch>"` and report the PR URL.

## Avoid
- `git switch` / `git checkout -b` in the main tree; force-push; `reset --hard`;
  `git clean`.
- `git add -A` / `git add .` / `git commit -a`. The user may have unrelated
  uncommitted work (balancing edits especially) sitting in the tree — stage only
  the files the target skill changed, by explicit path.
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
