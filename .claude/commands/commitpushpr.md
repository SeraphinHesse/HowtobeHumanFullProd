---
description: Report what this branch changed, offer a summary artifact, open an UNTESTED PR into Development, merge Development in, then gate and ship — in that order, on the user's go-ahead.
argument-hint: [optional PR subject — inferred from the diff if omitted]
allowed-tools: Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git log*), Bash(git show*), Bash(git rev-list*), Bash(git branch*), Bash(git fetch*), Bash(git merge*), Bash(git merge-base*), Bash(git merge-tree*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git check-ignore*), Bash(gh pr create*), Bash(gh pr edit*), Bash(gh pr view*), Bash(gh pr list*), Bash(gh pr checks*), Bash(grep*), Bash(py -c*), Bash(py -m pytest*), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Read, Edit, Write, Glob, Grep, AskUserQuestion, Artifact, Skill
disable-model-invocation: false
---

**This is THE way work leaves a session — always, not optionally.** Root
`CLAUDE.md` Step 2 item 4 makes it the required closing move, so invoke it
whenever the session is wrapping up and the branch needs to land: the user
saying "let's ship this", "wrap up", "open a PR", "commit and push", or asking
to finish up. Do not hand-roll `commit → push → PR` instead, and do not run the
gate before stage 5. (It is model-invocable for exactly that reason — but only
at session close; it is not a mid-task tool.)

Close out a branch: **report what it changed, offer an artifact, open the PR,
merge `Development` in, then gate and ship** — subject: **$ARGUMENTS** (infer
from the diff if empty). This is the closing move of a session. It makes no
*feature* edits; the only code it may touch is a merge-conflict resolution and a
fix for a failure the gate itself surfaced.

**The order below is the point of this skill, and the user's go-ahead gates
stages 2, 4, 5 and 6.** The PR goes up *before* any test runs, so the work is
visible and reviewable while the slow parts happen; the merge-down happens
*before* the gate, so the gate measures the tree that will actually land.
Running the suite early — "just to see where we are" — throws away the one run
the policy allows and measures a tree that no longer exists after the merge.

Stage map, in order: **1** report · **2** offer an artifact (optional) ·
**3** UNTESTED PR · **4** offer the merge-down · **5** offer the gate, with skip ·
**6** fix, push, update the PR. Nothing runs a test before stage 5.

## Preconditions (abort with a clear report on any failure)

1. `git rev-parse --abbrev-ref HEAD` — refuse to run on `Development` or
   `main`; work belongs on a phase/feature branch (branch first if needed).
2. `git status` — a dirty tree is fine and normal here (stage 1 commits it).
   If the tree is clean AND there are no unpushed commits AND the branch is
   level with `Development`, say so and stop.
3. Review the diff before committing anything — never blind-commit: no
   `build/`, `dist/`, `*.exe`, no stray scratch files. If a plan doc should
   reflect this work and doesn't, flag it before committing.

---

## Stage 1 — Report what is on this branch (NO TESTS)

Commit any outstanding work first (brief message; group unrelated changes into
separate commits), then summarise **everything on this branch that has not gone
into `Development` yet** — the `/report` shape, written for a reader who has not
seen the session.

Gather it from the diff, not from memory:

```bash
git fetch origin
git log --oneline origin/Development..HEAD          # what is ahead
git rev-list --count HEAD..origin/Development       # how far behind
git diff --stat $(git merge-base origin/Development HEAD)..HEAD
git log --format='%h %s%n%b---' $(git merge-base origin/Development HEAD)..HEAD --no-merges
```

Then read the **package `CLAUDE.md` diffs first** — on this repo a real feature
almost always documented itself, so `git diff <base>..HEAD -- '**/CLAUDE.md'` is
the fastest accurate summary of intent that exists. Follow with the `data/`
diffs (balancing numbers, schema additions, new slots) and spot-read the code
for anything the docs left implicit.

If the branch executed a **plan doc** (`planning/*PLAN.md`, or `PLAN.md`'s
active-plan marker), walk the plan and explain **every phase it covers, by its
ID** — `G1`…`G6`, `M1`…`M5`, `10B`…`10E`, whatever that plan numbers them — one
short paragraph each: what the phase was meant to do, what actually landed, and
where (`file:line`). A phase the branch skipped or only partly did gets said so
in the same list; silence reads as "done". This per-phase walk is the spine of
the write-up — the feature grouping below hangs off it.

Group the rest of the write-up by **feature, not by commit** — commit subjects on
a long branch are frequently `a`, `edits`, `Test Edits`. Call out, explicitly:

- Any **shipped flag flip** — a feature boolean that is now `true` in `data/`
  is a live behaviour change, and it is the single most common thing a reviewer
  misses. State the value and the file.
- Balancing numbers that moved, old → new.
- New files, new schema keys, new slot-registry entries.
- Anything **deleted**.

Tag every claim **measured** / **verified** / **inferred** (`/report`).

**Run no tests in this stage.** Not `smoke.py`, not a targeted pytest.

## Stage 2 — Offer an artifact (OPTIONAL, STILL NO TESTS)

Having delivered stage 1's write-up in the terminal, **ask** whether the user
wants it as an artifact — a private hosted page they can read properly and share
with whoever reviews this branch. Ask once, with `AskUserQuestion`; a "no" ends
the stage immediately and stage 3 follows unchanged. Do not publish without
being asked to, and do not skip the offer because the branch feels small — a
one-phase branch still produces a readable page, and the answer is the user's.

On "yes":

1. Load the **`artifact-design`** skill first — it calibrates how much design
   the page warrants. Do not start writing HTML before it.
2. Write the page to the scratchpad and publish with `Artifact`. It carries the
   **same content stage 1 reported**, laid out to be read rather than scrolled:
   the per-phase walk (`G1`…, `M1`…) as the main spine, one section per phase;
   the shipped flag flips and old → new balancing numbers as a table; new files,
   schema keys and slot entries; deletions; and the same
   **measured / verified / inferred** tags stage 1 used, visibly, not silently
   dropped because they look untidy in a nice layout.
3. The page states, in a banner of its own, that **no tests have been run at the
   time of writing** — it is published before the gate, and it must not read as
   a completion certificate. If stages 5–6 later change that position, update
   the same artifact (same file path, or pass its `url`) rather than publishing
   a second page.
4. Hand the user the URL in the terminal.

The artifact is a **summary of work, never a substitute for the PR body** —
stage 3 still writes the full body. Link the artifact URL from the PR body when
one was published.

## Stage 3 — Open the PR, marked UNTESTED (STILL NO TESTS)

Push the branch and `gh pr create --base Development`. If a PR already exists
(`gh pr list --head <branch>`), push and `gh pr edit` it instead — never open a
duplicate.

- Title is prefixed **`UNTESTED: `**.
- The body **opens with a blockquote banner** saying no test run has been
  performed, the suite has not been run, `GATE PASS` is not established, and it
  must not be merged until CI is green or the gate is run.
- The body carries stage 1's write-up (including the per-phase walk), the
  stage-2 artifact URL if one was published, a concrete **in-game Quick Test**
  scenario (numbered steps a human can follow in `py game/main.py`), and a
  closing **Test status** section repeating the UNTESTED position and naming
  which test files the branch touched without verifying.
- State how far behind `Development` the branch is.

Write the body to a file in the scratchpad and pass `--body-file`; a body this
long does not survive being inlined as a shell argument.

## Stage 4 — Offer the merge-down, then do it (STILL NO TESTS)

**Ask** whether to pull `Development` in. Before asking, state the facts that
decide it: how far behind, whether the tree is clean, whether this branch has
merged `Development` before, and the likely conflict hotspots. Preview them for
real rather than guessing:

```bash
git merge-tree --write-tree --name-only HEAD origin/Development
```

On go-ahead, `git merge origin/Development --no-commit` and resolve **forward**:

- **Never `git restore`, `git checkout -- <file>`, `reset --hard`, `clean`, or
  `stash`.** See §Branching in the root `CLAUDE.md` — an agent used `git
  restore` to tidy its own mistake and silently destroyed a parallel agent's
  uncommitted work. Undo by editing forward, always.
- **A registry, tier table or import list conflict is almost always a UNION**,
  not a choice: both sides added a row. `conftest.TIERS`, `tools/test_domains.py`,
  `tools/ci_shards.py` and import blocks all behave this way.
- **A generated or append-only data file is resolved by rebuilding it, not by
  hand-editing the markers.** Read both stages (`git show :2:<path>` = ours,
  `:3:<path>` = theirs, `:1:<path>` = base), diff them by their identity key,
  confirm neither side *removed* anything, then write the union back **through
  the validating writer** (`engine.data_io.write_validated`) so ordering and
  formatting stay canonical. `data/balancing_history/*.json` is the standing
  example.
- If a conflict is genuinely ambiguous — both sides retuned the same balancing
  number, both rewrote the same function — **stop and ask.** Do not guess.

Then **prove nothing was lost**, and show the proof in the report:

- Grep the merged tree for the branch's headline symbols and confirm each still
  resolves and is still used.
- For every auto-merged file where both sides were active, confirm *both* sides'
  changes survived — e.g. `git diff origin/Development -- <file>` should show
  only this branch's work, and `git diff HEAD@{1} -- <file>` only Development's.
- Confirm `git rev-list --count HEAD..origin/Development` is now `0`.

Commit the merge with a message that names each conflict and how it was
resolved. **Still no tests.**

## Stage 5 — Ask before the gate, and offer the skip

**Ask** — do not assume. Offer three routes:

1. **Run the full gate once** — `py tools/testgate.py check`, the single run
   §"Test Suite Policy" allows the main session at handoff.
2. **Skip, and clear UNTESTED** — the user verified independently or trusts CI.
3. **Skip, and keep UNTESTED** — push the merge, leave the banner for CI.

The skip is a first-class answer, not a fallback: CI may already be green, or
the user may have run the suite themselves in the editor or by hand. Note also
that a completed run started from the **editor's *Run tests* button** counts as
that one run and is recorded in the guard's ledger — but **any edit to the tree
clears it**, so a stage-4 merge invalidates a run from before it.

Run the gate at most ONCE, and never from inside a dispatched agent.

## Stage 6 — Fix, push, update the PR

If the gate failed: read the report it names (`.claude/testruns/*.md`), fix the
cause, and **re-check with a targeted run over the files you touched only** —
`py -m pytest <file> -q`. Never re-run the full suite to reproduce or to
confirm; the gate is ZERO, so a red test is yours, and CI is the confirmation
that the fix holds suite-wide.

A failure whose cause is clearly outside the diff's blast radius is a **report,
not an investigation** — surface it and stop.

Then push and `gh pr edit` the PR:

- Drop the `UNTESTED: ` title prefix **only if the position genuinely changed.**
- Replace the banner with what actually happened — if the gate ran, failed, and
  was fixed, say exactly that, name the failing node-IDs, the fix commit, and
  the targeted re-run result, and state plainly that the full suite has not been
  re-run since. Never round "fixed and targeted-green" up to "green".
- Add a **merge section** documenting each conflict resolution and the
  no-work-lost checks from stage 4.
- Update the "behind `Development`" line.
- If a stage-2 artifact was published, **update that same artifact** to the
  final position — same file path, or pass its `url` — so the shared page does
  not keep claiming UNTESTED after the gate ran. Never publish a second page.

Finally `gh pr view` / `gh pr checks` to confirm the PR is `MERGEABLE` and to
report CI's state.

---

## Avoid

- **Running any test before stage 5.** This is the rule the skill exists to
  enforce.
- Publishing a stage-2 artifact the user did not ask for, skipping the offer, or
  leaving a published one still saying UNTESTED after stage 6 changed that.
- A second full `testgate check`; any full run from a dispatched agent (the
  `test_guard.py` hook denies it); re-running a target you have not edited since.
- Committing on `Development`/`main`; force-push; amending pushed commits;
  destructive git on uncommitted work.
- Committing `build/`, `dist/`, any `*.exe`, editor prefs, or `graphify-out/`.
- Claiming verification that did not happen. "UNTESTED" in the PR body is a
  correct and useful state — a PR that overstates its verification is not.

## Verify

- Push succeeded; `gh pr view` shows the PR against `Development`, `MERGEABLE`.
- `git rev-list --count HEAD..origin/Development` is `0` if stage 4 ran.
- The PR body's test claims match what was actually run, exactly.
- If an artifact was published, its URL is in the PR body and its test-status
  banner matches the PR's.

## Final report

- Branch, commits landed, PR URL, artifact URL if one was published.
- Each conflict and how it was resolved; the no-work-lost evidence.
- What was verified, tagged **measured** / **verified** / **inferred**, and what
  was deliberately not.
